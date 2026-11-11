import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const collect = fileURLToPath(new URL('../scripts/collect-suite.mjs', import.meta.url));
const compare = fileURLToPath(new URL('../scripts/compare.mjs', import.meta.url));
const fixture = (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'hardware-metrics-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
};
const put = (file, value) => {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(value));
};
const job = (iteration) => ({ name: `celesto ${iteration}`, conclusion: 'success', steps: [] });

function collectFixture(dir, jobs) {
  put(join(dir, 'jobs.json'), { total_count: jobs.length, jobs });
  const preload = join(dir, 'fetch.mjs');
  writeFileSync(preload, `import { readFileSync } from 'node:fs';
    globalThis.fetch = async () => ({ ok: true, json: async () => JSON.parse(readFileSync(process.env.TEST_JOBS, 'utf8')) });`);
  execFileSync(process.execPath, ['--import', preload, collect, 'hardware', join(dir, 'metrics'), join(dir, 'results.json')], {
    env: { ...process.env, TEST_JOBS: join(dir, 'jobs.json'), GITHUB_TOKEN: 'test', GITHUB_REPOSITORY: 'owner/repo', GITHUB_RUN_ID: '10', GITHUB_RUN_ATTEMPT: '1', GITHUB_STEP_SUMMARY: '' },
  });
  return JSON.parse(readFileSync(join(dir, 'results.json'), 'utf8')).results;
}

test('collector attaches the flattened artifact for a single benchmark job', (t) => {
  const dir = fixture(t);
  const metrics = { cpu: { sysbenchMultiEps: 12345 } };
  put(join(dir, 'metrics', 'metrics.json'), metrics);
  assert.deepEqual(collectFixture(dir, [job(1), { name: 'collect' }])[0].metrics, metrics);
});

test('collector keeps per-job artifacts separate and does not guess a flattened artifact owner', (t) => {
  const dir = fixture(t);
  put(join(dir, 'metrics', 'metrics-celesto-1', 'metrics.json'), { cpu: { sysbenchMultiEps: 100 } });
  put(join(dir, 'metrics', 'metrics-celesto-2', 'metrics.json'), { cpu: { sysbenchMultiEps: 200 } });
  assert.deepEqual(collectFixture(dir, [job(1), job(2)]).map((r) => r.metrics.cpu.sysbenchMultiEps), [100, 200]);
  const ambiguous = fixture(t);
  put(join(ambiguous, 'metrics', 'metrics.json'), { cpu: { sysbenchMultiEps: 999 } });
  assert.deepEqual(collectFixture(ambiguous, [job(1), job(2)]).map((r) => r.metrics), [null, null]);
});

test('comparison recovers missing hardware metrics from the original run artifact', (t) => {
  const dir = fixture(t);
  const ours = join(dir, 'ours'), theirs = join(dir, 'theirs'), out = join(dir, 'out');
  mkdirSync(theirs);
  put(join(ours, 'results-hardware-10.json'), {
    suite: 'hardware', run: { id: 10, attempt: 1, date: new Date().toISOString().slice(0, 10) },
    results: [{ provider: 'celesto', iteration: 1, status: 'success', metrics: null }],
  });
  put(join(ours, 'metrics-hardware-10', 'metrics.json'), { cpu: { sysbenchMultiEps: 12345 } });
  execFileSync(process.execPath, [compare, ours, theirs, out, '30']);
  assert.match(readFileSync(join(out, 'README.md'), 'utf8'), /CPU all cores \(sysbench, events\/s\) \| \*\*12,345\*\*/);
  const run = JSON.parse(readFileSync(join(ours, 'results-hardware-10.json'), 'utf8'));
  run.results.push({ provider: 'github', iteration: 1, status: 'success', metrics: null });
  put(join(ours, 'results-hardware-10.json'), run);
  execFileSync(process.execPath, [compare, ours, theirs, out, '30']);
  assert.match(readFileSync(join(out, 'README.md'), 'utf8'), /CPU all cores \(sysbench, events\/s\) \| –/);
});
