// Builds the comparison page: Celesto results from this repository's suite
// runs, other providers from the runs-on.com public benchmark data.
//
// Usage: node scripts/compare.mjs <ours-dir> <theirs-results-dir> <out-dir> [days]
//   <ours-dir>            results-<suite>.json files from our latest suite runs
//   <theirs-results-dir>  results/ of https://github.com/runs-on-demo/benchmark-public
//   <out-dir>             gets README.md and one SVG chart per metric
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [oursDir, theirsDir, outDir, days = '30'] = process.argv.slice(2);
const SOURCE = 'https://github.com/runs-on-demo/benchmark-public';

// Other providers' 4 vCPU x64 runners in the source data.
const THEIRS = {
  'github-x64': 'GitHub',
  'blacksmith-x64': 'Blacksmith',
  'namespace-x64': 'Namespace',
  'warpbuild-x64': 'WarpBuild',
  'ubicloud-x64': 'Ubicloud',
};

// What each chart shows. `get` reads one value from one job result.
const total = (r) => r.workloadSeconds;
const phase = (name) => (r) => r.phases?.find((p) => p.name === name)?.seconds;
const metric = (path) => (r) => path.split('.').reduce((o, k) => o?.[k], r.metrics);
const CHARTS = {
  rust: [['Rust build and test (spotify-player)', 's', total, 'lower']],
  node: [['Node install and typecheck (opencode)', 's', total, 'lower'], ['bun install', 's', phase('bun install'), 'lower']],
  docker: [['Docker image build (PostHog)', 's', total, 'lower']],
  cache: [['Cache save, 4 GiB', 's', phase('cache save'), 'lower'], ['Cache restore, 4 GiB', 's', phase('cache restore'), 'lower']],
  burst: [['Queue time, 15 jobs at once (median)', 's', (r) => r.queueSeconds, 'lower', 'median'], ['Queue time, 15 jobs at once (slowest)', 's', (r) => r.queueSeconds, 'lower', 'max']],
  hardware: [
    ['CPU single-thread (PassMark)', 'score', metric('cpu.passmarkSingle'), 'higher'],
    ['CPU all cores (PassMark CPU Mark)', 'score', metric('cpu.passmarkCpuMark'), 'higher'],
    ['Memory read', 'MiB/s', metric('memory.readMiBps'), 'higher'],
    ['Disk sequential read', 'MiB/s', metric('disk.seqRead.MiBps'), 'higher'],
    ['Disk random write, 4 KiB', 'IOPS', metric('disk.randWrite.iops'), 'higher'],
    ['Disk write + fsync, 4 KiB', 'IOPS', metric('disk.syncWrite.iops'), 'higher'],
    ['PostgreSQL read-write (pgbench)', 'TPS', metric('postgres.readWriteTps'), 'higher'],
  ],
};

const stat = (xs, how = 'median') => {
  const s = xs.filter((x) => typeof x === 'number').sort((a, b) => a - b);
  if (!s.length) return null;
  if (how === 'max') return s.at(-1);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

// 1. Load results: data[suite][provider] = list of job results.
const data = {};
const dates = {};
const add = (suite, provider, r) => (((data[suite] ??= {})[provider] ??= []).push(r));

for (const f of readdirSync(oursDir).filter((f) => f.endsWith('.json'))) {
  const run = JSON.parse(readFileSync(join(oursDir, f), 'utf8'));
  dates[run.suite] = run.run.date;
  // Hardware jobs keep partial metrics when one group fails, so use them all.
  for (const r of run.results) {
    if (r.provider !== 'celesto') continue;
    if (r.status === 'success' || (run.suite === 'hardware' && r.metrics)) add(run.suite, 'Celesto', r);
  }
}

const since = Date.now() - Number(days) * 86400e3;
for (const suite of Object.keys(CHARTS)) {
  let files = [];
  try { files = readdirSync(join(theirsDir, suite)); } catch { continue; }
  for (const f of files.filter((f) => f.endsWith('.json') && Date.parse(f.slice(0, 10)) >= since)) {
    for (const r of JSON.parse(readFileSync(join(theirsDir, suite, f), 'utf8')).results) {
      const id = suite === 'cache' ? r.runnerId.replace(/\.actions-cache$/, '') : r.runnerId;
      if (suite === 'cache' && !r.runnerId.endsWith('.actions-cache')) continue;
      if (r.status === 'success' && THEIRS[id]) add(suite, THEIRS[id], r);
    }
  }
}

// 2. Draw one horizontal bar chart per metric. Celesto is highlighted.
function svg(title, unit, rows, better) {
  const W = 640, row = 28, top = 44, left = 110, right = 90;
  const H = top + rows.length * row + 26;
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  const bars = rows.map((r, i) => {
    const y = top + i * row;
    const w = Math.max(2, ((W - left - right) * r.value) / max);
    const fill = r.provider === 'Celesto' ? '#c2410c' : '#94a3b8';
    const label = Math.round(r.value).toLocaleString('en-US');
    return `<text x="${left - 8}" y="${y + 17}" text-anchor="end" class="t">${r.provider}</text>`
      + `<rect x="${left}" y="${y + 4}" width="${w.toFixed(1)}" height="18" rx="3" fill="${fill}"/>`
      + `<text x="${left + w + 6}" y="${y + 17}" class="t">${label}</text>`;
  }).join('');
  const note = `${unit} · ${better} is better`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="system-ui,-apple-system,Segoe UI,sans-serif">`
    + `<style>.t{font-size:13px;fill:#334155}.h{font-size:15px;font-weight:600;fill:#0f172a}.n{font-size:12px;fill:#64748b}</style>`
    + `<rect width="100%" height="100%" fill="#fff"/>`
    + `<text x="16" y="24" class="h">${title}</text><text x="${W - 16}" y="24" text-anchor="end" class="n">${note}</text>`
    + bars + `</svg>\n`;
}

// 3. Write the charts and the page.
mkdirSync(outDir, { recursive: true });
const today = new Date().toISOString().slice(0, 10);
const md = [
  '# Runner comparison',
  '',
  `Updated ${today}. All runners: 4 vCPU, x64. Each bar is a median.`,
  '',
  `- **Celesto:** this repository's [runner suites](../../docs/suites.md), latest run of each suite (3 jobs; 15 for burst).`,
  `- **Other providers:** [runs-on.com public benchmark data](${SOURCE}) from the last ${days} days. Same workloads and settings; measured by runs-on.com on their accounts.`,
  '',
];
for (const [suite, charts] of Object.entries(CHARTS)) {
  const providers = data[suite];
  if (!providers?.Celesto) continue;
  md.push(`## ${suite[0].toUpperCase() + suite.slice(1)}`, '', `Celesto run: ${dates[suite]}.`, '');
  charts.forEach(([title, unit, get, better, how], i) => {
    const rows = Object.entries(providers)
      .map(([provider, rs]) => ({ provider, value: stat(rs.map(get), how) }))
      .filter((r) => r.value != null)
      .sort((a, b) => (better === 'lower' ? a.value - b.value : b.value - a.value));
    if (!rows.some((r) => r.provider === 'Celesto')) return;
    const file = `${suite}-${i + 1}.svg`;
    writeFileSync(join(outDir, file), svg(title, unit, rows, better));
    md.push(`![${title}](${file})`, '');
  });
  md.push(`Jobs: ${Object.entries(providers).map(([p, rs]) => `${p} ${rs.length}`).join(', ')}.`, '');
}
writeFileSync(join(outDir, 'README.md'), md.join('\n'));
console.log(md.join('\n'));
