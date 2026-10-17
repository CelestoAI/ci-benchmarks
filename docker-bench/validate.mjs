// Independent checks of the published measurements, not a replay of Python's statistics.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { basename, join } from 'node:path';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';

const dir = process.argv[2];
if (!dir) throw new Error('Usage: node docker-bench/validate.mjs RESULTS_DIR');
const json = file => JSON.parse(readFileSync(join(dir, file)));
const run = json('run.json'), samples = json('samples.json'), summary = json('summary.json');
assert.equal(run.conclusion, 'success');
assert.deepEqual(json('failures.json'), []);
if (run.cohorts) {
  const audit = json('cache-log-audit.json');
  assert.equal(new Set(audit.audited_jobs).size, 120);
  assert.equal(audit.selected_job_cache_save_warnings, 0);
  assert(run.jobs.every(j => audit.audited_jobs.includes(j.url)));
}
const expected = new Set();
for (let repetition = 1; repetition <= 5; repetition++) {
  for (const provider of ['github', 'celesto']) {
    for (const backend of ['portable', 'registry']) {
      for (const scenario of ['seed', 'unchanged', 'source', 'dependency']) {
        expected.add(`${provider}/${backend}/${scenario}/${repetition}`);
      }
    }
    for (const scenario of ['nocache', 'runtime', 'image-seed', 'image-warm']) {
      expected.add(`${provider}/none/${scenario}/${repetition}`);
    }
  }
}
const actual = new Set();
let logHashes = 0;
let exactArchiveHits = 0;
for (const folder of readdirSync(join(dir, 'raw'))) {
  const events = readFileSync(join(dir, 'raw', folder, 'events.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  const host = events.find(e => e.phase === 'host').data;
  const key = `${host.provider}/${host.backend}/${host.scenario}/${host.repetition}`;
  assert(!actual.has(key), `Duplicate sample ${key}`);
  actual.add(key);
  const suffix = `${host.provider}-${host.backend}-${host.scenario}-${host.repetition}`;
  const job = run.jobs.find(j => j.name.endsWith(suffix));
  assert(job && job.conclusion === 'success');
  assert.equal(host.commit, job.headSha ?? run.headSha);
  assert.equal(host.cpus, 4);
  assert(host.memory_bytes >= 14 * 1024 ** 3 && host.memory_bytes <= 17 * 1024 ** 3);
  const docker = JSON.parse(readFileSync(join(dir, 'raw', folder, 'docker-version.log'), 'utf8'));
  assert.equal(docker.Server.Version, '29.1.3');
  assert.equal(docker.Server.Arch, 'amd64');
  assert(readFileSync(join(dir, 'raw', folder, 'buildx-version.log'), 'utf8').includes('v0.30.1'));
  assert(readFileSync(join(dir, 'raw', folder, 'compose-version.log'), 'utf8').includes('v2.40.3'));
  assert.equal(events.find(e => e.phase === 'suite-complete').data.success, true);
  for (const event of events) {
    if (!event.data.log_sha256) continue;
    const content = readFileSync(join(dir, 'raw', folder, basename(event.data.log)));
    assert.equal(createHash('sha256').update(content).digest('hex'), event.data.log_sha256);
    logHashes++;
  }
  if (host.scenario === 'image-warm') {
    assert.equal(events.find(e => e.phase === 'image-cache-restore-end').data.cache_hit, 'true');
    exactArchiveHits++;
  }
  if (host.backend === 'portable' && host.scenario !== 'seed') {
    assert.equal(events.find(e => e.phase === 'build-cache-restore-end').data.cache_hit, 'true');
    exactArchiveHits++;
  }
}
assert.equal(exactArchiveHits, 40);
assert.deepEqual([...actual].sort(), [...expected].sort());
for (const row of summary) {
  for (const provider of ['github', 'celesto']) {
    const measured = samples.filter(s => s.provider === provider && s.backend === row.backend && s.scenario === row.scenario && s.metric === row.metric);
    assert.equal(measured.length, 5, `Incomplete ${provider}/${row.backend}/${row.scenario}/${row.metric}`);
    const values = measured.map(s => s.seconds).sort((a, b) => a - b);
    assert.equal(row[provider].n, 5);
    assert.equal(row[provider].median, values[2]);
    assert.equal(row[provider].min, values[0]);
    assert.equal(row[provider].max, values[4]);
    assert(values.every(v => Number.isFinite(v) && v >= 0));
  }
  if (row.celesto.median > 0) {
    assert(Math.abs(row.github_over_celesto - row.github.median / row.celesto.median) < 1e-10);
  }
}
const hits = json('cache-observations.json').filter(o => ['unchanged', 'source'].includes(o.scenario));
assert.equal(hits.length, 80);
assert(hits.every(o => o.install_layer_cached));
const receipt = { run: run.url, source_commit: run.headSha, concrete_jobs: actual.size,
  cohorts: run.cohorts ?? null,
  repetitions_per_provider_scenario: 5, verified_log_hashes: logHashes,
  expected_dependency_layer_hits: 80, observed_dependency_layer_hits: hits.length,
  expected_exact_archive_hits: 40, observed_exact_archive_hits: exactArchiveHits,
  independently_recomputed_summary_rows: summary.length, result: 'passed' };
writeFileSync(join(dir, 'validation.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt, null, 2));
