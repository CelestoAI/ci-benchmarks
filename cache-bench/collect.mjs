// Summarize a "Cache benchmark" run (or several) as a Markdown table.
//   node cache-bench/collect.mjs <run-id> [run-id ...] [--repo owner/name] [--json out.json]
// Downloads each run's bench-* artifacts with `gh`, pairs <x>_start/<x>_end
// marks and prints medians (min–max) per cache, provider and phase.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i < 0 ? undefined : args.splice(i, 2)[1]; };
const repo = opt('--repo') ?? 'CelestoAI/ci-benchmarks';
const jsonOut = opt('--json');
if (!args.length) { console.error('usage: collect.mjs <run-id> [...] [--repo o/r] [--json file]'); process.exit(1); }

const samples = [];
const providers = () => ['github', ...[...new Set(samples.map((s) => s.provider))].filter((p) => p !== 'github').sort()];
for (const run of args) {
  const dir = mkdtempSync(join(tmpdir(), `cache-bench-${run}-`));
  execFileSync('gh', ['run', 'download', run, '--repo', repo, '--pattern', 'bench-*', '--dir', dir], { stdio: 'inherit' });
  for (const art of readdirSync(dir)) {
    const events = readFileSync(join(dir, art, 'bench-events.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
    const at = (n) => events.find((e) => e.name === n);
    const span = (x) => (at(`${x}_start`) && at(`${x}_end`) ? (at(`${x}_end`).t_ms - at(`${x}_start`).t_ms) / 1000 : undefined);
    const host = at('host').data;
    const s = { run, ...host, restore: span('restore'), work: span('work'), save: span('save'),
      hit: at('restore_end')?.data.hit, ...at('work_end')?.data };
    s.total = (s.restore ?? 0) + (s.work ?? 0) + (s.save ?? 0);
    s.machine = at('machine')?.data;
    // Celesto runs on several clouds; report each as its own provider.
    if (s.provider === 'celesto') s.provider = `celesto-${s.machine?.host ?? 'unknown'}`;
    // Resource use while the timed work ran (sampler, one row per second).
    const sf = join(dir, art, 'machine-samples.jsonl');
    if (existsSync(sf) && at('work_start') && at('work_end')) {
      const rows = readFileSync(sf, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l))
        .filter((r) => r.t_ms > at('work_start').t_ms && r.t_ms <= at('work_end').t_ms + 1000);
      const avg = (k) => rows.length ? rows.reduce((a, r) => a + (r[k] || 0), 0) / rows.length : undefined;
      const peak = (k) => rows.length ? Math.max(...rows.map((r) => r[k] || 0)) : undefined;
      s.during = { cpu_busy: avg('cpu_busy_pct'), iowait: avg('cpu_iowait_pct'), steal: avg('cpu_steal_pct'), psi_io: avg('psi_io'),
        mem_peak_gib: peak('mem_used_mib') / 1024, disk_w_peak: peak('disk_write_mib_s'), disk_r_peak: peak('disk_read_mib_s'), net_rx_peak: peak('net_rx_mib_s') };
    }
    samples.push(s);
  }
}
if (jsonOut) writeFileSync(jsonOut, JSON.stringify(samples, null, 2) + '\n');

const median = (xs) => { const v = [...xs].sort((a, b) => a - b), m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
const cell = (xs) => {
  xs = xs.filter((x) => x !== undefined);
  return xs.length ? `${median(xs).toFixed(1)} s (${Math.min(...xs).toFixed(1)}–${Math.max(...xs).toFixed(1)})` : '—';
};
const label = { dependency: 'Dependency: excalidraw yarn install', docker: 'Docker: plausible image (type=gha)', turbo: 'Turborepo: formbricks build' };
const work = { dependency: 'yarn install', docker: 'build + cache export', turbo: 'pnpm build --filter=@formbricks/web^...' };

console.log('| Cache | Phase | Provider | n | Restore | Work | Save | Total | Notes |');
console.log('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |');
for (const cache of ['dependency', 'docker', 'turbo']) for (const phase of ['cold', 'warm']) for (const provider of providers()) {
  const g = samples.filter((s) => s.cache === cache && s.phase === phase && s.provider === provider);
  if (!g.length) continue;
  const notes = [];
  const hits = g.filter((s) => s.hit !== undefined);
  if (hits.length) notes.push(`hits ${hits.filter((s) => s.hit === 'true').length}/${hits.length}`);
  if (cache === 'turbo') notes.push(`turbo cached ${g.map((s) => s.turbo_cached).join(',')}/${g[0].turbo_tasks}` + (provider.startsWith('celesto') ? `, remote ${g.map((s) => s.remote || 'no').join(',')}` : ''));
  notes.push(g[0].cpu_model ?? '');
  console.log(`| ${label[cache]} | ${phase} | ${provider} | ${g.length} | ${cell(g.map((s) => s.restore))} | ${cell(g.map((s) => s.work))} | ${cell(g.map((s) => s.save))} | ${cell(g.map((s) => s.total))} | ${notes.join('; ')} |`);
}
console.log('\nWork = ' + Object.entries(work).map(([k, v]) => `${k}: ${v}`).join(', ') + '. Total = restore + work + save. Median (min–max).');

// ---- Machines: what each provider gave us, probed at the start of every job ----
const med = (xs) => { xs = xs.filter((x) => typeof x === 'number' && !Number.isNaN(x)); return xs.length ? median(xs) : undefined; };
const f = (x, d = 0) => (x === undefined ? '—' : x.toFixed(d));
console.log('\n### Machines (median of every job\'s probe)\n');
console.log('| Provider | Jobs | Network | CPU models | Single-core M it/s | All-core M it/s | Disk write MiB/s | Disk read MiB/s | Workspace FS | Download MiB/s | npm TTFB ms | Virt |');
console.log('| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |');
for (const provider of providers()) {
  const m = samples.filter((s) => s.provider === provider && s.machine).map((s) => s.machine);
  if (!m.length) continue;
  const models = Object.entries(m.reduce((a, x) => ((a[x.cpu_model] = (a[x.cpu_model] ?? 0) + 1), a), {})).map(([k, v]) => `${k} ×${v}`).join('<br>');
  const nets = [...new Set(m.map((x) => `${x.network?.org ?? '?'} (${x.network?.region ?? '?'})`))].join('<br>');
  console.log(`| ${provider} | ${m.length} | ${nets} | ${models} | ${f(med(m.map((x) => x.cpu_single_mips)), 1)} | ${f(med(m.map((x) => x.cpu_all_mips)), 1)} | ${f(med(m.map((x) => x.disk.write_mib_s)))} | ${f(med(m.map((x) => x.disk.read_mib_s)))} | ${[...new Set(m.map((x) => x.fs?.list?.find((l) => l.places.includes('workspace'))?.fstype ?? '?'))].join(', ')} | ${f(med(m.map((x) => x.net.node_tarball_29mb?.mib_s)), 1)} | ${f(med(m.map((x) => x.net.npm_registry?.ttfb_ms)))} | ${[...new Set(m.map((x) => x.virtualization))].join(', ')} |`);
}
console.log('\n### Resource use during the timed work (median across samples)\n');
console.log('| Cache | Phase | Provider | CPU busy % | iowait % | steal % | IO pressure | Peak RAM GiB | Peak disk write MiB/s | Peak disk read MiB/s | Peak download MiB/s |');
console.log('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |');
for (const cache of ['dependency', 'docker', 'turbo']) for (const phase of ['cold', 'warm']) for (const provider of providers()) {
  const d = samples.filter((s) => s.cache === cache && s.phase === phase && s.provider === provider && s.during).map((s) => s.during);
  if (!d.length) continue;
  const c = (k, n = 0) => f(med(d.map((x) => x[k])), n);
  console.log(`| ${cache} | ${phase} | ${provider} | ${c('cpu_busy')} | ${c('iowait', 1)} | ${c('steal', 1)} | ${c('psi_io', 1)} | ${c('mem_peak_gib', 1)} | ${c('disk_w_peak')} | ${c('disk_r_peak')} | ${c('net_rx_peak')} |`);
}

// ---- Filesystems: small-file work on each place a job writes to ----
console.log('\n### Filesystems (20,000 files of 4 KiB; median per provider and place)\n');
console.log('| Provider | Place | FS (source) | Create/s | Copy/s | Stat/s | Delete/s | sync after create s | Synced 4K writes/s | p99 ms |');
console.log('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |');
for (const provider of providers()) {
  const rows = samples.filter((s) => s.provider === provider && s.machine?.fs).flatMap((s) => s.machine.fs.list.map((l) => ({ ...l, place: l.places.join('+') })));
  for (const place of [...new Set(rows.map((r) => r.place))]) {
    const g = rows.filter((r) => r.place === place && !r.error);
    if (!g.length) continue;
    const c = (k, n = 0) => f(med(g.map((x) => x[k])), n);
    const fsdesc = [...new Set(g.map((x) => `${x.fstype} (${x.source})`))].join('<br>');
    console.log(`| ${provider} | ${place} | ${fsdesc} | ${c('create_per_s')} | ${c('copy_per_s')} | ${c('stat_per_s')} | ${c('delete_per_s')} | ${c('sync_after_create_s', 2)} | ${c('sync_write_iops')} | ${c('sync_write_p99_ms', 1)} |`);
  }
  const one = samples.find((s) => s.provider === provider && s.machine?.fs);
  if (one) console.log(`\n<!-- ${provider}: root ${one.machine.fs.root_mount}; container ${one.machine.fs.in_container}; lsblk: ${one.machine.fs.block_devices.replace(/\n/g, ' | ')} -->\n`);
}
