import { closeSync, existsSync, openSync, statSync, writeSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomFillSync } from 'node:crypto';

const cacheDir = process.env.BENCHMARK_CACHE_DIR ?? '.benchmark-cache';
const requestedMiB = Number.parseInt(process.env.BENCHMARK_CACHE_MIB ?? '256', 10);
const expectedBytes = requestedMiB * 1024 * 1024;
const payloadPath = join(cacheDir, 'payload.bin');
const manifestPath = join(cacheDir, 'manifest.json');

if (!Number.isSafeInteger(requestedMiB) || requestedMiB < 1 || requestedMiB > 4096) {
  console.error('BENCHMARK_CACHE_MIB must be a whole number from 1 through 4096.');
  process.exit(1);
}

if (existsSync(payloadPath) && statSync(payloadPath).size === expectedBytes) {
  console.log(`Cache payload already present: ${requestedMiB} MiB`);
  process.exit(0);
}

const { mkdirSync } = await import('node:fs');
mkdirSync(cacheDir, { recursive: true });

const descriptor = openSync(payloadPath, 'w');
const chunk = Buffer.allocUnsafe(4 * 1024 * 1024);
let remaining = expectedBytes;
const start = performance.now();

try {
  while (remaining > 0) {
    const bytes = Math.min(chunk.length, remaining);
    randomFillSync(chunk, 0, bytes);
    writeSync(descriptor, chunk, 0, bytes);
    remaining -= bytes;
  }
} finally {
  closeSync(descriptor);
}

const elapsedMs = Math.round(performance.now() - start);
writeFileSync(manifestPath, `${JSON.stringify({
  requested_mib: requestedMiB,
  bytes: expectedBytes,
  generated_at: new Date().toISOString(),
  elapsed_ms: elapsedMs,
  content: 'cryptographically random bytes to avoid misleading compression ratios',
}, null, 2)}\n`);
console.log(`Generated ${requestedMiB} MiB cache payload in ${elapsedMs} ms`);
