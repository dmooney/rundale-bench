"""Offline automated screening, explicitly without human accuracy validation."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .accounting import actual_cost
from .bias import build_checks, summarize_biases
from .providers import load_profiles
from .qualification import PROFILES, digest, load_review
from .storage import atomic_json, rebuild_index, utc_now


def screen(root: Path) -> dict:
    """Select the cheapest structurally valid judge passing presentation checks.

    This does not measure accuracy. Agreement between judges is diagnostic only.
    Uses existing paid receipts; never calls a provider or invents reference labels.
    """
    pack, rubrics, split = load_review(root)
    english = {i['id']: i for i in pack['items'] if i['category'] in ('dialogue', 'multiturn')}
    checks = build_checks(english, split)
    out = root/'output/qualification'
    collection = json.loads((out/'collection.json').read_text())
    judgments = json.loads((out/'judgments.json').read_text())
    profiles = load_profiles(root/'config/providers.json')
    for filename, key in [('pack.json', 'pack_sha256'), ('rubric.json', 'rubric_sha256'), ('split.json', 'split_sha256')]:
        if collection.get(key) != digest(root/'review'/filename):
            raise ValueError('Frozen calibration inputs changed')
    protocol_hash = hashlib.sha256(json.dumps(checks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if collection.get('bias_protocol_sha256') != protocol_hash:
        raise ValueError('Calibration controls changed')
    metadata = [{k: v for k, v in c.items() if k != 'item'} for c in checks]
    if collection.get('checks') != metadata:
        raise ValueError('Calibration control metadata changed')
    if collection.get('profiles') != {pid: profiles[pid] for pid in PROFILES}:
        raise ValueError('Native judge profiles changed after collection')
    if collection.get('adapter_protocols') != {'typesafe_grade_order': 'state-and-criteria-v2'}:
        raise ValueError('Jev grade-order evidence uses the legacy adapter; explicitly repair that control')
    suite_rubrics = json.loads((root/'suites/3.0/rubrics.json').read_text())
    if suite_rubrics != {k: rubrics[k] for k in ('dialogue', 'multiturn')}:
        raise ValueError('Review anchors differ from launch rubric')
    expected = {**english, **{c['id']: c['item'] for c in checks}}
    if set(judgments) != set(PROFILES):
        raise ValueError('Both native judge collections are required')
    metrics, selected, distributions = {}, {}, {}
    costs = {}
    for pid in PROFILES:
        rows = judgments[pid]
        if set(rows) != set(expected):
            raise ValueError('Calibration must contain all 16 English cases and six controls')
        for cid, item in expected.items():
            axes = rows[cid].get('axes', {})
            if (set(axes) != set(rubrics[item['category']])
                    or any(type(v) is not int or not 1 <= v <= 5 for v in axes.values())):
                raise ValueError('Invalid calibration axis grades')
        costs[pid] = sum(actual_cost(profiles[pid], row['usage']) for row in rows.values())
        distributions[pid] = {}
        for category in ('dialogue', 'multiturn'):
            grades = [grade for cid, item in english.items() if item['category'] == category
                      for grade in rows[cid]['axes'].values()]
            distributions[pid][category] = {
                'cases': sum(i['category'] == category for i in english.values()),
                'axes': len(grades), 'grades': {str(g): grades.count(g) for g in range(1, 6)},
                'ceiling_fraction': grades.count(5)/len(grades)}
    for old in collection.get('superseded_evidence', []):
        pid = old.get('profile')
        if pid not in costs:
            raise ValueError('Unknown superseded calibration profile')
        costs[pid] += actual_cost(profiles[pid], old['response']['usage'])
    if not math.isclose(sum(costs.values()), collection['cost_usd'], abs_tol=1e-9):
        raise ValueError('Calibration usage costs do not match the collected total')
    for category in ('dialogue', 'multiturn'):
        metrics[category] = {}
        candidates = []
        for pid in PROFILES:
            relevant = [c for c in checks if c['expected_invariant'] and english[c['source_id']]['category'] == category]
            matching = total = 0
            ceiling = 0
            for c in relevant:
                base, repeat = judgments[pid][c['source_id']]['axes'], judgments[pid][c['id']]['axes']
                total += len(base)
                matching += sum(repeat[a] == grade for a, grade in base.items())
                ceiling += sum(grade == 5 for grade in base.values())
            fraction = matching/total if total else None
            grade_counts = distributions[pid][category]['grades']
            nonconstant = sum(n > 0 for n in grade_counts.values()) > 1
            passed = fraction is not None and fraction >= .9 and nonconstant
            metrics[category][pid] = {'automated_checks_passed': passed,
                'repeat_agreement': {'cases': len(relevant), 'matching_axes': matching, 'axes': total, 'fraction': fraction},
                'invariant_source_ceiling': {'max_grade_axes': ceiling, 'axes': total},
                'nonconstant_case_grades': nonconstant,
                'calibration_cost_usd': costs[pid], 'human_accuracy': None}
            if passed:
                candidates.append(pid)
        if not candidates:
            raise ValueError(f'No judge passes the automated repeat gate for {category}')
        selected[category] = min(candidates, key=lambda pid: (costs[pid], pid))
    agreement = {}
    for category in ('dialogue', 'multiturn'):
        deltas = [abs(judgments[PROFILES[0]][cid]['axes'][a] - judgments[PROFILES[1]][cid]['axes'][a])
                  for cid, item in english.items() if item['category'] == category
                  for a in rubrics[category]]
        agreement[category] = {'cases': sum(i['category'] == category for i in english.values()),
            'axes': len(deltas), 'mean_absolute_difference': sum(deltas)/len(deltas),
            'exact_agreement': sum(d == 0 for d in deltas)/len(deltas),
            'interpretation': 'Inter-judge agreement, not accuracy or human validation.'}
    manifest_path = root/'suites/3.0/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('status') == 'ready' and (manifest.get('judge_policy') != selected
                                             or manifest.get('validation_mode') != 'provisional'):
        raise ValueError('Active judge policy is frozen; create a new benchmark version')
    manifest.update(status='ready', validation_mode='provisional', judge_policy=selected,
                    judge_profiles={pid: profiles[pid] for pid in sorted(set(selected.values()))})
    manifest.pop('launch_blocker', None)
    target = root/'qualification/3.0'
    public_collection = dict(collection)
    public_collection.pop('judgments_path', None)
    artifacts = {'collection.json': public_collection, 'judgments.json': judgments,
                 'controls.json': {'checks': checks}, 'bias-diagnostics.json': summarize_biases(checks, judgments, profiles)}
    # Pin the exact public calibration evidence as well as the suite manifest.
    encode = lambda value: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    evidence_hashes = {name: hashlib.sha256(encode(value)).hexdigest() for name, value in artifacts.items()}
    receipt = {'status': 'provisional', 'screened_at': utc_now(),
        'reason': 'Automated judge checks passed. Scores are provisional; human agreement and accuracy have not been measured.',
        'validation_basis': 'automated_checks_only', 'human_validated': False,
        'suite_hash': hashlib.sha256(encode(manifest)).hexdigest(),
        'judges': {category: {'profile_id': pid, 'qualified': False, 'automated_checks_passed': True} for category, pid in selected.items()},
        'selection_rule': 'Cheapest collected native judge passing exact rubric-schema, >=90% invariant-axis agreement, and nonconstant original-case grades per eval; not selected for accuracy.',
        'thresholds': {'repeat_agreement_min': .9, 'distinct_original_axis_grades_min': 2}, 'metrics': metrics,
        'grade_distributions': distributions,
        'inter_judge_agreement': agreement, 'evidence_hashes': evidence_hashes,
        'cost_usd': collection['cost_usd'], 'cost_basis': 'provider usage at recorded prices; not invoice receipt',
        'exposed_case_ids': sorted(english),
        'limitations': ['No human reference ratings; no accuracy, human agreement, MAE-to-human, or severe-human-miss gate measured.',
                       'All 16 calibration cases are exposed development examples, not untouched human validation.',
                       'Tiny repeat and bias controls cannot establish general reliability or absence of bias.',
                       'Calibration grades are heavily concentrated at 5. Constant grading is rejected as a development screening heuristic; nonconstant grading still does not establish accuracy, score sensitivity, or ranking quality. Claimed-label upward preference is unobservable on ceiling axes.',
                       'The nonconstant-grade heuristic was added after inspecting these exposed development results during pre-launch review; it is not independently validated and can reject genuinely uniform ratings.',
                       'Dialogue invariance covers two cases (12 axes); multi-turn covers three cases (nine axes). There is no unperturbed-repeat baseline, so changes cannot be attributed to a particular bias rather than sampling noise.',
                       'Irish scoring uses attributed objective keys; Irish naturalness remains unqualified.']}
    status_path = target/'status.json'
    if status_path.exists():
        old = json.loads(status_path.read_text())
        if old.get('status') in ('qualified', 'provisional'):
            stable = lambda value: {k: v for k, v in value.items() if k != 'screened_at'}
            if stable(old) != stable(receipt):
                raise ValueError('Published screening evidence is frozen; create a new benchmark version')
            receipt = old
    for name, value in artifacts.items():
        atomic_json(target/name, value)
    atomic_json(manifest_path, manifest)
    atomic_json(status_path, receipt)
    if (root/'results').exists():
        rebuild_index(root/'results')
    return receipt
