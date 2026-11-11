// Reads this workflow run's jobs from the GitHub API and writes the suite
// result: queue time, a time per `phase: …` step, and the workload total.
// Timings come from GitHub, not from inside the job, so a runner cannot
// misreport its own speed.
//
// Usage: node scripts/collect-suite.mjs <suite> <metrics-dir> <out.json>
// Bench jobs must be named "<provider> <iteration>". Each job may upload
// metrics-<provider>-<iteration>/metrics.json, found in <metrics-dir>.
import { existsSync, readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';

const [suite, metricsDir, outFile] = process.argv.slice(2);
const { GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT = '1', GITHUB_STEP_SUMMARY } = process.env;

async function jobs() {
  const all = [];
  for (let page = 1; ; page++) {
    const url = `https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/attempts/${GITHUB_RUN_ATTEMPT}/jobs?per_page=100&page=${page}`;
    const res = await fetch(url, { headers: { authorization: `Bearer ${GITHUB_TOKEN}`, accept: 'application/vnd.github+json' } });
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    const body = await res.json();
    all.push(...body.jobs);
    if (all.length >= body.total_count || body.jobs.length === 0) return all;
  }
}

const seconds = (from, to) => (from && to ? Math.round((Date.parse(to) - Date.parse(from)) / 1000) : null);
const median = (xs) => {
  const s = xs.filter((x) => x != null).sort((a, b) => a - b);
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null;
};

const results = [];
for (const job of await jobs()) {
  const m = job.name.match(/^(\S+) (\d+)$/);
  if (!m) continue; // the collect job and anything else
  const [, provider, iteration] = m;
  const phases = (job.steps ?? [])
    .filter((s) => s.name.startsWith('phase: '))
    .map((s) => ({ name: s.name.slice(7), seconds: seconds(s.started_at, s.completed_at), status: s.conclusion }));
  const metricsFile = join(metricsDir, `metrics-${provider}-${iteration}`, 'metrics.json');
  results.push({
    provider,
    iteration: Number(iteration),
    status: job.conclusion ?? 'unavailable',
    failedAt: phases.find((p) => p.status === 'failure')?.name ?? null,
    runner: job.runner_name,
    queueSeconds: seconds(job.created_at, job.started_at),
    jobSeconds: seconds(job.started_at, job.completed_at),
    workloadSeconds: phases.length ? phases.reduce((t, p) => t + (p.seconds ?? 0), 0) : null,
    phases,
    metrics: existsSync(metricsFile) ? JSON.parse(readFileSync(metricsFile, 'utf8')) : null,
  });
}
results.sort((a, b) => a.provider.localeCompare(b.provider) || a.iteration - b.iteration);

const out = {
  suite,
  run: { id: Number(GITHUB_RUN_ID), attempt: Number(GITHUB_RUN_ATTEMPT), repository: GITHUB_REPOSITORY, date: new Date().toISOString().slice(0, 10) },
  results,
};
writeFileSync(outFile, JSON.stringify(out, null, 2) + '\n');

// Median per provider in the run summary.
const providers = [...new Set(results.map((r) => r.provider))];
const phaseNames = [...new Set(results.flatMap((r) => r.phases.map((p) => p.name)))];
const ok = (p) => results.filter((r) => r.provider === p && r.status === 'success');
const rows = [
  ['Jobs passed', ...providers.map((p) => `${ok(p).length}/${results.filter((r) => r.provider === p).length}`)],
  ['Queue (s)', ...providers.map((p) => median(ok(p).map((r) => r.queueSeconds)))],
  ...phaseNames.map((n) => [n + ' (s)', ...providers.map((p) => median(ok(p).map((r) => r.phases.find((x) => x.name === n)?.seconds)))]),
  ['**Workload (s)**', ...providers.map((p) => median(ok(p).map((r) => r.workloadSeconds)))],
];
const table = [`## ${suite}: median of successful jobs`, '', `| | ${providers.join(' | ')} |`, `|---|${providers.map(() => '---:').join('|')}|`, ...rows.map((r) => `| ${r.map((x) => x ?? '-').join(' | ')} |`)].join('\n');
console.log(table);
if (GITHUB_STEP_SUMMARY) appendFileSync(GITHUB_STEP_SUMMARY, table + '\n');
