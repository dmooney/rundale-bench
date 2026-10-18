"""Atomic immutable evidence, with cause-aware latest-result selection."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

RETAIN_PREVIOUS = {'budget', 'infrastructure', 'unknown', 'qualification', 'setup'}

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    with temp.open('w') as out:
        json.dump(data, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    temp.replace(path)

def safe_id(value: str) -> str:
    if not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_. ' for c in value) or value in ('.','..') or '/' in value:
        raise ValueError('Invalid evidence identifier')
    return value.replace(' ', '-')

def publish_run(root: Path, run: dict) -> Path:
    version, rid = safe_id(run['version']), safe_id(run['run_id'])
    path = root / version / 'runs' / (rid + '.json')
    encoded = json.dumps(run, sort_keys=True, ensure_ascii=False, allow_nan=False)
    if path.exists():
        if json.dumps(json.loads(path.read_text()), sort_keys=True, ensure_ascii=False, allow_nan=False) != encoded:
            raise ValueError('Published run evidence is immutable')
    else:
        atomic_json(path, run)
    rebuild_index(root)
    return path

def rebuild_index(root: Path) -> dict:
    prior = json.loads((root/'index.json').read_text()) if (root/'index.json').exists() else {'versions': []}
    previous = {x['version']: x for x in prior['versions']}
    versions = []
    names = sorted(set(previous) | {p.name for p in root.iterdir() if p.is_dir() and p.name[0:1].isdigit()})
    for version in names:
        all_runs = []
        for p in sorted((root/version/'runs').glob('*.json')):
            r = json.loads(p.read_text())
            r['evidence_path'] = f'{version}/runs/{p.name}'
            all_runs.append(r)
        all_runs.sort(key=lambda x: (x['completed_at'], x['run_id']))
        latest = {}
        for r in all_runs:
            key = (r['model'], r.get('reasoning'))
            old = latest.get(key)
            if old and old.get('status') == 'complete' and r['status'] != 'complete' and r.get('failure_cause') in RETAIN_PREVIOUS:
                old = dict(old)
                old['notice'] = f"Latest attempt {r['run_id']} on {r['completed_at']} was {r['status']}: {r.get('reason','')}"
                old['latest_attempt_id'] = r['run_id']
                latest[key] = old
            else:
                latest[key] = dict(r, notice=None, latest_attempt_id=r['run_id'])
        rows = sorted(latest.values(), key=lambda x: (x.get('overall') is None, -(x.get('overall') or 0), x['model']))
        # Site index excludes verbose raw evidence; immutable detail stays in run files.
        fields = ('model','reasoning','run_id','status','overall','scores','completed_at','cost_usd','notice','latest_attempt_id','failure_cause','reason','budget_usd','budget_status','spending_exposure_usd','coverage','uncertainty','variability','evidence_path')
        compact = lambda r: {k:r.get(k) for k in fields}
        qualification=previous.get(version,{}).get('qualification',{'status':'pending','reason':'Judge qualification evidence is missing.'})
        qpath=root.parent/'qualification'/version/'status.json'
        if qpath.exists():
            q=json.loads(qpath.read_text())
            qualification={'status':q['status'],'reason':q.get('reason'),'suite_hash':q.get('suite_hash')}
        versions.append({'version':version, 'qualification': qualification, 'rows':[compact(r) for r in rows], 'runs':[compact(r) for r in all_runs]})
    data = {'schema_version':1, 'versions':versions}
    atomic_json(root/'index.json', data)
    return data

def issue_payload(run: dict) -> dict:
    # Raw error details live in public evidence; secrets are redacted before storage.
    fingerprint = hashlib.sha256(json.dumps({'version':run['version'],'model':run['model'],'reasoning':run.get('reasoning'),'cause':run.get('failure_cause'),'errors':[e.get('kind') for e in run.get('errors',[])]},sort_keys=True).encode()).hexdigest()[:16]
    return {'fingerprint':fingerprint, 'title':f"Investigate benchmark DNF: {run['model']} ({fingerprint})", 'body':f"Run `{run['run_id']}` stopped: {run.get('reason','unknown cause')}.\n\nFailure cause: {run.get('failure_cause','unknown')}.\nEvidence: `{run['version']}/runs/{run['run_id']}.json`.\n\nAnother agent should diagnose the request, raw response, configuration, and billing status before retrying.\n\n<!-- benchmark-dnf:{fingerprint} -->"}
