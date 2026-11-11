// Hardware tests, one group per call.
//
// Usage: node scripts/hardware-bench.mjs <group> <metrics.json>
// Groups: cpu, passmark, memory, disk, network, docker, postgres
//
// Each call merges its numbers into metrics.json. A failed group records
// its error and exits 1; the numbers from other groups are kept.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { availableParallelism } from 'node:os';
import { join } from 'node:path';

const nproc = availableParallelism();
const workspace = process.env.GITHUB_WORKSPACE ?? process.cwd();

function run(cmd, args, opts = {}) {
  console.log('+', cmd, args.join(' '));
  return execFileSync(cmd, args, { encoding: 'utf8', maxBuffer: 64 << 20, ...opts });
}

function grab(text, re) {
  const m = text.match(re);
  return m ? Number(m[1]) : null;
}

function cpu() {
  const sysbench = (threads) =>
    grab(run('sysbench', ['cpu', `--threads=${threads}`, '--time=20', 'run']), /events per second:\s+([\d.]+)/);
  return {
    cpu: {
      sysbenchSingleEps: sysbench(1),
      sysbenchMultiEps: sysbench(nproc),
      sevenZipMips: grab(run('7z', ['b']), /^Tot:\s+\S+\s+\S+\s+(\d+)/m),
    },
  };
}

function passmark() {
  const bin = '/tmp/PerformanceTest/pt_linux';
  if (!existsSync(bin)) throw new Error(`${bin} not found: run scripts/install-passmark.sh first`);
  const dir = '/tmp/passmark-run';
  mkdirSync(dir, { recursive: true });
  // pt_linux needs a terminal; `script` gives it one.
  run('script', ['-q', '-c', `${bin} -r 1 -i 2 -p ${nproc} -d 2`, '/dev/null'], {
    cwd: dir,
    env: { ...process.env, TERM: 'xterm' },
  });
  const yml = readFileSync(join(dir, 'results_cpu.yml'), 'utf8');
  return {
    cpu: {
      passmarkSingle: grab(yml, /CPU_SINGLETHREAD:\s*([\d.]+)/),
      passmarkCpuMark: grab(yml, /SUMM_CPU:\s*([\d.]+)/),
    },
  };
}

function memory() {
  const mibps = (oper) =>
    grab(run('sysbench', ['memory', `--memory-oper=${oper}`, `--threads=${nproc}`, '--time=15', 'run']), /\(([\d.]+) MiB\/sec\)/);
  return { memory: { readMiBps: mibps('read'), writeMiBps: mibps('write') } };
}

// name, rw, block size, iodepth, jobs, extra args
const FIO_TESTS = [
  ['seqRead', 'read', '1M', 32, 1, []],
  ['seqWrite', 'write', '1M', 32, 1, []],
  ['randRead', 'randread', '4k', 32, 4, []],
  ['randWrite', 'randwrite', '4k', 32, 4, []],
  ['randReadQd1', 'randread', '4k', 1, 1, []],
  ['syncWrite', 'write', '4k', 1, 1, ['--fdatasync=1']],
];

function disk() {
  const dir = join(workspace, '.fio');
  const out = { directory: dir };
  for (const [name, rw, bs, iodepth, jobs, extra] of FIO_TESTS) {
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    const reads = rw.includes('read');
    const size = jobs === 1 ? '2G' : '1G';
    const common = [`--directory=${dir}`, '--ioengine=libaio', '--direct=1', `--size=${size}`, `--numjobs=${jobs}`, `--filename_format=${name}.$jobnum`];
    // Write real data first, so reads never hit empty file extents.
    if (reads) run('fio', [`--name=${name}-prep`, ...common, '--bs=1M', '--iodepth=32', '--rw=write', '--fallocate=none', '--refill_buffers=1', '--end_fsync=1']);
    const args = [`--name=${name}`, ...common, `--bs=${bs}`, `--iodepth=${iodepth}`, `--rw=${rw}`, '--time_based', '--runtime=20', '--ramp_time=2s', '--group_reporting=1', '--output-format=json', ...extra];
    if (reads) args.push('--allow_file_create=0', '--readonly');
    const job = JSON.parse(run('fio', args)).jobs[0];
    const side = reads ? job.read : job.write;
    const p99 = side.clat_ns?.percentile?.['99.000000'];
    out[name] = { MiBps: +(side.bw_bytes / 2 ** 20).toFixed(1), iops: Math.round(side.iops), p99us: p99 ? +(p99 / 1000).toFixed(1) : null };
  }
  rmSync(dir, { recursive: true, force: true });
  return { disk: out };
}

function download(url) {
  const [speed, size, total] = run('curl', ['-sS', '-L', '-o', '/dev/null', '--max-time', '60', '-w', '%{speed_download} %{size_download} %{time_total}', url]).split(' ').map(Number);
  return { MiBps: +(speed / 2 ** 20).toFixed(1), MiB: +(size / 2 ** 20).toFixed(1), seconds: total };
}

function network() {
  return {
    network: {
      cdnDownload: download('https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.tar.xz'),
      githubDownload: download('https://github.com/oven-sh/bun/releases/download/bun-v1.3.14/bun-linux-x64.zip'),
    },
  };
}

function seconds(fn) {
  const t = performance.now();
  fn();
  return +((performance.now() - t) / 1000).toFixed(2);
}

function docker() {
  const image = 'node:24-bookworm';
  try { run('docker', ['rmi', '-f', image]); } catch {}
  try { run('docker', ['builder', 'prune', '-af']); } catch {}
  return {
    docker: {
      image,
      pullSeconds: seconds(() => run('docker', ['pull', '-q', image])),
      firstRunSeconds: seconds(() => run('docker', ['run', '--rm', image, 'node', '-e', '1'])),
    },
  };
}

function postgres() {
  try { run('docker', ['rm', '-f', 'bench-pg']); } catch {}
  run('docker', ['run', '-d', '--name', 'bench-pg', '-e', 'POSTGRES_PASSWORD=postgres', '-e', 'POSTGRES_DB=bench', '-p', '5432:5432', 'postgres:16']);
  for (let i = 0; i < 60; i++) {
    try { run('pg_isready', ['-h', 'localhost', '-p', '5432']); break; } catch { execFileSync('sleep', ['1']); }
  }
  execFileSync('sleep', ['2']);
  const opts = { env: { ...process.env, PGPASSWORD: 'postgres' } };
  const base = ['-h', 'localhost', '-U', 'postgres'];
  run('pgbench', ['-i', '-s', '50', ...base, 'bench'], opts);
  const tps = (flags) => grab(run('pgbench', [...base, ...flags, '-c', '10', '-j', String(nproc), '-T', '30', 'bench'], opts), /tps = ([\d.]+)/);
  return { postgres: { readOnlyTps: tps(['-S']), readWriteTps: tps([]) } };
}

const GROUPS = { cpu, passmark, memory, disk, network, docker, postgres };
const [group, file] = process.argv.slice(2);
if (!GROUPS[group] || !file) {
  console.error(`Usage: node scripts/hardware-bench.mjs <${Object.keys(GROUPS).join('|')}> <metrics.json>`);
  process.exit(2);
}

const metrics = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
const start = performance.now();
let status = 0;
try {
  for (const [key, value] of Object.entries(GROUPS[group]())) metrics[key] = { ...metrics[key], ...value };
} catch (err) {
  console.log(`::warning::${group} failed: ${err.message.slice(0, 300)}`);
  (metrics.errors ??= {})[group] = err.message.slice(0, 500);
  status = 1;
}
(metrics.groupSeconds ??= {})[group] = +((performance.now() - start) / 1000).toFixed(1);
writeFileSync(file, JSON.stringify(metrics, null, 2) + '\n');
console.log(JSON.stringify(metrics[group] ?? metrics.errors, null, 2));
process.exit(status);
