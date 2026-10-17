import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Regenerate with: node scripts/render-chart.mjs
const root = new URL('../', import.meta.url);
const source = new URL('results/2026-10-17-matched/samples.json', root);
const { samples } = JSON.parse(readFileSync(source, 'utf8'));
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
const providers = [
  { id: 'github-hosted', label: 'GitHub Actions', color: '#475569' },
  { id: 'celesto-large', label: 'Celesto Large', color: '#c2410c' },
];
const metrics = [
  { key: 'single', title: 'Single-core CPU', unit: 'Million iterations / second', direction: 'Higher is better', phase: null, divisor: 1e6, max: 300, ticks: [0, 100, 200, 300], digits: 1 },
  { key: 'all', title: 'Four-core CPU', unit: 'Million iterations / second', direction: 'Higher is better', phase: null, divisor: 1e6, max: 1200, ticks: [0, 400, 800, 1200], digits: 1 },
  { key: 'restore_ms', title: 'Cache restore', unit: 'Seconds · 512 MiB cache hit', direction: 'Lower is better', phase: 'warm', divisor: 1000, max: 8, ticks: [0, 2, 4, 6, 8], digits: 2 },
  { key: 'save_ms', title: 'Cache save', unit: 'Seconds · 512 MiB cache miss', direction: 'Lower is better', phase: 'cold', divisor: 1000, max: 6, ticks: [0, 2, 4, 6], digits: 2 },
];
const panels = metrics.map((metric, index) => {
  const x = 36 + (index % 2) * 532;
  const y = 160 + Math.floor(index / 2) * 268;
  const plotX = x + 30;
  const plotWidth = 398;
  const barY = y + 112;
  const values = providers.map((provider) => {
    const selected = samples.filter((s) => s.provider === provider.id && (!metric.phase || s.phase === metric.phase));
    if (selected.length !== (metric.phase ? 3 : 6)) throw new Error('Unexpected sample count');
    return median(selected.map((s) => s[metric.key])) / metric.divisor;
  });
  if (values.some((value) => !Number.isFinite(value) || value < 0 || value > metric.max)) throw new Error('Chart scale does not fit data');
  const ticks = metric.ticks.map((tick) => {
    const tx = plotX + tick / metric.max * plotWidth;
    return `<line x1="${tx}" x2="${tx}" y1="${barY - 8}" y2="${barY + 95}" stroke="#e2e8f0"/><text x="${tx}" y="${barY + 120}" text-anchor="middle" class="tick">${tick}</text>`;
  }).join('');
  const bars = providers.map((provider, i) => {
    const by = barY + i * 56;
    const width = values[i] / metric.max * plotWidth;
    const rounded = Math.round(values[i] * 10 ** metric.digits) / 10 ** metric.digits;
    return `<text x="${plotX}" y="${by - 10}" class="label">${provider.label}</text><rect x="${plotX}" y="${by}" width="${width}" height="24" rx="4" fill="${provider.color}"/><text x="${plotX + width + 9}" y="${by + 19}" class="value">${rounded.toFixed(metric.digits)}</text>`;
  }).join('');
  return `<g><rect x="${x}" y="${y}" width="516" height="252" rx="16" fill="#ffffff" stroke="#e2e8f0"/><text x="${x + 28}" y="${y + 36}" class="panel-title">${metric.title}</text><text x="${x + 488}" y="${y + 36}" text-anchor="end" class="direction">${metric.direction}</text><text x="${x + 28}" y="${y + 65}" class="subtitle">${metric.unit}</text>${ticks}${bars}</g>`;
}).join('\n');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="790" viewBox="0 0 1120 790" role="img" aria-labelledby="title desc">
<title id="title">Celesto Large versus GitHub Actions: matched four-core benchmark</title>
<desc id="desc">Both providers use four vCPUs and 16 GiB RAM. Median single-core throughput: GitHub 199.4, Celesto 233.2 million iterations per second. Four-core: GitHub 786.7, Celesto 927.5 million. Cache restore: GitHub 3.30, Celesto 6.23 seconds. Cache save: GitHub 2.50, Celesto 5.18 seconds. All bar axes begin at zero; each panel has its own labeled scale.</desc>
<style>text{font-family:Inter,Arial,Helvetica,sans-serif;fill:#0f172a}.title{font-size:34px;font-weight:750}.subtitle{font-size:18px;fill:#64748b}.panel-title{font-size:23px;font-weight:700}.direction{font-size:16px;fill:#64748b}.label{font-size:17px}.tick{font-size:16px;fill:#64748b}.value{font-size:19px;font-weight:700}.footer{font-size:17px;fill:#475569}</style>
<rect width="1120" height="790" rx="20" fill="#f8fafc"/>
<text x="36" y="55" class="title">Same capacity. Different trade-offs.</text>
<text x="36" y="89" class="subtitle">4 vCPUs · 16 GiB RAM · Ubuntu 24.04.5 · Node 22.23.3</text>
<rect x="36" y="114" width="18" height="18" rx="3" fill="#475569"/><text x="64" y="130" class="label">GitHub Actions</text>
<rect x="242" y="114" width="18" height="18" rx="3" fill="#c2410c"/><text x="270" y="130" class="label">Celesto Large</text>
${panels}
<text x="36" y="720" class="footer">Medians · CPU: 6 runs/provider · Cache: 3 runs/operation/provider · October 17, 2026</text>
<text x="36" y="749" class="subtitle">Synthetic workloads. CPU models, kernels and disks differ. Full data and outliers in the linked report.</text>
</svg>\n`;
const output = new URL('docs/images/matched-benchmark.svg', root);
mkdirSync(new URL('docs/images/', root), { recursive: true });
writeFileSync(output, svg);
console.log(`Rendered ${fileURLToPath(output)} from ${fileURLToPath(source)}`);
