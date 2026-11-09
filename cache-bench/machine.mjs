// Machine metrics for the cache benchmark (Linux runners).
//
//   node cache-bench/machine.mjs probe    spec + quick CPU, disk and network tests;
//                                         fails unless 4 CPUs and >= 14 GiB RAM
//   node cache-bench/machine.mjs sample   runs until killed; every second appends
//                                         CPU, memory, disk, network and pressure
//                                         counters to $BENCH_SAMPLES
//
// Probe results go to $BENCH_EVENTS as a "machine" event. collect.mjs turns the
// samples into per-phase averages and peaks (for example during `work`).
import { appendFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { availableParallelism, cpus, release, totalmem } from 'node:os';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

const read = (p) => { try { return readFileSync(p, 'utf8'); } catch { return ''; } };
const sh = (cmd, args, opts = {}) => { try { return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...opts }).trim(); } catch (e) { return `error: ${e.message.split('\n')[0]}`; } };

// ---- CPU worker: a fixed integer hash loop, timed for DURATION_MS ----
if (!isMainThread) {
  const end = Date.now() + workerData.ms;
  let acc = workerData.seed >>> 0, ops = 0;
  while (Date.now() < end) {
    for (let i = 0; i < 1_000_000; i++) { acc = Math.imul(acc ^ i, 0x45d9f3b) >>> 0; acc = (acc ^ (acc >>> 16)) >>> 0; }
    ops += 1_000_000;
  }
  parentPort.postMessage({ ops, acc });
} else {
  const mode = process.argv[2];
  if (mode === 'probe') await probe();
  else if (mode === 'sample') sample();
  else { console.error('usage: machine.mjs probe|sample'); process.exit(1); }
}

async function cpuTest(workers, ms = 5000) {
  const results = await Promise.all([...Array(workers).keys()].map((seed) => new Promise((resolve, reject) => {
    const w = new Worker(fileURLToPath(import.meta.url), { workerData: { ms, seed: seed + 1 } });
    w.once('message', resolve); w.once('error', reject);
  })));
  return +(results.reduce((s, r) => s + r.ops, 0) / (ms / 1000) / 1e6).toFixed(1); // million iterations/s
}

function diskTest() {
  // 1 GiB sequential write and read, bypassing the page cache.
  const file = 'machine-disk-test.bin';
  const dd = (args) => {
    const t = process.hrtime.bigint();
    const out = sh('dd', args);
    const s = Number(process.hrtime.bigint() - t) / 1e9;
    return out.startsWith('error') ? null : +(1024 / s).toFixed(0);
  };
  const write_mib_s = dd(['if=/dev/zero', `of=${file}`, 'bs=4M', 'count=256', 'oflag=direct', 'conv=fsync']);
  const read_mib_s = dd([`if=${file}`, 'of=/dev/null', 'bs=4M', 'iflag=direct']);
  // Small-file metadata work, like unpacking node_modules: 5,000 files of 4 KiB.
  const t = process.hrtime.bigint();
  sh('bash', ['-c', 'mkdir -p machine-small && cd machine-small && for i in $(seq 1 5000); do head -c 4096 /dev/zero > f$i; done && sync']);
  const small_files_per_s = +(5000 / (Number(process.hrtime.bigint() - t) / 1e9)).toFixed(0);
  rmSync(file, { force: true }); rmSync('machine-small', { recursive: true, force: true });
  return { write_mib_s, read_mib_s, small_files_per_s };
}

function netTest() {
  // Download speed and latency to the places cache and package traffic go.
  const curl = (url) => {
    const out = sh('curl', ['-sS', '-o', '/dev/null', '--max-time', '60', '-f', '-w', '%{speed_download} %{time_connect} %{time_starttransfer}', url]);
    if (out.startsWith('error')) return { error: out };
    const [speed, connect, ttfb] = out.split(' ').map(Number);
    return { mib_s: +(speed / 2 ** 20).toFixed(1), connect_ms: +(connect * 1000).toFixed(0), ttfb_ms: +(ttfb * 1000).toFixed(0) };
  };
  return {
    node_tarball_29mb: curl('https://nodejs.org/dist/v22.16.0/node-v22.16.0-linux-x64.tar.xz'),
    npm_registry: curl('https://registry.npmjs.org/next'),
    github_api: curl('https://api.github.com/zen'),
  };
}

function diskInfo() {
  const src = sh('findmnt', ['-n', '-o', 'SOURCE,FSTYPE', '-T', process.cwd()]);
  const dev = src.split(/\s+/)[0]?.replace('/dev/', '').replace(/p?\d+$/, '');
  return { mount: src, rotational: read(`/sys/block/${dev}/queue/rotational`).trim() || undefined,
    model: read(`/sys/block/${dev}/device/model`).trim() || undefined, free: sh('df', ['-h', '--output=size,avail', '.']).split('\n')[1]?.trim() };
}

// Who runs the machine: the owner of the egress IP (AWS, OVH, Microsoft...)
// and its region. Celesto has no label that picks a host provider, so this is
// how results are grouped by provider afterwards.
function hostNetwork() {
  const out = sh('curl', ['-sS', '-f', '--max-time', '10', 'https://ipinfo.io/json']);
  try { const j = JSON.parse(out); return { org: j.org, region: [j.city, j.region, j.country].filter(Boolean).join(', ') }; } catch { return { org: 'unknown' }; }
}
function hostKind(org = '') { return /amazon|aws/i.test(org) ? 'aws' : /ovh/i.test(org) ? 'ovh' : /microsoft|azure/i.test(org) ? 'azure' : /google/i.test(org) ? 'gcp' : 'other'; }

async function probe() {
  const spec = {
    cpu_model: cpus()[0]?.model, logical_cpus: cpus().length, available_cpus: availableParallelism(),
    memory_gib: +(totalmem() / 2 ** 30).toFixed(1), kernel: release(),
    os: (read('/etc/os-release').match(/PRETTY_NAME="([^"]+)"/) ?? [])[1],
    virtualization: sh('systemd-detect-virt', []), cgroup_cpu_max: read('/sys/fs/cgroup/cpu.max').trim() || undefined,
    cpu_flags_avx512: /avx512f/.test(read('/proc/cpuinfo')), disk: diskInfo(),
  };
  spec.network = hostNetwork();
  spec.host = hostKind(spec.network.org);
  const ok = spec.available_cpus === 4 && spec.memory_gib >= 14;
  const machine = { ...spec, matched: ok, cpu_single_mips: await cpuTest(1), cpu_all_mips: await cpuTest(spec.available_cpus), disk: { ...spec.disk, ...diskTest() }, net: netTest() };
  const event = { name: 'machine', t_ms: Date.now(), data: machine };
  appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
  console.log(JSON.stringify(machine, null, 2));
  if (!ok) { console.error(`Not a matched runner: need 4 available CPUs and >= 14 GiB RAM, got ${spec.available_cpus} CPUs, ${spec.memory_gib} GiB.`); process.exit(1); }
}

// ---- sampler ----
function counters() {
  const cpu = read('/proc/stat').split('\n')[0].trim().split(/\s+/).slice(1).map(Number); // user nice system idle iowait irq softirq steal
  const mem = Object.fromEntries(read('/proc/meminfo').split('\n').filter(Boolean).map((l) => { const [k, v] = l.split(':'); return [k, parseInt(v, 10)]; }));
  let rd = 0, wr = 0; // sectors on whole disks only
  const disks = new Set(readdirSync('/sys/block').filter((d) => !/^(loop|ram|zram|dm-)/.test(d)));
  for (const l of read('/proc/diskstats').split('\n')) { const f = l.trim().split(/\s+/); if (disks.has(f[2])) { rd += +f[5]; wr += +f[9]; } }
  let rx = 0, tx = 0;
  for (const l of read('/proc/net/dev').split('\n').slice(2)) { const [name, rest] = l.split(':'); if (!rest || /^(lo|docker|veth|br-)/.test(name.trim())) continue; const f = rest.trim().split(/\s+/).map(Number); rx += f[0]; tx += f[8]; }
  const psi = (k) => +((read(`/proc/pressure/${k}`).match(/some avg10=([\d.]+)/) ?? [])[1] ?? NaN);
  return { cpu, mem_used_mib: (mem.MemTotal - mem.MemAvailable) / 1024, rd, wr, rx, tx, psi_cpu: psi('cpu'), psi_io: psi('io'), psi_mem: psi('memory') };
}

function sample() {
  const out = process.env.BENCH_SAMPLES ?? 'machine-samples.jsonl';
  let prev = counters(), prevT = Date.now();
  setInterval(() => {
    const now = counters(), t = Date.now(), dt = (t - prevT) / 1000;
    const d = now.cpu.map((v, i) => v - prev.cpu[i]); const total = d.reduce((a, b) => a + b, 0) || 1;
    const pct = (i) => +(100 * d[i] / total).toFixed(1);
    appendFileSync(out, JSON.stringify({ t_ms: t,
      cpu_busy_pct: +(100 - pct(3) - pct(4)).toFixed(1), cpu_iowait_pct: pct(4), cpu_steal_pct: pct(7),
      mem_used_mib: Math.round(now.mem_used_mib),
      disk_read_mib_s: +((now.rd - prev.rd) * 512 / 2 ** 20 / dt).toFixed(1), disk_write_mib_s: +((now.wr - prev.wr) * 512 / 2 ** 20 / dt).toFixed(1),
      net_rx_mib_s: +((now.rx - prev.rx) / 2 ** 20 / dt).toFixed(1), net_tx_mib_s: +((now.tx - prev.tx) / 2 ** 20 / dt).toFixed(1),
      psi_cpu: now.psi_cpu, psi_io: now.psi_io, psi_mem: now.psi_mem }) + '\n');
    prev = now; prevT = t;
  }, 1000);
}
