// Usage: node scripts/summarize-deps.mjs <dir with downloaded result.json files>
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
const walk = d => readdirSync(d).flatMap(f => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : f === 'result.json' ? [p] : []; });
const rows = walk(process.argv[2]).map(p => JSON.parse(readFileSync(p, 'utf8')));
const med = a => { a = a.filter(x => x != null).sort((x, y) => x - y); if (!a.length) return null; const m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; };
const s = ms => ms == null ? '—' : (ms / 1000).toFixed(1);
console.log('| Provider | Phase | n | Hits | Restore s (median, range) | Install s (median, range) | Save s (median, range) | Cache MiB |');
console.log('|---|---|--:|--:|--:|--:|--:|--:|');
for (const prov of ['github-hosted', 'celesto-large']) for (const ph of ['cold', 'warm']) {
  const g = rows.filter(r => r.provider === prov && r.phase === ph); if (!g.length) continue;
  const f = k => `${s(med(g.map(r => r[k])))} (${s(Math.min(...g.map(r => r[k]).filter(x => x != null)))}–${s(Math.max(...g.map(r => r[k]).filter(x => x != null)))})`;
  console.log(`| ${prov} | ${ph} | ${g.length} | ${g.filter(r => r.cache_hit === 'true').length} | ${f('restore_ms')} | ${f('install_ms')} | ${ph === 'cold' ? f('save_ms') : '—'} | ${Math.round(med(g.map(r => r.cache_bytes)) / 1048576)} |`);
}
console.log('\nCPU models:', [...new Set(rows.map(r => `${r.provider}: ${r.cpu_model}`))].join('; '));
console.log('Runs:', [...new Set(rows.map(r => r.run_id))].join(', '));
