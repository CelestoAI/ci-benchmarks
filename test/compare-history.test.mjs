import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('comparison pools recent Celesto runs once, ignores failed jobs and expired runs', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'compare-history-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const ours = join(dir, 'ours'), theirs = join(dir, 'theirs'), out = join(dir, 'out');
  mkdirSync(ours);
  mkdirSync(join(theirs, 'rust'), { recursive: true });
  const date = (daysAgo) => new Date(Date.now() - daysAgo * 86400e3).toISOString().slice(0, 10);
  const result = (seconds, status = 'success') => ({ provider: 'celesto', status, workloadSeconds: seconds });
  const run = (id, daysAgo, results) => ({ suite: 'rust', run: { id, attempt: 1, date: date(daysAgo) }, results });
  const newest = run(1, 0, [result(80), result(1000, 'failure')]);
  for (const [name, data] of Object.entries({
    'a-newest.json': newest,
    'b-middle.json': run(2, 1, [result(40)]),
    'c-oldest.json': run(3, 2, [result(20)]),
    'd-duplicate.json': newest,
    'e-expired.json': run(4, 40, [result(1)]),
  })) writeFileSync(join(ours, name), JSON.stringify(data));
  writeFileSync(join(theirs, 'rust', `${date(0)}-github.json`), JSON.stringify({
    results: [{ runnerId: 'github-x64', status: 'success', workloadSeconds: 100 }],
  }));
  execFileSync(process.execPath, [fileURLToPath(new URL('../scripts/compare.mjs', import.meta.url)), ours, theirs, out, '30']);
  const readme = readFileSync(join(out, 'README.md'), 'utf8');
  assert.match(readme, /Jobs: Celesto 3, GitHub 1\./);
  assert.ok(readme.includes(`Latest Celesto run: ${date(0)}.`));
  assert.match(readme, /last 30 days of runs/);
  for (const theme of ['light', 'dark']) {
    const svg = readFileSync(join(out, `summary-${theme}.svg`), 'utf8');
    const row = svg.split('>Celesto</text>')[1]?.split('<text x="16"')[0];
    assert.match(row, />40s<\/text>/);
  }
});
