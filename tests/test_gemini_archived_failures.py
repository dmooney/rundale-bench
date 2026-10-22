"""Offline regressions for issue #12; replay immutable native SSE evidence."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from rundale_bench.providers import NativeClient
from rundale_bench.runner import _npc_text
from rundale_bench.scoring import objective_score


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'results/3.0/runs/4b4f0c1824d6.json'


class ArchivedStream:
    status = 200

    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        for chunk in self.chunks:
            yield ('data: ' + chunk + '\n').encode()
            yield b'\n'


class ReplayTransport:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream_post(self, url, headers, body, timeout=180):
        self.calls.append(json.loads(body))
        return ArchivedStream(self.chunks)


class GeminiArchivedFailuresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = json.loads(RUN.read_bytes())
        cls.cases = {c['id']: c for c in map(json.loads, (ROOT / 'suites/3.0/cases.jsonl').read_text().splitlines())}

    def replay(self, request_id, text_hash):
        saved = next(q for q in self.artifact['requests'] if q['id'] == request_id)
        request, response = saved['request'], saved['response']
        chunks = response['raw']['stream_chunks']
        transport = ReplayTransport(chunks)
        profile = self.artifact['candidate_profile']
        # Any accidental network fallback fails the test before a connection opens.
        with patch('socket.socket', side_effect=AssertionError('Offline replay only')):
            result = NativeClient({profile['api_key_env']: 'offline'}, transport).generate(
                profile, request['messages'], request['max_output_tokens'])
        self.assertEqual(result.text, response['text'])
        self.assertEqual(result.usage, response['usage'])
        self.assertEqual(hashlib.sha256(result.text.encode()).hexdigest(), text_hash)
        self.assertEqual(len(transport.calls), 1)
        config = transport.calls[0]['generationConfig']
        self.assertEqual(config['thinkingConfig'], {'thinkingLevel': 'high'})
        self.assertEqual(config['maxOutputTokens'], 4096)
        self.assertNotIn('responseMimeType', config)
        self.assertNotIn('responseSchema', config)
        self.assertEqual(response['raw']['candidates'][0]['finishReason'], 'STOP')
        self.assertLess(result.usage['output_tokens'], 4096)
        parts = [p for c in map(json.loads, chunks) for candidate in c.get('candidates', [])
                 for p in candidate.get('content', {}).get('parts', [])]
        self.assertFalse(any(p.get('thought', False) for p in parts))
        self.assertEqual(result.text, ''.join(p.get('text', '') for p in parts))
        return result.text, request['messages']

    def test_original_evidence_is_unchanged(self):
        self.assertEqual(hashlib.sha256(RUN.read_bytes()).hexdigest(),
                         '90fe38027bc3c04e18f76333e08e410b8bd7aca65d3db5c64cddf1025db697e8')
        self.assertEqual(self.artifact['status'], 'dnf')
        self.assertEqual(self.artifact['failure_cause'], 'model')
        self.assertEqual(self.artifact['failure_events'], 2)

    def test_npc_native_text_is_invalid_json_and_fails_contract(self):
        text, messages = self.replay('m08:0:candidate:4',
            'a9424e24c8e3beec955c35fed9fbea72b862f30e110e2feaef6bd60c6d3ae3b8')
        with self.assertRaises(json.JSONDecodeError) as caught:
            json.loads(text)
        self.assertEqual(caught.exception.pos, 41)
        self.assertEqual(text[41], '\n')
        # Permitting literal control characters still does not repair the JSON.
        with self.assertRaises(json.JSONDecodeError):
            json.loads(text, strict=False)
        self.assertEqual(_npc_text(text, messages),
                         ('', 'Expected a JSON object containing NPC dialogue.'))

    def test_gaeilge_fences_fail_and_unfenced_event_still_scores_zero(self):
        text, _ = self.replay('g24:0:candidate:0',
            '5e4180a6d3203cba7f9ddb7341d320b4b60f899e2326086ee920e561d6266667')
        answer = self.cases['g24']['answer']
        with self.assertRaises(json.JSONDecodeError):
            objective_score(text, answer)
        self.assertTrue(text.startswith('```json\n'))
        self.assertTrue(text.rstrip().endswith('```'))
        # Diagnostic counterfactual only; never passed back to the runner.
        inner = text.strip()[len('```json\n'):-3].strip()
        self.assertEqual(json.loads(inner), {
            'irish_meaning_choice': 'B', 'event': 'The fair', 'time': 'noon tomorrow'})
        self.assertEqual(objective_score(inner, answer), 0.0)
