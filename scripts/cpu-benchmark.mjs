import { cpus, availableParallelism } from 'node:os';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { performance } from 'node:perf_hooks';
import { appendFileSync } from 'node:fs';

const eventFile = process.env.BENCHMARK_EVENT_FILE ?? 'benchmark-events.jsonl';

function record(phase, data) {
  const event = {
    phase,
    timestamp_ms: Date.now(),
    timestamp_iso: new Date().toISOString(),
    data,
  };
  appendFileSync(eventFile, `${JSON.stringify(event)}\n`);
  console.log(`BENCHMARK_EVENT ${JSON.stringify(event)}`);
}
function integerEnvironment(name, fallback, { min, max }) {
  const value = Number.parseInt(process.env[name] ?? `${fallback}`, 10);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be a whole number from ${min} through ${max}.`);
  }
  return value;
}

if (!isMainThread) {
  const started = performance.now();
  const cpuStarted = process.cpuUsage();
  let accumulator = workerData.seed >>> 0;
  let checksum = 0;

  for (let index = 0; index < workerData.iterations; index += 1) {
    accumulator = Math.imul(accumulator ^ index, 0x45d9f3b) >>> 0;
    accumulator = (accumulator ^ (accumulator >>> 16)) >>> 0;
    checksum = (checksum + accumulator) >>> 0;
  }

  const cpu = process.cpuUsage(cpuStarted);
  parentPort.postMessage({
    elapsed_ms: performance.now() - started,
    cpu_user_ms: cpu.user / 1_000,
    cpu_system_ms: cpu.system / 1_000,
    checksum,
  });
} else {
  const label = process.env.BENCHMARK_CPU_LABEL ?? 'single_core';
  const logicalCpus = cpus().length;
  const availableCpus = availableParallelism();
  const iterations = integerEnvironment('BENCHMARK_CPU_ITERATIONS', 250_000_000, { min: 1_000_000, max: 2_000_000_000 });
  const requestedWorkers = process.env.BENCHMARK_CPU_WORKERS === 'all'
    ? availableCpus
    : integerEnvironment('BENCHMARK_CPU_WORKERS', 1, { min: 1, max: 64 });
  const workers = Math.min(requestedWorkers, availableCpus);

  record(`cpu_${label}_start`, {
    node: process.version,
    platform: process.platform,
    arch: process.arch,
    logical_cpus: logicalCpus,
    available_cpus: availableCpus,
    workers,
    iterations_per_worker: iterations,
  });

  const started = performance.now();
  const results = await Promise.all([...Array(workers)].map((_, index) => new Promise((resolve, reject) => {
    const worker = new Worker(new URL(import.meta.url), {
      workerData: { iterations, seed: 0x9e3779b9 ^ index },
    });
    worker.once('message', resolve);
    worker.once('error', reject);
    worker.once('exit', (code) => {
      if (code !== 0) reject(new Error(`Worker ${index} exited with code ${code}.`));
    });
  })));
  const elapsedMs = performance.now() - started;
  const totalIterations = iterations * workers;
  const totalCpuMs = results.reduce((total, result) => total + result.cpu_user_ms + result.cpu_system_ms, 0);
  const output = {
    workers,
    iterations_per_worker: iterations,
    total_iterations: totalIterations,
    wall_ms: Math.round(elapsedMs),
    aggregate_cpu_ms: Math.round(totalCpuMs),
    iterations_per_second: Math.round((totalIterations / elapsedMs) * 1_000),
    checksums: results.map((result) => result.checksum),
  };
  record(`cpu_${label}_end`, output);
  console.log(`CPU benchmark: ${output.iterations_per_second.toLocaleString()} iterations/s across ${workers} worker(s)`);
}
