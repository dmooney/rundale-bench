import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aggregateCoverage, budgetLabel, coverageLabel, escapeHtml, findRun,
  latestRows, performanceLabel, qualificationCopy, runNoticeLabel, runStatusLabel, scoreLabel,
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

test('qualification and performance summaries follow published status and p95 values', () => {
  assert.equal(qualificationCopy(version).title, 'Version 3.0 qualification pending.');
  assert.equal(qualificationCopy(version).description, 'Native judge review remains open.');
  assert.equal(performanceLabel(version.rows[0].uncertainty), 'Dialogue: latency 1.8 s, TTFT 450 ms');
  assert.equal(qualificationCopy({ version: '2.0', qualification: { status: 'qualified' } }).title, 'Version 2.0 is qualified.');
  assert.equal(scoreLabel(null, 'complete'), '—');
});

test('untrusted display strings are escaped before table markup is assembled', () => {
  assert.equal(escapeHtml('<img src=x onerror="x">'), '&lt;img src=x onerror=&quot;x&quot;&gt;');
});
