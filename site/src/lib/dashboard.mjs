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
  if (status === 'provisional') {
    return {
      status,
      title: `Version ${version?.version} scores are provisional.`,
      description: reason || 'Automated judge checks passed. Human agreement and scoring accuracy have not been measured.',
    };
  }
  const title = status === 'qualified'
    ? `Version ${version?.version} is qualified.`
    : `Version ${version?.version} qualification ${status}.`;
  const description = reason || (status === 'qualified'
    ? 'Qualification evidence is complete. Results below reproduce published run records.'
    : 'No qualified results are available yet.');
  return { status, title, description };
}

export function scoreStatusLabel(row) {
  const status = String(row?.score_status || '').toLowerCase();
  if (status === 'provisional') return 'Provisional score';
  if (status === 'human_validated') return 'Human validated score';
  return status ? status.replaceAll('_', ' ') : 'Score status unreported';
}

export function rowQualificationLabel(row) {
  const status = String(row?.qualification_status || '').toLowerCase();
  if (status === 'provisional') return 'Provisional';
  if (status === 'human_validated') return 'Human validated';
  if (status === 'qualified') return 'Qualified';
  return status ? status.replaceAll('_', ' ') : 'Unreported';
}

export function qualificationEvidenceLinks(version, baseUrl) {
  const value = String(version?.version || '');
  if (!/^[A-Za-z0-9._-]+$/.test(value)) return [];
  const base = String(baseUrl || '').replace(/\/$/, '');
  const root = `${base}/evidence/qualification/${encodeURIComponent(value)}`;
  return [
    { label: 'Qualification status', href: `${root}/status.json` },
    { label: 'Automated checks', href: `${root}/controls.json` },
    { label: 'Raw judgments', href: `${root}/judgments.json` },
  ];
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

function formatDollars(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(4)}` : null;
}

export function recordedCostLabel(run) {
  const amount = formatDollars(run?.cost_usd);
  if (String(run?.budget_status || '').toLowerCase() === 'billing_uncertain') {
    return amount ? `≥ ${amount} · billing uncertain` : 'Unknown · billing uncertain';
  }
  return amount || '—';
}

export function aggregateCostLabel(runs) {
  const history = Array.isArray(runs) ? runs : [];
  const entries = history.map((run) => run?.cost_usd).filter((value) => typeof value === 'number' && Number.isFinite(value));
  const uncertain = history.some((run) => String(run?.budget_status || '').toLowerCase() === 'billing_uncertain');
  const exposure = history.map((run) => run?.spending_exposure_usd)
    .filter((value) => typeof value === 'number' && Number.isFinite(value));
  const total = entries.reduce((sum, value) => sum + value, 0);
  const label = uncertain
    ? (entries.length ? `≥ ${formatDollars(total)} · billing uncertain` : 'Unknown · billing uncertain')
    : (entries.length ? formatDollars(total) : '—');
  return (uncertain || history.some((run) => run?.budget_status === 'cap_reached')) && exposure.length ? `${label} · exposure ${formatDollars(exposure.reduce((sum, value) => sum + value, 0))}` : label;
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
