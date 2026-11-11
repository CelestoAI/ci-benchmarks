// Puts our suite results next to the public runs-on.com data for the same
// suites and 4 vCPU x64 runners. Prints one Markdown table per suite.
//
// Usage:
//   git clone https://github.com/runs-on-demo/benchmark-public
//   node scripts/compare-runs-on.mjs <our-results-dir> benchmark-public/results [days]
// <our-results-dir> holds the results-<suite>.json files from our runs.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const [oursDir, theirsDir, days = '30'] = process.argv.slice(2);
const THEIR_RUNNERS = ['github-x64', 'blacksmith-x64', 'namespace-x64', 'warpbuild-x64', 'ubicloud-x64'];
const HARDWARE = [
  ['PassMark single-thread', 'cpu.passmarkSingle'],
  ['PassMark CPU Mark', 'cpu.passmarkCpuMark'],
  ['sysbench 1 thread (events/s)', 'cpu.sysbenchSingleEps'],
  ['sysbench all threads (events/s)', 'cpu.sysbenchMultiEps'],
  ['7-Zip (MIPS)', 'cpu.sevenZipMips'],
  ['Memory read (MiB/s)', 'memory.readMiBps'],
  ['Memory write (MiB/s)', 'memory.writeMiBps'],
  ['Disk seq read (MiB/s)', 'disk.seqRead.MiBps'],
  ['Disk seq write (MiB/s)', 'disk.seqWrite.MiBps'],
  ['Disk rand read 4K QD32 (IOPS)', 'disk.randRead.iops'],
  ['Disk rand write 4K QD32 (IOPS)', 'disk.randWrite.iops'],
  ['Disk rand read 4K QD1 (IOPS)', 'disk.randReadQd1.iops'],
  ['Disk 4K write + fdatasync (IOPS)', 'disk.syncWrite.iops'],
  ['Download from CDN (MiB/s)', 'network.cdnDownload.MiBps'],
  ['Download from GitHub (MiB/s)', 'network.githubDownload.MiBps'],
  ['docker pull (s)', 'docker.pullSeconds'],
  ['pgbench read-only (TPS)', 'postgres.readOnlyTps'],
  ['pgbench read-write (TPS)', 'postgres.readWriteTps'],
];

const median = (xs) => {
  const s = xs.filter((x) => typeof x === 'number').sort((a, b) => a - b);
  if (!s.length) return null;
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const pick = (obj, path) => path.split('.').reduce((o, k) => o?.[k], obj);
const fmt = (x) => (x == null ? '-' : Math.round(x).toLocaleString('en-US'));

// columns[suite][column] = list of successful results
const columns = {};
const add = (suite, column, r) => ((columns[suite] ??= {})[column] ??= []).push(r);

for (const f of readdirSync(oursDir).filter((f) => f.endsWith('.json'))) {
  const data = JSON.parse(readFileSync(join(oursDir, f), 'utf8'));
  for (const r of data.results) if (r.status === 'success') add(data.suite, `${r.provider} (ours)`, r);
}

const since = Date.now() - Number(days) * 86400e3;
for (const suite of Object.keys(columns)) {
  const dir = join(theirsDir, suite);
  let files = [];
  try { files = readdirSync(dir).filter((f) => f.endsWith('.json')); } catch { continue; }
  for (const f of files) {
    if (Date.parse(f.slice(0, 10)) < since) continue;
    for (const r of JSON.parse(readFileSync(join(dir, f), 'utf8')).results) {
      if (r.status === 'success' && THEIR_RUNNERS.includes(r.runnerId.replace(/\.actions-cache$/, ''))) add(suite, `${r.provider} (runs-on.com)`, r);
    }
  }
}

for (const [suite, cols] of Object.entries(columns)) {
  const names = Object.keys(cols);
  const rows = [['Jobs', ...names.map((n) => cols[n].length)]];
  if (suite === 'hardware') {
    for (const [label, path] of HARDWARE) rows.push([label, ...names.map((n) => fmt(median(cols[n].map((r) => pick(r.metrics, path)))))]);
  } else {
    rows.push(['Queue (s)', ...names.map((n) => fmt(median(cols[n].map((r) => r.queueSeconds))))]);
    const phases = [...new Set(Object.values(cols).flat().flatMap((r) => r.phases.map((p) => p.name)))];
    for (const p of phases) rows.push([`${p} (s)`, ...names.map((n) => fmt(median(cols[n].map((r) => r.phases.find((x) => x.name === p)?.seconds))))]);
    rows.push(['**Workload (s)**', ...names.map((n) => fmt(median(cols[n].map((r) => r.workloadSeconds))))]);
  }
  console.log(`\n## ${suite}\n\nMedians of successful jobs. runs-on.com data from the last ${days} days.\n`);
  console.log(`| | ${names.join(' | ')} |\n|---|${names.map(() => '---:').join('|')}|`);
  for (const r of rows) console.log(`| ${r.join(' | ')} |`);
}
