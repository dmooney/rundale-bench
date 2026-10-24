#!/usr/bin/env python3
"""Audit final-code request/scoring equivalence from a local paid-call cache.

No credentials or network calls. Original run, ledger and result files are read
only; run reconstruction and publication happen in a temporary fixture root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from rundale_bench.accounting import Ledger
from rundale_bench.runner import run
from rundale_bench.storage import atomic_json, safe_id


class NoNetworkClient:
    def generate(self, *args, **kwargs):
        raise AssertionError('Offline replay tried to generate a new paid response')

    def _post_typesafe(self, *args, **kwargs):
        raise AssertionError('Offline replay tried to request a new judgment')


def replay(root: Path, run_id: str) -> dict:
    run_id = safe_id(run_id)
    source = root/'output'/run_id
    original = json.loads((source/'run.json').read_text())
    if original['status'] != 'complete':
        raise ValueError('This equivalence audit requires a complete original run')
    calls = []
    original_cached = Ledger.cached

    def audited_cached(ledger, call_id, request):
        cached = original_cached(ledger, call_id, request)
        if cached is None:
            raise AssertionError('Offline replay encountered a missing cached call')
        calls.append({'id': call_id, 'request_digest': Ledger.request_digest(request)})
        return cached

    with tempfile.TemporaryDirectory(prefix='rundale-cached-replay-') as td:
        isolated = Path(td)
        for directory in ('config', 'suites', 'qualification'):
            shutil.copytree(root/directory, isolated/directory)
        work = isolated/'output'/run_id
        work.mkdir(parents=True)
        with sqlite3.connect(source/'ledger.sqlite') as old_db:
            with sqlite3.connect(work/'ledger.sqlite') as new_db:
                old_db.backup(new_db)
            ledger_rows = [dict(zip(('id', 'digest', 'state', 'reserved', 'actual'), row))
                           for row in old_db.execute('SELECT id,digest,state,reserved,actual FROM calls ORDER BY id')]
        state = {**original, 'status': 'running', 'case_results': [], 'requests': [],
                 'judgments': [], 'errors': [], 'failure_events': 0}
        atomic_json(work/'run.json', state)
        with patch.object(Ledger, 'cached', audited_cached):
            reconstructed = run(original['model'], reasoning=original['reasoning'],
                root=isolated, version=original['version'], budget=original['budget_usd'],
                resume=run_id, client=NoNetworkClient())
    if reconstructed['status'] != 'complete':
        raise AssertionError('Final code did not reproduce a complete cached run')
    for key in ('scores', 'overall', 'coverage', 'trial_coverage', 'cost_usd', 'spending_exposure_usd'):
        if reconstructed[key] != original[key]:
            raise AssertionError(f'Cached replay changed {key}')
    case_scores = lambda result: [(c['case_id'], c['trial'], c['score']) for c in result['case_results']]
    if case_scores(reconstructed) != case_scores(original):
        raise AssertionError('Cached replay changed a case score')
    if len(calls) != len(original['requests']):
        raise AssertionError('Cached replay did not check every paid request')
    recorded = {row['id']: row['digest'] for row in ledger_rows}
    if any(recorded.get(call['id']) != call['request_digest'] for call in calls):
        raise AssertionError('Final-code requests differ from original ledger digests')
    return {'run_id': run_id, 'original_run_sha256': hashlib.sha256((source/'run.json').read_bytes()).hexdigest(),
            'matched_request_digests': len(calls), 'case_scores_identical': True,
            'aggregate_and_costs_identical': True, 'provider_calls': 0, 'ledger_calls': ledger_rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_ids', nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = {'purpose': 'Offline final-source equivalence audit; not a new model evaluation',
        'audit_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_files_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted((root/'src/rundale_bench').glob('*.py'))},
        'runs': [replay(root, run_id) for run_id in args.run_ids]}
    atomic_json(args.output, result)
    print(json.dumps([{k: v for k, v in run.items() if k != 'ledger_calls'} for run in result['runs']], indent=2))
