import { cpus, availableParallelism, totalmem, release } from 'node:os';
import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync } from 'node:fs';

const [phase, rawData = '{}'] = process.argv.slice(2);

if (!phase) {
  console.error('Usage: node scripts/record-event.mjs <phase> [json-data]');
  process.exit(1);
}

let data;
try {
  data = JSON.parse(rawData);
} catch {
  data = { value: rawData };
}

if (phase === 'host_fingerprint') {
  data = { provider: process.env.BENCHMARK_PROVIDER, runner_name: process.env.RUNNER_NAME, os: process.platform, arch: process.arch, node: process.version,
    cpu_model: cpus()[0]?.model, logical_cpus: cpus().length, available_cpus: availableParallelism(),
    memory_bytes: totalmem(), kernel: release(), os_release: readFileSync('/etc/os-release', 'utf8'),
    disk: execFileSync('df', ['-B1', '.'], { encoding: 'utf8' }).trim()
  };
  if (data.available_cpus !== 4 || data.memory_bytes < 14 * 1024 ** 3) {
    throw new Error('Matched benchmark requires four available CPUs and at least 14 GiB usable RAM: ' + JSON.stringify(data));
  }
}
if (phase === 'cache_restore_end') data.cache_hit ||= 'false';

const event = {
  phase,
  timestamp_ms: Date.now(),
  timestamp_iso: new Date().toISOString(),
  data,
};

appendFileSync(process.env.BENCHMARK_EVENT_FILE ?? 'benchmark-events.jsonl', `${JSON.stringify(event)}\n`);
console.log(`BENCHMARK_EVENT ${JSON.stringify(event)}`);
