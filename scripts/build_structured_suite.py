#!/usr/bin/env python3
"""Derive 3.1 once from immutable 3.0 inputs and existing judge screening."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from rundale_bench.contracts import candidate_schema
from rundale_bench.runner import validate_suite
from rundale_bench.storage import atomic_json


def build(root: Path) -> None:
    target = root/'suites/3.1'
    qualification = root/'qualification/3.1'
    if target.exists() or qualification.exists():
        raise ValueError('Refusing to overwrite versioned suite or qualification evidence')
    source = root/'suites/3.0'
    report = validate_suite(root, '3.0')
    if not report['valid'] or report['blockers']:
        raise ValueError('Source suite and judge screening must pass before reuse')
    cases = [json.loads(line) for line in (source/'cases.jsonl').read_text().splitlines()]
    for case in cases:
        case['response_schema'] = candidate_schema(case)
        if case.get('answer', {}).get('type') == 'choice':
            for message in case['messages']:
                message['content'] = message['content'].replace(
                    'Reply A or B only.', 'Reply with exactly one JSON object: {"answer":"A"} or {"answer":"B"}.')
    manifest = copy.deepcopy(json.loads((source/'manifest.json').read_text()))
    manifest.update(version='3.1', derived_from={'version': '3.0', 'suite_hash': report['suite_hash']})
    manifest.setdefault('generation', {})['output_protocol'] = 'native-json-schema-v1'
    manifest['generation']['prompt_contract'] = 'Native schema-constrained JSON; no output repair or automatic retry.'
    target.mkdir(parents=True)
    (target/'cases.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in cases))
    shutil.copyfile(source/'rubrics.json', target/'rubrics.json')
    manifest['cases_sha256'] = hashlib.sha256((target/'cases.jsonl').read_bytes()).hexdigest()
    atomic_json(target/'manifest.json', manifest)
    # Candidate decoding changes; the judge prompts, profiles, anchors and screening
    # calls do not. Reuse the actual original evidence rather than rerunning it.
    shutil.copytree(root/'qualification/3.0', qualification)
    receipt = json.loads((qualification/'status.json').read_text())
    receipt['reused_from'] = {'version': '3.0', 'suite_hash': report['suite_hash'],
        'receipt_sha256': hashlib.sha256((root/'qualification/3.0/status.json').read_bytes()).hexdigest(),
        'basis': 'Unchanged judge profiles, English rubrics and calibration inputs; candidate schema constraints plus JSON answer-envelope instructions for the 16 objective A/B cases.'}
    receipt['suite_hash'] = hashlib.sha256((target/'manifest.json').read_bytes()).hexdigest()
    atomic_json(qualification/'status.json', receipt)


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1])
