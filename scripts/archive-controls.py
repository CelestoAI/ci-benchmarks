"""Run real archive controls; keep payloads outside the evidence directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--work-dir', type=Path, required=True)
parser.add_argument('--ram-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--mib', type=int, default=4096)
parser.add_argument('--repetitions', type=int, default=3)
args = parser.parse_args()
assert args.mib > 0 and args.repetitions > 0
work, ram, out = (p.resolve() for p in (args.work_dir, args.ram_dir, args.output_dir))
for p in (work, ram, out):
    p.mkdir(parents=True, exist_ok=True)
assert work != out and ram != out
sample = int(os.environ.get('ARCHIVE_SAMPLE', '1'))
payload = work / 'cache-file'
payload_bytes = args.mib * 1024**2


def command(*argv):
    return subprocess.check_output(argv, text=True).strip()


def filesystem(path):
    return json.loads(command('findmnt', '--json', '--target', str(path),
                              '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'))['filesystems'][0]


def snapshot():
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in {'MemAvailable', 'Cached', 'Dirty', 'Writeback', 'SwapFree'}:
            mem[key + '_kib'] = int(value.split()[0])
    pressure = {}
    for name in ('io', 'cpu', 'memory'):
        p = Path('/proc/pressure') / name
        pressure[name] = p.read_text() if p.exists() else None
    cg = {}
    for name in ('cpu.max', 'cpu.stat', 'memory.max', 'memory.current', 'io.max', 'io.stat'):
        p = Path('/sys/fs/cgroup') / name
        cg[name] = p.read_text() if p.exists() else None
    return {'monotonic_seconds': time.monotonic(), 'memory': mem, 'pressure': pressure,
            'cgroup': cg, 'diskstats': Path('/proc/diskstats').read_text(),
            'cpu_ticks': list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:]))}


def payload_digest(stream):
    digest = hashlib.sha256()
    count = 0
    while block := stream.read(1024**2):
        digest.update(block)
        count += len(block)
    return digest.hexdigest(), count


def host_provider():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            values = (entry / 'cmdline').read_bytes().decode().split('\0')
        except (OSError, UnicodeError):
            continue
        if values and 'celesto-ci-cache-proxy' in values[0] and '--host-provider' in values:
            value = values[values.index('--host-provider') + 1]
            return value if value in ('aws', 'ovh') else 'unknown'
    return 'unknown'


disk_fs, ram_fs = filesystem(work), filesystem(ram)
assert disk_fs['fstype'] != 'tmpfs', f'Disk control is RAM-backed: {disk_fs}'
assert ram_fs['fstype'] == 'tmpfs', f'RAM control is not tmpfs: {ram_fs}'
assert shutil.disk_usage(work).free > payload_bytes * 2 + 512 * 1024**2
assert shutil.disk_usage(ram).free > payload_bytes + 128 * 1024**2
host = {'sample': sample, 'provider': host_provider(), 'runner': os.environ.get('RUNNER_NAME'),
        'run_url': f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'local')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'smoke')}",
        'kernel': platform.release(), 'cpu': command('lscpu'),
        'available_cpus': len(os.sched_getaffinity(0)), 'self_cgroup': Path('/proc/self/cgroup').read_text(),
        'disk_filesystem': disk_fs, 'ram_filesystem': ram_fs,
        'tar': command('tar', '--version'), 'zstd': command('zstd', '--version'),
        'payload_bytes': payload_bytes, 'repetitions': args.repetitions, 'initial_state': snapshot()}
(out / 'host.json').write_text(json.dumps(host, indent=2) + '\n')

started = time.monotonic()
with payload.open('wb') as target:
    subprocess.run(['head', '-c', str(payload_bytes), '/dev/urandom'], stdout=target, check=True)
with payload.open('rb') as source:
    expected_hash, count = payload_digest(source)
assert count == payload_bytes
(out / 'input.json').write_text(json.dumps({'bytes': count, 'sha256': expected_hash,
    'generate_and_hash_seconds': time.monotonic() - started}, indent=2) + '\n')
(work / 'manifest.txt').write_text('cache-file\n')
rows = []


def trial(mode, repetition, clean):
    label = f'{mode}-r{repetition}' if clean else 'disk-after-generation'
    target = (ram if mode == 'ram' else work) / 'archive.tzst'
    assert not target.exists(), f'Previous output was not removed: {target}'
    preparation = time.monotonic()
    if clean:
        os.sync()
        with payload.open('rb') as source:
            digest, count = payload_digest(source)
        assert digest == expected_hash and count == payload_bytes
    preparation = time.monotonic() - preparation
    archive_path = '-' if mode == 'pipe' else str(target)
    argv = ['tar', '--posix', '-cf', archive_path, '-P', '-C', str(work),
            '--files-from', str(work / 'manifest.txt'), '--use-compress-program', 'zstdmt']
    before = snapshot()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    parent_before = time.process_time()
    started = time.monotonic()
    with (out / f'{label}.stderr').open('wb') as err:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE if mode == 'pipe' else subprocess.DEVNULL,
                                stderr=err)
        byte_count = 0
        if mode == 'pipe':
            buffer = bytearray(1024**2)
            while size := proc.stdout.readinto(buffer):
                byte_count += size
            proc.stdout.close()
        status = proc.wait(timeout=600)
    seconds = time.monotonic() - started
    parent_seconds = time.process_time() - parent_before
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    after = snapshot()
    assert status == 0, f'Archive failed: {label}; see stderr'
    assert payload.stat().st_size == payload_bytes
    fsync_seconds = None
    verification_seconds = None
    if mode != 'pipe':
        byte_count = target.stat().st_size
        flush_started = time.monotonic()
        with target.open('rb') as archive:
            os.fsync(archive.fileno())
        fsync_seconds = time.monotonic() - flush_started
        verification_started = time.monotonic()
        with (out / f'{label}.verify.stderr').open('wb') as err:
            extract = subprocess.Popen(['tar', '-xOf', str(target), '--use-compress-program', 'unzstd', 'cache-file'],
                                       stdout=subprocess.PIPE, stderr=err)
            actual_hash, actual_bytes = payload_digest(extract.stdout)
            extract.stdout.close()
            assert extract.wait(timeout=600) == 0
        assert actual_hash == expected_hash and actual_bytes == payload_bytes, f'Round-trip mismatch: {label}'
        verification_seconds = time.monotonic() - verification_started
        target.unlink()
    assert payload_bytes <= byte_count <= payload_bytes * 1.02 + 1024**2, f'Short/unexpected archive: {label}: {byte_count}'
    row = {'mode': mode, 'repetition': repetition, 'clean_input': clean,
           'archive_seconds': seconds, 'archive_bytes': byte_count,
           'output_fsync_seconds': fsync_seconds, 'verification_seconds': verification_seconds,
           'verification': 'payload_sha256_matches' if mode != 'pipe' else 'full_compressed_stream_counted_and_tar_succeeded',
           'prepare_sync_and_warm_seconds': preparation, 'command': argv,
           'child_user_cpu_seconds': usage_after.ru_utime - usage_before.ru_utime,
           'child_system_cpu_seconds': usage_after.ru_stime - usage_before.ru_stime,
           'child_inblock': usage_after.ru_inblock - usage_before.ru_inblock,
           'child_oublock': usage_after.ru_oublock - usage_before.ru_oublock,
           'parent_cpu_seconds': parent_seconds, 'before': before, 'after': after}
    rows.append(row)
    with (out / 'trials.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps({k: v for k, v in row.items() if k not in ('before', 'after', 'command')}), flush=True)


trial('disk', 0, False)
modes = ['disk', 'ram', 'pipe']
for repetition in range(1, args.repetitions + 1):
    offset = (sample + repetition - 2) % 3
    for mode in modes[offset:] + modes[:offset]:
        trial(mode, repetition, True)
assert len(rows) == args.repetitions * 3 + 1
result = {'host': host, 'input_sha256': expected_hash, 'trials': rows}
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
payload.unlink()
(work / 'manifest.txt').unlink()
print('PASS: real disk/tmpfs outputs round-trip; pipe consumed a complete compressed stream.', flush=True)
