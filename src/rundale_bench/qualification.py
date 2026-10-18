"""Blind native-API judge trials, held-out validation, and explicit pending gates."""
from __future__ import annotations
import hashlib
import json
import math
import statistics
from pathlib import Path
from .accounting import Ledger, BudgetError, actual_cost, upper_cost
from .judges import judge_response
from .bias import build_checks, summarize_biases
from .providers import NativeClient, ProviderError, load_profiles
from .storage import atomic_json, utc_now

PROFILES = ('gpt-6.1-sol-judge-high', 'jev-1.13.0')

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_review(root: Path) -> tuple[dict,dict,dict]:
    pack = json.loads((root/'review/pack.json').read_text())
    rubrics = json.loads((root/'review/rubric.json').read_text())['categories']
    split = json.loads((root/'review/split.json').read_text())
    return pack, rubrics, split

def owner_references(root: Path, path: Path) -> dict:
    export = json.loads(path.read_text())
    if export.get('pack_sha256') != digest(root/'review/pack.json'):
        raise ValueError('Reference ratings do not match the frozen review pack')
    if export.get('rubric_sha256') != digest(root/'review/rubric.json'):
        raise ValueError('Reference ratings do not match the frozen rubric')
    if export.get('track') != 'owner':
        raise ValueError('English owner reference ratings required; no Irish fluency claim is requested')
    pack,rubrics,split = load_review(root)
    cases = {i['id']:i for i in pack['items'] if i['category'] in ('dialogue','multiturn')}
    rows = export['items']
    if len(rows) != len(cases) or {r['id'] for r in rows} != set(cases):
        raise ValueError('Reference export must cover all 16 unique English cases')
    refs = {}
    for row in rows:
        axes = row.get('axes', {})
        required = rubrics[cases[row['id']]['category']]
        if set(axes) != set(required):
            raise ValueError('Reference axes do not match rubric')
        if any(v is None for v in axes.values()):
            raise ValueError('Cannot-judge axes remain unlabelled; qualification is pending')
        if any(type(v) is not int or not 1<=v<=5 for v in axes.values()):
            raise ValueError('Reference scores must be integers 1–5')
        refs[row['id']] = axes
    return refs

def collect(root: Path, credentials: dict, client: NativeClient|None=None, *, repair_grade_order: bool=False) -> dict:
    pack,rubrics,split = load_review(root)
    english = [i for i in pack['items'] if i['category'] in ('dialogue','multiturn')]
    profiles = load_profiles(root/'config/providers.json')
    out = root/'output/qualification';out.mkdir(parents=True,exist_ok=True)
    checks = build_checks({i['id']:i for i in english}, split)
    protocol_hash=hashlib.sha256(json.dumps(checks,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    contract = {'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'split_sha256':digest(root/'review/split.json'),'bias_protocol_sha256':protocol_hash,'profiles':{k:profiles[k] for k in PROFILES},'adapter_protocols':{'typesafe_grade_order':'state-and-criteria-v2'}}
    frozen = out/'contract.json'
    if frozen.exists():
        existing=json.loads(frozen.read_text())
        if existing != contract:
            stable_keys=set(contract)|set(existing)
            amendable={'bias_protocol_sha256','adapter_protocols'}
            if (not repair_grade_order
                    or any(existing.get(k)!=contract.get(k) for k in stable_keys-amendable)):
                raise ValueError('Qualification contract changed; do not reuse its held-out evidence')
            old_controls_path=out/'controls.json'
            old_controls=json.loads(old_controls_path.read_text()) if old_controls_path.exists() else None
            if old_controls is None:
                raise ValueError('Cannot amend without preserving the previous control payloads')
            contract_sha=hashlib.sha256(json.dumps(existing,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            archive=out/'contracts'/f'{contract_sha}.json';archive.parent.mkdir(parents=True,exist_ok=True)
            archived={'contract':existing,'controls':old_controls}
            if archive.exists() and json.loads(archive.read_text()) != archived:
                raise ValueError('Contract archive already contains different evidence')
            if not archive.exists(): atomic_json(archive,archived)
    atomic_json(frozen,contract)
    atomic_json(out/'controls.json',{'checks':checks})
    ledger = Ledger(out/'ledger.sqlite',10)
    results = json.loads((out/'judgments.json').read_text()) if (out/'judgments.json').exists() else {}
    client = client or NativeClient(credentials)
    requests = [(i['id'],dict(i,eval=i['category']),None) for i in english]
    requests += [(check['id'],check['item'],check.get('grade_order')) for check in checks]
    selected_call_ids=set()
    try:
        for profile_id in PROFILES:
            results.setdefault(profile_id,{})
            for rid,item,grade_order in requests:
                request={'profile':profiles[profile_id],'item':item,'rubric':rubrics[item['category']],'grade_order':grade_order}
                if profiles[profile_id]['provider'] == 'typesafe' and grade_order is not None:
                    request['adapter_revision']='state-and-criteria-v2'
                cached=ledger.cached_request(request)
                if cached is not None:
                    call_id, answer = cached
                    selected_call_ids.add(call_id)
                    if 'axes' not in answer:
                        raise ValueError('A previous paid judgment failed; investigate it before continuing')
                    results[profile_id][rid]=answer
                    continue
                request_sha=ledger.request_digest(request)
                call_id=f'{profile_id}:{rid}:{request_sha[:12]}'
                bound=upper_cost(profiles[profile_id],[{'role':'user','content':json.dumps(item,ensure_ascii=False)}],4096,request['rubric'])
                ledger.reserve(call_id,request,bound)
                try:
                    answer=judge_response(client,profiles[profile_id],item,request['rubric'],grade_order=grade_order)
                except ProviderError as exc:
                    if exc.payload.get('usage'):
                        known={'error':exc.kind,'usage':exc.payload['usage'],'raw':exc.payload}
                        ledger.commit(call_id,known,actual_cost(profiles[profile_id],known['usage']))
                    else:
                        ledger.fail(call_id,exc.billing_uncertain)
                    atomic_json(out/'error.json',{'profile':profile_id,'request_id':rid,'kind':exc.kind,'billing_uncertain':exc.billing_uncertain,'raw':exc.payload})
                    raise
                ledger.commit(call_id,answer,actual_cost(profiles[profile_id],answer['usage']))
                selected_call_ids.add(call_id)
                results[profile_id][rid]=answer
                atomic_json(out/'judgments.json',results)
        superseded=[]
        for old_id,response in ledger.committed_calls():
            if old_id in selected_call_ids: continue
            parts=old_id.split(':',2)
            superseded.append({'profile':parts[0],'request_id':parts[1] if len(parts)>1 else old_id,
                'reason':'This committed receipt belongs to an earlier request or qualification protocol and was superseded by the current collection.','response':response})
        if superseded: atomic_json(out/'superseded.json',superseded)
        elif (out/'superseded.json').exists(): (out/'superseded.json').unlink()
        check_metadata=[{k:v for k,v in check.items() if k!='item'} for check in checks]
        receipt={'status':'collected','judgments_path':str(out/'judgments.json'),'checks':check_metadata,'bias_diagnostics':summarize_biases(checks,results,profiles),'cost_usd':ledger.spent,'cost_basis':'provider usage × recorded prices; not invoice receipt',**contract}
        history=[]
        for path in sorted((out/'contracts').glob('*.json')):
            archive=json.loads(path.read_text())
            archived_contract=archive.get('contract',archive)
            if archived_contract.get('pack_sha256') != contract['pack_sha256']:
                raise ValueError('Archived contract does not match this calibration pack')
            history.append({'contract':{k:archived_contract[k] for k in contract if k in archived_contract},
                            'controls':archive.get('controls')})
        if history: receipt['contract_history']=history
        if superseded: receipt['superseded_evidence']=superseded
        atomic_json(out/'collection.json',receipt)
        return receipt
    finally:
        ledger.close()

def metrics(ids: list[str], refs: dict, judgments: dict) -> dict:
    errors=[];misses=[]
    for cid in ids:
        if cid not in judgments or 'axes' not in judgments[cid]:
            return {'passed':False,'reason':'Missing judgment','cases':len(ids)}
        for axis,expected in refs[cid].items():
            actual=judgments[cid]['axes'].get(axis)
            if type(actual) is not int or not 1<=actual<=5:
                return {'passed':False,'reason':'Malformed axis grade','cases':len(ids)}
            errors.append(abs(expected-actual))
            if expected<=2 and actual>=4:misses.append({'id':cid,'axis':axis})
    mae=statistics.mean(errors) if errors else None
    return {'passed':mae is not None and mae<=.75 and not misses,'cases':len(ids),'axes':len(errors),'mae':mae,'severe_misses':misses,'evidence_strength':'small development-launch sample; not population accuracy'}

def evaluate(root:Path, references:Path) -> dict:
    target=root/'qualification/3.0/status.json'
    if target.exists() and json.loads(target.read_text()).get('status')=='provisional':
        raise ValueError('Benchmark 3.0 qualification is provisional; human evaluation requires a new benchmark version')
    manifest_path=root/'suites/3.0/manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text()).get('validation_mode')=='provisional':
        raise ValueError('Benchmark 3.0 validation is provisional; human evaluation requires a new benchmark version')
    refs=owner_references(root,references)
    pack,rubrics,split=load_review(root);by={i['id']:i for i in pack['items']}
    out=root/'output/qualification';collection=json.loads((out/'collection.json').read_text());judgments=json.loads((out/'judgments.json').read_text())
    for file,key in [('review/pack.json','pack_sha256'),('review/rubric.json','rubric_sha256'),('review/split.json','split_sha256')]:
        if collection[key]!=digest(root/file):raise ValueError('Frozen qualification inputs changed')
    current_profiles=load_profiles(root/'config/providers.json')
    if collection['profiles']!={k:current_profiles[k] for k in PROFILES}:
        raise ValueError('Native profiles changed after qualification collection')
    controls=build_checks({i['id']:i for i in pack['items'] if i['category'] in ('dialogue','multiturn')},split)
    protocol_hash=hashlib.sha256(json.dumps(controls,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if collection.get('bias_protocol_sha256')!=protocol_hash:
        raise ValueError('Qualification bias protocol changed or was not recorded')
    if collection['checks']!=[{k:v for k,v in c.items() if k!='item'} for c in controls]:
        raise ValueError('Qualification control metadata does not match its frozen protocol')
    selection={};judges={};all_metrics={}
    for category in ('dialogue','multiturn'):
        ids=[cid for cid in split['selection'] if by[cid]['category']==category]
        all_metrics[category]={}
        eligible=[]
        for pid in PROFILES:
            m=metrics(ids,refs,judgments[pid]);all_metrics[category][pid]={'selection':m}
            relevant=[c for c in collection['checks'] if by[c['source_id']]['category']==category and c.get('expected_invariant',True)]
            matches=total=0
            for check in relevant:
                primary=judgments[pid][check['source_id']]['axes'];repeat=judgments[pid][check['id']]['axes']
                for axis,value in primary.items():total+=1;matches+=repeat.get(axis)==value
            agreement=matches/total if total else None
            all_metrics[category][pid]['repeat_agreement']={'matching_axes':matches,'axes':total,'fraction':agreement}
            if m['passed'] and agreement is not None and agreement>=.9:
                usagecost=sum(actual_cost(collection['profiles'][pid],row['usage']) for row in judgments[pid].values())
                eligible.append((m['mae'],usagecost,pid))
        if not eligible:
            judges[category]={'qualified':False,'reason':'No candidate passed selection and repeat gates'};continue
        best=min(e[0] for e in eligible);selected=min((e for e in eligible if e[0]-best<.1),key=lambda e:e[1])[2]
        valid_ids=[cid for cid in split['validation'] if by[cid]['category']==category]
        validation=metrics(valid_ids,refs,judgments[selected]);all_metrics[category][selected]['validation']=validation
        judges[category]={'profile_id':selected,'qualified':validation['passed'],'validation':validation}
    qualified=all(j['qualified'] for j in judges.values())
    manifest=json.loads(manifest_path.read_text())
    suite_rubrics=json.loads((root/'suites/3.0/rubrics.json').read_text())
    if suite_rubrics != {k:rubrics[k] for k in ('dialogue','multiturn')}:
        raise ValueError('Review anchors differ from launch rubric')
    if qualified:
        policy={k:v['profile_id'] for k,v in judges.items()}
        if manifest.get('status')=='ready' and manifest.get('judge_policy')!=policy:
            raise ValueError('Qualified judge policy is frozen; create a new benchmark version')
        manifest.update(status='ready',judge_policy=policy,judge_profiles={pid:current_profiles[pid] for pid in sorted(set(policy.values()))})
        manifest.pop('providers_sha256',None)
        manifest.pop('launch_blocker',None)
    receipt={'status':'qualified' if qualified else 'pending','qualified_at':utc_now() if qualified else None,'suite_hash':hashlib.sha256((json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest() if qualified else digest(manifest_path),'review_pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'suites/3.0/rubrics.json'),'references_sha256':digest(references),'judges':judges,'metrics':all_metrics,'scope':'English only; Irish style diagnostics unqualified; objective Irish keys require source evidence','cost_usd':collection['cost_usd'],'thresholds':{'mae_max':.75,'severe_misses_max':0,'repeat_agreement_min':.9},'limitations':['Only four held-out cases per English eval; no general accuracy guarantee.','Authorised owner preference reference, not expert panel consensus.']}
    # Never overwrite qualification with a new judge silently inside a frozen version.
    if target.exists():
        old=json.loads(target.read_text())
        if old.get('status')=='qualified':
            stable=lambda x:{k:v for k,v in x.items() if k!='qualified_at'}
            if stable(old)!=stable(receipt):raise ValueError('Qualified configuration is frozen; create a new benchmark version')
            receipt=old
    if qualified:
        # Both writes are atomic individually; any interruption fails closed on hash mismatch.
        atomic_json(manifest_path,manifest)
    atomic_json(target,receipt)
    if collection.get('bias_diagnostics'):
        atomic_json(target.parent/'bias-diagnostics.json',collection['bias_diagnostics'])
    if (out/'controls.json').exists():
        atomic_json(target.parent/'controls.json',json.loads((out/'controls.json').read_text()))
    atomic_json(target.parent/'judgments.json',judgments)
    atomic_json(target.parent/'collection.json',collection)
    atomic_json(target.parent/'references.json',{'scope':'Owner English preference references; reviewer identifiers omitted','axes':refs})
    from .storage import rebuild_index
    if (root/'results').exists():rebuild_index(root/'results')
    return receipt
