"""Compare guest disk settings with complete write/archive/flush accounting."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--work-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--mib', type=int, default=4096)
parser.add_argument('--variants', nargs='+', choices=['baseline', 'scheduler_none', 'requests_1m', 'writeback_256m'],
                    default=['scheduler_none', 'requests_1m', 'writeback_256m'])
args = parser.parse_args()
work, out = args.work_dir.resolve(), args.output_dir.resolve()
assert work != out and args.mib > 0
work.mkdir(parents=True, exist_ok=True)
out.mkdir(parents=True, exist_ok=True)
sample = int(os.environ.get('DISK_SAMPLE', '1'))
variants = [v for v in args.variants if v != 'baseline']
offset = (sample - 1) % len(variants) if variants else 0
variants = variants[offset:] + variants[:offset]
sequence = ['baseline', *variants, 'baseline'] if variants else ['baseline']
size = args.mib * 1024**2
assert shutil.disk_usage(work).free > size * (len(sequence) + 1) + 512 * 1024**2
payload = work / 'cache-file'


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def command(*argv):
    return subprocess.check_output(argv, text=True).strip()


def digest(stream):
    h = hashlib.sha256()
    count = 0
    while chunk := stream.read(1024**2):
        h.update(chunk)
        count += len(chunk)
    return h.hexdigest(), count


def provider():
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            values = (p / 'cmdline').read_bytes().decode().split('\0')
        except (OSError, UnicodeError):
            continue
        if values and 'celesto-ci-cache-proxy' in values[0] and '--host-provider' in values:
            value = values[values.index('--host-provider') + 1]
            return value if value in ('aws', 'ovh') else 'unknown'
    return 'unknown'


def snapshot():
    return {'utc': time.time(), 'monotonic': time.monotonic(),
            'diskstats': read('/proc/diskstats'), 'meminfo': read('/proc/meminfo'),
            'cpu': read('/proc/stat').splitlines()[0],
            'io_pressure': read('/proc/pressure/io'), 'cpu_stat': read('/sys/fs/cgroup/cpu.stat')}


dev = os.stat(work).st_dev
device = Path(f'/sys/dev/block/{os.major(dev)}:{os.minor(dev)}').resolve()
while device != device.parent and not (device / 'queue').exists():
    device = device.parent
queue = device / 'queue' if (device / 'queue').exists() else None
assert queue is not None or not variants, 'Guest root filesystem did not resolve to a block device'
sysctl = Path('/proc/sys/vm')


def settings():
    scheduler = read(queue / 'scheduler') if queue else None
    selected = scheduler.split('[')[1].split(']')[0] if scheduler and '[' in scheduler else scheduler
    return {'scheduler': selected,
            'max_sectors_kb': read(queue / 'max_sectors_kb') if queue else None,
            **{key: read(sysctl / key) for key in ('dirty_background_bytes', 'dirty_background_ratio', 'dirty_bytes', 'dirty_ratio')}}


original = settings()


def write(path, value):
    if read(path) == str(value):
        return
    subprocess.run(['sudo', '-n', 'tee', str(path)], input=str(value) + '\n',
                   text=True, stdout=subprocess.DEVNULL, check=True)
    observed = read(path)
    if path.name == 'scheduler':
        assert f'[{value}]' in observed, f'Scheduler not applied: {observed}'
    else:
        assert observed == str(value), f'Setting not applied: {path}: {observed}'


def restore():
    if queue:
        write(queue / 'scheduler', original['scheduler'])
        write(queue / 'max_sectors_kb', original['max_sectors_kb'])
    for prefix in ('dirty_background', 'dirty'):
        key = prefix + '_bytes' if int(original[prefix + '_bytes']) else prefix + '_ratio'
        write(sysctl / key, original[key])
    assert settings() == original, 'Original settings were not restored'


def apply(variant):
    restore()
    if variant == 'scheduler_none':
        write(queue / 'scheduler', 'none')
    elif variant == 'requests_1m':
        write(queue / 'max_sectors_kb', min(1024, int(original['max_sectors_kb'])))
    elif variant == 'writeback_256m':
        write(sysctl / 'dirty_background_bytes', 64 * 1024**2)
        write(sysctl / 'dirty_bytes', 256 * 1024**2)


filesystem = json.loads(command('findmnt', '-J', '-T', str(work), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'))['filesystems'][0]
assert filesystem['fstype'] != 'tmpfs', 'Disk test is RAM-backed'
host = {'sample': sample, 'provider': provider(), 'runner': os.environ.get('RUNNER_NAME'),
        'run_url': f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'local')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'smoke')}",
        'cpu': command('lscpu'), 'kernel': command('uname', '-r'),
        'tar': command('tar', '--version'), 'zstd': command('zstd', '--version'),
        'device': device.name if queue else None, 'filesystem': filesystem,
        'macs': {p.parent.name: p.read_text().strip() for p in Path('/sys/class/net').glob('*/address') if p.parent.name != 'lo'},
        'original_settings': original, 'sequence': sequence, 'payload_bytes': size}
(out / 'host.json').write_text(json.dumps(host, indent=2) + '\n')
with payload.open('wb') as target:
    subprocess.run(['head', '-c', str(size), '/dev/urandom'], stdout=target, check=True)
with payload.open('rb') as source:
    expected, count = digest(source)
assert count == size
(work / 'manifest.txt').write_text('cache-file\n')
rows = []
try:
    for index, variant in enumerate(sequence):
        os.sync()
        apply(variant)
        with payload.open('rb') as source:
            actual, count = digest(source)
        assert actual == expected and count == size
        target = work / f'archive-{index}.tzst'
        assert not target.exists()
        before = snapshot()
        began = time.monotonic()
        fd = os.open(payload, os.O_RDWR)
        try:
            for offset in range(0, size, 4 * 1024**2):
                wanted = min(4 * 1024**2, size - offset)
                data = os.pread(fd, wanted, offset)
                assert len(data) == wanted and os.pwrite(fd, data, offset) == wanted
            rewritten = time.monotonic()
            after_input = snapshot()
            argv = ['tar', '--posix', '-cf', str(target), '-P', '-C', str(work),
                    '--files-from', str(work / 'manifest.txt'), '--use-compress-program', 'zstdmt']
            with (out / f'{index}-{variant}.stderr').open('wb') as stderr:
                subprocess.run(argv, stderr=stderr, check=True, timeout=600)
            archived = time.monotonic()
            after_archive = snapshot()
            with target.open('rb') as archive:
                os.fsync(archive.fileno())
            output_flushed = time.monotonic()
            os.fsync(fd)
            flushed = time.monotonic()
            after_flush = snapshot()
        finally:
            os.close(fd)
        assert size <= target.stat().st_size <= size * 1.02 + 1024**2
        with (out / f'{index}-{variant}.verify.stderr').open('wb') as stderr:
            proc = subprocess.Popen(['tar', '-xOf', str(target), '--use-compress-program', 'unzstd', 'cache-file'],
                                    stdout=subprocess.PIPE, stderr=stderr)
            actual, count = digest(proc.stdout)
            proc.stdout.close()
            assert proc.wait(timeout=600) == 0 and actual == expected and count == size
        row = {'index': index, 'variant': variant, 'settings': settings(),
               'input_write_seconds': rewritten - began, 'archive_seconds': archived - rewritten,
               'ready_for_upload_seconds': archived - began,
               'archive_fsync_seconds': output_flushed - archived,
               'input_fsync_seconds': flushed - output_flushed,
               'durable_total_seconds': flushed - began,
               'archive_bytes': target.stat().st_size, 'roundtrip_sha256_matches': True,
               'before': before, 'after_input': after_input, 'after_archive': after_archive, 'after_flush': after_flush}
        rows.append(row)
        with (out / 'trials.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n')
        print(json.dumps({k: v for k, v in row.items() if k not in ('before', 'after_input', 'after_archive', 'after_flush')}), flush=True)
        # Keep extents allocated but release clean output cache before the next trial.
        with target.open('rb') as archive:
            os.posix_fadvise(archive.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
finally:
    restore()
    (out / 'restored-settings.json').write_text(json.dumps(settings(), indent=2) + '\n')
assert len(rows) == len(sequence)
(out / 'result.json').write_text(json.dumps({'host': host, 'input_sha256': expected, 'trials': rows,
                                           'settings_restored': True}, indent=2) + '\n')
for path in work.glob('archive-*.tzst'):
    path.unlink()
payload.unlink()
(work / 'manifest.txt').unlink()
print('PASS: disk-only trials verified; guest settings restored.', flush=True)
