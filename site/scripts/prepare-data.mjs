import { cp, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const qualificationArtifacts = new Set([
  'status.json', 'collection.json', 'judgments.json', 'controls.json',
  'bias-diagnostics.json', 'references.json',
]);

async function copyPublicQualificationArtifacts(sourceDir, targetDir) {
  let entries;
  try { entries = await readdir(sourceDir, { withFileTypes: true }); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  for (const entry of entries) {
    const source = path.join(sourceDir, entry.name);
    const target = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      await copyPublicQualificationArtifacts(source, target);
    } else if (entry.isFile() && qualificationArtifacts.has(entry.name)) {
      await mkdir(targetDir, { recursive: true });
      await cp(source, target);
    }
  }
}

const root = path.resolve('..');
const dataPath = path.join(root, 'results/index.json');
const publicPath = path.resolve('public');
const evidenceRoot = path.join(publicPath, 'evidence');
await mkdir(evidenceRoot, { recursive: true });
let data = { schema_version: 1, versions: [] };
try { data = JSON.parse(await readFile(dataPath, 'utf8')); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
if (data.schema_version !== 1 || !Array.isArray(data.versions)) throw new Error('Unsupported results/index.json schema');
for (const version of data.versions) {
  const versionName = String(version.version);
  if (!/^[A-Za-z0-9._-]+$/.test(versionName) || versionName === '.' || versionName === '..') throw new Error('Invalid evaluation version in results/index.json');
  const runDir = path.join(root, 'results', version.version, 'runs');
  try {
    const entries = await readdir(runDir, { withFileTypes: true });
    await mkdir(path.join(evidenceRoot, version.version, 'runs'), { recursive: true });
    for (const entry of entries) if (entry.isFile() && entry.name.endsWith('.json')) {
      await cp(path.join(runDir, entry.name), path.join(evidenceRoot, version.version, 'runs', entry.name));
    }
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const reconciliationPaths = new Set();
  const ledgerPaths = new Set();
  const escapedVersion = versionName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const run of [...(version.runs || []), ...(version.rows || [])]) {
    if (!run?.billing_reconciliation) continue;
    const evidencePath = run.billing_reconciliation.evidence_path;
    if (typeof evidencePath !== 'string' || !new RegExp(`^${escapedVersion}/reconciliations/[A-Za-z0-9._-]+\\.json$`).test(evidencePath)) {
      throw new Error('Invalid billing reconciliation evidence path in results/index.json');
    }
    reconciliationPaths.add(evidencePath);
    const ledgerPath = run.billing_reconciliation.ledger_evidence_path;
    if (typeof ledgerPath !== 'string' || !new RegExp(`^${escapedVersion}/ledgers/[A-Za-z0-9._-]+\\.json$`).test(ledgerPath)) {
      throw new Error('Invalid billing reconciliation ledger path in results/index.json');
    }
    ledgerPaths.add(ledgerPath);
  }
  for (const evidencePath of [...reconciliationPaths, ...ledgerPaths]) {
    const relative = evidencePath.split('/');
    const expectedDirectory = relative[1] === 'reconciliations' ? 'reconciliations' : 'ledgers';
    if (relative[0] !== versionName || relative[1] !== expectedDirectory || relative.length !== 3
        || (expectedDirectory === 'reconciliations' && !reconciliationPaths.has(evidencePath))
        || (expectedDirectory === 'ledgers' && !ledgerPaths.has(evidencePath))) throw new Error('Invalid billing reconciliation evidence path');
    const source = path.resolve(root, 'results', ...relative);
    if (path.dirname(source) !== path.resolve(root, 'results', versionName, expectedDirectory)) throw new Error('Invalid billing reconciliation evidence path');
    const target = path.join(evidenceRoot, ...relative);
    await mkdir(path.dirname(target), { recursive: true });
    await cp(source, target);
  }
  await copyPublicQualificationArtifacts(
    path.join(root, 'qualification', version.version),
    path.join(evidenceRoot, 'qualification', version.version),
  );
}
await writeFile(path.join(publicPath, 'results.json'), JSON.stringify(data, null, 2) + '\n');

await mkdir(path.join(publicPath, "review"), { recursive: true });
await cp(path.join(root, "review/review.html"), path.join(publicPath, "review/index.html"));

await cp(path.join(root, "archive"), path.join(publicPath, "archive"), { recursive: true });
