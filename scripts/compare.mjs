// Builds the comparison page: Celesto results from this repository's suite
// runs, other providers from the runs-on.com public benchmark data.
//
// Usage: node scripts/compare.mjs <ours-dir> <theirs-results-dir> <out-dir> [days]
//   <ours-dir>            results-<suite>-<run-id>.json files from our suite history
//                         metrics-hardware-<run-id>/ holds original metric artifacts
//   <theirs-results-dir>  results/ of https://github.com/runs-on-demo/benchmark-public
//   <out-dir>             gets README.md and light/dark SVG charts
//
// The page has three parts:
//   1. summary-<theme>.svg: p50 workload and queue times by provider
//   2. one stacked bar chart per build suite: where the time goes, by phase
//   3. a hardware table
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { readMetrics } from './read-metrics.mjs';

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
const since = Date.now() - Number(days) * 86400e3;
const seen = new Set();

for (const f of readdirSync(oursDir).filter((f) => f.endsWith('.json'))) {
  const run = JSON.parse(readFileSync(join(oursDir, f), 'utf8'));
  if (!SUITES.includes(run.suite)) continue;
  if (!(Date.parse(run.run.date) >= since)) continue;
  const key = `${run.suite}:${run.run.id}:${run.run.attempt}`;
  if (seen.has(key)) continue;
  seen.add(key);
  if (!dates[run.suite] || run.run.date > dates[run.suite]) dates[run.suite] = run.run.date;
  const results = run.results.filter((r) => r.provider === 'celesto');
  for (const r of results) {
    if (run.suite === 'hardware' && !r.metrics) {
      r.metrics = readMetrics(join(oursDir, `metrics-hardware-${run.run.id}`), r.provider, r.iteration, run.results.length === 1);
    }
    // Hardware jobs keep partial metrics when one group fails, so use them all.
    if (r.status === 'success' || (run.suite === 'hardware' && r.metrics)) add(run.suite, 'Celesto', r);
  }
}

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

// ── 2. Summary: p50 workload and queue times ─────────────────────────────

// Each column is a time (lower is better).
const COLUMNS = [
  ['Rust', 'rust', (r) => r.workloadSeconds],
  ['Node', 'node', (r) => r.workloadSeconds],
  ['Docker', 'docker', (r) => r.workloadSeconds],
  ['Cache', 'cache', (r) => r.workloadSeconds],
  ['Queue', 'burst', (r) => r.queueSeconds],
];
const p50 = {};
for (const p of providers) {
  p50[p] = COLUMNS.map(([, suite, get]) => med(suite, p, get));
}
// Keep GitHub's baseline next to Celesto; other providers follow alphabetically.
const referenceOrder = ['GitHub', 'Celesto'];
const rows = providers.filter((p) => p50[p].some((x) => x != null)).sort((a, b) =>
  (referenceOrder.indexOf(a) < 0 ? 2 : referenceOrder.indexOf(a)) -
  (referenceOrder.indexOf(b) < 0 ? 2 : referenceOrder.indexOf(b)) || a.localeCompare(b));

// Charts are drawn for GitHub's README view: transparent background, colours
// that work in light and dark mode, and a wide viewBox so they fill the page.
// Geist type and neutral text. The summary gives every provider the same
// treatment; phase charts use orange for Celesto. Fonts fall back to the system font.
const FONT = 'font-family="Geist,Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif"';
const MONO = 'font-family="Geist Mono,SFMono-Regular,Menlo,Consolas,monospace"';
// GitHub picks the file by its own theme (#gh-light-mode-only /
// #gh-dark-mode-only), so each chart is written once per theme.
const THEMES = {
  light: '.t{fill:#171717}.m{fill:#4d4d4d}.hl{fill:#F04C24;fill-opacity:.07}.n{fill:#8f8f8f;fill-opacity:.12}',
  dark: '.t{fill:#ededed}.m{fill:#a1a1a1}.hl{fill:#F04C24;fill-opacity:.14}.n{fill:#8f8f8f;fill-opacity:.16}',
};
const style = (theme) => `<style>${THEMES[theme]}</style>`;
const ORANGE = '#F04C24';

const duration = (seconds) => {
  if (seconds == null) return '–';
  const rounded = Math.round(seconds);
  return rounded < 60 ? `${rounded}s` : `${Math.floor(rounded / 60)}m ${String(rounded % 60).padStart(2, '0')}s`;
};

function summarySvg(theme) {
  const W = 960, left = 170, top = 64, rh = 46, gap = 8;
  const cw = (W - left - 8) / COLUMNS.length;
  const H = top + rows.length * rh + 34;
  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" ${FONT}>${style(theme)}`;
  // Column headers: suite name and what it runs.
  const sub = { Rust: 'spotify-player', Node: 'opencode', Docker: 'PostHog image', Cache: '4 GiB', Queue: '15 jobs at once' };
  COLUMNS.forEach(([label], i) => {
    const cx = left + i * cw + cw / 2;
    s += `<text x="${cx}" y="24" text-anchor="middle" font-size="17" font-weight="600" class="t">${label}</text>`;
    s += `<text x="${cx}" y="44" text-anchor="middle" font-size="13" class="m">${sub[label]}</text>`;
  });
  rows.forEach((p, j) => {
    const y = top + j * rh;
    s += `<text x="16" y="${y + rh / 2 + 6}" font-size="17" font-weight="500" class="t">${p}</text>`;
    p50[p].forEach((x, i) => {
      const cx = left + i * cw;
      s += `<rect x="${cx + gap / 2}" y="${y + 6}" width="${cw - gap}" height="${rh - 12}" rx="6" class="n"/>`;
      s += `<text x="${cx + cw / 2}" y="${y + rh / 2 + 6}" text-anchor="middle" font-size="16" font-weight="400" ${MONO} class="t">${duration(x)}</text>`;
    });
  });
  s += `<text x="16" y="${H - 8}" font-size="13" class="m">p50 times (median). Lower is faster. 4 vCPU x64. GitHub baseline, then Celesto; others alphabetical.</text>`;
  return s + `</svg>\n`;
}

// Phase colours: setup steps grey, work steps in distinct hues.
const PALETTE = ['#8f8f8f', '#c7c7c7', '#0070f3', '#8e4ec6', '#12a594', '#ffb224', '#e93d82'];

function phaseSvg(suite, theme) {
  const [, phases] = BUILDS[suite];
  const list = providers
    .map((p) => ({ p, parts: phases.map((n) => med(suite, p, phaseOf(n)) ?? 0), total: med(suite, p, (r) => r.workloadSeconds) }))
    .filter((x) => x.total)
    .sort((a, b) => a.total - b.total);
  if (!list.some((x) => x.p === 'Celesto')) return null;
  const W = 960, left = 150, right = 90, top = 52, rh = 40;
  const H = top + list.length * rh + 30;
  const max = Math.max(...list.map((x) => Math.max(x.total, x.parts.reduce((a, b) => a + b, 0))));
  const scale = (W - left - right) / max;
  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" ${FONT}>${style(theme)}`;
  // Legend on one line.
  let lx = 16;
  phases.forEach((n, i) => {
    s += `<rect x="${lx}" y="14" width="14" height="14" rx="3" fill="${PALETTE[i]}"/><text x="${lx + 20}" y="26" font-size="14" class="m">${esc(n)}</text>`;
    lx += 34 + n.length * 7.4;
  });
  list.forEach(({ p, parts, total }, j) => {
    const y = top + j * rh;
    const me = p === 'Celesto';
    if (me) s += `<rect x="0" y="${y}" width="${W}" height="${rh}" rx="8" class="hl"/>`;
    s += `<text x="16" y="${y + rh / 2 + 6}" font-size="16" font-weight="${me ? 600 : 500}" ${me ? `fill="${ORANGE}"` : 'class="t"'}>${p}</text>`;
    let x = left;
    parts.forEach((v, i) => {
      if (!v) return;
      const w = v * scale;
      s += `<rect x="${x.toFixed(1)}" y="${y + 9}" width="${Math.max(w - 1.5, 1).toFixed(1)}" height="${rh - 18}" rx="3" fill="${PALETTE[i]}"><title>${esc(phases[i])}: ${fmt(v)} s</title></rect>`;
      x += w;
    });
    s += `<text x="${x + 10}" y="${y + rh / 2 + 6}" font-size="15" font-weight="${me ? 600 : 400}" ${MONO} class="t">${fmt(total)} s</text>`;
  });
  s += `<text x="16" y="${H - 8}" font-size="13" class="m">Seconds, lower is better. p50 (median). Hover a segment for its time.</text>`;
  return s + `</svg>\n`;
}

// ── 4. Write the page ────────────────────────────────────────────────────

// One image per theme; GitHub shows the one that matches the reader's theme.
const themed = (alt, name) => [`![${alt}](${name}-light.svg#gh-light-mode-only)`, `![${alt}](${name}-dark.svg#gh-dark-mode-only)`];

mkdirSync(outDir, { recursive: true });
for (const theme of Object.keys(THEMES)) writeFileSync(join(outDir, `summary-${theme}.svg`), summarySvg(theme));

const today = new Date().toISOString().slice(0, 10);
const md = [
  '# Runner comparison',
  '',
  `Updated ${today}. All runners: 4 vCPU, x64. Values are p50 (medians).`,
  '',
  'The summary shows p50 times across successful jobs, in minutes and seconds. Lower is faster. Cache time includes save and restore. Workload times exclude queue time and runner overhead. Queue shows the wait from job creation to runner start for a burst of 15 jobs.',
  '',
  'RunsOn also publishes [p50 (median) results](https://runs-on.com/benchmarks/methodology/). Its main build chart defaults to whole-job time and ranks by time × cost; the build columns here show workload time only.',
  '',
  `- **Celesto:** this repository's [runner suites](../../docs/suites.md), last ${days} days of runs.`,
  `- **Other providers:** [runs-on.com public benchmark data](${SOURCE}), last ${days} days. Same workloads and settings, measured by runs-on.com on their accounts.`,
  '',
  ...themed('p50 workload and queue times by provider; lower is faster', 'summary'),
  '',
];

for (const suite of Object.keys(BUILDS)) {
  if (!phaseSvg(suite, 'light')) continue;
  for (const theme of Object.keys(THEMES)) writeFileSync(join(outDir, `${suite}-${theme}.svg`), phaseSvg(suite, theme));
  const jobs = Object.entries(data[suite]).map(([p, rs]) => `${p} ${rs.length}`).join(', ');
  md.push(`## ${BUILDS[suite][0].split(':')[0]}`, '', `${BUILDS[suite][0].split(': ')[1][0].toUpperCase()}${BUILDS[suite][0].split(': ')[1].slice(1)}.`, '', ...themed(BUILDS[suite][0], suite), '', `Jobs: ${jobs}. Latest Celesto run: ${dates[suite]}.`, '');
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
  md.push('', `Jobs: ${Object.entries(data.hardware).map(([p, rs]) => `${p} ${rs.length}`).join(', ')}. Latest Celesto run: ${dates.hardware}.`, '');
}

writeFileSync(join(outDir, 'README.md'), md.join('\n'));
console.log(md.join('\n'));
