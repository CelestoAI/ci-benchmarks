import * as profileFs from 'node:fs';
const profileStart = process.hrtime.bigint();
const profileFile = process.env.CACHE_PROFILE_EVENTS;

function profileRead(path) {
  try { return profileFs.readFileSync(path, 'utf8'); } catch { return null; }
}

function profileSnapshot() {
  const net = profileRead('/proc/net/dev').trim().split('\n').slice(2);
  let rx = 0, tx = 0;
  for (const line of net) {
    const [name, values] = line.trim().split(':');
    if (name.trim() === 'lo') continue;
    const fields = values.trim().split(/\s+/).map(Number);
    rx += fields[0]; tx += fields[8];
  }
  const cpu = profileRead('/proc/stat').split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
  const io = Object.fromEntries(profileRead('/proc/self/io').trim().split('\n').map(line => {
    const [key, value] = line.split(':'); return [key, Number(value.trim())];
  }));
  return { cpu: process.cpuUsage(), system_cpu_ticks: cpu, io, net_rx_bytes: rx, net_tx_bytes: tx,
    meminfo: profileRead('/proc/meminfo'), diskstats: profileRead('/proc/diskstats'),
    io_pressure: profileRead('/proc/pressure/io'), cpu_stat: profileRead('/sys/fs/cgroup/cpu.stat') };
}

function profileWrite(record) {
  profileFs.appendFileSync(profileFile, JSON.stringify({
    timestamp_utc: new Date().toISOString(),
    offset_ms: Number(process.hrtime.bigint() - profileStart) / 1e6,
    ...record,
  }) + '\n');
}

async function profileCachePhase(phase, operation) {
  const before = profileSnapshot();
  const started = process.hrtime.bigint();
  profileWrite({ phase, event: 'start', snapshot: before });
  let status = 'success';
  try {
    const result = await operation();
    if (phase === 'create_temp_dir') profileWrite({phase: 'archive_directory', event: 'observed', path: result, device: profileFs.statSync(result).dev});
    return result;
  }
  catch (error) { status = 'error'; throw error; }
  finally {
    const duration_ms = Number(process.hrtime.bigint() - started) / 1e6;
    const after = profileSnapshot();
    profileWrite({ phase, event: 'end', status, duration_ms, snapshot: after,
      process_user_cpu_ms: (after.cpu.user - before.cpu.user) / 1000,
      process_system_cpu_ms: (after.cpu.system - before.cpu.system) / 1000,
      system_cpu_ticks: after.system_cpu_ticks.map((n, i) => n - before.system_cpu_ticks[i]),
      process_io: Object.fromEntries(Object.keys(after.io).map(k => [k, after.io[k] - before.io[k]])),
      net_rx_bytes: after.net_rx_bytes - before.net_rx_bytes,
      net_tx_bytes: after.net_tx_bytes - before.net_tx_bytes,
    });
  }
}

profileWrite({ phase: 'process', event: 'start', node: process.version,
  script: import.meta.url.split('/').pop(), snapshot: profileSnapshot() });
const profileSampler = setInterval(() => profileWrite({phase: 'sample', event: 'tick', snapshot: profileSnapshot()}), 1000);
profileSampler.unref();
process.once('exit', code => profileWrite({ phase: 'process', event: 'end', exit_code: code,
  duration_ms: Number(process.hrtime.bigint() - profileStart) / 1e6 }));
