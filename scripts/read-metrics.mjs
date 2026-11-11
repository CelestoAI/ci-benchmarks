import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export function readMetrics(dir, provider, iteration, singleJob) {
  const nested = join(dir, `metrics-${provider}-${iteration}`, 'metrics.json');
  // A single downloaded artifact is flattened, even with merge-multiple=false.
  // Only use that layout when its benchmark-job owner is unambiguous.
  const file = existsSync(nested) ? nested : singleJob ? join(dir, 'metrics.json') : null;
  return file && existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : null;
}
