"""Observe only this disposable CI guest; archive files stay on the normal disk."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

OUT = Path('/dev/shm/cache-native-profile')


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def cgroups(pid):
    rows = []
    for line in (read(f'/proc/{pid}/cgroup') or '').splitlines():
        if not line.startswith('0::'):
            continue
        p = Path('/sys/fs/cgroup') / line[3:].lstrip('/')
        while p.is_relative_to('/sys/fs/cgroup'):
            rows.append({'path': str(p), **{n: read(p / n) for n in
                ['cpu.max', 'cpu.stat', 'cpuset.cpus.effective', 'cpu.pressure', 'io.pressure']}})
            if p == Path('/sys/fs/cgroup'):
                break
            p = p.parent
    return rows


def status(path):
    text = read(path) or ''
    return {k: v.strip() for l in text.splitlines() if ':' in l
            for k, v in [l.split(':', 1)] if k in ['Cpus_allowed_list', 'Threads', 'State']}


def observe():
    assert os.geteuid() == 0
    (OUT / 'observer-identity.json').write_text(json.dumps({'pid': os.getpid(),
        'start_stat': read('/proc/self/stat'), 'sample_interval_seconds': 0.1,
        'metadata_device': OUT.stat().st_dev}))
    started = time.monotonic()
    known = set()
    previous_system = 0
    with (OUT / 'thread-waits.jsonl').open('w', buffering=1) as log:
        while not (OUT / 'stop-observer').exists() and time.monotonic() - started < 1000:
            now = time.time()
            tasks = []
            for p in Path('/proc').iterdir():
                if not p.name.isdigit():
                    continue
                comm = read(p / 'comm')
                if comm not in ['tar', 'zstd', 'zstdmt']:
                    continue
                stat = read(p / 'stat')
                if not stat:
                    continue
                fields = stat.rsplit(')', 1)[1].split()
                identity = (int(p.name), fields[19])
                if identity not in known:
                    known.add(identity)
                    try:
                        args = (p / 'cmdline').read_bytes().decode().split('\0')
                        items = (p / 'environ').read_bytes().decode().split('\0')
                    except OSError:
                        continue
                    env = {}
                    for item in items:
                        if '=' in item:
                            key, val = item.split('=', 1)
                            if key in ['ZSTD_NBTHREADS', 'ZSTD_CLEVEL']:
                                env[key] = val
                    log.write(json.dumps({'event': 'process', 'utc': now, 'pid': int(p.name),
                        'ppid': int(fields[1]), 'comm': comm, 'argv': args, 'env': env,
                        'status': status(p / 'status'), 'cgroups': cgroups(p.name)}) + '\n')
                try:
                    children = list((p / 'task').iterdir())
                except OSError:
                    continue
                for task in children:
                    text = read(task / 'stat')
                    if not text:
                        continue
                    f = text.rsplit(')', 1)[1].split()
                    wchan = read(task / 'wchan')
                    row = {'pid': int(p.name), 'tid': int(task.name), 'comm': comm,
                        'task_comm': read(task / 'comm'), 'state': f[0], 'start_ticks': int(f[19]),
                        'cpu_ticks': int(f[11]) + int(f[12]), 'wchan': wchan,
                        'schedstat': read(task / 'schedstat')}
                    if f[0] == 'D' or (int(now * 10) % 5 == 0 and f[0] == 'S'):
                        row['stack'] = read(task / 'stack')
                    tasks.append(row)
            if tasks:
                log.write(json.dumps({'event': 'tasks', 'utc': now, 'tasks': tasks}) + '\n')
            if now - previous_system >= 1:
                log.write(json.dumps({'event': 'system', 'utc': now,
                    **{n: read('/proc/' + n) for n in ['stat', 'meminfo', 'diskstats']},
                    'cgroups': cgroups(os.getpid())}) + '\n')
                previous_system = now
            time.sleep(0.1)
    (OUT / 'observer-stopped').touch()


def cpu_probe():
    code = '''import hashlib,json,time,resource,os
t=time.monotonic();c=time.process_time();b=b"x"*1048576;n=0
while time.monotonic()-t<3:
 hashlib.sha256(b).digest();n+=1
print(json.dumps({"cpu_seconds":time.process_time()-c,"wall_seconds":time.monotonic()-t,"iterations":n,"affinity":sorted(os.sched_getaffinity(0))}))'''
    t = time.monotonic()
    before = cgroups(os.getpid())
    ps = [subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
          for _ in range(4)]
    rows = []
    for p in ps:
        stdout, _ = p.communicate(timeout=20)
        assert p.returncode == 0
        rows.append(json.loads(stdout))
    wall = time.monotonic() - t
    result = {'guest_cpus': os.cpu_count(), 'processes': rows, 'wall_seconds': wall,
        'average_busy_cores': sum(x['cpu_seconds'] for x in rows) / wall,
        'cgroups_before': before, 'cgroups_after': cgroups(os.getpid())}
    assert os.cpu_count() == 4
    (OUT / 'four-core-probe.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


def compression_controls():
    # Real counted pipe prevents tar's /dev/null output optimization. These
    # controls follow the verified cache restore and are not normal save times.
    os.sync()
    rows = []
    for name, command in [('auto', 'zstdmt'), ('one', 'zstd -T1'), ('four', 'zstd -T4')]:
        resource = OUT / ('control-' + name + '-resources.txt')
        argv = ['/usr/bin/time', '-v', '-o', str(resource), 'tar', '--posix', '-cf', '-',
            '-P', '-C', os.getcwd(), '--files-from', str(OUT / 'control-manifest.txt'),
            '--use-compress-program', command]
        (OUT / 'control-manifest.txt').write_text('cache-file\n')
        started = time.time()
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        count = 0
        while chunk := p.stdout.read(4 * 1024**2):
            count += len(chunk)
        err = p.stderr.read()
        assert p.wait(timeout=30) == 0, err
        ended = time.time()
        assert count > 4 * 1024**3
        rows.append({'name': name, 'command': command, 'start_utc': started,
            'end_utc': ended, 'seconds': ended - started, 'compressed_bytes_counted': count,
            'resources': resource.read_text(), 'output': 'counted pipe; no archive disk writes',
            'source': 'warm source after full restore verification and explicit sync'})
    (OUT / 'compression-controls.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows))


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'observe':
        observe()
    elif mode == 'start':
        assert not (OUT / 'observer-identity.json').exists()
        with (OUT / 'observer.log').open('w') as log:
            p = subprocess.Popen(['sudo', '-n', sys.executable, str(Path(__file__).resolve()), 'observe'],
                stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 10
        while not (OUT / 'observer-identity.json').exists():
            assert p.poll() is None, 'Observer failed to start'
            assert time.monotonic() < deadline
            time.sleep(0.1)
    elif mode == 'stop':
        (OUT / 'stop-observer').touch()
        deadline = time.monotonic() + 10
        while not (OUT / 'observer-stopped').exists():
            assert time.monotonic() < deadline, 'Observer did not stop cleanly'
            time.sleep(0.1)
        subprocess.run(['sudo', '-n', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', str(OUT)], check=True)
    elif mode == 'cpu':
        cpu_probe()
    elif mode == 'controls':
        compression_controls()
    else:
        raise ValueError(mode)
