import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rundale_bench.reconciliation import append_monitoring_reconciliation
from rundale_bench.storage import rebuild_index


class BillingReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'results'
        self.run_dir = self.root / '3.0' / 'runs'
        self.ledger_dir = self.root / '3.0' / 'ledgers'
        self.run_dir.mkdir(parents=True)
        self.ledger_dir.mkdir()
        self.run_id = '5e2177f168e2'
        self.run = {
            'version': '3.0', 'run_id': self.run_id, 'status': 'dnf', 'failure_cause': 'unknown',
            'budget_status': 'billing_uncertain', 'cost_usd': 0, 'spending_exposure_usd': 0.0185515,
            'model': 'Example', 'reasoning': 'high', 'completed_at': '2026-10-18T17:34:15.099859+00:00',
            'overall': None, 'scores': {},
        }
        self.run_path = self.run_dir / f'{self.run_id}.json'
        self.run_path.write_text(json.dumps(self.run, indent=2) + '\n')
        self.ledger = {
            'run_id': self.run_id, 'ledger_sha256': 'a' * 64, 'billing_reconciled': False,
            'calls': [{'id': 'candidate', 'state': 'uncertain', 'reserved': 0.0185515, 'actual': None}],
        }
        self.ledger_path = self.ledger_dir / f'{self.run_id}.json'
        self.ledger_path.write_text(json.dumps(self.ledger, indent=2) + '\n')
        self.evidence = {
            'schema_version': 1, 'run_id': self.run_id, 'captured_at': '2026-10-18T23:15:28Z',
            'identity_binding': {
                'checked_locally': True, 'independently_verified': False,
                'key_resource_sha256': 'b' * 64, 'described_project_id_sha256': 'c' * 64,
                'lookup_project_number_sha256': 'd' * 64, 'described_project_number_sha256': 'd' * 64,
            },
            'queries': {
                'request_count': {
                    'parameters': {
                        'filter': 'metric.type="serviceruntime.googleapis.com/api/request_count" AND resource.labels.service="generativelanguage.googleapis.com"',
                        'interval.startTime': '2026-10-18T17:30:00Z', 'interval.endTime': '2026-10-18T17:45:00Z',
                        'view': 'FULL', 'pageSize': 1000,
                    },
                    'http_status': 200, 'pagination_complete': True,
                    'pages': [{'timeSeries': [{'metric': {
                        'type': 'serviceruntime.googleapis.com/api/request_count',
                        'labels': {'response_code': '200', 'grpc_status_code': '0'},
                    }, 'resource': {'labels': {
                        'service': 'generativelanguage.googleapis.com',
                        'method': 'google.ai.generativelanguage.v1beta.ModelService.GetModel',
                        'credential_id': 'key-resource-sha256:' + 'b' * 64,
                        'project_id': 'sha256:' + 'c' * 64,
                    }}, 'points': [{'interval': {'startTime': '2026-10-18T17:35:48.001Z', 'endTime': '2026-10-18T17:36:48Z'},
                                     'value': {'int64Value': '1'}}]}]}],
                },
                'output_tokens': {
                    'parameters': {
                        'filter': 'metric.type="generativelanguage.googleapis.com/generate_content_usage_output_token_count"',
                        'interval.startTime': '2026-10-18T17:25:00Z', 'interval.endTime': '2026-10-18T17:50:00Z',
                        'view': 'FULL', 'pageSize': 1000,
                    },
                    'http_status': 200, 'pagination_complete': True, 'pages': [{'unit': '1'}],
                },
            },
            'limitations': ['Provider monitoring is not an invoice or request-specific billing receipt.'],
        }
        self.evidence_path = Path(self.temp.name) / 'monitoring.json'
        self.evidence_path.write_text(json.dumps(self.evidence, indent=2) + '\n')

    def tearDown(self):
        self.temp.cleanup()

    def reconcile(self):
        return append_monitoring_reconciliation(self.root, self.run_id, self.ledger_path, self.evidence_path)

    def test_append_keeps_original_history_unchanged_and_is_idempotent(self):
        run_bytes = self.run_path.read_bytes()
        ledger_bytes = self.ledger_path.read_bytes()
        record = self.reconcile()
        self.assertEqual(self.reconcile(), record)
        self.assertEqual(self.run_path.read_bytes(), run_bytes)
        self.assertEqual(self.ledger_path.read_bytes(), ledger_bytes)
        self.assertEqual(record['conclusion'], 'not_billed_based_on_provider_monitoring')
        self.assertEqual(record['monitoring_estimate_usd'], 0)
        self.assertIsNone(record['actual_cost_usd'])
        self.assertEqual(record['original_artifacts']['run_sha256'], hashlib.sha256(run_bytes).hexdigest())

        indexed = rebuild_index(self.root)
        row = indexed['versions'][0]['runs'][0]
        self.assertEqual(row['failure_cause'], 'unknown')
        self.assertEqual(row['budget_status'], 'billing_uncertain')
        self.assertEqual(row['spending_exposure_usd'], 0.0185515)
        self.assertEqual(row['billing_reconciliation']['monitoring_estimate_usd'], 0)
        self.assertIsNone(row['billing_reconciliation']['actual_cost_usd'])
        self.assertEqual(indexed['versions'][0]['rows'][0]['billing_reconciliation'], row['billing_reconciliation'])

    def test_source_changes_and_evidence_mismatches_fail_closed(self):
        self.reconcile()
        changed_run = copy.deepcopy(self.run)
        changed_run['reason'] = 'modified'
        self.run_path.write_text(json.dumps(changed_run))
        with self.assertRaisesRegex(ValueError, 'run hash'):
            rebuild_index(self.root)

        self.run_path.write_text(json.dumps(self.run))
        changed = copy.deepcopy(self.evidence)
        changed['run_id'] = 'another-run'
        self.evidence_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'run ID'):
            self.reconcile()

    def test_conflicting_existing_record_cannot_be_overwritten(self):
        self.reconcile()
        path = self.root / '3.0' / 'reconciliations' / f'{self.run_id}.json'
        record = json.loads(path.read_text())
        record['monitoring_estimate_usd'] = 1
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'append-only'):
            self.reconcile()

    def test_published_embedded_monitoring_evidence_is_hash_checked(self):
        self.reconcile()
        path = self.root / '3.0' / 'reconciliations' / f'{self.run_id}.json'
        record = json.loads(path.read_text())
        record['monitoring_evidence']['limitations'] = ['Changed after review']
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'evidence hash'):
            rebuild_index(self.root)

    def test_changed_ledger_export_is_rejected_when_rebuilding_index(self):
        self.reconcile()
        changed = json.loads(self.ledger_path.read_text())
        changed['calls'][0]['reserved'] = 0.02
        self.ledger_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'ledger hash'):
            rebuild_index(self.root)

    def test_monitoring_windows_and_positive_control_must_cover_failure_time(self):
        invalid_windows = copy.deepcopy(self.evidence)
        invalid_windows['queries']['request_count']['parameters']['interval.startTime'] = '2026-10-18T17:33:00Z'
        self.evidence_path.write_text(json.dumps(invalid_windows))
        with self.assertRaisesRegex(ValueError, 'inferred failure window'):
            self.reconcile()

        invalid_control = copy.deepcopy(self.evidence)
        point = invalid_control['queries']['request_count']['pages'][0]['timeSeries'][0]['points'][0]
        point['interval'] = {'startTime': '2026-10-18T17:46:00Z', 'endTime': '2026-10-18T17:47:00Z'}
        self.evidence_path.write_text(json.dumps(invalid_control))
        with self.assertRaisesRegex(ValueError, 'positive control falls outside'):
            self.reconcile()

    def test_malformed_nested_monitoring_data_fails_as_value_error(self):
        malformed = copy.deepcopy(self.evidence)
        malformed['queries']['request_count']['pages'][0]['timeSeries'][0]['resource'] = ['unexpected']
        self.evidence_path.write_text(json.dumps(malformed))
        with self.assertRaisesRegex(ValueError, 'series is malformed'):
            self.reconcile()

    def test_output_token_evidence_cannot_contradict_not_billed_conclusion(self):
        self.evidence['queries']['output_tokens']['pages'][0]['timeSeries'] = [{'points': [{'value': {'int64Value': '1'}}]}]
        self.evidence_path.write_text(json.dumps(self.evidence))
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            self.reconcile()

    def test_published_record_exposes_identity_caveat_and_matching_download_hash(self):
        record = self.reconcile()
        self.assertTrue(any('not independently verified' in text for text in record['limitations']))
        self.assertTrue(any('known-generation positive control' in text for text in record['limitations']))
        row = rebuild_index(self.root)['versions'][0]['rows'][0]
        downloaded = self.root/row['billing_reconciliation']['evidence_path']
        self.assertEqual(row['billing_reconciliation']['evidence_sha256'], hashlib.sha256(downloaded.read_bytes()).hexdigest())

    def test_rebuilding_cannot_drop_public_identity_caveat(self):
        self.reconcile()
        path = self.root/'3.0'/'reconciliations'/f'{self.run_id}.json'
        record = json.loads(path.read_text())
        record['limitations'] = ['This is not an invoice.']
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'identity and invoice limitations'):
            rebuild_index(self.root)

    def test_original_run_and_ledger_shape_are_required(self):
        self.run['failure_cause'] = 'infrastructure'
        self.run_path.write_text(json.dumps(self.run))
        with self.assertRaisesRegex(ValueError, 'unknown-cause DNF'):
            self.reconcile()


if __name__ == '__main__':
    unittest.main()
