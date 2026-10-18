const CATEGORIES = ['dialogue', 'multiturn', 'gaeilge'];
const CATEGORY_LABELS = { dialogue: 'Dialogue', multiturn: 'Multi-turn', gaeilge: 'Gaeilge' };

export function latestRows(version) {
  return Array.isArray(version?.rows) ? version.rows : [];
}

export function findRun(version, runId) {
  return (Array.isArray(version?.runs) ? version.runs : []).find((run) => run.run_id === runId);
}

export function qualificationCopy(version) {
  const status = String(version?.qualification?.status || 'pending').toLowerCase();
  const reason = version?.qualification?.reason || '';
  const title = status === 'qualified'
    ? `Version ${version?.version} is qualified.`
    : `Version ${version?.version} qualification ${status}.`;
  const description = reason || (status === 'qualified'
    ? 'Qualification evidence is complete. Results below reproduce published run records.'
    : 'No qualified results are available yet.');
  return { status, title, description };
}

export function runStatusLabel(row) {
  const status = String(row?.status || 'unknown').toUpperCase();
  const cause = row?.failure_cause ? ` (${row.failure_cause})` : '';
  return `${status}${cause}`;
}

export function runNoticeLabel(row) {
  return row?.notice || (String(row?.status || '').toLowerCase() === 'dnf' ? row?.reason : '') || '—';
}

export function scoreLabel(value, status) {
  if ((status || '').toLowerCase() === 'dnf' && (value === null || value === undefined)) return 'DNF';
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return String(value);
}

export function coverageLabel(coverage) {
  if (!coverage || typeof coverage !== 'object') return '—';
  return CATEGORIES.map((category) => {
    const value = coverage[category];
    if (!value || typeof value !== 'object') return `${CATEGORY_LABELS[category]} —`;
    const completed = value.completed ?? 0;
    const required = value.required ?? 0;
    return `${CATEGORY_LABELS[category]} ${completed}/${required}`;
  }).join(' · ');
}

function percentile(value) {
  const raw = value?.p95;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
  return `${raw >= 1000 ? `${(raw / 1000).toFixed(1)} s` : `${Math.round(raw)} ms`}`;
}

export function performanceLabel(uncertainty) {
  const parts = [];
  for (const category of CATEGORIES) {
    const entry = uncertainty?.[category];
    const latency = percentile(entry?.latency_ms);
    const ttft = percentile(entry?.ttft_ms);
    if (latency || ttft) {
      const label = CATEGORY_LABELS[category];
      parts.push(`${label}: ${latency ? `latency ${latency}` : ''}${latency && ttft ? ', ' : ''}${ttft ? `TTFT ${ttft}` : ''}`);
    }
  }
  return parts.length ? parts.join(' · ') : '—';
}

export function budgetLabel(run) {
  const states = {
    within_cap: 'Within cap',
    cap_reached: 'Cap reached',
    billing_uncertain: 'Billing uncertain',
  };
  const status = states[run?.budget_status] || run?.budget_status || '—';
  const cap = run?.budget_usd;
  return typeof cap === 'number' && Number.isFinite(cap) ? `${status} ($${cap.toFixed(2)} cap)` : String(status);
}

export function aggregateCoverage(rows) {
  const totals = Object.fromEntries(CATEGORIES.map((category) => [category, { completed: 0, required: 0 }]));
  let hasCoverage = false;
  for (const row of rows) {
    for (const category of CATEGORIES) {
      const source = row?.coverage?.[category];
      if (!source || typeof source !== 'object') continue;
      hasCoverage = true;
      totals[category].completed += Number(source.completed) || 0;
      totals[category].required += Number(source.required) || 0;
    }
  }
  if (!hasCoverage) return 'No coverage recorded';
  return coverageLabel(totals);
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}
