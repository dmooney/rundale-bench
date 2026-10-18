import { cp, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

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
  const runDir = path.join(root, 'results', version.version, 'runs');
  try {
    const entries = await readdir(runDir, { withFileTypes: true });
    await mkdir(path.join(evidenceRoot, version.version, 'runs'), { recursive: true });
    for (const entry of entries) if (entry.isFile() && entry.name.endsWith('.json')) {
      await cp(path.join(runDir, entry.name), path.join(evidenceRoot, version.version, 'runs', entry.name));
    }
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
}
await writeFile(path.join(publicPath, 'results.json'), JSON.stringify(data, null, 2) + '\n');

await mkdir(path.join(publicPath, "review"), { recursive: true });
await cp(path.join(root, "review/review.html"), path.join(publicPath, "review/index.html"));

await cp(path.join(root, "archive"), path.join(publicPath, "archive"), { recursive: true });
