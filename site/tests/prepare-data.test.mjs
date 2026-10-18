import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../scripts/prepare-data.mjs', import.meta.url));

test('site preparation copies only named public qualification JSON, including nested artifacts', async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'rundale-bench-site-'));
  const root = temp;
  const site = path.join(root, 'site');
  const qualification = path.join(root, 'qualification', '3.0');
  try {
    await mkdir(site, { recursive: true });
    await mkdir(path.join(root, 'results'), { recursive: true });
    await mkdir(path.join(root, 'review'), { recursive: true });
    await mkdir(path.join(root, 'archive'), { recursive: true });
    await mkdir(path.join(qualification, 'cases'), { recursive: true });
    await writeFile(path.join(root, 'results', 'index.json'), JSON.stringify({ schema_version: 1, versions: [{ version: '3.0' }] }));
    await writeFile(path.join(root, 'review', 'review.html'), '<html></html>');
    await writeFile(path.join(root, 'archive', 'old.json'), '{}');
    await writeFile(path.join(qualification, 'status.json'), '{"status":"provisional"}');
    await writeFile(path.join(qualification, 'controls.json'), '{"checks":[]}');
    await writeFile(path.join(qualification, 'private-notes.json'), '{"secret":true}');
    await writeFile(path.join(qualification, 'cases', 'judgments.json'), '{"judgments":[]}');
    await writeFile(path.join(qualification, 'cases', 'private.json'), '{"secret":true}');

    execFileSync(process.execPath, [script], { cwd: site, stdio: 'pipe' });

    const published = path.join(site, 'public', 'evidence', 'qualification', '3.0');
    assert.equal(await readFile(path.join(published, 'status.json'), 'utf8'), '{"status":"provisional"}');
    assert.equal(await readFile(path.join(published, 'controls.json'), 'utf8'), '{"checks":[]}');
    assert.equal(await readFile(path.join(published, 'cases', 'judgments.json'), 'utf8'), '{"judgments":[]}');
    const topLevel = await readdir(published);
    assert.deepEqual(topLevel.sort(), ['cases', 'controls.json', 'status.json']);
    assert.deepEqual((await readdir(path.join(published, 'cases'))).sort(), ['judgments.json']);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
