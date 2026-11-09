// Summarize a "Cache benchmark" run (or several) as a Markdown table.
//   node cache-bench/collect.mjs <run-id> [run-id ...] [--repo owner/name] [--json out.json]
// Downloads each run's bench-* artifacts with `gh`, pairs <x>_start/<x>_end
// marks and prints medians (min–max) per cache, provider and phase.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i < 0 ? undefined : args.splice(i, 2)[1]; };
const repo = opt('--repo') ?? 'CelestoAI/ci-benchmarks';
const jsonOut = opt('--json');
if (!args.length) { console.error('usage: collect.mjs <run-id> [...] [--repo o/r] [--json file]'); process.exit(1); }

const samples = [];
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
for (const cache of ['dependency', 'docker', 'turbo']) for (const phase of ['cold', 'warm']) for (const provider of ['github', 'celesto']) {
  const g = samples.filter((s) => s.cache === cache && s.phase === phase && s.provider === provider);
  if (!g.length) continue;
  const notes = [];
  const hits = g.filter((s) => s.hit !== undefined);
  if (hits.length) notes.push(`hits ${hits.filter((s) => s.hit === 'true').length}/${hits.length}`);
  if (cache === 'turbo') notes.push(`turbo cached ${g.map((s) => s.turbo_cached).join(',')}/${g[0].turbo_tasks}` + (provider === 'celesto' ? `, remote ${g.map((s) => s.remote || 'no').join(',')}` : ''));
  notes.push(g[0].cpu_model ?? '');
  console.log(`| ${label[cache]} | ${phase} | ${provider} | ${g.length} | ${cell(g.map((s) => s.restore))} | ${cell(g.map((s) => s.work))} | ${cell(g.map((s) => s.save))} | ${cell(g.map((s) => s.total))} | ${notes.join('; ')} |`);
}
console.log('\nWork = ' + Object.entries(work).map(([k, v]) => `${k}: ${v}`).join(', ') + '. Total = restore + work + save. Median (min–max).');
