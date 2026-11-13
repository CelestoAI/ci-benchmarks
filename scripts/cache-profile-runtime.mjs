import * as profileFs from 'node:fs';
const profileStart = process.hrtime.bigint();
const profileFile = process.env.CACHE_PROFILE_EVENTS;

function profileSnapshot() {
  const net = profileFs.readFileSync('/proc/net/dev', 'utf8').trim().split('\n').slice(2);
  let rx = 0, tx = 0;
  for (const line of net) {
    const [name, values] = line.trim().split(':');
    if (name.trim() === 'lo') continue;
    const fields = values.trim().split(/\s+/).map(Number);
    rx += fields[0];
    tx += fields[8];
  }
  const cpu = profileFs.readFileSync('/proc/stat', 'utf8').split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
  const io = Object.fromEntries(profileFs.readFileSync('/proc/self/io', 'utf8').trim().split('\n').map(line => {
    const [key, value] = line.split(':');
    return [key, Number(value.trim())];
  }));
  return { cpu: process.cpuUsage(), system_cpu_ticks: cpu, io, net_rx_bytes: rx, net_tx_bytes: tx };
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
  profileWrite({ phase, event: 'start' });
  let status = 'success';
  try {
    return await operation();
  } catch (error) {
    status = 'error';
    throw error;
  } finally {
    const duration_ms = Number(process.hrtime.bigint() - started) / 1e6;
    const after = profileSnapshot();
    profileWrite({
      phase, event: 'end', status, duration_ms,
      process_user_cpu_ms: (after.cpu.user - before.cpu.user) / 1000,
      process_system_cpu_ms: (after.cpu.system - before.cpu.system) / 1000,
      system_cpu_ticks: after.system_cpu_ticks.map((n, i) => n - before.system_cpu_ticks[i]),
      process_io: Object.fromEntries(Object.keys(after.io).map(k => [k, after.io[k] - before.io[k]])),
      net_rx_bytes: after.net_rx_bytes - before.net_rx_bytes,
      net_tx_bytes: after.net_tx_bytes - before.net_tx_bytes,
    });
  }
}

profileWrite({ phase: 'process', event: 'start', node: process.version });
process.once('exit', code => profileWrite({
  phase: 'process', event: 'end', exit_code: code,
  duration_ms: Number(process.hrtime.bigint() - profileStart) / 1e6,
}));
