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
        reconciliation_dir = root/version/'reconciliations'
        reconciliations = {}
        if reconciliation_dir.exists():
            if reconciliation_dir.is_symlink() or not reconciliation_dir.is_dir():
                raise ValueError('Invalid billing reconciliation directory')
            for reconciliation_path in sorted(reconciliation_dir.glob('*.json')):
                if reconciliation_path.is_symlink() or not reconciliation_path.is_file():
                    raise ValueError('Invalid billing reconciliation artifact')
                record = json.loads(reconciliation_path.read_text())
                rid = safe_id(record.get('run_id', ''))
                if record.get('schema_version') != 1 or record.get('conclusion') != 'not_billed_based_on_provider_monitoring':
                    raise ValueError('Unsupported billing reconciliation artifact')
                if reconciliation_path.name != f'{rid}.json' or rid in reconciliations:
                    raise ValueError('Billing reconciliation identity mismatch')
                evidence = record.get('monitoring_evidence')
                artifact_hashes = record.get('original_artifacts', {})
                canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
                if not isinstance(evidence, dict) or artifact_hashes.get('monitoring_evidence_canonical_sha256') != hashlib.sha256(canonical.encode('utf-8')).hexdigest():
                    raise ValueError('Billing reconciliation monitoring evidence hash mismatch')
                if record.get('monitoring_estimate_usd') != 0 or record.get('actual_cost_usd') is not None:
                    raise ValueError('Monitoring reconciliation cannot claim an invoice-backed actual cost')
                limitations = record.get('limitations')
                if (not isinstance(record.get('basis'), str) or 'locally checked' not in record['basis']
                        or not isinstance(limitations, list) or not all(isinstance(value, str) for value in limitations)
                        or not any('not independently verified' in value for value in limitations)
                        or not any('not an invoice' in value for value in limitations)):
                    raise ValueError('Billing reconciliation must retain its identity and invoice limitations')
                reconciliations[rid] = record
        for p in sorted((root/version/'runs').glob('*.json')):
            r = json.loads(p.read_text())
            r['evidence_path'] = f'{version}/runs/{p.name}'
            reconciliation = reconciliations.get(r.get('run_id'))
            if reconciliation:
                artifact_hashes = reconciliation.get('original_artifacts', {})
                expected_hash = artifact_hashes.get('run_sha256')
                if expected_hash != hashlib.sha256(p.read_bytes()).hexdigest():
                    raise ValueError('Billing reconciliation run hash does not match immutable run evidence')
                ledger_path = root/version/'ledgers'/(str(r.get('run_id')) + '.json')
                if ledger_path.is_symlink() or not ledger_path.is_file():
                    raise ValueError('Billing reconciliation ledger export is missing or unsafe')
                if artifact_hashes.get('ledger_export_sha256') != hashlib.sha256(ledger_path.read_bytes()).hexdigest():
                    raise ValueError('Billing reconciliation ledger hash does not match immutable ledger export')
                from .reconciliation import _validate_monitoring_evidence
                _validate_monitoring_evidence(reconciliation['monitoring_evidence'], r['run_id'], r.get('completed_at'))
                r['billing_reconciliation'] = {
                    'recorded_at': reconciliation.get('recorded_at'),
                    'conclusion': reconciliation.get('conclusion'),
                    'monitoring_estimate_usd': reconciliation.get('monitoring_estimate_usd'),
                    'actual_cost_usd': reconciliation.get('actual_cost_usd'),
                    'basis': reconciliation.get('basis'),
                    'limitations': reconciliation.get('limitations'),
                    'evidence_path': f'{version}/reconciliations/{p.stem}.json',
                    'evidence_sha256': hashlib.sha256((reconciliation_dir/f'{r["run_id"]}.json').read_bytes()).hexdigest(),
                    'monitoring_evidence_sha256': artifact_hashes.get('monitoring_evidence_sha256'),
                    'ledger_evidence_path': f'{version}/ledgers/{r.get("run_id")}.json',
                    'ledger_export_sha256': artifact_hashes.get('ledger_export_sha256'),
                }
            all_runs.append(r)
        if set(reconciliations) - {r.get('run_id') for r in all_runs}:
            raise ValueError('Billing reconciliation references missing run evidence')
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
        fields = ('model','reasoning','run_id','status','overall','scores','completed_at','cost_usd','notice','latest_attempt_id','failure_cause','reason','budget_usd','budget_status','spending_exposure_usd','coverage','uncertainty','variability','evidence_path','qualification_status','score_status','validation_basis','billing_reconciliation')
        compact = lambda r: {k:r.get(k) for k in fields}
        qualification=previous.get(version,{}).get('qualification',{'status':'pending','reason':'Judge qualification evidence is missing.'})
        qpath=root.parent/'qualification'/version/'status.json'
        if qpath.exists():
            q=json.loads(qpath.read_text())
            qualification={'status':q['status'],'reason':q.get('reason'),'suite_hash':q.get('suite_hash'),'validation_basis':q.get('validation_basis')}
        versions.append({'version':version, 'qualification': qualification, 'rows':[compact(r) for r in rows], 'runs':[compact(r) for r in all_runs]})
    data = {'schema_version':1, 'versions':versions}
    atomic_json(root/'index.json', data)
    return data

def issue_payload(run: dict) -> dict:
    # Raw error details live in public evidence; secrets are redacted before storage.
    fingerprint = hashlib.sha256(json.dumps({'version':run['version'],'model':run['model'],'reasoning':run.get('reasoning'),'cause':run.get('failure_cause'),'errors':[e.get('kind') for e in run.get('errors',[])]},sort_keys=True).encode()).hexdigest()[:16]
    return {'fingerprint':fingerprint, 'title':f"Investigate benchmark DNF: {run['model']} ({fingerprint})", 'body':f"Run `{run['run_id']}` stopped: {run.get('reason','unknown cause')}.\n\nFailure cause: {run.get('failure_cause','unknown')}.\nEvidence: `{run['version']}/runs/{run['run_id']}.json`.\n\nAnother agent should diagnose the request, raw response, configuration, and billing status before retrying.\n\n<!-- benchmark-dnf:{fingerprint} -->"}
