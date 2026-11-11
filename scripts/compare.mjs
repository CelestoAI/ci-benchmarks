// Builds the comparison page: Celesto results from this repository's suite
// runs, other providers from the runs-on.com public benchmark data.
//
// Usage: node scripts/compare.mjs <ours-dir> <theirs-results-dir> <out-dir> [days]
//   <ours-dir>            results-<suite>.json files from our latest suite runs
//   <theirs-results-dir>  results/ of https://github.com/runs-on-demo/benchmark-public
//   <out-dir>             gets README.md, summary.svg and one phase chart per build suite
//
// The page has three parts:
//   1. summary.svg: speed of each provider on each suite, relative to GitHub
//   2. one stacked bar chart per build suite: where the time goes, by phase
//   3. a hardware table
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [oursDir, theirsDir, outDir, days = '30'] = process.argv.slice(2);
const SOURCE = 'https://github.com/runs-on-demo/benchmark-public';
const BASE = 'GitHub';

// Other providers' 4 vCPU x64 runners in the source data.
const THEIRS = {
  'github-x64': 'GitHub',
  'blacksmith-x64': 'Blacksmith',
  'namespace-x64': 'Namespace',
  'warpbuild-x64': 'WarpBuild',
  'ubicloud-x64': 'Ubicloud',
};
const SUITES = ['rust', 'node', 'docker', 'cache', 'burst', 'hardware'];

// Build suites: title and the phases to show, in order. Phases not listed
// (for example `verify`) still count in the total.
const BUILDS = {
  rust: ['Rust: build and test spotify-player', ['system packages', 'toolchain', 'cargo test', 'cargo clippy', 'cargo clippy (no features)']],
  node: ['Node: install and typecheck opencode', ['toolchain', 'clone', 'bun install', 'typecheck']],
  docker: ['Docker: build the PostHog image', ['fetch source', 'buildx setup', 'docker build']],
  cache: ['Cache: save and restore 4 GiB', ['cache save', 'cache restore']],
};

const HARDWARE = [
  ['CPU single-thread (PassMark)', 'cpu.passmarkSingle', ''],
  ['CPU all cores (PassMark CPU Mark)', 'cpu.passmarkCpuMark', ''],
  ['CPU all cores (sysbench, events/s)', 'cpu.sysbenchMultiEps', ''],
  ['Memory read', 'memory.readMiBps', ' MiB/s'],
  ['Disk sequential read', 'disk.seqRead.MiBps', ' MiB/s'],
  ['Disk random write, 4 KiB', 'disk.randWrite.iops', ' IOPS'],
  ['Disk write + fsync, 4 KiB', 'disk.syncWrite.iops', ' IOPS'],
  ['docker pull', 'docker.pullSeconds', ' s', 'lower'],
  ['PostgreSQL read-write (pgbench)', 'postgres.readWriteTps', ' TPS'],
];

const median = (xs) => {
  const s = xs.filter((x) => typeof x === 'number').sort((a, b) => a - b);
  if (!s.length) return null;
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const fmt = (x) => (x == null ? '–' : Math.round(x).toLocaleString('en-US'));
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

// ── 1. Load results: data[suite][provider] = list of job results ─────────

const data = {};
const dates = {};
const add = (suite, provider, r) => (((data[suite] ??= {})[provider] ??= []).push(r));

for (const f of readdirSync(oursDir).filter((f) => f.endsWith('.json'))) {
  const run = JSON.parse(readFileSync(join(oursDir, f), 'utf8'));
  dates[run.suite] = run.run.date;
  for (const r of run.results) {
    if (r.provider !== 'celesto') continue;
    // Hardware jobs keep partial metrics when one group fails, so use them all.
    if (r.status === 'success' || (run.suite === 'hardware' && r.metrics)) add(run.suite, 'Celesto', r);
  }
}

const since = Date.now() - Number(days) * 86400e3;
for (const suite of SUITES) {
  let files = [];
  try { files = readdirSync(join(theirsDir, suite)); } catch { continue; }
  for (const f of files.filter((f) => f.endsWith('.json') && Date.parse(f.slice(0, 10)) >= since)) {
    for (const r of JSON.parse(readFileSync(join(theirsDir, suite, f), 'utf8')).results) {
      // The cache suite tests several cache actions; compare actions/cache only.
      if (suite === 'cache' && !r.runnerId.endsWith('.actions-cache')) continue;
      const name = THEIRS[r.runnerId.replace(/\.actions-cache$/, '')];
      if (name && r.status === 'success') add(suite, name, r);
    }
  }
}

const providers = [...new Set(Object.values(data).flatMap((d) => Object.keys(d)))];
const med = (suite, provider, get) => median((data[suite]?.[provider] ?? []).map(get));
const phaseOf = (name) => (r) => r.phases?.find((p) => p.name === name)?.seconds;
const metricOf = (path) => (r) => path.split('.').reduce((o, k) => o?.[k], r.metrics);

// ── 2. Summary: speed relative to GitHub ─────────────────────────────────

// Each column is a time (lower is better). Speed = GitHub time / provider time.
const COLUMNS = [
  ['Rust', 'rust', (r) => r.workloadSeconds],
  ['Node', 'node', (r) => r.workloadSeconds],
  ['Docker', 'docker', (r) => r.workloadSeconds],
  ['Cache', 'cache', (r) => r.workloadSeconds],
  ['Queue', 'burst', (r) => Math.max(r.queueSeconds, 1)],
];
const speed = {};
for (const p of providers) {
  speed[p] = COLUMNS.map(([, suite, get]) => {
    const base = med(suite, BASE, get);
    const mine = med(suite, p, get);
    return base && mine ? base / mine : null;
  });
}
// Order rows by the geometric mean of the build columns (queue is separate).
const geo = (xs) => {
  const v = xs.filter((x) => x);
  return v.length ? Math.exp(v.reduce((t, x) => t + Math.log(x), 0) / v.length) : 0;
};
const rows = providers.filter((p) => speed[p].some((x) => x)).sort((a, b) => geo(speed[b].slice(0, 4)) - geo(speed[a].slice(0, 4)));

// Green for faster than GitHub, red for slower; stronger with distance.
function cellColor(x) {
  if (x == null) return '#f1f5f9';
  const t = Math.min(Math.abs(Math.log2(x)) / 2, 1); // 4x away = full colour
  const [r, g, b] = x >= 1 ? [22, 163, 74] : [220, 38, 38];
  const mix = (c) => Math.round(255 + (c - 255) * (0.15 + 0.75 * t));
  return `rgb(${mix(r)},${mix(g)},${mix(b)})`;
}

function summarySvg() {
  const cw = 96, rh = 34, left = 120, top = 70;
  const W = left + COLUMNS.length * cw + 16;
  const H = top + rows.length * rh + 40;
  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" font-family="system-ui,-apple-system,Segoe UI,sans-serif">`;
  s += `<rect width="100%" height="100%" fill="#fff"/>`;
  s += `<text x="16" y="26" font-size="16" font-weight="600" fill="#0f172a">Speed relative to GitHub-hosted (4 vCPU)</text>`;
  s += `<text x="16" y="46" font-size="12" fill="#64748b">2.0× = twice as fast as GitHub · 0.5× = half as fast · medians</text>`;
  COLUMNS.forEach(([label], i) => {
    s += `<text x="${left + i * cw + cw / 2}" y="${top - 8}" text-anchor="middle" font-size="12" font-weight="600" fill="#334155">${label}</text>`;
  });
  rows.forEach((p, j) => {
    const y = top + j * rh;
    const bold = p === 'Celesto' ? ' font-weight="700"' : '';
    s += `<text x="${left - 10}" y="${y + rh / 2 + 4}" text-anchor="end" font-size="13" fill="#0f172a"${bold}>${p}</text>`;
    speed[p].forEach((x, i) => {
      const cx = left + i * cw;
      s += `<rect x="${cx + 3}" y="${y + 3}" width="${cw - 6}" height="${rh - 6}" rx="4" fill="${cellColor(x)}"/>`;
      const text = x == null ? '–' : x >= 10 ? `${Math.round(x)}×` : `${x.toFixed(x < 0.1 ? 2 : 1)}×`;
      s += `<text x="${cx + cw / 2}" y="${y + rh / 2 + 4}" text-anchor="middle" font-size="13" fill="#0f172a"${bold}>${text}</text>`;
    });
    if (p === 'Celesto') s += `<rect x="${left}" y="${y + 1}" width="${COLUMNS.length * cw}" height="${rh - 2}" rx="5" fill="none" stroke="#c2410c" stroke-width="2"/>`;
  });
  s += `<text x="16" y="${H - 14}" font-size="11" fill="#64748b">Queue: median wait with 15 jobs queued at once. Celesto: this repository. Others: runs-on.com public data.</text>`;
  return s + `</svg>\n`;
}

// ── 3. Stacked phase chart per build suite ───────────────────────────────

const PALETTE = ['#cbd5e1', '#94a3b8', '#3b82f6', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899'];

function phaseSvg(suite) {
  const [title, phases] = BUILDS[suite];
  const list = providers
    .map((p) => {
      const parts = phases.map((n) => med(suite, p, phaseOf(n)) ?? 0);
      return { p, parts, total: med(suite, p, (r) => r.workloadSeconds) };
    })
    .filter((x) => x.total)
    .sort((a, b) => a.total - b.total);
  if (!list.some((x) => x.p === 'Celesto')) return null;
  const W = 720, left = 110, right = 70, top = 78, rh = 30;
  const H = top + list.length * rh + 16;
  const max = Math.max(...list.map((x) => Math.max(x.total, x.parts.reduce((a, b) => a + b, 0))));
  const scale = (W - left - right) / max;
  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" font-family="system-ui,-apple-system,Segoe UI,sans-serif">`;
  s += `<rect width="100%" height="100%" fill="#fff"/>`;
  s += `<text x="16" y="26" font-size="16" font-weight="600" fill="#0f172a">${esc(title)}</text>`;
  s += `<text x="${W - 16}" y="26" text-anchor="end" font-size="12" fill="#64748b">seconds · lower is better</text>`;
  // Legend
  let lx = 16;
  phases.forEach((n, i) => {
    s += `<rect x="${lx}" y="42" width="11" height="11" rx="2" fill="${PALETTE[i]}"/><text x="${lx + 16}" y="52" font-size="12" fill="#334155">${esc(n)}</text>`;
    lx += 26 + n.length * 6.6;
  });
  list.forEach(({ p, parts, total }, j) => {
    const y = top + j * rh;
    const bold = p === 'Celesto' ? ' font-weight="700"' : '';
    s += `<text x="${left - 10}" y="${y + 19}" text-anchor="end" font-size="13" fill="#0f172a"${bold}>${p}</text>`;
    let x = left;
    parts.forEach((v, i) => {
      if (!v) return;
      const w = v * scale;
      s += `<rect x="${x.toFixed(1)}" y="${y + 6}" width="${w.toFixed(1)}" height="18" fill="${PALETTE[i]}"><title>${esc(phases[i])}: ${fmt(v)} s</title></rect>`;
      x += w;
    });
    if (p === 'Celesto') s += `<rect x="${left - 2}" y="${y + 4}" width="${(x - left + 4).toFixed(1)}" height="22" rx="3" fill="none" stroke="#c2410c" stroke-width="2"/>`;
    s += `<text x="${x + 8}" y="${y + 19}" font-size="13" fill="#0f172a"${bold}>${fmt(total)} s</text>`;
  });
  return s + `</svg>\n`;
}

// ── 4. Write the page ────────────────────────────────────────────────────

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'summary.svg'), summarySvg());

const today = new Date().toISOString().slice(0, 10);
const md = [
  '# Runner comparison',
  '',
  `Updated ${today}. All runners: 4 vCPU, x64. Values are medians.`,
  '',
  `- **Celesto:** this repository's [runner suites](../../docs/suites.md), latest run of each suite.`,
  `- **Other providers:** [runs-on.com public benchmark data](${SOURCE}), last ${days} days. Same workloads and settings, measured by runs-on.com on their accounts.`,
  '',
  '![Speed relative to GitHub](summary.svg)',
  '',
];

for (const suite of Object.keys(BUILDS)) {
  const chart = phaseSvg(suite);
  if (!chart) continue;
  writeFileSync(join(outDir, `${suite}.svg`), chart);
  const jobs = Object.entries(data[suite]).map(([p, rs]) => `${p} ${rs.length}`).join(', ');
  md.push(`## ${BUILDS[suite][0].split(':')[0]}`, '', `![${BUILDS[suite][0]}](${suite}.svg)`, '', `Jobs: ${jobs}. Celesto run: ${dates[suite]}.`, '');
}

if (data.burst?.Celesto) {
  md.push('## Queue', '', '15 jobs queued at the same moment, each holding its runner for 60 s.', '', '| Provider | Median wait | Slowest wait | Jobs |', '| --- | ---: | ---: | ---: |');
  const q = (p) => (data.burst[p] ?? []).map((r) => r.queueSeconds).filter((x) => x != null).sort((a, b) => a - b);
  for (const p of Object.keys(data.burst).sort((a, b) => median(q(a)) - median(q(b)))) {
    const b = p === 'Celesto' ? '**' : '';
    md.push(`| ${b}${p}${b} | ${b}${fmt(median(q(p)))} s${b} | ${b}${fmt(q(p).at(-1))} s${b} | ${q(p).length} |`);
  }
  md.push('', `Celesto run: ${dates.burst}.`, '');
}

if (data.hardware?.Celesto) {
  const cols = ['Celesto', ...Object.keys(data.hardware).filter((p) => p !== 'Celesto')];
  md.push('## Hardware', '', 'Higher is better, except `docker pull`. ↑ / ↓: better / worse than GitHub by more than 10 %.', '');
  md.push(`| | ${cols.map((p) => (p === 'Celesto' ? '**Celesto**' : p)).join(' | ')} |`, `| --- |${cols.map(() => ' ---: |').join('')}`);
  for (const [label, path, unit, better = 'higher'] of HARDWARE) {
    const base = med('hardware', BASE, metricOf(path));
    const cells = cols.map((p) => {
      const v = med('hardware', p, metricOf(path));
      if (v == null) return '–';
      let mark = '';
      if (base && p !== BASE) {
        const ratio = better === 'higher' ? v / base : base / v;
        mark = ratio > 1.1 ? ' ↑' : ratio < 0.9 ? ' ↓' : '';
      }
      const text = `${fmt(v)}${unit}${mark}`;
      return p === 'Celesto' ? `**${text}**` : text;
    });
    md.push(`| ${label} | ${cells.join(' | ')} |`);
  }
  md.push('', `Jobs: ${Object.entries(data.hardware).map(([p, rs]) => `${p} ${rs.length}`).join(', ')}. Celesto run: ${dates.hardware}.`, '');
}

writeFileSync(join(outDir, 'README.md'), md.join('\n'));
console.log(md.join('\n'));
