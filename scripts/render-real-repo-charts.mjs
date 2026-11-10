import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Regenerate with: node scripts/render-real-repo-charts.mjs
// Same layout as render-chart.mjs, for the Turborepo and Docker real-repo reports.
const root = new URL('../', import.meta.url);
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
// Axis step of 1, 2, 2.5 or 5 x 10^k giving 3-5 ticks, with room for the value label.
const niceStep = (v) => { const raw = (v * 1.15) / 4; const p = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 2.5, 5, 10].map((s) => s * p).find((s) => s >= raw); };
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

function render({ source, output, title, heading, subtitle, footer, note, series, metrics, desc }) {
  const { samples } = JSON.parse(readFileSync(new URL(source, root), 'utf8'));
  const rowH = 168 / series.length;
  const panelH = 120 + series.length * rowH + 40;
  const legend = series.map((s, i) => `<rect x="${36 + i * 250}" y="114" width="18" height="18" rx="3" fill="${s.color}"/><text x="${64 + i * 250}" y="130" class="label">${esc(s.label)}</text>`).join('');
  const descParts = [];
  const panels = metrics.map((metric, index) => {
    const x = 36 + (index % 2) * 532;
    const y = 160 + Math.floor(index / 2) * (panelH + 16);
    const plotX = x + 30, plotWidth = 398, barY = y + 112;
    const values = series.map((s) => {
      const selected = samples.filter((r) => s.match(r) && r.phase === metric.phase);
      if (selected.length !== metric.count) throw new Error(`Unexpected sample count for ${s.label} ${metric.title}: ${selected.length}`);
      return median(selected.map(metric.value)) / 1000;
    });
    const step = niceStep(Math.max(...values));
    const max = step * Math.ceil((Math.max(...values) * 1.15) / step);
    const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => i * step).map((tick) => {
      const tx = plotX + (tick / max) * plotWidth;
      return `<line x1="${tx}" x2="${tx}" y1="${barY - 8}" y2="${barY + series.length * rowH - 20}" stroke="#e2e8f0"/><text x="${tx}" y="${barY + series.length * rowH + 8}" text-anchor="middle" class="tick">${+tick.toFixed(1)}</text>`;
    }).join('');
    const bars = series.map((s, i) => {
      const by = barY + i * rowH;
      const width = (values[i] / max) * plotWidth;
      return `<text x="${plotX}" y="${by - 10}" class="label">${esc(s.label)}</text><rect x="${plotX}" y="${by}" width="${width}" height="24" rx="4" fill="${s.color}"/><text x="${plotX + width + 9}" y="${by + 19}" class="value">${values[i].toFixed(1)}</text>`;
    }).join('');
    descParts.push(`${metric.title}: ${series.map((s, i) => `${s.label} ${values[i].toFixed(1)} s`).join(', ')}`);
    return `<g><rect x="${x}" y="${y}" width="516" height="${panelH}" rx="16" fill="#ffffff" stroke="#e2e8f0"/><text x="${x + 28}" y="${y + 36}" class="panel-title">${esc(metric.title)}</text><text x="${x + 488}" y="${y + 36}" text-anchor="end" class="direction">Lower is better</text><text x="${x + 28}" y="${y + 65}" class="subtitle">${esc(metric.unit)}</text>${ticks}${bars}</g>`;
  }).join('\n');
  const height = 160 + Math.ceil(metrics.length / 2) * (panelH + 16) + 80;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="${height}" viewBox="0 0 1120 ${height}" role="img" aria-labelledby="title desc">
<title id="title">${esc(title)}</title>
<desc id="desc">${esc(desc)} Medians in seconds. ${esc(descParts.join('. '))}. All bar axes begin at zero.</desc>
<style>text{font-family:Inter,Arial,Helvetica,sans-serif;fill:#0f172a}.title{font-size:34px;font-weight:750}.subtitle{font-size:18px;fill:#64748b}.panel-title{font-size:23px;font-weight:700}.direction{font-size:16px;fill:#64748b}.label{font-size:17px}.tick{font-size:16px;fill:#64748b}.value{font-size:19px;font-weight:700}.footer{font-size:17px;fill:#475569}</style>
<rect width="1120" height="${height}" rx="20" fill="#f8fafc"/>
<text x="36" y="55" class="title">${esc(heading)}</text>
<text x="36" y="89" class="subtitle">${esc(subtitle)}</text>
${legend}
${panels}
<text x="36" y="${height - 50}" class="footer">${esc(footer)}</text>
<text x="36" y="${height - 21}" class="subtitle">${esc(note)}</text>
</svg>\n`;
  const out = new URL(output, root);
  mkdirSync(new URL('docs/images/', root), { recursive: true });
  writeFileSync(out, svg);
  console.log(`Rendered ${fileURLToPath(out)}`);
}

const gh = { label: 'GitHub Actions', color: '#475569' };
const total = (r) => (r.restore_ms ?? 0) + r.turbo_ms + (r.save_ms ?? 0);

if (existsSync(new URL('results/2026-11-10-turbo-t3/samples.json', root))) render({
  source: 'results/2026-11-10-turbo-t3/samples.json',
  output: 'docs/images/turbo-t3.svg',
  title: 'Celesto Large versus GitHub Actions: create-t3-turbo Turborepo cache',
  heading: 'A real Turborepo cache: create-t3-turbo',
  subtitle: 'turbo run build typecheck lint · 25 tasks · 4 vCPUs · 16 GiB RAM · Node 22',
  footer: 'Medians of 3 runs, November 10, 2026 · 9 jobs per setup and phase',
  note: 'Time = cache restore + turbo + cache save. Celesto remote cache transfers happen inside turbo.',
  desc: 'create-t3-turbo, turbo run build typecheck lint, three cache setups.',
  series: [
    { ...gh, label: 'GitHub · actions/cache', match: (r) => r.provider === 'github-hosted' },
    { label: 'Celesto · actions/cache', color: '#fb923c', match: (r) => r.provider === 'celesto-large' && r.method === 'actions-cache' },
    { label: 'Celesto · Turbo remote', color: '#c2410c', match: (r) => r.provider === 'celesto-large' && r.method === 'turbo-remote' },
  ],
  metrics: [
    { title: 'No cache', unit: 'Seconds · cold job, 0 of 25 tasks cached', phase: 'cold', value: total, count: 9 },
    { title: 'Same commit again', unit: 'Seconds · warm job, 25 of 25 cached', phase: 'warm', value: total, count: 9 },
    { title: 'One page changed', unit: 'Seconds · partial job, 22 of 25 cached', phase: 'partial', value: total, count: 9 },
    { title: 'Cache overhead, warm job', unit: 'Seconds · restore + save, or turbo on a full hit', phase: 'warm', value: (r) => r.method === 'turbo-remote' ? r.turbo_ms : r.restore_ms + r.save_ms, count: 9 },
  ],
});

if (existsSync(new URL('results/2026-11-10-docker-n8n/samples.json', root))) render({
  source: 'results/2026-11-10-docker-n8n/samples.json',
  output: 'docs/images/docker-n8n.svg',
  title: 'Celesto Large versus GitHub Actions: n8n Docker layer cache',
  heading: 'A real Docker layer cache: n8n',
  subtitle: 'docker/images/n8n/Dockerfile · BuildKit type=gha, mode=max · 4 vCPUs · 16 GiB RAM',
  footer: 'Medians of 3 runs, November 10, 2026 · 9 jobs per provider and phase',
  note: 'Build time includes cache import and export. Every job builds the same compiled n8n.',
  desc: 'n8n image build with BuildKit type=gha cache.',
  series: [
    { ...gh, match: (r) => r.provider === 'github-hosted' },
    { label: 'Celesto Large', color: '#c2410c', match: (r) => r.provider === 'celesto-large' },
  ],
  metrics: [
    { title: 'No cache', unit: 'Seconds · cold build, cache export included', phase: 'cold', value: (r) => r.build_ms, count: 9 },
    { title: 'Same input again', unit: 'Seconds · warm build, all layers cached', phase: 'warm', value: (r) => r.build_ms, count: 9 },
    { title: 'App changed', unit: 'Seconds · partial build, native layers cached', phase: 'partial', value: (r) => r.build_ms, count: 9 },
    { title: 'Cache export, cold build', unit: 'Seconds · writing layers to the cache', phase: 'cold', value: (r) => r.export_ms, count: 9 },
  ],
});
