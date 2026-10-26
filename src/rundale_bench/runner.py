"""Budgeted, resumable execution of the frozen versioned benchmark suites."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from .accounting import Ledger, BudgetError, UncertainBilling, upper_cost, actual_cost
from .judges import judge_response, JUDGE_MAX_OUTPUT_TOKENS, judge_output_limit
from .providers import NativeClient, ProviderError, resolve_profile, load_profiles
from .scoring import aggregate, rubric_score, objective_score, variability, wilson
from .storage import utc_now, atomic_json, publish_run, issue_payload, safe_id

PACKAGE = Path(__file__).resolve().parents[2]
STRUCTURED_PROVIDERS = frozenset(('google', 'openai', 'anthropic'))


def load_suite(root: Path = PACKAGE, version: str = '3.0') -> tuple[dict, list[dict], dict, str]:
    base = root / 'suites' / safe_id(version)
    manifest = json.loads((base/'manifest.json').read_text())
    cases_path, rubric_path = base/'cases.jsonl', base/'rubrics.json'
    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    rubrics = json.loads(rubric_path.read_text())
    for key, path in [('cases_sha256', cases_path), ('rubrics_sha256', rubric_path)]:
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest.get(key) != got:
            raise ValueError(f'{key} does not match the frozen suite file')
    digest = hashlib.sha256((base/'manifest.json').read_bytes()).hexdigest()
    return manifest, cases, rubrics, digest


def qualification_blockers(root: Path, manifest: dict, suite_hash: str) -> list[str]:
    qpath = root/'qualification'/safe_id(manifest.get('version', '3.0'))/'status.json'
    if not qpath.exists():
        return ['Qualification receipt is missing; no paid requests are allowed.']
    try:
        receipt = json.loads(qpath.read_text())
    except Exception:
        return ['Qualification receipt is invalid JSON.']
    blockers = []
    try:
        current_profiles=load_profiles(root/'config'/'providers.json')
    except Exception as exc:
        return [f'Provider profile registry is invalid: {exc}']
    pinned_profiles=manifest.get('judge_profiles',{})
    provisional = receipt.get('status') == 'provisional'
    if receipt.get('status') not in ('qualified', 'provisional'):
        blockers.append('Judge screening is neither qualified nor explicitly provisional.')
    if provisional:
        if (manifest.get('validation_mode') != 'provisional'
                or receipt.get('validation_basis') != 'automated_checks_only'
                or receipt.get('human_validated') is not False):
            blockers.append('Provisional validation policy is missing or inconsistent.')
        evidence_hashes = receipt.get('evidence_hashes', {})
        if set(evidence_hashes) != {'collection.json', 'judgments.json', 'controls.json', 'bias-diagnostics.json'}:
            blockers.append('Provisional calibration evidence hashes are missing.')
        else:
            for name, expected in evidence_hashes.items():
                path = qpath.parent/name
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    blockers.append(f'Provisional calibration evidence changed: {name}.')
    if receipt.get('suite_hash') != suite_hash: blockers.append('Qualification receipt is for a different suite manifest.')
    for category in ('dialogue', 'multiturn'):
        policy = manifest.get('judge_policy', {}).get(category)
        evidence = receipt.get('judges', {}).get(category, {})
        if not policy: blockers.append(f'{category} judge is not pinned in the suite manifest.')
        accepted = (evidence.get('automated_checks_passed') is True and evidence.get('qualified') is False
                    if provisional else evidence.get('qualified') is True)
        if not accepted or evidence.get('profile_id') != policy:
            blockers.append(f'{category} judge does not have matching screening evidence.')
        if policy:
            if policy not in pinned_profiles:
                blockers.append(f'{category} judge profile snapshot is missing from the suite manifest.')
            elif current_profiles.get(policy) != pinned_profiles[policy]:
                blockers.append(f'{category} judge profile differs from its manifest snapshot.')
    if manifest.get('status') != 'ready': blockers.append('Suite manifest status is draft, not ready.')
    engine = manifest.get('engine', {})
    if engine.get('capture_sha256') in (None, 'pending-capture'):
        blockers.append('Engine prompt capture is pending.')
    return blockers


def validate_suite(root: Path = PACKAGE, version: str = '3.0') -> dict:
    manifest, cases, rubrics, digest = load_suite(root, version)
    if manifest.get('version') != version:
        raise ValueError('Suite manifest version does not match requested version')
    ids = [c.get('id') for c in cases]
    problems = []
    if len(ids) != len(set(ids)): problems.append('Case IDs are not unique.')
    for c in cases:
        if c.get('eval') not in ('dialogue','multiturn','gaeilge'): problems.append(f"{c.get('id')}: unknown eval")
        if c.get('eval') == 'multiturn' and len(c.get('turns', [])) != 6: problems.append(f"{c.get('id')}: multiturn requires six turns")
        if c.get('eval') == 'gaeilge' and c.get('answer', {}).get('type') not in ('choice','exact_json'): problems.append(f"{c.get('id')}: missing objective answer")
    if not set(manifest.get('repeat_ids', [])).issubset(ids): problems.append('Repeat list contains unknown case IDs.')
    if version != '3.0':
        from .contracts import candidate_schema
        for case in cases:
            expected = candidate_schema(case)
            if case.get('response_schema') != expected:
                problems.append(f"{case['id']}: response schema does not match the output contract")
    actual = {k: sum(c.get('eval') == k for c in cases) for k in ('dialogue','multiturn','gaeilge')}
    if actual != manifest.get('counts'): problems.append(f'Suite counts {actual} do not match manifest counts {manifest.get("counts")}.')
    ga_counts = {g: sum(c.get('eval') == 'gaeilge' and c.get('subcategory') == g for c in cases) for g in ('grammar','meaning','code_switch')}
    if any(n != 8 for n in ga_counts.values()): problems.append(f'Gaeilge subcategory counts must be 8 each; found {ga_counts}.')
    return {'valid': not problems, 'problems': problems, 'suite_hash': digest,
            'counts': actual, 'gaeilge_counts': ga_counts,
            'blockers': qualification_blockers(root, manifest, digest)}


def _load_env(path: Path | None) -> dict[str, str]:
    values = {}
    if not path: return values
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('export '): line = line[7:].strip()
        if '=' not in line: raise ValueError(f'Invalid env-file line {n}')
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key): raise ValueError(f'Invalid env-file key on line {n}')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"): value = value[1:-1]
        values[key] = value
    return values


def _request_for(case: dict, turns: list[dict] | None = None) -> dict:
    if turns is None:
        messages = case.get('messages', [])
    else:
        messages = [{'role':'system','content':case['system']}, *turns]
    return {'messages': messages, 'max_output_tokens': case['max_output_tokens']}


def _judge_case(case: dict) -> dict:
    # Native decoding instructions are candidate transport metadata, not rubric input.
    return {key: value for key, value in case.items() if key != 'response_schema'}


def _rubric_axes(rubrics: dict, category: str) -> dict:
    return rubrics[category]


def _profile_for(category: str, manifest: dict, profiles: dict) -> dict | None:
    profile_id = manifest.get('judge_policy', {}).get(category)
    return profiles.get(profile_id) if profile_id else None


def _resolve_candidate(model: str, reasoning: str | None, profiles: dict) -> dict:
    profile=resolve_profile(model,reasoning,profiles)
    if profile.get('enabled') is False:
        raise ValueError(f"Profile {profile['id']} is unavailable: {profile.get('model_status','disabled')}")
    return profile


def _version_candidate_blockers(version: str, profile: dict) -> list[str]:
    if version == '3.2' and profile.get('provider') == 'anthropic':
        return ['Anthropic profiles are reserved for judging in Benchmark 3.2 and cannot be candidates.']
    return []


def dry_run(model: str, reasoning: str | None = None, budget: float = 5.0,
            root: Path = PACKAGE, env_file: Path | None = None, version: str = '3.0') -> dict:
    result = validate_suite(root, version)
    try:
        profiles = load_profiles(root/'config'/'providers.json')
        profile = _resolve_candidate(model, reasoning, profiles)
        result['candidate_profile'] = profile['id']
        result['blockers'].extend(_version_candidate_blockers(version, profile))
        if version != '3.0' and profile['provider'] not in STRUCTURED_PROVIDERS:
            result['blockers'].append('Candidate provider does not support native structured output.')
    except Exception as exc:
        result['blockers'].append(f'Candidate profile: {exc}')
        profile = None
        profiles = {}
    try:
        _load_env(env_file)
    except (OSError, ValueError) as exc:
        result['blockers'].append(f'Env file: {exc}')
    if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not __import__('math').isfinite(budget) or budget <= 0 or budget > 5:
        result['blockers'].append('Budget must be finite, greater than $0 and at most $5.')
    try:
        manifest, cases, rubrics, _ = load_suite(root, version)
        estimated = 0.0
        if profile:
            for case in cases:
                trials = 2 if case['id'] in manifest.get('repeat_ids', []) else 1
                for _ in range(trials):
                    if case['eval'] == 'multiturn':
                        msgs = [{'role':'system','content':case['system']}]
                        for turn_index,turn in enumerate(case['turns']):
                            if turn_index == 0 and case.get('initial_context'):
                                ctx=case['initial_context']; ctx=json.dumps(ctx,ensure_ascii=False) if isinstance(ctx,dict) else str(ctx)
                                turn='Captured initial scene context:\n'+ctx+'\n\nPlayer turn:\n'+turn
                            msgs.append({'role':'user','content':turn})
                            estimated += upper_cost(profile,msgs,case['max_output_tokens'],case.get('response_schema'))
                            msgs.append({'role':'assistant','content':'x'*min(case['max_output_tokens']*4,64000)})
                    else:
                        req = _request_for(case)
                        estimated += upper_cost(profile, req['messages'], req['max_output_tokens'],case.get('response_schema'))
                    if case['eval'] in ('dialogue','multiturn'):
                        jp = _profile_for(case['eval'], manifest, profiles)
                        if jp:
                            projected = _project_transcript(case,case['max_output_tokens']) if case['eval']=='multiturn' else [{'role':'assistant','content':'x'*min(case['max_output_tokens']*4,64000)}]
                            ji={**_judge_case(case),'candidate_response':json.dumps(projected,ensure_ascii=False),'transcript':projected}
                            estimated += upper_cost(jp,[{'role':'user','content':json.dumps(ji,ensure_ascii=False)}],judge_output_limit(jp),{'rubric':rubrics[case['eval']]})
            result['estimated_max_usd'] = estimated
            if estimated > budget: result['budget_warning']=f'Worst-case full-suite reservation ${estimated:.4f} exceeds ${budget:.2f}; per-call reservations enforce the cap and may end the run as budget DNF.'
    except Exception as exc: result['blockers'].append(f'Pricing or suite error: {exc}')
    return result


def _response_record(resp) -> dict:
    return {'text':resp.text,'usage':resp.usage,'model':resp.model,'elapsed_ms':resp.elapsed_ms,'ttft_ms':resp.ttft_ms,'raw':resp.raw}


def _settle_error(ledger: Ledger, call_id: str, profile: dict, exc: ProviderError) -> bool:
    if exc.billing_uncertain:
        ledger.fail(call_id, uncertain=True)
        return True
    usage = exc.payload.get('usage') if isinstance(exc.payload, dict) else None
    if isinstance(usage, dict):
        try:
            cost = actual_cost(profile, usage)
        except UncertainBilling:
            ledger.fail(call_id, uncertain=True)
            return True
        ledger.commit(call_id, {'error':str(exc),'kind':exc.kind,'payload':exc.payload,'usage':usage}, cost)
        return False
    ledger.fail(call_id, uncertain=False)
    return False


def _recorded_failure(errors: list[dict], case_id: str, trial: int, step: int | str, kind: str) -> bool:
    return any(e.get('case_id') == case_id and e.get('trial', 0) == trial
               and e.get('step') == step and e.get('kind') == kind for e in errors)


def _error_cost(profile: dict, payload: dict) -> float | None:
    usage = payload.get('usage') if isinstance(payload, dict) else None
    if not isinstance(usage, dict): return None
    try: return actual_cost(profile, usage)
    except UncertainBilling: return None


def _dialogue_contract(messages: list[dict]) -> bool:
    return any('must respond with a json object' in m.get('content','').lower() for m in messages if m.get('role') == 'system')


def _npc_text(text: str, messages: list[dict]) -> tuple[str, str | None]:
    if not _dialogue_contract(messages): return text, None
    try: value = json.loads(text)
    except Exception: return '', 'Expected a JSON object containing NPC dialogue.'
    if not isinstance(value, dict) or not isinstance(value.get('dialogue'), str) or not value['dialogue'].strip():
        return '', 'NPC JSON output must contain non-empty dialogue.'
    for key in ('action','mood'):
        if key in value and not isinstance(value[key], str): return '', f'NPC JSON {key} must be text.'
    if 'language_hints' in value and not isinstance(value['language_hints'], list): return '', 'NPC JSON language_hints must be an array.'
    if 'language_hints' in value and any(not isinstance(x,dict) or set(x) != {'word','pronunciation','meaning'} or any(not isinstance(x[k],str) for k in x) for x in value['language_hints']):
        return '', 'Each NPC language hint must contain word, pronunciation, and meaning text.'
    if 'assigned_task' in value and value['assigned_task'] is not None and not isinstance(value['assigned_task'], str):
        return '', 'NPC JSON assigned_task must be text or null.'
    allowed = {'dialogue','action','mood','language_hints','assigned_task'}
    if set(value)-allowed: return '', 'NPC JSON contains unsupported fields.'
    return value['dialogue'], None


def _performance_summary(results: list[dict], cases: list[dict]) -> dict:
    by_id = {c['id']: c for c in cases}
    summary = {}
    for category in ('dialogue','multiturn','gaeilge'):
        rows = [r for r in results if r.get('trial',0)==0 and r.get('eval')==category and r.get('score') is not None]
        values = [r['score'] for r in rows]
        entry = {'n':len(values),'mean_score':sum(values)/len(values) if values else None,
                 'median_score':__import__('statistics').median(values) if values else None,
                 'stddev_score':__import__('statistics').pstdev(values) if values else None,
                 'min_score':min(values) if values else None,'max_score':max(values) if values else None}
        records=[rec for row in rows for rec in row.get('response_records',[])]
        def timing(key):
            import math
            vals=sorted(r[key] for r in records if isinstance(r.get(key),(int,float)) and not isinstance(r[key],bool) and math.isfinite(r[key]) and r[key]>=0)
            return {'n':len(vals),'p50':vals[max(0,math.ceil(len(vals)*.5)-1)] if vals else None,'p95':vals[max(0,math.ceil(len(vals)*.95)-1)] if vals else None,'unit':'generation request; nearest-rank percentile'}
        entry['latency_ms']=timing('elapsed_ms')
        entry['ttft_ms']=timing('ttft_ms')
        if category == 'gaeilge':
            correct = sum(v == 100 for v in values)
            entry['accuracy'] = {'correct':correct,'count':len(values),'interval_95':None,'dependency_note':'The same eight source examples occur across three subcategories; pooled Wilson independence is not assumed.'}
            entry['subcategories'] = {}
            for group in ('grammar','meaning','code_switch'):
                group_rows=[r for r in rows if by_id.get(r['case_id'],{}).get('subcategory')==group]
                successes=sum(r['score']==100 for r in group_rows)
                entry['subcategories'][group]={'correct':successes,'count':len(group_rows),'interval_95':wilson(successes,len(group_rows))}
        summary[category]=entry
    return summary


def _project_transcript(case: dict, max_output_tokens: int) -> list[dict]:
    bound = 'x' * min(max_output_tokens * 4, 64000)
    turns = list(case.get('turns', []))
    if turns and case.get('initial_context'):
        context=case['initial_context']; context=json.dumps(context,ensure_ascii=False) if isinstance(context,dict) else str(context)
        turns[0]='Captured initial scene context:\n'+context+'\n\nPlayer turn:\n'+turns[0]
    return [row for turn in turns for row in ({'role':'user','content':turn},{'role':'assistant','content':bound})]


def run(model: str, *, reasoning: str | None = None, budget: float = 5.0,
        root: Path = PACKAGE, output: Path | None = None, run_id: str | None = None,
        resume: str | None = None, dry: bool = False, env_file: Path | None = None,
        client=None, version: str = '3.0') -> dict:
    root = Path(root)
    if dry:
        return dry_run(model, reasoning, budget, root, env_file, version)
    if isinstance(budget, bool) or not isinstance(budget, (int,float)) or not __import__('math').isfinite(budget) or not 0 < budget <= 5:
        raise ValueError('Budget must be finite, greater than $0, and at most $5.')
    profiles = load_profiles(root/'config'/'providers.json')
    profile = _resolve_candidate(model, reasoning, profiles)
    candidate_blockers = _version_candidate_blockers(version, profile)
    if candidate_blockers: raise ValueError('Candidate profile: ' + ' '.join(candidate_blockers))
    if version != '3.0' and profile['provider'] not in STRUCTURED_PROVIDERS:
        raise ValueError('Candidate provider does not support native structured output.')
    manifest, cases, rubrics, suite_hash = load_suite(root, version)
    validation = validate_suite(root, version)
    if not validation['valid']: raise ValueError('Invalid suite: ' + ' '.join(validation['problems']))
    blockers = qualification_blockers(root, manifest, suite_hash)
    if blockers: raise ValueError('Paid launch blocked: ' + ' '.join(blockers))
    qualification = json.loads((root/'qualification'/safe_id(version)/'status.json').read_text())
    selected_reasoning = profile.get('reasoning')
    run_id = safe_id(resume or run_id or uuid.uuid4().hex[:12])
    outroot = Path(output or root/'output')
    work = outroot/run_id
    work.mkdir(parents=True, exist_ok=True)
    state_path = work/'run.json'
    if resume and state_path.exists():
        run_data = json.loads(state_path.read_text())
        if run_data.get('suite_hash') != suite_hash or run_data.get('model') != model or run_data.get('reasoning') != selected_reasoning:
            raise ValueError('Resume target differs from the original run configuration.')
        current_judges={pid:profiles[pid] for pid in set(manifest.get('judge_policy',{}).values()) if pid in profiles}
        if run_data.get('candidate_profile') != profile or run_data.get('judge_profiles') != current_judges:
            raise ValueError('Resume provider profiles differ from the original run configuration.')
        if run_data.get('status') == 'complete': return run_data
        if run_data.get('status') == 'dnf':
            raise ValueError('A finalized DNF is immutable; start a new run ID after resolving its cause.')
    else:
        run_data = {'run_id':run_id,'version':version,'model':model,'reasoning':selected_reasoning,'status':'running',
            'failure_cause':None,'reason':None,'completed_at':utc_now(),'cost_usd':0.0,'scores':{},'overall':None,
            'coverage':{},'case_results':[],'requests':[],'judgments':[],'errors':[],'engine':manifest.get('engine'),
            'suite_hash':suite_hash,'uncertainty':{},'variability':{},'budget_usd':budget,
            'budget_status':'within_cap','spending_exposure_usd':0.0,
            'actual_cost_basis':'provider usage priced with the pinned profile rates',
            'qualification_status':qualification['status'],
            'score_status':'provisional' if qualification['status']=='provisional' else 'human_validated',
            'validation_basis':qualification.get('validation_basis','owner_reference_ratings'),
            'candidate_profile':profile,
            'judge_profiles':{pid:profiles[pid] for pid in set(manifest.get('judge_policy',{}).values()) if pid in profiles}}
    run_data['budget_usd']=budget
    run_data.setdefault('budget_status','within_cap')
    run_data.setdefault('spending_exposure_usd',0.0)
    run_data.setdefault('actual_cost_basis','provider usage priced with the pinned profile rates')
    atomic_json(state_path,run_data)
    env = _load_env(env_file)
    creds = {**os.environ, **env}
    client = client or NativeClient(credentials=creds)
    ledger = Ledger(work/'ledger.sqlite', budget)
    trial_cases = [(c, t) for c in cases for t in (range(2) if c['id'] in manifest.get('repeat_ids',[]) else range(1))]
    results = run_data['case_results']
    judgments = run_data['judgments']
    errors = run_data['errors']
    failures = int(run_data.get('failure_events', 0))
    try:
        for case, trial in trial_cases:
            key = f"{case['id']}:{trial}"
            if any(r.get('case_id') == case['id'] and r.get('trial',0) == trial for r in results): continue
            category = case['eval']
            messages = []
            if category == 'multiturn':
                messages = [{'role':'system','content':case['system']}]
            else: messages = list(case.get('messages', []))
            candidate_texts = []
            candidate_records = []
            transcript = []
            candidate_failed = False
            last_response = None
            nturns = 6 if category == 'multiturn' else 1
            for step in range(nturns):
                turn_content = case['turns'][step] if category == 'multiturn' else None
                if category == 'multiturn':
                    if step == 0 and case.get('initial_context'):
                        context = case['initial_context']
                        if isinstance(context, dict): context = json.dumps(context,ensure_ascii=False)
                        turn_content = 'Captured initial scene context:\n'+str(context)+'\n\nPlayer turn:\n'+turn_content
                    messages.append({'role':'user','content':turn_content})
                prompt_messages = [dict(message) for message in messages]
                request = {'profile':profile['id'],'messages':prompt_messages,'max_output_tokens':case['max_output_tokens']}
                schema = case.get('response_schema')
                if schema is not None:
                    request['response_schema'] = schema
                    request['output_protocol'] = 'native-json-schema-v1'
                call_id = f'{key}:candidate:{step}'
                cached = ledger.cached(call_id, request)
                if cached is not None:
                    record = cached
                    if not any(x.get('id') == call_id for x in run_data['requests']):
                        run_data['requests'].append({'id':call_id,'request':request,'response':record,
                            'cost_usd':actual_cost(profile,record.get('usage',{})) if record.get('usage') else None})
                    if 'error' in record:
                        error_kind=record.get('kind','provider_refusal')
                        err = {'kind':error_kind,'reason':record['error'],'raw':record.get('payload',{}),'billing_uncertain':False}
                        new_error = not _recorded_failure(errors, case['id'], trial, step, error_kind)
                        if new_error:
                            errors.append({'case_id':case['id'],'trial':trial,'step':step,**err})
                        if error_kind == 'output_limit':
                            run_data['failure_cause']='setup'
                            run_data['reason']='Configured output token limit reached.'
                            atomic_json(state_path,run_data)
                            raise RuntimeError('Configured output token limit reached')
                        run_data['failure_cause']='model' if error_kind=='provider_refusal' else ('setup' if error_kind=='auth' else 'infrastructure')
                        if error_kind != 'provider_refusal':
                            atomic_json(state_path,run_data)
                            raise RuntimeError(f'Provider failure ({error_kind})')
                        if new_error: failures += 1
                        run_data['failure_events']=failures
                        atomic_json(state_path,run_data)
                        if failures >= 2: raise RuntimeError('Repeated confirmed model failures')
                        candidate_failed=True
                        record={'text':'','usage':record.get('usage',{}),'raw':record.get('payload',{}),'model':profile['model'],'elapsed_ms':None,'ttft_ms':None}
                else:
                    reserve = upper_cost(profile, prompt_messages, case['max_output_tokens'], schema)
                    future = 0.0
                    if category == 'multiturn':
                        projected = [dict(x) for x in prompt_messages]
                        for next_step in range(step+1,nturns):
                            projected.append({'role':'assistant','content':'x' * min(case['max_output_tokens'] * 4, 64000)})
                            projected.append({'role':'user','content':case['turns'][next_step]})
                            future += upper_cost(profile, projected, case['max_output_tokens'], schema)
                    if category in ('dialogue','multiturn'):
                        jp = _profile_for(category, manifest, profiles)
                        if jp:
                            projected_transcript = _project_transcript(case,case['max_output_tokens']) if category == 'multiturn' else [{'role':'assistant','content':'x' * min(case['max_output_tokens']*4,64000)}]
                            judge_item = {**_judge_case(case),'candidate_response':json.dumps(projected_transcript,ensure_ascii=False),'transcript':projected_transcript}
                            jm = [{'role':'user','content':json.dumps(judge_item,ensure_ascii=False)}]
                            future += upper_cost(jp, jm, judge_output_limit(jp), {'rubric':rubrics[category]})
                    ledger.reserve(call_id, request, reserve, future)
                    try:
                        response = client.generate(profile, prompt_messages, case['max_output_tokens'], **({'response_schema': schema} if schema is not None else {}))
                        cost = actual_cost(profile, response.usage)
                        record = _response_record(response)
                        ledger.commit(call_id, record, cost)
                        run_data['requests'].append({'id':call_id,'request':request,'response':record,'cost_usd':cost})
                    except ProviderError as exc:
                        settled_uncertain = _settle_error(ledger, call_id, profile, exc)
                        errors.append({'case_id':case['id'],'trial':trial,'step':step,'kind':exc.kind,'reason':str(exc),'raw':exc.payload,'billing_uncertain':exc.billing_uncertain or settled_uncertain})
                        run_data['requests'].append({'id':call_id,'request':request,'response':exc.payload,'cost_usd':None if settled_uncertain else _error_cost(profile, exc.payload)})
                        if exc.billing_uncertain or settled_uncertain: run_data['failure_cause']='unknown'
                        elif exc.kind in ('auth', 'output_limit'): run_data['failure_cause']='setup'
                        elif exc.kind == 'provider_refusal': run_data['failure_cause']='model'
                        else: run_data['failure_cause']='infrastructure'
                        if exc.billing_uncertain or settled_uncertain: raise UncertainBilling(str(exc))
                        if exc.kind == 'output_limit':
                            run_data['reason']='Configured output token limit reached.'
                            atomic_json(state_path,run_data)
                            raise RuntimeError('Configured output token limit reached')
                        if exc.kind != 'provider_refusal': raise RuntimeError(f'Provider failure ({exc.kind})')
                        failures += 1
                        run_data['failure_events']=failures
                        atomic_json(state_path,run_data)
                        if failures >= 2: raise RuntimeError('Repeated confirmed model failures')
                        candidate_failed = True
                        record = {'text':'','usage':exc.payload.get('usage',{}),'raw':exc.payload,'model':profile['model'],'elapsed_ms':None,'ttft_ms':None}
                last_response = record
                npc_text, contract_error = ('',None) if candidate_failed else _npc_text(record.get('text',''), prompt_messages)
                if not candidate_failed and schema is not None:
                    from .contracts import validate_output
                    try:
                        validate_output(record.get('text', ''), schema)
                    except ValueError as exc:
                        contract_error = str(exc)
                if contract_error:
                    errors.append({'case_id':case['id'],'trial':trial,'step':step,'kind':('npc_contract' if category in ('dialogue','multiturn') else 'output_contract'),'reason':contract_error,'raw':record.get('text'),'billing_uncertain':False})
                    failures += 1; run_data['failure_events']=failures; run_data['failure_cause']='model'
                    atomic_json(state_path,run_data)
                    if failures >= 2: raise RuntimeError('Repeated confirmed model failures')
                    candidate_failed=True
                candidate_texts.append(npc_text)
                candidate_records.append(record)
                if category == 'multiturn':
                    transcript.extend([{'role':'user','content':turn_content},{'role':'assistant','content':npc_text,'raw':record.get('text')}])
                if candidate_failed: break
                if category == 'multiturn': messages.append({'role':'assistant','content':record['text']})
            total_text = '\n'.join(candidate_texts)
            score = None
            if candidate_failed:
                score = 0.0
            elif category == 'gaeilge':
                try: score = objective_score(total_text, case['answer'])
                except Exception as exc:
                    score = 0.0
                    errors.append({'case_id':case['id'],'trial':trial,'kind':'malformed','reason':str(exc),'raw':total_text})
                    failures += 1
                    run_data['failure_events']=failures
                    run_data['failure_cause']='model'
                    if failures >= 2: raise RuntimeError('Repeated confirmed model failures')
            else:
                judge_profile = _profile_for(category, manifest, profiles)
                judge_item = {**_judge_case(case),'candidate_response':total_text,'transcript':transcript or [{'role':'assistant','content':total_text,'raw':candidate_records[0].get('text','')}]}
                judge_limit = judge_output_limit(judge_profile)
                judge_request = {'profile':judge_profile['id'],'item':judge_item,'rubric':rubrics[category]}
                if judge_limit != JUDGE_MAX_OUTPUT_TOKENS:
                    judge_request['max_output_tokens'] = judge_limit
                judge_id = f'{key}:judge'
                cached_judge = ledger.cached(judge_id, judge_request)
                if cached_judge is not None:
                    judged = cached_judge
                    if not any(x.get('id') == judge_id for x in run_data['requests']):
                        run_data['requests'].append({'id':judge_id,'request':judge_request,'response':judged,
                            'cost_usd':actual_cost(judge_profile,judged['usage']) if judged.get('usage') else None})
                    if 'error' in judged:
                        kind = judged.get('kind', 'malformed')
                        if not _recorded_failure(errors, case['id'], trial, 'judge', kind):
                            errors.append({'case_id':case['id'],'trial':trial,'step':'judge','kind':kind,'reason':judged['error'],
                                           'raw':judged.get('payload',{}),'billing_uncertain':False})
                        run_data['failure_cause']='setup' if kind in ('auth','output_limit') else 'infrastructure'
                        if kind == 'output_limit': run_data['reason']='Configured output token limit reached.'
                        atomic_json(state_path,run_data)
                        raise RuntimeError('Configured output token limit reached' if kind == 'output_limit' else f'Judge failure ({kind})')
                else:
                    jm = [{'role':'user','content':json.dumps(judge_item,ensure_ascii=False)}]
                    reserve = upper_cost(judge_profile,jm,judge_limit,{'rubric':rubrics[category],'candidate':judge_item})
                    ledger.reserve(judge_id, judge_request, reserve)
                    try:
                        judged = judge_response(client, judge_profile, judge_item, rubrics[category])
                        cost = actual_cost(judge_profile, judged['usage'])
                        ledger.commit(judge_id, judged, cost)
                        run_data['requests'].append({'id':judge_id,'request':judge_request,'response':judged,'cost_usd':cost})
                    except ProviderError as exc:
                        settled_uncertain = _settle_error(ledger, judge_id, judge_profile, exc)
                        errors.append({'case_id':case['id'],'trial':trial,'step':'judge','kind':exc.kind,'reason':str(exc),'raw':exc.payload,'billing_uncertain':exc.billing_uncertain or settled_uncertain})
                        run_data['requests'].append({'id':judge_id,'request':judge_request,'response':exc.payload,'cost_usd':None if settled_uncertain else _error_cost(judge_profile, exc.payload)})
                        run_data['failure_cause']='unknown' if exc.billing_uncertain or settled_uncertain else ('setup' if exc.kind in ('auth','output_limit') else 'infrastructure')
                        if exc.billing_uncertain or settled_uncertain: raise UncertainBilling(str(exc))
                        if exc.kind == 'output_limit': run_data['reason']='Configured output token limit reached.'
                        raise RuntimeError('Configured output token limit reached' if exc.kind == 'output_limit' else f'Judge failure ({exc.kind})')
                if judged.get('axes'):
                    score = rubric_score(judged['axes'], rubrics[category])
                judgments.append({'case_id':case['id'],'trial':trial,**judged})
            results.append({'case_id':case['id'],'trial':trial,'eval':category,'score':score,
                            'response':'\n'.join(candidate_texts),'response_records':candidate_records})
            run_data['cost_usd'] = ledger.spent
            atomic_json(state_path, run_data)
        agg = aggregate(results,cases)
        run_data.update(agg)
        run_data['variability'] = variability(results)
        run_data['uncertainty'] = _performance_summary(results,cases)
        required_trials = {(c['id'],t) for c in cases for t in (range(2) if c['id'] in manifest.get('repeat_ids',[]) else range(1))}
        finished_trials = {(r['case_id'],r.get('trial',0)) for r in results if r.get('score') is not None}
        run_data['trial_coverage']={'completed':len(required_trials & finished_trials),'required':len(required_trials)}
        run_data['cost_usd'] = ledger.spent
        run_data['status'] = 'complete' if agg['overall'] is not None and len(required_trials & finished_trials) == len(required_trials) and run_data.get('failure_cause') not in ('unknown','setup','budget','infrastructure') else 'dnf'
        if run_data['status'] == 'dnf' and not run_data.get('failure_cause'): run_data['failure_cause']='unknown'
    except (BudgetError, UncertainBilling) as exc:
        run_data['status']='dnf'; run_data['failure_cause']='budget' if isinstance(exc,BudgetError) and not isinstance(exc,UncertainBilling) else 'unknown'; run_data['reason']=str(exc)
    except Exception as exc:
        run_data['status']='dnf'; run_data['failure_cause']=run_data.get('failure_cause') or 'unknown'; run_data['reason']=str(exc)
    finally:
        # Keep complete category scores and case coverage on budget/infrastructure DNF.
        try:
            partial=aggregate(results,cases)
            run_data['scores']=partial['scores']
            run_data['coverage']=partial['coverage']
            run_data['overall']=partial['overall'] if run_data.get('status')=='complete' else None
            run_data['variability']=variability(results)
            run_data['uncertainty']=_performance_summary(results,cases)
            required_trials={(c['id'],t) for c in cases for t in (range(2) if c['id'] in manifest.get('repeat_ids',[]) else range(1))}
            finished_trials={(r['case_id'],r.get('trial',0)) for r in results if r.get('score') is not None}
            run_data['trial_coverage']={'completed':len(required_trials & finished_trials),'required':len(required_trials)}
        except Exception as exc:
            run_data.setdefault('errors',[]).append({'kind':'summary','reason':str(exc)})
        run_data['errors']=errors
        run_data['failure_events']=failures
        run_data['cost_usd']=ledger.spent
        run_data['spending_exposure_usd']=ledger.exposure
        if ledger.exposure > ledger.spent + 1e-12:
            run_data['budget_status']='billing_uncertain'
        elif run_data.get('failure_cause')=='budget' or ledger.exposure >= budget - 1e-12:
            run_data['budget_status']='cap_reached'
        else:
            run_data['budget_status']='within_cap'
        run_data['completed_at']=utc_now()
        atomic_json(state_path,run_data)
        ledger.close()
    if run_data['status']=='dnf':
        atomic_json(work/'issue.json',issue_payload(run_data))
    if run_data['status'] in ('complete','dnf'):
        publish_run(root/'results',run_data)
    return run_data
