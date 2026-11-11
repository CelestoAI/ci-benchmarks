// Rebuild the colour comparison from the current README table:
//   node scripts/preview-summary-colors.mjs
import { readFileSync, writeFileSync } from 'node:fs';

const options = [
  { name: 'Neutral', color: '#8f8f8f', light: '.12', dark: '.16' },
  { name: 'Blue', color: '#6089b5', light: '.14', dark: '.20' },
  { name: 'Sage', color: '#729786', light: '.14', dark: '.20' },
  { name: 'Lavender', color: '#9683b5', light: '.14', dark: '.20' },
];
const tables = Object.fromEntries(['light', 'dark'].map((theme) => [
  theme, readFileSync(new URL(`../results/latest/summary-${theme}.svg`, import.meta.url), 'utf8'),
]));
const cards = options.map(({ name, color, ...opacity }) => `<section>
  <h2><span style="background:${color}"></span>${name}${name === 'Neutral' ? ' <small>README default</small>' : ''}</h2>
  ${['light', 'dark'].map((theme) => {
    const id = `${name.toLowerCase()}-${theme}`;
    const svg = tables[theme]
      .replace('<svg ', `<svg id="${id}" `)
      .replace(/\.n\{[^}]+\}/, `.n{fill:${color};fill-opacity:${opacity[theme]}}`)
      .replace(/\.(t|m|hl|n)\{/g, `#${id} .$1{`);
    return `<div class="${theme}">${svg}</div>`;
  }).join('\n')}
</section>`).join('\n');

writeFileSync(new URL('../docs/summary-color-options.html', import.meta.url), `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>README table · colour options</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 32px; background: #f6f7f8; color: #171717; font-family: system-ui, sans-serif; }
  header { max-width: 1960px; margin: 0 auto 24px; }
  h1 { font-size: 24px; margin: 0 0 8px; }
  p { color: #4d4d4d; margin: 0; }
  main { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; max-width: 1960px; margin: auto; }
  section { min-width: 0; border: 1px solid #dfe2e5; border-radius: 12px; overflow: hidden; background: white; }
  h2 { display: flex; align-items: center; gap: 10px; font-size: 18px; padding: 16px 20px; margin: 0; }
  h2 span { width: 16px; height: 16px; border-radius: 50%; }
  small { margin-left: auto; font-size: 12px; font-weight: 400; color: #666; }
  .light, .dark { padding: 16px; overflow-x: auto; }
  .light { background: #fff; }
  .dark { background: #0d1117; }
  svg { display: block; width: 100%; min-width: 640px; }
  @media (max-width: 1100px) { main { grid-template-columns: 1fr; } }
  @media (max-width: 600px) { body { padding: 16px; } }
</style>
<header>
  <h1>README table · colour options</h1>
  <p>Every provider uses the same plain styling. Each option is shown on light and dark backgrounds.</p>
</header>
<main>${cards}</main>
</html>
`);
console.log('Wrote docs/summary-color-options.html');

const images = Object.fromEntries(options.map(({ name, color, ...opacity }) => [name,
  Object.fromEntries(['light', 'dark'].map((theme) => [theme,
    `data:image/svg+xml,${encodeURIComponent(tables[theme].replace(/\.n\{[^}]+\}/, `.n{fill:${color};fill-opacity:${opacity[theme]}}`))}`,
  ])),
]));

writeFileSync(new URL('../docs/readme-preview.html', import.meta.url), `<!doctype html>
<html lang="en" data-theme="light">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Celesto CI Benchmark · README preview</title>
<style>
  * { box-sizing: border-box; }
  :root { --bg:#fff; --text:#1f2328; --muted:#59636e; --line:#d1d9e0; --subtle:#f6f8fa; --link:#0969da; }
  [data-theme="dark"] { color-scheme:dark; --bg:#0d1117; --text:#f0f6fc; --muted:#9198a1; --line:#3d444d; --subtle:#151b23; --link:#4493f8; }
  body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .controls { display:flex; align-items:center; gap:12px; padding:12px 24px; background:var(--subtle); border-bottom:1px solid var(--line); flex-wrap:wrap; }
  .controls span { margin-right:auto; color:var(--muted); }
  select { font:inherit; padding:5px 10px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }
  .repo { padding:20px 32px 0; background:var(--subtle); border-bottom:1px solid var(--line); }
  .name { font-size:20px; color:var(--link); margin-bottom:20px; }
  .badge { color:var(--muted); border:1px solid var(--line); border-radius:20px; font-size:12px; padding:2px 7px; margin-left:8px; }
  nav { display:flex; gap:28px; height:42px; }
  nav b { border-bottom:2px solid #fd8c73; }
  .file { max-width:1012px; margin:24px auto; border:1px solid var(--line); border-radius:6px; overflow:hidden; }
  .file-title { padding:12px 16px; border-bottom:1px solid var(--line); font-weight:600; }
  article { padding:32px; font-size:16px; line-height:1.5; }
  h1 { font-size:32px; margin:0 0 16px; padding-bottom:8px; border-bottom:1px solid var(--line); line-height:1.25; }
  h2 { font-size:24px; margin:24px 0 16px; padding-bottom:8px; border-bottom:1px solid var(--line); line-height:1.25; }
  p { margin:0 0 16px; }
  #table { display:block; width:100%; height:auto; margin-bottom:16px; }
  table { border-collapse:collapse; margin-bottom:16px; }
  th, td { padding:6px 13px; border:1px solid var(--line); }
  th { text-align:left; }
  tr:nth-child(even) { background:var(--subtle); }
  a { color:var(--link); text-decoration:none; }
  code { padding:2px 5px; border-radius:6px; background:var(--subtle); font-size:85%; }
  @media(max-width:1050px) { .file { margin:16px; } article { padding:24px; } }
</style>
<div class="controls">
  <span>Local preview · GitHub-style README</span>
  <label>Cells <select id="color">${options.map(({name}) => `<option>${name}</option>`).join('')}</select></label>
  <label>Theme <select id="theme"><option value="light">Light</option><option value="dark">Dark</option></select></label>
</div>
<header class="repo">
  <div class="name">CelestoAI / <strong>ci-benchmarks</strong><span class="badge">Public</span></div>
  <nav><b>Code</b><span>Issues</span><span>Pull requests</span><span>Actions</span><span>Insights</span></nav>
</header>
<main class="file">
  <div class="file-title">README.md</div>
  <article>
    <h1>Celesto CI Benchmark</h1>
    <p>Open benchmarks for GitHub Actions runners. Real builds of public projects, pinned to a commit, run on a schedule. Every workflow, script and raw result is in this repository.</p>
    <h2>Latest results</h2>
    <p>p50 (median) workload and queue times for each provider. Lower is faster.</p>
    <img id="table" alt="p50 workload and queue times by provider; lower is faster">
    <table>
      <tr><th>Suite</th><th>Workload</th></tr>
      <tr><td>Rust</td><td>Cold <code>cargo test</code> and <code>clippy</code> of <a href="https://github.com/aome510/spotify-player">spotify-player</a></td></tr>
      <tr><td>Node</td><td>Cold <code>bun install</code> and typecheck of <a href="https://github.com/anomalyco/opencode">opencode</a></td></tr>
      <tr><td>Docker</td><td><code>docker buildx build</code> of <a href="https://github.com/PostHog/posthog">PostHog</a>'s production image, no cache</td></tr>
      <tr><td>Cache</td><td>Save and restore a 4 GiB file with <code>actions/cache</code></td></tr>
      <tr><td>Queue</td><td>Wait from job creation to runner start when 15 jobs are queued at once</td></tr>
    </table>
    <p>All runners have 4 vCPU (x64). Celesto results come from this repository's runner suites. Other providers' results come from the runs-on.com public benchmark data, which uses the same workloads and settings. Both include the last 30 days of runs. Updated daily.</p>
  </article>
</main>
<script>
  const images = ${JSON.stringify(images)};
  const color = document.querySelector('#color');
  const theme = document.querySelector('#theme');
  function update() {
    document.documentElement.dataset.theme = theme.value;
    document.querySelector('#table').src = images[color.value][theme.value];
  }
  color.addEventListener('change', update);
  theme.addEventListener('change', update);
  update();
</script>
</html>
`);
console.log('Wrote docs/readme-preview.html');
