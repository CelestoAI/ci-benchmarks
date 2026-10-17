import { readFileSync, writeFileSync } from 'node:fs';

const eventFile = process.env.BENCHMARK_EVENT_FILE ?? 'benchmark-events.jsonl';
const outputFile = process.env.GITHUB_STEP_SUMMARY ?? 'benchmark-summary.md';
const events = readFileSync(eventFile, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
const first = (phase) => events.find((event) => event.phase === phase);
const duration = (start, end) => { const a = first(start); const b = first(end); return a && b ? b.timestamp_ms - a.timestamp_ms : null; };
const seconds = (value) => value === null ? 'n/a' : (value / 1000).toFixed(2) + ' s';
const host = first('host_fingerprint')?.data ?? {};
const cache = first('cache_restore_end')?.data ?? {};
const single = first('cpu_single_core_end')?.data ?? {};
const all = first('cpu_all_cores_end')?.data ?? {};
const lines = [
  '## Celesto CI vs. GitHub Actions benchmark',
  '',
  '- Provider: **' + (host.provider ?? 'unknown') + '**',
  '- Cache hit: **' + (cache.cache_hit ?? 'unknown') + '**',
  '',
  '| Measurement | Result |',
  '| --- | ---: |',
  '| Cache restore boundary | ' + seconds(duration('cache_restore_start', 'cache_restore_end')) + ' |',
  '| Cache save boundary | ' + seconds(duration('cache_save_start', 'cache_save_end')) + ' |',
  '| Single-core throughput | ' + (single.iterations_per_second?.toLocaleString?.() ?? 'n/a') + ' iterations/s |',
  '| All-core throughput | ' + (all.iterations_per_second?.toLocaleString?.() ?? 'n/a') + ' iterations/s |',
  '| All-core workers | ' + (all.workers ?? 'n/a') + ' |',
].join('\n') + '\n';
writeFileSync(outputFile, lines);
if (outputFile !== 'benchmark-summary.md') writeFileSync('benchmark-summary.md', lines);
console.log(lines);
