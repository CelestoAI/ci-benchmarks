import { appendFileSync } from 'node:fs';

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

const event = {
  phase,
  timestamp_ms: Date.now(),
  timestamp_iso: new Date().toISOString(),
  data,
};

appendFileSync(process.env.BENCHMARK_EVENT_FILE ?? 'benchmark-events.jsonl', `${JSON.stringify(event)}\n`);
console.log(`BENCHMARK_EVENT ${JSON.stringify(event)}`);
