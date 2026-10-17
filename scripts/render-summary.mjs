import { existsSync, readFileSync, writeFileSync } from 'node:fs';

const eventFile = process.env.BENCHMARK_EVENT_FILE ?? 'benchmark-events.jsonl';
const outputFile = process.env.GITHUB_STEP_SUMMARY ?? 'benchmark-summary.md';

if (!existsSync(eventFile)) {
  console.error(`No event file found at ${eventFile}.`);
  process.exit(1);
}

const events = readFileSync(eventFile, 'utf8')
  .trim()
  .split('\n')
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const first = (phase) => events.find((event) => event.phase === phase);
const duration = (startPhase, endPhase) => {
  const start = first(startPhase);
  const end = first(endPhase);
  return start && end ? end.timestamp_ms - start.timestamp_ms : null;
};
const format = (value) => value === null ? 'n/a' : `${(value / 1_000).toFixed(2)} s`;
const host = first('host_fingerprint')?.data ?? {};
const restore = first('cache_restore_end')?.data ?? {};
const singleCpu = first('cpu_single_core_end')?.data ?? {};
const allCpu = first('cpu_all_cores_end')?.data ?? {};
const jobDuration = duration('job_start', 'job_end');
const cacheRestoreDuration = duration('cache_restore_start', 'cache_restore_end');
const payloadDuration = duration('cache_payload_start', 'cache_payload_end');
const cacheSaveDuration = duration('cache_save_start', 'cache_save_end');

const lines = [
  '## Celesto CI vs. GitHub Actions benchmark',
  '',
  `- Provider: **${host.provider ?? 'unknown'}**`,
  `- Runner: \`${host.runner_name ?? 'unknown'}\` (${host.runner_os ?? 'unknown'}/${host.runner_arch ?? 'unknown'})`,
  `- Cache key: \`${restore.cache_primary_key ?? 'unknown'}\``,
  `- Cache result: **${restore.cache_hit ?? 'unknown'}**`,
  '',
  '### Cache timings',
  '',
  '| Measurement | Duration |',
  '| --- | ---: |',
  `| Cache restore boundary | ${format(cacheRestoreDuration)} |`,
  `| Payload generation (miss only) | ${format(payloadDuration)} |`,
  `| Cache save boundary (miss only) | ${format(cacheSaveDuration)} |`,
  `| Instrumented job wall time | ${format(jobDuration)} |`,
  '',
  '### CPU baseline',
  '',
  '| Mode | Workers | Throughput | Aggregate CPU | Wall time |',
  '| --- | ---: | ---: | ---: | ---: |',
  `| Single core | ${singleCpu.workers ?? 'n/a'} | ${singleCpu.iterations_per_second?.toLocaleString?.() ?? 'n/a'} iterations/s | ${singleCpu.aggregate_cpu_ms ? format(singleCpu.aggregate_cpu_ms) : 'n/a'} | ${singleCpu.wall_ms ? format(singleCpu.wall_ms) : 'n/a'} |`,
  `| All available cores | ${allCpu.workers ?? 'n/a'} | ${allCpu.iterations_per_second?.toLocaleString?.() ?? 'n/a'} iterations/s | ${alm
