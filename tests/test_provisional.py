import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rundale_bench.provisional import screen
from rundale_bench.qualification import collect, PROFILES
from rundale_bench.runner import qualification_blockers

ROOT = Path(__file__).resolve().parents[1]
OPUS = 'claude-opus-5-5-judge-high'


def fixture(root):
    for directory in ('review', 'config', 'suites'):
        shutil.copytree(ROOT/directory, root/directory)
    path = root/'suites/3.0/manifest.json'
    manifest = json.loads(path.read_text())
    manifest.update(status='draft', judge_policy={'dialogue': None, 'multiturn': None})
    manifest.pop('validation_mode', None)
    path.write_text(json.dumps(manifest))
    pack = json.loads((root/'review/pack.json').read_text())
    from rundale_bench.bias import build_checks
    _, _, split = __import__('rundale_bench.qualification', fromlist=['load_review']).load_review(root)
    english = {i['id']: i for i in pack['items'] if i['category'] in ('dialogue', 'multiturn')}
    sources = {c['source_id'] for c in build_checks(english, split)}
    varied = {next(cid for cid, item in english.items() if item['category'] == cat and cid not in sources)
              for cat in ('dialogue', 'multiturn')}
    def judge(client, profile, item, rubric, *, grade_order=None):
        return {'axes': {a: 2 if item['id'] in varied else 3 for a in rubric}, 'usage': {'input_tokens': 100, 'output_tokens': 10}, 'model': profile['model']}
    with patch('rundale_bench.qualification.judge_response', side_effect=judge):
        collect(root, {}, client=object())


def opus_fixture(root):
    pack = json.loads((root/'review/pack.json').read_text())
    from rundale_bench.bias import build_checks
    _, _, split = __import__('rundale_bench.qualification', fromlist=['load_review']).load_review(root)
    english = {i['id']: i for i in pack['items'] if i['category'] in ('dialogue', 'multiturn')}
    sources = {c['source_id'] for c in build_checks(english, split)}
    varied = {next(cid for cid, item in english.items() if item['category'] == cat and cid not in sources)
              for cat in ('dialogue', 'multiturn')}
    def judge(client, profile, item, rubric, *, grade_order=None):
        return {'axes': {a: 2 if item['id'] in varied else 3 for a in rubric}, 'usage': {'input_tokens': 100, 'output_tokens': 10}, 'model': profile['model']}
    with patch('rundale_bench.qualification.judge_response', side_effect=judge):
        collect(root, {}, client=object(), version='3.2', profile_ids=(OPUS,))


class ProvisionalTests(unittest.TestCase):
    def test_legacy_screen_recomputes_cheapest_passing_judge(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            manifest_path = root/'suites/3.0/manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['judge_policy'] = {'dialogue': 'gpt-6.1-sol-judge-high', 'multiturn': 'gpt-6.1-sol-judge-high'}
            manifest_path.write_text(json.dumps(manifest))
            receipt = screen(root)
            self.assertEqual({row['profile_id'] for row in receipt['judges'].values()}, {'jev-1.13.0'})

    def test_single_opus_screen_is_versioned_and_does_not_touch_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root); screen(root)
            legacy_files = list((root/'qualification/3.0').glob('*.json')) + [root/'suites/3.0/manifest.json']
            before = {p: p.read_bytes() for p in legacy_files}
            opus_fixture(root)
            receipt = screen(root, '3.2')
            self.assertEqual({row['profile_id'] for row in receipt['judges'].values()}, {OPUS})
            self.assertTrue(all(row['automated_checks_passed'] for row in receipt['judges'].values()))
            self.assertEqual(receipt['inter_judge_agreement']['dialogue']['cases'], 8)
            self.assertIsNone(receipt['inter_judge_agreement']['dialogue']['mean_absolute_difference'])
            self.assertEqual(before, {p: p.read_bytes() for p in legacy_files})
            self.assertTrue((root/'qualification/3.2/status.json').exists())
            self.assertFalse((root/'qualification/3.0/status.json').read_bytes() == (root/'qualification/3.2/status.json').read_bytes())

    def test_single_opus_screen_fails_closed_when_repeat_gate_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root); opus_fixture(root)
            path = root/'output/qualification/3.2/judgments.json'
            judgments = json.loads(path.read_text())
            judgments[OPUS]['check-0']['axes'] = {axis: 5 for axis in judgments[OPUS]['check-0']['axes']}
            path.write_text(json.dumps(judgments))
            with self.assertRaisesRegex(ValueError, 'repeat gate for dialogue'):
                screen(root, '3.2')
            self.assertFalse((root/'qualification/3.2/status.json').exists())

    def test_nonlegacy_collection_requires_an_explicit_version_key(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root); opus_fixture(root)
            path = root/'output/qualification/3.2/collection.json'
            collection = json.loads(path.read_text()); collection.pop('version')
            path.write_text(json.dumps(collection))
            with self.assertRaisesRegex(ValueError, 'collection version does not match'):
                screen(root, '3.2')

    def test_screen_requires_complete_legacy_and_exact_pinned_v32_profiles(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            path = root/'output/qualification/collection.json'
            collection = json.loads(path.read_text()); collection['profiles'].pop(PROFILES[0])
            path.write_text(json.dumps(collection))
            with self.assertRaisesRegex(ValueError, 'versioned judge policy'):
                screen(root)
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root); opus_fixture(root)
            path = root/'output/qualification/3.2/collection.json'
            from rundale_bench.providers import load_profiles
            collection = json.loads(path.read_text()); collection['profiles']['jev-1.13.0'] = load_profiles(root/'config/providers.json')['jev-1.13.0']
            path.write_text(json.dumps(collection))
            with self.assertRaisesRegex(ValueError, 'versioned judge policy'):
                screen(root, '3.2')

    def test_screen_is_offline_honest_and_idempotent(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            with patch('rundale_bench.providers.NativeClient.generate', side_effect=AssertionError('No paid calls')):
                receipt = screen(root)
                self.assertEqual(screen(root), receipt)
            self.assertEqual(receipt['status'], 'provisional')
            self.assertFalse(receipt['human_validated'])
            self.assertEqual(receipt['validation_basis'], 'automated_checks_only')
            self.assertEqual(len(receipt['exposed_case_ids']), 16)
            for row in receipt['judges'].values():
                self.assertFalse(row['qualified'])
                self.assertTrue(row['automated_checks_passed'])
                self.assertEqual(row['profile_id'], 'jev-1.13.0')
            manifest = json.loads((root/'suites/3.0/manifest.json').read_text())
            self.assertEqual(qualification_blockers(root, manifest, receipt['suite_hash']), [])
            self.assertFalse((root/'qualification/3.0/references.json').exists())
            from rundale_bench.qualification import evaluate
            files = list((root/'qualification/3.0').glob('*.json')) + [root/'suites/3.0/manifest.json']
            before = {p: p.read_bytes() for p in files}
            with self.assertRaisesRegex(ValueError, 'new benchmark version'):
                evaluate(root, root/'no-human-ratings.json')
            self.assertEqual(before, {p: p.read_bytes() for p in files})
            (root/'qualification/3.0/judgments.json').write_text('{}')
            self.assertTrue(any('evidence changed' in s for s in qualification_blockers(root, manifest, receipt['suite_hash'])))

    def test_missing_calls_and_malformed_axes_block_screening(self):
        for defect in ('missing', 'null', 'boolean', 'extra_axis'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as t:
                root = Path(t); fixture(root)
                p = root/'output/qualification/judgments.json'; rows = json.loads(p.read_text())
                sample = next(iter(rows[PROFILES[0]]))
                if defect == 'missing': del rows[PROFILES[0]][sample]
                else:
                    axis = next(iter(rows[PROFILES[0]][sample]['axes']))
                    if defect == 'extra_axis': rows[PROFILES[0]][sample]['axes']['unknown'] = 3
                    else: rows[PROFILES[0]][sample]['axes'][axis] = None if defect == 'null' else True
                p.write_text(json.dumps(rows))
                with self.assertRaises(ValueError): screen(root)
                self.assertFalse((root/'qualification/3.0/status.json').exists())

    def test_failed_controls_cannot_be_bypassed_or_presented_as_accuracy(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            p = root/'output/qualification/judgments.json'; rows = json.loads(p.read_text())
            for pid in PROFILES:
                rows[pid]['check-0']['axes'] = {a: 5 for a in rows[pid]['check-0']['axes']}
            p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'repeat gate for dialogue'): screen(root)

    def test_changed_protocol_and_pinned_selection_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            screen(root)
            manifest = root/'suites/3.0/manifest.json'; m = json.loads(manifest.read_text())
            m['judge_policy']['dialogue'] = PROFILES[0]; manifest.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, 'frozen'): screen(root)
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            p = root/'output/qualification/collection.json'; c = json.loads(p.read_text())
            c['bias_protocol_sha256'] = 'changed'; p.write_text(json.dumps(c))
            with self.assertRaisesRegex(ValueError, 'controls changed'): screen(root)

    def test_suite_builder_cannot_reset_a_ready_policy(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root); screen(root)
            (root/'scripts').mkdir(); shutil.copy2(ROOT/'scripts/build_suite.py', root/'scripts/build_suite.py')
            paths = list((root/'suites/3.0').iterdir())
            before = {p: p.read_bytes() for p in paths if p.is_file()}
            result = subprocess.run([sys.executable, str(root/'scripts/build_suite.py')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Ready suite is frozen', result.stderr)
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_provisional_run_and_index_keep_validation_labels(self):
        from test_runner import fixture as run_fixture, FakeClient
        from rundale_bench.runner import run
        import hashlib
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); run_fixture(root)
            manifest_path = root/'suites/3.0/manifest.json'
            manifest = json.loads(manifest_path.read_text()); manifest['validation_mode'] = 'provisional'
            manifest_path.write_text(json.dumps(manifest))
            qpath = root/'qualification/3.0/status.json'; q = json.loads(qpath.read_text())
            q.update(status='provisional', validation_basis='automated_checks_only', human_validated=False,
                     suite_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(), evidence_hashes={})
            for name in ('collection.json', 'judgments.json', 'controls.json', 'bias-diagnostics.json'):
                p = qpath.parent/name; p.write_text('{}')
                q['evidence_hashes'][name] = hashlib.sha256(p.read_bytes()).hexdigest()
            for value in q['judges'].values(): value.update(qualified=False, automated_checks_passed=True)
            qpath.write_text(json.dumps(q))
            def judge(client, profile, item, rubric):
                return {'axes': {a: 4 for a in rubric}, 'usage': {'input_tokens': 2, 'output_tokens': 1}}
            with patch('rundale_bench.runner.judge_response', side_effect=judge):
                result = run('fake', root=root, client=FakeClient(), run_id='provisional')
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['score_status'], 'provisional')
            self.assertEqual(result['validation_basis'], 'automated_checks_only')
            index = json.loads((root/'results/index.json').read_text())
            self.assertEqual(index['versions'][0]['rows'][0]['score_status'], 'provisional')
            self.assertEqual(index['versions'][0]['runs'][0]['qualification_status'], 'provisional')
            # Later global status must not rewrite the immutable run's label.
            q['status'] = 'qualified'; qpath.write_text(json.dumps(q))
            from rundale_bench.storage import rebuild_index
            self.assertEqual(rebuild_index(root/'results')['versions'][0]['rows'][0]['score_status'], 'provisional')

    def test_ceiling_distribution_and_constant_high_grader_limit_are_explicit(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            p = root/'output/qualification/judgments.json'; rows = json.loads(p.read_text())
            for row in rows[PROFILES[0]].values():
                row['axes'] = {a: 5 for a in row['axes']}
            p.write_text(json.dumps(rows))
            receipt = screen(root)
            for pid in (PROFILES[0],):
                d = receipt['grade_distributions'][pid]['dialogue']
                self.assertEqual(d['grades']['5'], 48)
                self.assertEqual(d['ceiling_fraction'], 1)
                self.assertIsNone(receipt['metrics']['dialogue'][pid]['human_accuracy'])
            self.assertFalse(receipt['metrics']['dialogue'][PROFILES[0]]['automated_checks_passed'])
            self.assertFalse(receipt['metrics']['multiturn'][PROFILES[0]]['nonconstant_case_grades'])
            self.assertFalse(receipt['human_validated'])
            self.assertTrue(any('Constant grading is rejected' in note for note in receipt['limitations']))

    def test_obeying_low_grade_injection_fails_multiturn_screening(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); fixture(root)
            p = root/'output/qualification/judgments.json'; rows = json.loads(p.read_text())
            for profile_rows in rows.values():
                profile_rows['check-5']['axes'] = {a: 1 for a in profile_rows['check-5']['axes']}
            p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'repeat gate for multiturn'):
                screen(root)

    def test_cli_screen_dispatch_needs_no_ratings(self):
        from rundale_bench.cli import main
        import contextlib, io
        with patch('rundale_bench.provisional.screen', return_value={'status': 'provisional'}) as screened:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['qualify', 'screen']), 0)
            screened.assert_called_once()
