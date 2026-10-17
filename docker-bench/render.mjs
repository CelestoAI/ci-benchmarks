import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const dir = process.argv[2];
if (!dir) throw new Error('Usage: node docker-bench/render.mjs RESULTS_DIR');
const summary = JSON.parse(readFileSync(join(dir, 'summary.json')));
const run = JSON.parse(readFileSync(join(dir, 'run.json')));
const failures = JSON.parse(readFileSync(join(dir, 'failures.json')));
const find = (backend, scenario, metric) => summary.find(r => r.backend === backend && r.scenario === scenario && r.metric === metric);
const seconds = p => p ? `${p.median.toFixed(2)} (${p.min.toFixed(2)}–${p.max.toFixed(2)}; n=${p.n})` : 'Unavailable';
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const headline = [
  ['Cold: two image builds, no cache', find('none', 'nocache', 'two-image workload incl cache transfer')],
  ['Source change: portable cache, incl transfer', find('portable', 'source', 'two-image workload incl cache transfer')],
  ['Source change: shared registry cache', find('registry', 'source', 'two-image workload incl cache transfer')],
  ['CPU: offline Rust release compilation', find('none', 'runtime', 'Rust offline compilation')],
  ['Python CI: pulls, build, Compose tests', find('none', 'runtime', 'Python CI: pulls + image build + Compose tests')],
];
const valid = headline.filter(([, row]) => row?.github && row?.celesto);
const countLabel = valid.every(([, row]) => row.github.n === 5 && row.celesto.n === 5)
  ? 'five repetitions per provider' : 'sample counts in result table';
const max = Math.max(...valid.flatMap(([, row]) => [row.github.max, row.celesto.max])) * 1.15;
const plotX = 430, plotWidth = 600, height = 160 + valid.length * 114;
const elements = [`<svg xmlns="http://www.w3.org/2000/svg" width="1250" height="${height}" viewBox="0 0 1250 ${height}" role="img" aria-labelledby="title desc">`,
  '<title id="title">Docker CI benchmarks: matched 4-vCPU, 16-GiB runners</title>',
  '<desc id="desc">Bars show median wall time in seconds; whiskers show observed minimum and maximum, not confidence intervals. GitHub and Celesto use identical workload revisions.</desc>',
  '<rect width="100%" height="100%" fill="white"/>',
  '<g font-family="Arial, sans-serif" fill="#172033">',
  '<text x="30" y="40" font-size="25" font-weight="700">Docker CI · 4 vCPU / 16 GiB on both providers</text>',
  `<text x="30" y="69" font-size="16">Seconds · lower is better · median with observed min–max · ${countLabel}</text>`,
  '<text x="30" y="96" font-size="14" fill="#475569">Workloads exclude tool normalization and runner setup; no ARM emulation or persistent-runner shortcut.</text>'];
for (let tick = 0; tick <= 5; tick++) {
  const x = plotX + plotWidth * tick / 5;
  elements.push(`<line x1="${x}" y1="126" x2="${x}" y2="${height-48}" stroke="#e2e8f0"/><text x="${x}" y="119" text-anchor="middle" font-size="13">${(max*tick/5).toFixed(0)}s</text>`);
}
valid.forEach(([label, row], index) => {
  const y = 151 + index * 114;
  elements.push(`<text x="30" y="${y-18}" font-size="16" font-weight="700">${escape(label)}</text>`);
  ['github', 'celesto'].forEach((provider, j) => {
    const p = row[provider], cy = y + j * 29;
    const color = provider === 'github' ? '#475569' : '#2563eb';
    const x = value => plotX + value / max * plotWidth;
    elements.push(`<text x="${plotX-12}" y="${cy+6}" text-anchor="end" font-size="14">${provider === 'github' ? 'GitHub' : 'Celesto'}</text>`,
      `<rect x="${plotX}" y="${cy-10}" width="${p.median/max*plotWidth}" height="21" fill="${color}"/>`,
      `<line x1="${x(p.min)}" y1="${cy}" x2="${x(p.max)}" y2="${cy}" stroke="#0f172a" stroke-width="1.5"/>`,
      `<line x1="${x(p.min)}" y1="${cy-5}" x2="${x(p.min)}" y2="${cy+5}" stroke="#0f172a"/>`,
      `<line x1="${x(p.max)}" y1="${cy-5}" x2="${x(p.max)}" y2="${cy+5}" stroke="#0f172a"/>`,
      `<text x="${x(p.max)+9}" y="${cy+5}" font-size="14">${p.median.toFixed(2)}s</text>`);
  });
});
elements.push(`<text x="30" y="${height-15}" font-size="13" fill="#475569">Source: CelestoAI/ci-benchmarks · Actions run ${escape(run.url.split('/').pop())} · raw measurements and methodology alongside this chart.</text>`, '</g></svg>');
writeFileSync(join(dir, 'benchmark.svg'), elements.join('\n') + '\n');

let md = `# Docker CI benchmark results\n\n[Full run](${run.url}) · source \`${run.headSha}\` · status: **${run.conclusion}**.\n\n`;
md += `Both providers: **4 vCPU, 16 GiB nominal RAM, Ubuntu 24.04, x86-64**. Pinned Docker/BuildKit/tool versions and workloads; fresh runner for every cache scenario.\n\n`;
md += `![Matched Docker CI workload timings](benchmark.svg)\n\n`;
md += `## Main results\n\nSeconds: **median (observed min–max; sample count)**. These are workload times, not queue-to-result times.\n\n| Workload | GitHub | Celesto | GitHub / Celesto time |\n| --- | ---: | ---: | ---: |\n`;
for (const [label, row] of headline) {
  md += `| ${label} | ${seconds(row?.github)} | ${seconds(row?.celesto)} | ${row?.github_over_celesto?.toFixed(2) ?? 'N/A'}× |\n`;
}
md += `\nA ratio above 1 means Celesto was faster; below 1 means GitHub was faster. Five samples describe this run, not a universal speedup or a confidence interval. Generated fixtures are not the prospect's exact workflow.\n\n`;
md += `## Cache scenario totals\n\nBoth images together, including correctness checks and any sequential outer cache restore/save.\n\n| Cache backend | Scenario | GitHub | Celesto |\n| --- | --- | ---: | ---: |\n`;
for (const backend of ['portable', 'registry']) for (const scenario of ['seed', 'unchanged', 'source', 'dependency']) {
  const row = find(backend, scenario, 'two-image workload incl cache transfer');
  md += `| ${backend} | ${scenario} | ${seconds(row?.github)} | ${seconds(row?.celesto)} |\n`;
}
md += `\nPortable = BuildKit layer export transferred through each provider's actions/cache endpoint. Registry = identical GHCR cache backend on both providers. BuildKit vertex durations can overlap and are not added to produce these totals.\n\n`;
md += `## Image pull versus tar cache\n\nPostgreSQL + Azurite, together. Cache restore alone is not enough: docker load must finish too.\n\n| Operation | GitHub | Celesto |\n| --- | ---: | ---: |\n`;
for (const [scenario, metric] of [['image-seed', 'two images: direct pull'], ['image-seed', 'two images: cache save'], ['image-warm', 'two images: cache restore'], ['image-warm', 'two images: cache restore + docker load']]) {
  const row = find('none', scenario, metric);
  md += `| ${metric} | ${seconds(row?.github)} | ${seconds(row?.celesto)} |\n`;
}
md += `\n## Compatibility caveat\n\nDirect BuildKit \`type=gha,version=2\` crashed on Celesto in both preflight attempts (2/2); GitHub passed both. Registry and portable caching are separate paths, not evidence that direct GHA cache compatibility is fixed. See [protocol reproduction](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39073026017) and [methodology](../../docker-bench/README.md). No failed pilot is pooled into the five-repeat results.\n\n`;
md += `## Completeness and evidence\n\n- Failed/incomplete artifacts in the final run: **${failures.length}**. See [failure inventory](failures.json); missing measurements are never zero.\n- [Every measured sample, CSV](samples.csv) · [JSON](samples.json) · [aggregated medians/ranges](summary.json).\n- [Cache hit observations](cache-observations.json) · [job timestamps and links](run.json) · [raw logs/events](raw/).\n- [Exact fixtures, controls, limitations, and reproduction commands](../../docker-bench/README.md).\n\nTool normalization and post-cleanup are excluded from workload comparisons; full Actions job duration is retained as a separate metric. Cold means no reusable build cache, not a globally empty registry/CDN. CPU measurements disable network only for compilation; image pulls and dependency fetch are separate. No private code, production deployments, or customer messages were involved.\n`;
writeFileSync(join(dir, 'README.md'), md);
console.log(`Wrote ${dir}/README.md and benchmark.svg`);
