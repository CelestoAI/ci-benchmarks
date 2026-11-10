import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Regenerate with: node scripts/render-deps-chart.mjs
// Same layout as render-chart.mjs, for the excalidraw dependency-cache report.
const root = new URL('../', import.meta.url);
const source = new URL('results/2026-11-10-deps-excalidraw/samples.json', root);
const { samples, cache_mib } = JSON.parse(readFileSync(source, 'utf8'));
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
  { key: 'total_ms', title: 'No cache: install', unit: 'Seconds · cold job, cache miss', phase: 'cold', max: 60, ticks: [0, 20, 40, 60] },
  { key: 'total_ms', title: 'With cache: restore + install', unit: 'Seconds · warm job, cache hit', phase: 'warm', max: 60, ticks: [0, 20, 40, 60] },
  { key: 'restore_ms', title: 'Cache restore', unit: `Seconds · ${(cache_mib / 1024).toFixed(1)} GiB yarn cache hit`, phase: 'warm', max: 30, ticks: [0, 10, 20, 30] },
  { key: 'save_ms', title: 'Cache save', unit: `Seconds · ${(cache_mib / 1024).toFixed(1)} GiB yarn cache miss`, phase: 'cold', max: 30, ticks: [0, 10, 20, 30] },
];
const panels = metrics.map((metric, index) => {
  const x = 36 + (index % 2) * 532;
  const y = 160 + Math.floor(index / 2) * 268;
  const plotX = x + 30;
  const plotWidth = 398;
  const barY = y + 112;
  const values = providers.map((provider) => {
    const selected = samples.filter((s) => s.provider === provider.id && s.phase === metric.phase);
    if (selected.length !== 9) throw new Error('Unexpected sample count');
    return median(selected.map((s) => s[metric.key])) / 1000;
  });
  if (values.some((value) => !Number.isFinite(value) || value < 0 || value > metric.max)) throw new Error('Chart scale does not fit data');
  const ticks = metric.ticks.map((tick) => {
    const tx = plotX + tick / metric.max * plotWidth;
    return `<line x1="${tx}" x2="${tx}" y1="${barY - 8}" y2="${barY + 95}" stroke="#e2e8f0"/><text x="${tx}" y="${barY + 120}" text-anchor="middle" class="tick">${tick}</text>`;
  }).join('');
  const bars = providers.map((provider, i) => {
    const by = barY + i * 56;
    const width = values[i] / metric.max * plotWidth;
    return `<text x="${plotX}" y="${by - 10}" class="label">${provider.label}</text><rect x="${plotX}" y="${by}" width="${width}" height="24" rx="4" fill="${provider.color}"/><text x="${plotX + width + 9}" y="${by + 19}" class="value">${values[i].toFixed(1)}</text>`;
  }).join('');
  return `<g><rect x="${x}" y="${y}" width="516" height="252" rx="16" fill="#ffffff" stroke="#e2e8f0"/><text x="${x + 28}" y="${y + 36}" class="panel-title">${metric.title}</text><text x="${x + 488}" y="${y + 36}" text-anchor="end" class="direction">Lower is better</text><text x="${x + 28}" y="${y + 65}" class="subtitle">${metric.unit}</text>${ticks}${bars}</g>`;
}).join('\n');
const m = (p, ph, k) => (median(samples.filter((s) => s.provider === p && s.phase === ph).map((s) => s[k])) / 1000).toFixed(1);
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="790" viewBox="0 0 1120 790" role="img" aria-labelledby="title desc">
<title id="title">Celesto Large versus GitHub Actions: excalidraw dependency cache</title>
<desc id="desc">yarn install of excalidraw with actions/cache. Cold install: GitHub ${m('github-hosted', 'cold', 'total_ms')}, Celesto ${m('celesto-large', 'cold', 'total_ms')} seconds. Warm restore plus install: GitHub ${m('github-hosted', 'warm', 'total_ms')}, Celesto ${m('celesto-large', 'warm', 'total_ms')} seconds. Restore: GitHub ${m('github-hosted', 'warm', 'restore_ms')}, Celesto ${m('celesto-large', 'warm', 'restore_ms')} seconds. Save: GitHub ${m('github-hosted', 'cold', 'save_ms')}, Celesto ${m('celesto-large', 'cold', 'save_ms')} seconds. All bar axes begin at zero.</desc>
<style>text{font-family:Inter,Arial,Helvetica,sans-serif;fill:#0f172a}.title{font-size:34px;font-weight:750}.subtitle{font-size:18px;fill:#64748b}.panel-title{font-size:23px;font-weight:700}.direction{font-size:16px;fill:#64748b}.label{font-size:17px}.tick{font-size:16px;fill:#64748b}.value{font-size:19px;font-weight:700}.footer{font-size:17px;fill:#475569}</style>
<rect width="1120" height="790" rx="20" fill="#f8fafc"/>
<text x="36" y="55" class="title">A real dependency cache: excalidraw</text>
<text x="36" y="89" class="subtitle">yarn install · actions/cache · 4 vCPUs · 16 GiB RAM · Node 22</text>
<rect x="36" y="114" width="18" height="18" rx="3" fill="#475569"/><text x="64" y="130" class="label">GitHub Actions</text>
<rect x="242" y="114" width="18" height="18" rx="3" fill="#c2410c"/><text x="270" y="130" class="label">Celesto Large</text>
${panels}
<text x="36" y="720" class="footer">Medians of 3 runs, November 10, 2026 · 9 cold and 9 warm jobs per provider</text>
<text x="36" y="749" class="subtitle">Cache times include action startup, transfer and extraction. CPU models differ. Full data in the linked report.</text>
</svg>\n`;
const output = new URL('docs/images/deps-excalidraw.svg', root);
mkdirSync(new URL('docs/images/', root), { recursive: true });
writeFileSync(output, svg);
console.log(`Rendered ${fileURLToPath(output)} from ${fileURLToPath(source)}`);
