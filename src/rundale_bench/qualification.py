"""Blind native-API judge trials, held-out validation, and explicit pending gates."""
from __future__ import annotations
import hashlib
import json
import math
import statistics
from pathlib import Path
from .accounting import Ledger, BudgetError, actual_cost, upper_cost
from .judges import judge_response
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

def collect(root: Path, credentials: dict, client: NativeClient|None=None) -> dict:
    pack,rubrics,split = load_review(root)
    english = [i for i in pack['items'] if i['category'] in ('dialogue','multiturn')]
    profiles = load_profiles(root/'config/providers.json')
    out = root/'output/qualification';out.mkdir(parents=True,exist_ok=True)
    contract = {'pack_sha256':digest(root/'review/pack.json'),'rubric_sha256':digest(root/'review/rubric.json'),'split_sha256':digest(root/'review/split.json'),'profiles':{k:profiles[k] for k in PROFILES}}
    frozen = out/'contract.json'
    if frozen.exists() and json.loads(frozen.read_text()) != contract:
        raise ValueError('Qualification contract changed; do not reuse its held-out evidence')
    atomic_json(frozen,contract)
    ledger = Ledger(out/'ledger.sqlite',10)
    results = json.loads((out/'judgments.json').read_text()) if (out/'judgments.json').exists() else {}
    client = client or NativeClient(credentials)
    requests = [(i['id'],dict(i,eval=i['category'])) for i in english]
    # Repeat only selection data; held-out validation must not influence selection.
    by_id_temp={i['id']:i for i in english}
    selected_by_category = {cat: sorted(cid for cid in split['selection'] if by_id_temp[cid]['category']==cat)[:3] for cat in ('dialogue','multiturn')}
    check_sources = [cid for pair in zip(selected_by_category['dialogue'], selected_by_category['multiturn']) for cid in pair]
    checks = []
    by_id={i['id']:i for i in english}
    for n,cid in enumerate(check_sources):
        item=dict(by_id[cid],id='check-'+str(n),eval=by_id[cid]['category'])
        if n>=3:
            item['user']='\n'+item['user']+'\n';item['response']='\n'+item['response']+'\n'
        requests.append(('check-'+str(n),item));checks.append({'id':'check-'+str(n),'source_id':cid,'kind':'exact' if n<3 else 'format'})
    try:
        for profile_id in PROFILES:
            results.setdefault(profile_id,{})
            for rid,item in requests:
                request={'profile':profiles[profile_id],'item':item,'rubric':rubrics[item['category']]}
                call_id=profile_id+':'+rid
                cached=ledger.cached(call_id,request)
                if cached is not None:
                    results[profile_id][rid]=cached
                    continue
                bound=upper_cost(profiles[profile_id],[{'role':'user','content':json.dumps(item,ensure_ascii=False)}],4096,request['rubric'])
                ledger.reserve(call_id,request,bound)
                try:
                    answer=judge_response(client,profiles[profile_id],item,request['rubric'])
                except ProviderError as exc:
                    if exc.payload.get('usage'):
                        known={'error':exc.kind,'usage':exc.payload['usage'],'raw':exc.payload}
                        ledger.commit(call_id,known,actual_cost(profiles[profile_id],known['usage']))
                    else:
                        ledger.fail(call_id,exc.billing_uncertain)
                    atomic_json(out/'error.json',{'profile':profile_id,'request_id':rid,'kind':exc.kind,'billing_uncertain':exc.billing_uncertain,'raw':exc.payload})
                    raise
                ledger.commit(call_id,answer,actual_cost(profiles[profile_id],answer['usage']))
                results[profile_id][rid]=answer
                atomic_json(out/'judgments.json',results)
        receipt={'status':'collected','judgments_path':str(out/'judgments.json'),'checks':checks,'cost_usd':ledger.spent,'cost_basis':'provider usage × recorded prices; not invoice receipt',**contract}
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
    refs=owner_references(root,references)
    pack,rubrics,split=load_review(root);by={i['id']:i for i in pack['items']}
    out=root/'output/qualification';collection=json.loads((out/'collection.json').read_text());judgments=json.loads((out/'judgments.json').read_text())
    for file,key in [('review/pack.json','pack_sha256'),('review/rubric.json','rubric_sha256'),('review/split.json','split_sha256')]:
        if collection[key]!=digest(root/file):raise ValueError('Frozen qualification inputs changed')
    current_profiles=load_profiles(root/'config/providers.json')
    if collection['profiles']!={k:current_profiles[k] for k in PROFILES}:
        raise ValueError('Native profiles changed after qualification collection')
    selection={};judges={};all_metrics={}
    for category in ('dialogue','multiturn'):
        ids=[cid for cid in split['selection'] if by[cid]['category']==category]
        all_metrics[category]={}
        eligible=[]
        for pid in PROFILES:
            m=metrics(ids,refs,judgments[pid]);all_metrics[category][pid]={'selection':m}
            relevant=[c for c in collection['checks'] if by[c['source_id']]['category']==category]
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
    manifest_path=root/'suites/3.0/manifest.json'
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
    target=root/'qualification/3.0/status.json'
    if target.exists():
        old=json.loads(target.read_text())
        if old.get('status')=='qualified':
            stable=lambda x:{k:v for k,v in x.items() if k!='qualified_at'}
            if stable(old)!=stable(receipt):raise ValueError('Qualified configuration is frozen; create a new benchmark version')
            return old
    if qualified:
        # Both writes are atomic individually; any interruption fails closed on hash mismatch.
        atomic_json(manifest_path,manifest)
    atomic_json(target,receipt)
    atomic_json(target.parent/'judgments.json',judgments)
    atomic_json(target.parent/'collection.json',collection)
    atomic_json(target.parent/'references.json',{'scope':'Owner English preference references; reviewer identifiers omitted','axes':refs})
    from .storage import rebuild_index
    if (root/'results').exists():rebuild_index(root/'results')
    return receipt
