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
import { appendFileSync, closeSync, copyFileSync, fdatasyncSync, mkdirSync, mkdtempSync, openSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync, writeSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import * as childProcess from 'node:child_process';
import { execFileSync } from 'node:child_process';
import { availableParallelism, cpus, release, totalmem } from 'node:os';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

const read = (p) => { try { return readFileSync(p, 'utf8'); } catch { return ''; } };
const sh = (cmd, args, opts = {}) => { try { return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], ...opts }).trim(); } catch (e) { return `error: ${e.message.split('\n')[0]}`; } };

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
  rmSync(file, { force: true });
  return { write_mib_s, read_mib_s };
}

// ---- Filesystems: what each place a job writes to is mounted on, and how
// fast it handles many small files (what tar extraction and yarn linking do).
const secs = (t) => Number(process.hrtime.bigint() - t) / 1e9;
const DIRS = 200, PER_DIR = 100, FILES = DIRS * PER_DIR; // 20,000 files of 4 KiB, like a node_modules tree
const BLOCK = Buffer.alloc(4096, 7);

function smallFileTest(base) {
  let root;
  try {
    root = mkdtempSync(join(base, 'machine-fs-'));
    const src = join(root, 'a'), dst = join(root, 'b');
    let t = process.hrtime.bigint();
    for (let d = 0; d < DIRS; d++) { const dir = join(src, `d${d}`); mkdirSync(dir, { recursive: true }); for (let f = 0; f < PER_DIR; f++) writeFileSync(join(dir, `f${f}.js`), BLOCK); }
    const create = secs(t);
    t = process.hrtime.bigint(); sh('sync', []); const sync_s = secs(t);
    t = process.hrtime.bigint();
    for (let d = 0; d < DIRS; d++) for (let f = 0; f < PER_DIR; f++) statSync(join(src, `d${d}`, `f${f}.js`));
    const stat = secs(t);
    // yarn 1 "Linking dependencies" copies every file from its cache into node_modules.
    t = process.hrtime.bigint();
    for (let d = 0; d < DIRS; d++) { const dir = join(dst, `d${d}`); mkdirSync(dir, { recursive: true }); for (let f = 0; f < PER_DIR; f++) copyFileSync(join(src, `d${d}`, `f${f}.js`), join(dir, `f${f}.js`)); }
    const copy = secs(t);
    t = process.hrtime.bigint(); rmSync(root, { recursive: true, force: true }); const remove = secs(t);
    // Synced 4 KiB writes: the latency of a durable small write (metadata journals, lock files).
    const sync4k = syncWriteTest(base);
    const rate = (x) => Math.round(FILES / x);
    return { create_per_s: rate(create), sync_after_create_s: +sync_s.toFixed(2), stat_per_s: rate(stat), copy_per_s: rate(copy), delete_per_s: rate(remove), ...sync4k };
  } catch (e) { if (root) rmSync(root, { recursive: true, force: true }); return { error: e.message }; }
}

function syncWriteTest(base, ms = 2000) {
  const file = join(base, `machine-sync-${process.pid}.bin`);
  const fd = openSync(file, 'w');
  const lat = []; const end = Date.now() + ms;
  try {
    while (Date.now() < end) { const t = process.hrtime.bigint(); writeSync(fd, BLOCK, 0, 4096, Math.floor(Math.random() * 16384) * 4096); fdatasyncSync(fd); lat.push(secs(t) * 1000); }
  } finally { closeSync(fd); rmSync(file, { force: true }); }
  lat.sort((a, b) => a - b);
  return { sync_write_iops: Math.round(lat.length / (ms / 1000)), sync_write_p50_ms: +lat[lat.length >> 1].toFixed(2), sync_write_p99_ms: +lat[Math.floor(lat.length * 0.99)].toFixed(2) };
}

function filesystems() {
  // Every distinct filesystem behind the places a job writes to; /dev/shm (RAM) is the baseline.
  const places = { workspace: process.cwd(), home: homedir(), tmp: tmpdir(), runner_temp: process.env.RUNNER_TEMP, shm: '/dev/shm' };
  const seen = new Map();
  for (const [name, path] of Object.entries(places)) {
    if (!path) continue;
    const info = sh('findmnt', ['-n', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS', '-T', path]);
    const [target, source, fstype, options = ''] = info.startsWith('error') ? [path, '?', '?', ''] : info.split(/\s+/);
    if (seen.has(target)) { seen.get(target).places.push(name); continue; }
    seen.set(target, { places: [name], target, source, fstype, options: options.slice(0, 200), ...smallFileTest(path) });
  }
  return { list: [...seen.values()],
    root_mount: sh('findmnt', ['-n', '-o', 'SOURCE,FSTYPE,OPTIONS', '/']).slice(0, 400),
    block_devices: sh('lsblk', ['-n', '-o', 'NAME,TYPE,FSTYPE,SIZE,ROTA,MOUNTPOINTS']).slice(0, 1500),
    in_container: /docker|containerd|kubepods/.test(read('/proc/1/cgroup')) || readdirSync('/').includes('.dockerenv') };
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
  const machine = { ...spec, matched: ok, cpu_single_mips: await cpuTest(1), cpu_all_mips: await cpuTest(spec.available_cpus), disk: { ...spec.disk, ...diskTest() }, fs: filesystems(), net: netTest() };
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


// ---- copytrace: why does copying small files sometimes collapse? ----
// Runs the 20,000-file copy several times while a separate process samples the
// disk every 100 ms, before and after pre-writing (then deleting) 4 GiB so the
// VM disk's qcow2 clusters are already allocated. If the collapse comes from
// first-write allocation in the qcow2 overlay, the "after" rounds are fast.
function ioSample(out) {
  const disk = () => { for (const l of read('/proc/diskstats').split('\n')) { const f = l.trim().split(/\s+/); if (/^(vd[a-z]|nvme\d+n\d+|sd[a-z])$/.test(f[2]) && +f[3] + +f[7] > 0) return { dev: f[2], wios: +f[7], wsec: +f[9], wms: +f[10], inflight: +f[11], ticks: +f[12], fl: +(f[18] ?? 0), flms: +(f[19] ?? 0) }; } return {}; };
  const mem = () => Object.fromEntries(read('/proc/meminfo').split('\n').filter((l) => /^(Dirty|Writeback):/.test(l)).map((l) => [l.split(':')[0], parseInt(l.split(':')[1], 10)]));
  setInterval(() => appendFileSync(out, JSON.stringify({ t: Date.now(), ...disk(), ...mem(), psi_io: +((read('/proc/pressure/io').match(/full avg10=([\d.]+)/) ?? [])[1] ?? NaN) }) + '\n'), 100);
}

function copyTrace() {
  const { spawn } = childProcess;
  const out = join(process.cwd(), 'copytrace-samples.jsonl');
  const sampler = spawn(process.execPath, [fileURLToPath(import.meta.url), 'iosample', out], { stdio: 'ignore' });
  // Where does this (copying) process wait? Sample its kernel stack and state every 20 ms (needs root).
  const stackOut = join(process.cwd(), 'copytrace-stacks.txt');
  const stackSampler = spawn('sudo', ['bash', '-c', `while kill -0 ${process.pid} 2>/dev/null; do echo "S $(date +%s%3N) $(awk '{print $3}' /proc/${process.pid}/stat) $(tr '\\n' '|' < /proc/${process.pid}/stack)"; sleep 0.02; done > ${stackOut}`], { stdio: 'ignore', detached: true });
  const rows = [];
  const round = (label) => {
    const t0 = Date.now(); const r = smallFileTest(process.cwd()); const t1 = Date.now();
    rows.push({ label, t0, t1, ...r }); console.log(label, JSON.stringify(r));
  };
  try {
    sh('sync', []); sh('bash', ['-c', 'echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null']);
    for (let i = 1; i <= 3; i++) round(`fresh-${i}`);
    // Pre-write 4 GiB of real data, sync, delete: ext4 then reuses those now-allocated blocks.
    const tf = process.hrtime.bigint();
    sh('dd', ['if=/dev/urandom', 'of=machine-fill.bin', 'bs=4M', 'count=1024', 'conv=fsync']);
    const fill_s = secs(tf); rmSync('machine-fill.bin', { force: true }); sh('sync', []);
    rows.push({ label: 'fill-4GiB', fill_s: +fill_s.toFixed(1) }); console.log('fill-4GiB', fill_s.toFixed(1), 's');
    for (let i = 1; i <= 3; i++) round(`after-fill-${i}`);
  } finally { sampler.kill(); sh('sudo', ['pkill', '-f', `kill -0 ${process.pid}`]); }
  // Where the copy waited in each round: top kernel frames of the sampled stacks.
  const stacks = read(stackOut).split('\n').filter((l) => l.startsWith('S ')).map((l) => { const m = l.match(/^S (\d+) (\S+) ?(.*)$/) ?? []; return { t: +m[1], state: m[2], st: m[3] ?? '' }; });
  // Disk activity inside each round's window.
  const samples = read(out).trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
  for (const r of rows.filter((x) => x.t0)) {
    const w = samples.filter((s) => s.t >= r.t0 && s.t <= r.t1);
    if (w.length < 2) continue;
    const a = w[0], b = w[w.length - 1], sec = (b.t - a.t) / 1000;
    Object.assign(r, { window_s: +sec.toFixed(1), write_ios: b.wios - a.wios, write_mib: +((b.wsec - a.wsec) * 512 / 2 ** 20).toFixed(0),
      avg_write_ms: b.wios > a.wios ? +((b.wms - a.wms) / (b.wios - a.wios)).toFixed(2) : null, flushes: b.fl - a.fl, avg_flush_ms: b.fl > a.fl ? +((b.flms - a.flms) / (b.fl - a.fl)).toFixed(1) : null,
      waits: (() => { const c = {}; let n = 0; for (const x of stacks.filter((x) => x.t >= r.t0 && x.t <= r.t1)) { n++; const fr = x.st.split('|').map((f) => f.replace(/^\[<[0-9a-f]+>\] /, '').split('+')[0]).filter((f) => f && !/^(__schedule|schedule|schedule_timeout|io_schedule|schedule_preempt_disabled)$/.test(f)); const k = x.state === 'R' ? 'running' : `${x.state}:${fr.slice(0, 4).join('<') || '(user)'}`; c[k] = (c[k] || 0) + 1; } return { n, top: Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 6) }; })(),
      disk_busy_pct: +(100 * (b.ticks - a.ticks) / (b.t - a.t)).toFixed(0), max_inflight: Math.max(...w.map((x) => x.inflight)), max_dirty_mib: Math.round(Math.max(...w.map((x) => x.Dirty || 0)) / 1024), max_psi_io: Math.max(...w.map((x) => x.psi_io || 0)) });
  }
  const event = { name: 'copytrace', t_ms: Date.now(), data: { rows, ip: sh('hostname', ['-I']).split(/\s+/)[0], disk: samples[0]?.dev, scheduler: read('/sys/block/vda/queue/scheduler').trim() || read('/sys/block/nvme0n1/queue/scheduler').trim(), nr_requests: read('/sys/block/vda/queue/nr_requests').trim(), write_cache: read('/sys/block/vda/queue/write_cache').trim(), dirty_ratio: read('/proc/sys/vm/dirty_ratio').trim(), dirty_bg_ratio: read('/proc/sys/vm/dirty_background_ratio').trim() } };
  appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
  console.log(JSON.stringify(event.data, null, 2));
}


// ---- copyab: does a guest block-layer setting remove the slow copies? ----
// Interleaves copy rounds under different settings of the VM's root disk, three times each,
// and samples the disk during each round. Settings are restored after every round.
function copyAB() {
  const dev = (sh('lsblk', ['-no', 'PKNAME', sh('findmnt', ['-no', 'SOURCE', '-T', process.cwd()])]) || '').trim() || sh('bash', ['-c', `basename $(findmnt -no SOURCE -T ${process.cwd()})`]);
  const q = (k) => `/sys/block/${dev}/queue/${k}`;
  const get = (k) => read(q(k)).trim();
  const set = (k, v) => sh('bash', ['-c', `echo ${v} | sudo tee ${q(k)} >/dev/null`]);
  const base = { scheduler: (get('scheduler').match(/\[(\S+)\]/) ?? [])[1], rotational: get('rotational'), wbt_lat_usec: get('wbt_lat_usec'), nr_requests: get('nr_requests') };
  const modes = [['default', {}], ['sched-none', { scheduler: 'none' }], ['nonrot', { rotational: '0' }], ['wbt-off', { wbt_lat_usec: '0' }]];
  const out = join(process.cwd(), 'copyab-samples.jsonl');
  const sampler = childProcess.spawn(process.execPath, [fileURLToPath(import.meta.url), 'iosample', out], { stdio: 'ignore' });
  const rows = [];
  try {
    for (let rep = 1; rep <= 3; rep++) {
      const order = rep % 2 ? modes : [...modes].reverse();
      for (const [name, cfg] of order) {
        for (const [k, v] of Object.entries(cfg)) set(k, v);
        const applied = { scheduler: get('scheduler'), rotational: get('rotational'), wbt_lat_usec: get('wbt_lat_usec') };
        const t0 = Date.now(); const r = smallFileTest(process.cwd()); const t1 = Date.now();
        // restore every setting to its starting value
        set('scheduler', base.scheduler); set('rotational', base.rotational); set('wbt_lat_usec', base.wbt_lat_usec);
        rows.push({ label: `${name}-${rep}`, mode: name, rep, t0, t1, applied, ...r });
        console.log(name, rep, r.copy_per_s, JSON.stringify(applied));
      }
    }
  } finally { sampler.kill(); }
  const samples = read(out).trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
  for (const r of rows) {
    const w = samples.filter((s) => s.t >= r.t0 && s.t <= r.t1);
    if (w.length < 2) continue;
    const a = w[0], b = w[w.length - 1];
    Object.assign(r, { write_ios: b.wios - a.wios, avg_write_ms: b.wios > a.wios ? +((b.wms - a.wms) / (b.wios - a.wios)).toFixed(2) : null, max_inflight: Math.max(...w.map((x) => x.inflight)) });
  }
  const event = { name: 'copyab', t_ms: Date.now(), data: { dev, base, rows, ip: sh('hostname', ['-I']).split(/\s+/)[0] } };
  appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
}


// ---- journalab: is the ext4 journal size what makes copies collapse? ----
// Records the root filesystem's ext4 setup, then copies 20,000 files on loop-mounted ext4
// filesystems in the same workspace (same VM disk path) with a small and a large journal,
// interleaved, three rounds each; jbd2 statistics are kept per round.
function journalAB() {
  const rootDev = sh('findmnt', ['-no', 'SOURCE', '/']);
  const wsDev = sh('findmnt', ['-no', 'SOURCE', '-T', process.cwd()]);
  const fsInfo = (dev) => sh('sudo', ['dumpe2fs', '-h', dev]).split('\n').filter((l) => /^(Journal size|Journal length|Filesystem features|Default mount options|Block size|Journal features|Filesystem created|Inode count)/.test(l));
  const jbd2 = () => { const o = {}; for (const d of readdirSync('/proc/fs/jbd2')) o[d] = read(`/proc/fs/jbd2/${d}/info`).trim().split('\n').slice(0, 12); return o; };
  const root = { rootDev, wsDev, mount: sh('findmnt', ['-no', 'OPTIONS', '-T', process.cwd()]), fs: fsInfo(wsDev), jbd2: jbd2() };
  console.log(JSON.stringify(root, null, 2));
  const rows = [];
  const sizes = [64, 1024];
  const dirs = {};
  for (const mb of sizes) {
    const img = join(process.cwd(), `jtest-${mb}.img`), mnt = join(process.cwd(), `jtest-${mb}`);
    sh('fallocate', ['-l', '6G', img]);
    sh('sudo', ['mkfs.ext4', '-q', '-F', '-J', `size=${mb}`, img]);
    mkdirSync(mnt, { recursive: true });
    sh('sudo', ['mount', '-o', 'loop', img, mnt]); sh('sudo', ['chown', process.env.USER || 'runner', mnt]);
    dirs[mb] = mnt;
  }
  try {
    for (let rep = 1; rep <= 3; rep++) {
      for (const mb of rep % 2 ? sizes : [...sizes].reverse()) {
        const t0 = Date.now(); const r = smallFileTest(dirs[mb]); const t1 = Date.now();
        rows.push({ label: `journal-${mb}M-${rep}`, journal_mb: mb, rep, t0, t1, ...r });
        console.log(`journal ${mb} MiB rep ${rep}: copy/s=${r.copy_per_s} create/s=${r.create_per_s}`);
      }
      // the root filesystem itself, same test, for reference
      const t0 = Date.now(); const r = smallFileTest(process.cwd()); const t1 = Date.now();
      rows.push({ label: `root-${rep}`, journal_mb: 'root', rep, t0, t1, ...r });
      console.log(`root fs rep ${rep}: copy/s=${r.copy_per_s}`);
    }
  } finally {
    for (const mb of sizes) { sh('sudo', ['umount', dirs[mb]]); rmSync(join(process.cwd(), `jtest-${mb}.img`), { force: true }); }
  }
  const event = { name: 'journalab', t_ms: Date.now(), data: { root, rows, jbd2_after: jbd2(), ip: sh('hostname', ['-I']).split(/\s+/)[0] } };
  appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
}


// ---- blktrace: where do the guest's disk requests spend their time? ----
// Copy rounds on the root filesystem while the kernel's block tracepoints record every request
// (insert, issue, complete) for the root disk; plus virtio interrupt counts per vCPU per round.
function blkTrace() {
  const dev = sh('bash', ['-c', `lsblk -no PKNAME $(findmnt -no SOURCE -T ${process.cwd()}) | head -1`]) || sh('bash', ['-c', `basename $(findmnt -no SOURCE -T ${process.cwd()})`]);
  const majmin = read(`/sys/block/${dev}/dev`).trim();
  const T = '/sys/kernel/tracing';
  sh('sudo', ['bash', '-c', `mountpoint -q ${T} || mount -t tracefs nodev ${T}`]);
  const tw = (f, v) => sh('sudo', ['bash', '-c', `echo '${v}' > ${T}/${f}`]);
  tw('trace', ''); tw('buffer_size_kb', '65536'); tw('trace_clock', 'mono');
  for (const e of ['block_rq_insert', 'block_rq_issue', 'block_rq_complete']) { tw(`events/block/${e}/filter`, `dev == ${(+majmin.split(':')[0] << 20) | +majmin.split(':')[1]}`); tw(`events/block/${e}/enable`, '1'); }
  const out = join(process.cwd(), 'blktrace.txt');
  const reader = childProcess.spawn('sudo', ['bash', '-c', `cat ${T}/trace_pipe > ${out}`], { stdio: 'ignore', detached: true });
  const irqs = () => read('/proc/interrupts').split('\n').filter((l) => /virtio/.test(l)).map((l) => l.trim().split(/\s+/));
  const mono0 = Number(process.hrtime.bigint() / 1000000n), epoch0 = Date.now();
  const rows = [];
  try {
    for (let i = 1; i <= 6; i++) {
      const before = irqs(); const t0 = Date.now(); const r = smallFileTest(process.cwd()); const t1 = Date.now(); const after = irqs();
      rows.push({ label: `root-${i}`, t0, t1, ...r, irq_before: before, irq_after: after });
      console.log(`root ${i}: copy/s=${r.copy_per_s}`);
    }
  } finally {
    for (const e of ['block_rq_insert', 'block_rq_issue', 'block_rq_complete']) tw(`events/block/${e}/enable`, '0');
    sh('sudo', ['pkill', '-f', `cat ${T}/trace_pipe`]);
  }
  // Per round: per-request issue->complete (D2C) and insert->issue (Q2D) from the trace.
  const ins = new Map(), iss = new Map(); const reqs = [];
  for (const l of read(out).split('\n')) {
    const m = l.match(/\s(\d+\.\d+): block_rq_(insert|issue|complete): \d+,\d+ (\S+) .*? (\d+) \+ (\d+)/);
    if (!m) continue;
    const t = parseFloat(m[1]) * 1000, kind = m[2], rw = m[3], key = `${m[4]}+${m[5]}`;
    if (kind === 'insert') ins.set(key, t);
    else if (kind === 'issue') iss.set(key, t);
    else if (iss.has(key)) { reqs.push({ t, d2c: t - iss.get(key), q2d: ins.has(key) ? iss.get(key) - ins.get(key) : null, rw }); iss.delete(key); ins.delete(key); }
  }
  const toEpoch = (mono) => mono - mono0 + epoch0;
  for (const r of rows) {
    const w = reqs.filter((x) => toEpoch(x.t) >= r.t0 && toEpoch(x.t) <= r.t1);
    const d = w.map((x) => x.d2c).sort((a, b) => a - b), q = w.map((x) => x.q2d).filter((x) => x != null).sort((a, b) => a - b);
    const pct = (a, p) => (a.length ? +a[Math.min(a.length - 1, Math.floor(a.length * p))].toFixed(3) : null);
    Object.assign(r, { requests: w.length, d2c_p50: pct(d, 0.5), d2c_p90: pct(d, 0.9), d2c_p99: pct(d, 0.99), d2c_max: pct(d, 1),
      q2d_p50: pct(q, 0.5), q2d_p99: pct(q, 0.99), writes: w.filter((x) => x.rw.includes('W')).length, flush_fua: w.filter((x) => /F/.test(x.rw)).length });
    // virtio interrupts during the round, per vCPU, per virtio line
    r.virtio_irqs = r.irq_after.map((a) => { const b = r.irq_before.find((x) => x[0] === a[0]) ?? []; const cpus = a.slice(1).filter((x) => /^\d+$/.test(x)); return { irq: a[0], name: a.slice(1 + cpus.length).join(' '), per_cpu: cpus.map((v, i) => +v - +(b[1 + i] ?? 0)) }; }).filter((x) => x.per_cpu.some((v) => v > 0));
    delete r.irq_before; delete r.irq_after;
  }
  const event = { name: 'blktrace', t_ms: Date.now(), data: { dev, rows, trace_lines: reqs.length, mono0, epoch0, ip: sh('hostname', ['-I']).split(/\s+/)[0] } };
  appendFileSync(process.env.BENCH_EVENTS ?? 'bench-events.jsonl', JSON.stringify(event) + '\n');
  console.log(JSON.stringify(rows.map(({ label, copy_per_s, requests, d2c_p50, d2c_p90, d2c_p99, d2c_max, q2d_p50, q2d_p99 }) => ({ label, copy_per_s, requests, d2c_p50, d2c_p90, d2c_p99, d2c_max, q2d_p50, q2d_p99 })), null, 1));
}

// Entry point last, so every constant above is initialized first.
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
  else if (mode === 'fs') console.log(JSON.stringify(filesystems(), null, 2));
  else if (mode === 'copytrace') copyTrace();
  else if (mode === 'copyab') copyAB();
  else if (mode === 'journalab') journalAB();
  else if (mode === 'blktrace') blkTrace();
  else if (mode === 'iosample') ioSample(process.argv[3]);
  else if (mode === 'sample') sample();
  else { console.error('usage: machine.mjs probe|fs|copytrace|sample'); process.exit(1); }
}
