import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aggregateCostLabel, aggregateCoverage, billingLedgerLink, billingReconciliationLink, budgetLabel, coverageLabel, escapeHtml, findRun,
  monitoringReconciliationLabel, reconciliationDetailsHtml,
  historicalRuns, latestRows, performanceLabel, qualificationCopy, qualificationEvidenceLinks,
  recordedCostLabel, rowQualificationLabel, runNoticeLabel, runStatusLabel,
  scoreLabel, scoreStatusLabel,
} from '../src/lib/dashboard.mjs';

const version = {
  version: '3.0',
  qualification: { status: 'pending', reason: 'Native judge review remains open.' },
  rows: [{
    model: 'Example', run_id: 'attempt-2', status: 'dnf', overall: null,
    reason: 'Repeated model contract failures', failure_cause: 'model',
    coverage: {
      dialogue: { completed: 4, required: 32 },
      multiturn: { completed: 2, required: 16 },
      gaeilge: { completed: 0, required: 24 },
    },
    uncertainty: { dialogue: { latency_ms: { p95: 1800 }, ttft_ms: { p95: 450 } } },
    budget_status: 'within_cap', budget_usd: 5,
  }],
  runs: [
    { run_id: 'attempt-1', status: 'complete', overall: 72 },
    { run_id: 'attempt-2', status: 'dnf', overall: null },
  ],
};

test('latest rows and raw history stay separate while details resolve by run id', () => {
  assert.deepEqual(latestRows(version).map((row) => row.run_id), ['attempt-2']);
  assert.equal(findRun(version, 'attempt-1').overall, 72);
  assert.equal(findRun(version, 'attempt-2').status, 'dnf');
  assert.equal(findRun(version, 'missing'), undefined);
  assert.deepEqual(historicalRuns(version).map((run) => run.run_id), ['attempt-1']);
});

test('latest complete result stays selected while an older DNF remains inspectable', () => {
  const example = {
    version: '3.0',
    rows: [{ run_id: 'complete-new', model: 'Example', status: 'complete', overall: 84 }],
    runs: [
      { run_id: 'dnf-old', model: 'Example', status: 'dnf', overall: null },
      { run_id: 'complete-new', model: 'Example', status: 'complete', overall: 84 },
    ],
  };
  assert.equal(latestRows(example)[0].run_id, 'complete-new');
  assert.deepEqual(historicalRuns(example).map((run) => run.run_id), ['dnf-old']);
  assert.equal(findRun(example, historicalRuns(example)[0].run_id).status, 'dnf');
});

test('retained complete score keeps the newer infrastructure DNF attempt inspectable', () => {
  const example = {
    version: '3.0',
    rows: [{ run_id: 'complete-prior', latest_attempt_id: 'dnf-infrastructure', model: 'Example', status: 'complete', overall: 84 }],
    runs: [
      { run_id: 'complete-prior', model: 'Example', status: 'complete', overall: 84 },
      { run_id: 'dnf-infrastructure', model: 'Example', status: 'dnf', overall: null, failure_cause: 'infrastructure' },
    ],
  };
  assert.equal(latestRows(example)[0].run_id, 'complete-prior');
  assert.deepEqual(historicalRuns(example).map((run) => run.run_id), ['dnf-infrastructure']);
  assert.equal(findRun(example, historicalRuns(example)[0].run_id).failure_cause, 'infrastructure');
});

test('DNF, reason, category coverage, and capped budget have readable labels', () => {
  const [row] = latestRows(version);
  assert.equal(scoreLabel(row.overall, row.status), 'DNF');
  assert.equal(coverageLabel(row.coverage), 'Dialogue 4/32 · Multi-turn 2/16 · Gaeilge 0/24');
  assert.equal(aggregateCoverage([row]), 'Dialogue 4/32 · Multi-turn 2/16 · Gaeilge 0/24');
  assert.equal(budgetLabel(row), 'Within cap ($5.00 cap)');
  assert.equal(runStatusLabel(row), 'DNF (model)');
  assert.equal(runNoticeLabel(row), 'Repeated model contract failures');
  const budgetDnf = { ...row, failure_cause: 'budget', reason: 'Budget cap reached', budget_status: 'cap_reached' };
  assert.equal(scoreLabel(budgetDnf.overall, budgetDnf.status), 'DNF');
  assert.equal(budgetLabel(budgetDnf), 'Cap reached ($5.00 cap)');
  assert.equal(runStatusLabel(budgetDnf), 'DNF (budget)');
  assert.equal(runNoticeLabel(budgetDnf), 'Budget cap reached');
  assert.equal(runNoticeLabel({ ...row, reason: undefined, notice: 'A later attempt failed; this score is retained.' }), 'A later attempt failed; this score is retained.');
});

test('billing-uncertain DNF cost stays a lower bound and exposes uncertain billing in row and total', () => {
  const billingUncertainDnf = {
    model: 'Example', status: 'dnf', overall: null, cost_usd: 0,
    budget_status: 'billing_uncertain', spending_exposure_usd: 0.0185515,
  };
  assert.equal(recordedCostLabel(billingUncertainDnf), '≥ $0.0000 · billing uncertain');
  assert.equal(aggregateCostLabel([billingUncertainDnf]), '≥ $0.0000 · billing uncertain · exposure $0.0186');
  assert.equal(aggregateCostLabel([
    { cost_usd: 0.3, budget_status: 'within_cap', spending_exposure_usd: 0.3 }, billingUncertainDnf,
  ]), '≥ $0.3000 · billing uncertain · exposure $0.3186');
  assert.equal(recordedCostLabel({ ...billingUncertainDnf, cost_usd: null }), 'Unknown · billing uncertain');
  assert.equal(aggregateCostLabel([{ cost_usd: 0.3, budget_status: 'within_cap', spending_exposure_usd: 0.3 }]), '$0.3000');
});

test('monitoring reconciliation stays distinct from original uncertain cost and invoice actuals', () => {
  const reconciliation = {
    conclusion: 'not_billed_based_on_provider_monitoring',
    monitoring_estimate_usd: 0,
    actual_cost_usd: null,
    evidence_path: '3.0/reconciliations/attempt-1.json',
    ledger_evidence_path: '3.0/ledgers/attempt-1.json',
  };
  const row = { cost_usd: 0, budget_status: 'billing_uncertain', billing_reconciliation: reconciliation };
  assert.equal(recordedCostLabel(row), '≥ $0.0000 · billing uncertain');
  assert.equal(monitoringReconciliationLabel(reconciliation), 'Monitoring: not billed · $0.0000 estimate; not invoice-backed');
  assert.equal(billingReconciliationLink(reconciliation, '/rundale-bench'), '/rundale-bench/evidence/3.0/reconciliations/attempt-1.json');
  assert.equal(billingLedgerLink(reconciliation, '/rundale-bench'), '/rundale-bench/evidence/3.0/ledgers/attempt-1.json');
  assert.equal(billingReconciliationLink({ ...reconciliation, evidence_path: '../private.json' }, '/'), null);
  assert.equal(billingLedgerLink({ ...reconciliation, ledger_evidence_path: '3.0/ledgers/../private.json' }, '/'), null);
  assert.equal(monitoringReconciliationLabel({ ...reconciliation, actual_cost_usd: 0 }), null);
});

test('qualification and performance summaries follow published status and p95 values', () => {
  assert.equal(qualificationCopy(version).title, 'Version 3.0 qualification pending.');
  assert.equal(qualificationCopy(version).description, 'Native judge review remains open.');
  assert.equal(performanceLabel(version.rows[0].uncertainty), 'Dialogue: latency 1.8 s, TTFT 450 ms');
  assert.equal(qualificationCopy({ version: '2.0', qualification: { status: 'qualified' } }).title, 'Version 2.0 is qualified.');
  assert.equal(scoreLabel(null, 'complete'), '—');
});

test('provisional scoring status is explicit and each row uses its own validation record', () => {
  const provisional = {
    version: '3.0',
    qualification: {
      status: 'provisional',
      validation_basis: 'automated_checks_only',
      reason: 'Owner authorized provisional publication.',
    },
  };
  assert.deepEqual(qualificationCopy(provisional), {
    status: 'provisional',
    title: 'Version 3.0 scores are provisional.',
    description: 'Owner authorized provisional publication.',
  });
  assert.equal(scoreStatusLabel({ score_status: 'provisional' }), 'Provisional score');
  assert.equal(scoreStatusLabel({ score_status: 'human_validated' }), 'Human validated score');
  assert.equal(rowQualificationLabel({ qualification_status: 'provisional' }), 'Provisional');
  assert.equal(rowQualificationLabel({ qualification_status: 'human_validated' }), 'Human validated');
  assert.equal(rowQualificationLabel({ qualification_status: 'qualified' }), 'Qualified');
  assert.equal(rowQualificationLabel({}), 'Unreported');
  // A qualified version receipt must not confer validation on a row without its own status.
  assert.equal(rowQualificationLabel({ score_status: 'provisional' }), 'Unreported');
  assert.deepEqual(qualificationEvidenceLinks({ version: '3.0' }, '/rundale-bench/'), [
    { label: 'Qualification status', href: '/rundale-bench/evidence/qualification/3.0/status.json' },
    { label: 'Automated checks', href: '/rundale-bench/evidence/qualification/3.0/controls.json' },
    { label: 'Raw judgments', href: '/rundale-bench/evidence/qualification/3.0/judgments.json' },
  ]);
  assert.deepEqual(qualificationEvidenceLinks({ version: '../private' }, '/rundale-bench/'), []);
});

test('untrusted display strings are escaped before table markup is assembled', () => {
  assert.equal(escapeHtml('<img src=x onerror="x">'), '&lt;img src=x onerror=&quot;x&quot;&gt;');
});

 test('monitoring detail displays identity and invoice caveats with escaped content', () => {
  const detail = reconciliationDetailsHtml({
    basis: 'No generation request for the locally checked key and project.',
    limitations: ['Identity mapping was checked locally, not independently verified.', 'Monitoring is not an invoice.', '<script>private()</script>'],
  });
  assert.match(detail, /locally checked key/);
  assert.match(detail, /not independently verified/);
  assert.match(detail, /not an invoice/);
  assert.match(detail, /&lt;script&gt;/);
  assert.doesNotMatch(detail, /<script>/);
});
