import copy
import contextlib
import io
import hashlib
import importlib.util
import json
import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from rundale_bench.contracts import candidate_schema, validate_output
from rundale_bench.providers import NativeClient, ProviderResponse
from rundale_bench.runner import dry_run, load_suite, run, validate_suite
from test_runner import fixture, FakeClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_structured_suite', ROOT/'scripts/build_structured_suite.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

NPC = {'dialogue': 'Aye.', 'action': 'nods', 'mood': 'calm', 'language_hints': [], 'assigned_task': None}
USAGE = {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 10, 'reasoning_tokens': 0}


class StructuredOutputTests(unittest.TestCase):
    def test_frozen_schemas_constrain_shape_without_gold_answers(self):
        _, old, _, _ = load_suite(ROOT)
        _, new, _, _ = load_suite(ROOT, '3.1')
        self.assertEqual(len(new), len(old))
        for original, structured in zip(old, new):
            self.assertEqual(original.get('answer'), structured.get('answer'))
            self.assertEqual(structured['response_schema'], candidate_schema(original))
            if original['eval'] in ('dialogue', 'multiturn'):
                self.assertEqual(original.get('system'), structured.get('system'))
                self.assertEqual(original.get('messages'), structured.get('messages'))
                self.assertEqual(list(structured['response_schema']['properties']), list(NPC))
                validate_output(json.dumps(NPC), structured['response_schema'])
            else:
                expected_messages = copy.deepcopy(original['messages'])
                if original['answer']['type'] == 'choice':
                    for message in expected_messages:
                        self.assertIn('Reply A or B only.', message['content'])
                        message['content'] = message['content'].replace(
                            'Reply A or B only.', 'Reply with exactly one JSON object: {"answer":"A"} or {"answer":"B"}.')
                self.assertEqual(structured['messages'], expected_messages)
                changed = copy.deepcopy(original)
                if changed['answer']['type'] == 'choice':
                    changed['answer']['expected'] = 'A' if original['answer']['expected'] == 'B' else 'B'
                else:
                    changed['answer']['expected'] = {k: 'different correct answer' for k in original['answer']['expected']}
                self.assertEqual(candidate_schema(original), candidate_schema(changed))
        self.assertFalse(validate_suite(ROOT, '3.1')['blockers'])

    def test_provider_native_requests_include_complete_json_schema(self):
        schema = candidate_schema({'eval': 'dialogue'})
        messages = [{'role': 'user', 'content': 'hello'}]
        for provider in ('google', 'openai', 'anthropic'):
            profile = {'provider': provider, 'model': 'fake', 'reasoning': 'high'}
            body, _, _ = NativeClient._request(profile, messages, 4096, schema, 'test', 'https://example.invalid')
            if provider == 'google':
                self.assertEqual(body['generationConfig']['responseJsonSchema'], schema)
                self.assertNotIn('responseSchema', body['generationConfig'])
                self.assertEqual(body['generationConfig']['responseMimeType'], 'application/json')
            elif provider == 'openai':
                self.assertEqual(body['text']['format']['schema'], schema)
                self.assertTrue(body['text']['format']['strict'])
            else:
                self.assertEqual(body['output_config']['format']['schema'], schema)

    def test_malformed_and_wrong_shapes_still_fail_without_repair(self):
        schema = candidate_schema({'eval': 'dialogue'})
        bad = [f'```json\n{json.dumps(NPC)}\n```', json.dumps({'dialogue': 'Aye.'}),
               json.dumps({**NPC, 'thought_process': 'extra'}),
               json.dumps({**NPC, 'language_hints': [{'word': 'x'}]}),
               json.dumps({**NPC, 'assigned_task': 12}),
               '{"dialogue":"a","dialogue":"b"}']
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_output(text, schema)

    def test_schema_is_recorded_sent_each_turn_and_wrong_semantics_score_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            # Fixture has qualified screening rather than provisional evidence.
            before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
                      for directory in ('suites/3.0', 'qualification/3.0') for p in (root/directory).iterdir()}
            builder.build(root)
            self.assertTrue(all(hashlib.sha256((root/p).read_bytes()).hexdigest() == h for p, h in before.items()))
            with self.assertRaises(ValueError):
                builder.build(root)
            calls = []
            class Client:
                def generate(self, profile, messages, max_output_tokens, response_schema=None):
                    calls.append(response_schema)
                    value = {'answer': 'B'} if 'answer' in response_schema['properties'] else NPC
                    return ProviderResponse(json.dumps(value), USAGE, 'fake', 1, None, {})
            def judge(client, profile, item, rubric):
                self.assertNotIn('response_schema', item)
                return {'axes': {key: 4 for key in rubric}, 'usage': USAGE, 'raw': {}}
            with patch('rundale_bench.runner.judge_response', side_effect=judge):
                result = run('fake', root=root, version='3.1', client=Client(), run_id='structured')
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['version'], '3.1')
            self.assertEqual(result['scores']['gaeilge'], 0)
            self.assertEqual(len(calls), 31)  # 1 dialogue, 6 turns, 24 Gaeilge.
            self.assertTrue(all(calls))
            for request in result['requests']:
                if ':candidate:' in request['id']:
                    self.assertEqual(request['request']['output_protocol'], 'native-json-schema-v1')
                    self.assertIn('response_schema', request['request'])
            self.assertFalse(dry_run('fake', root=root, version='3.1')['blockers'])
            manifest, _, _, _ = load_suite(root, '3.1')
            cp = root/'suites/3.1/cases.jsonl'
            cases = [json.loads(line) for line in cp.read_text().splitlines()]
            cases[0]['response_schema']['properties']['dialogue']['enum'] = ['gold answer']
            cp.write_text(''.join(json.dumps(case)+'\n' for case in cases))
            manifest['cases_sha256'] = hashlib.sha256(cp.read_bytes()).hexdigest()
            (root/'suites/3.1/manifest.json').write_text(json.dumps(manifest))
            self.assertTrue(validate_suite(root, '3.1')['problems'])

    def test_cli_defaults_to_structured_and_rejects_cross_version_comparison(self):
        from rundale_bench import cli
        for command in (['run', 'fake'], ['status'], ['validate-suite'], ['compare', 'a', 'b']):
            self.assertEqual(cli.parser().parse_args(command).version, '3.1')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root/'results/3.1/runs'
            directory.mkdir(parents=True)
            for name, version in [('a', '3.0'), ('b', '3.1')]:
                (directory/(name+'.json')).write_text(json.dumps({'version': version}))
            with patch.object(cli, 'PACKAGE', root), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['compare', 'a', 'b']), 2)

    def test_legacy_run_cannot_resume_under_structured_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            def judge(client, profile, item, rubric):
                return {'axes': {key: 4 for key in rubric}, 'usage': USAGE, 'raw': {}}
            with patch('rundale_bench.runner.judge_response', side_effect=judge):
                old = run('fake', root=root, client=FakeClient(), run_id='legacy')
            self.assertEqual(old['status'], 'complete')
            builder.build(root)
            client = FakeClient()
            with self.assertRaisesRegex(ValueError, 'Resume target differs'):
                run('fake', root=root, version='3.1', client=client, resume='legacy')
            self.assertEqual(client.calls, 0)

    def test_unsupported_provider_is_blocked_before_any_paid_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            builder.build(root)
            path = root/'config/providers.json'
            registry = json.loads(path.read_text())
            registry['profiles'][0]['provider'] = 'typesafe'
            path.write_text(json.dumps(registry))
            report = dry_run('fake', root=root, version='3.1')
            self.assertTrue(any('does not support native structured' in item for item in report['blockers']))
            client = FakeClient()
            with self.assertRaisesRegex(ValueError, 'does not support native structured'):
                run('fake', root=root, version='3.1', client=client)
            self.assertEqual(client.calls, 0)

    def test_cached_audit_reconstructs_final_requests_and_rejects_digest_drift(self):
        audit_spec = importlib.util.spec_from_file_location('replay_cached_run', ROOT/'scripts/replay_cached_run.py')
        audit = importlib.util.module_from_spec(audit_spec)
        audit_spec.loader.exec_module(audit)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            def judge(client, profile, item, rubric):
                return {'axes': {key: 4 for key in rubric}, 'usage': USAGE, 'raw': {}}
            with patch('rundale_bench.runner.judge_response', side_effect=judge):
                original = run('fake', root=root, client=FakeClient(), run_id='audit')
            state_path = root/'output/audit/run.json'
            before = state_path.read_bytes()
            with patch('rundale_bench.runner.NativeClient', side_effect=AssertionError('No network client')):
                result = audit.replay(root, 'audit')
            self.assertEqual(result['matched_request_digests'], len(original['requests']))
            self.assertEqual(state_path.read_bytes(), before)
            with sqlite3.connect(root/'output/audit/ledger.sqlite') as db:
                db.execute("UPDATE calls SET digest=? WHERE id=?", ('0'*64, 'd:0:candidate:0'))
            with self.assertRaisesRegex(AssertionError, 'did not reproduce'):
                audit.replay(root, 'audit')


if __name__ == '__main__':
    unittest.main()
