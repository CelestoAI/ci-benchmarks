// Appends one timing mark to $BENCH_EVENTS: node cache-bench/mark.mjs <name> [json]
// Durations are pairs <x>_start / <x>_end, computed by collect.mjs.
import { appendFileSync } from 'node:fs';
import { cpus, totalmem } from 'node:os';
const [name, raw = '{}'] = process.argv.slice(2);
const data = JSON.parse(raw);
if (name === 'host') Object.assign(data, { cpu_model: cpus()[0]?.model, cpus: cpus().length, memory_gib: +(totalmem() / 2 ** 30).toFixed(1) });
const event = { name, t_ms: Date.now(), data };
appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
console.log('BENCH', JSON.stringify(event));
