// Summarize a "filesystem trace" run: node cache-bench/fstrace.mjs <run-id> [--repo o/r]
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const args = process.argv.slice(2);
const i = args.indexOf('--repo'); const repo = i < 0 ? 'CelestoAI/ci-benchmarks' : args.splice(i, 2)[1];
const dir = mkdtempSync(join(tmpdir(), 'fstrace-'));
execFileSync('gh', ['run', 'download', args[0], '--repo', repo, '--pattern', 'fstrace-*', '--dir', dir], { stdio: 'inherit' });
console.log('| Job | Host | Round | Copy/s | Create/s | Window s | Write IOs | Write MiB | Avg write ms | Flushes | Avg flush ms | Disk busy % | Max in-flight | Max dirty MiB | Max IO PSI |');
console.log('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |');
for (const art of readdirSync(dir).sort()) {
  const ev = readFileSync(join(dir, art, 'bench-events.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  const m = ev.find((e) => e.name === 'machine')?.data; const ct = ev.find((e) => e.name === 'copytrace')?.data;
  if (!ct) { console.log(`| ${art} | ${m?.host ?? '?'} | no trace | | | | | | | | | | | | |`); continue; }
  for (const r of ct.rows) {
    if (r.fill_s) { console.log(`| ${art} | ${m?.host} | fill 4 GiB: ${r.fill_s} s | | | | | | | | | | | | |`); continue; }
    const v = (k) => r[k] ?? '—';
    console.log(`| ${art} | ${m?.host} | ${r.label} | ${v('copy_per_s')} | ${v('create_per_s')} | ${v('window_s')} | ${v('write_ios')} | ${v('write_mib')} | ${v('avg_write_ms')} | ${v('flushes')} | ${v('avg_flush_ms')} | ${v('disk_busy_pct')} | ${v('max_inflight')} | ${v('max_dirty_mib')} | ${v('max_psi_io')} |`);
  }
  console.log(`| ${art} | settings | scheduler ${ct.scheduler}, nr_requests ${ct.nr_requests}, write_cache ${ct.write_cache}, dirty ${ct.dirty_ratio}/${ct.dirty_bg_ratio} | | | | | | | | | | | | |`);
}
