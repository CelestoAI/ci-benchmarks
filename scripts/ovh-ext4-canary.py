"""One disposable CI guest: compare lazytime/preallocation, keeping archives on disk."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUT = Path('/dev/shm/cache-native-profile')
PLAN = ['baseline', 'combined', 'combined', 'baseline', 'combined', 'baseline']
PREALLOCATOR = '''import ctypes,json,os,stat,subprocess,time
from pathlib import Path
before=os.fstat(1);assert stat.S_ISREG(before.st_mode),"Compressor stdout must be the real archive file"
expected=os.stat(os.environ['PREALLOC_ARCHIVE']);assert (before.st_dev,before.st_ino)==(expected.st_dev,expected.st_ino)
libc=ctypes.CDLL(None,use_errno=True);fn=libc.fallocate;fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_longlong];fn.restype=ctypes.c_int
n=int(os.environ['PREALLOC_BYTES']);start=time.monotonic();rc=fn(1,0,0,n);duration=time.monotonic()-start
if rc!=0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
after=os.fstat(1);assert before.st_size==0 and after.st_size==n;assert after.st_blocks*512>=n
rc=subprocess.run(['zstdmt']).returncode
if rc:raise SystemExit(rc)
actual_bytes=os.lseek(1,0,os.SEEK_CUR);stream_size=os.fstat(1).st_size;assert 0<actual_bytes<n and stream_size==n
t=time.monotonic();os.ftruncate(1,actual_bytes);truncate_seconds=time.monotonic()-t
assert os.fstat(1).st_size==actual_bytes
Path(os.environ['PREALLOC_EVIDENCE']).write_text(json.dumps({'seconds':duration,'requested_bytes':n,'allocated_bytes':after.st_blocks*512,'logical_size_before':before.st_size,'preallocated_size':after.st_size,'device':after.st_dev,'fixed_size_during_stream':stream_size==n,'actual_written_bytes':actual_bytes,'truncate_seconds':truncate_seconds,'final_size':os.fstat(1).st_size}))
'''


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def root_mount():
    return json.loads(command('findmnt', '-J', '-T', '/', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'))['filesystems'][0]


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def load():
    c = json.loads((OUT / 'ext4-control.json').read_text())
    p = Path(c['work'])
    assert p.parent == Path.cwd() and p.name.startswith('ovh-ext4-canary-')
    assert json.loads((p / 'owner.json').read_text()) == c['identity']
    return c, p


def set_lazytime(c, enabled):
    original = c['mount']
    options = [x for x in original['options'].split(',') if x not in ['lazytime', 'nolazytime']]
    subprocess.run(['mount', '-o', 'remount,' + ','.join(options) + ',' +
                    ('lazytime' if enabled else 'nolazytime'), '/'], check=True, capture_output=True)
    actual = root_mount()
    assert actual['source'] == original['source'] and actual['fstype'] == 'ext4'
    flags = set(actual['options'].split(','))
    assert ('lazytime' in flags) == enabled
    assert flags - {'lazytime', 'nolazytime'} == set(options), 'Unrelated mount flags changed'
    return actual


def snapshot():
    result = {n: read('/proc/' + n) for n in ['stat', 'diskstats', 'meminfo']}
    result['jbd2'] = {str(p): read(p) for p in Path('/proc/fs/jbd2').glob('*/info')}
    result['ext4_options'] = {str(p): read(p) for p in Path('/proc/fs/ext4').glob('*/options')}
    return result


def digest(stream):
    h = hashlib.sha256()
    size = 0
    while chunk := stream.read(4 * 1024**2):
        h.update(chunk)
        size += len(chunk)
    return h.hexdigest(), size


def flush(path):
    t = time.monotonic()
    with path.open('rb') as f:
        os.fsync(f.fileno())
    return time.monotonic() - t


def workload(name, variant, size):
    c, work = load()
    case = OUT / name
    case.mkdir()
    source, archive = work / 'cache-file', work / 'cache.tzst'
    assert not source.exists() and not archive.exists()
    lazy = variant in ['lazytime', 'combined']
    preallocate = variant in ['preallocate', 'combined']
    try:
        mounted = set_lazytime(c, lazy)
        start = time.monotonic()
        os.sync()
        initial_sync = time.monotonic() - start
        before = snapshot()
        env = dict(os.environ, PREALLOC_BYTES=str(size + 16 * 1024**2),
                   PREALLOC_ARCHIVE=str(archive), PREALLOC_EVIDENCE=str(case / 'preallocation.json'))
        program = 'python3 ' + str(OUT / 'preallocate-writer.py') if preallocate else 'zstdmt'
        argv = ['/usr/bin/time', '-v', '-o', str(case / 'archive-resources.txt'),
                'tar', '--posix', '-cf', str(archive), '--exclude', 'cache.tzst', '-P',
                '-C', str(work), '--files-from', str(work / 'manifest.txt'),
                '--use-compress-program', program]
        generation_start_utc = time.time()
        started = time.monotonic()
        with source.open('wb') as f:
            subprocess.run(['head', '-c', str(size), '/dev/urandom'], stdout=f, check=True)
        generation = time.monotonic() - started
        archive_start = time.time()
        t = time.monotonic()
        assert source.stat().st_size == size
        manifest_start = time.monotonic()
        (work / 'manifest.txt').write_text('cache-file\n')
        manifest_seconds = time.monotonic() - manifest_start
        subprocess.run(argv, check=True, capture_output=True, env=env)
        archive_seconds = time.monotonic() - t
        archive_end = time.time()
        archive_fsync_start_utc = time.time()
        archive_fsync = flush(archive)
        source_fsync_start_utc = time.time()
        source_fsync = flush(source)
        total = time.monotonic() - started
        flush_end_utc = time.time()
        outside_phases = total - generation - archive_seconds - archive_fsync - source_fsync
        # Detailed proc snapshots occur only before generation and after both
        # flushes; no diagnostic reads are interposed in the measured pipeline.
        after_flush = snapshot()
        archive_bytes = archive.stat().st_size
        assert size < archive_bytes < size * 1.01 + 65536
        if preallocate:
            allocation = json.loads((case / 'preallocation.json').read_text())
            assert allocation['device'] == archive.stat().st_dev and allocation['fixed_size_during_stream']
            assert allocation['actual_written_bytes'] == allocation['final_size'] == archive_bytes
        with source.open('rb') as f:
            expected, original_bytes = digest(f)
        p = subprocess.Popen(['tar', '-xOf', str(archive), '--use-compress-program', 'unzstd',
                              'cache-file'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        actual, restored_bytes = digest(p.stdout)
        err = p.stderr.read()
        assert p.wait(timeout=30) == 0, err
        assert expected == actual and original_bytes == restored_bytes == size
        result = {'name': name, 'variant': variant, 'source_bytes': size, 'mount': mounted,
                  'initial_sync_seconds': initial_sync, 'generation_seconds': generation,
                  'generation_start_utc': generation_start_utc,
                  'archive_seconds': archive_seconds, 'archive_start_utc': archive_start,
                  'archive_end_utc': archive_end, 'archive_bytes': archive_bytes,
                  'manifest_seconds': manifest_seconds,
                  'archive_fsync_start_utc': archive_fsync_start_utc,
                  'source_fsync_start_utc': source_fsync_start_utc, 'flush_end_utc': flush_end_utc,
                  'archive_fsync_seconds': archive_fsync, 'source_fsync_seconds': source_fsync,
                  'generation_archive_flush_seconds': total,
                  'outside_phase_seconds': outside_phases,
                  'archive_plus_flush_seconds': archive_seconds + archive_fsync,
                  'sha256': expected, 'restored_sha256': actual, 'restored_bytes': restored_bytes,
                  'archive_device': archive.stat().st_dev, 'metadata_device': case.stat().st_dev,
                  'tar_resources': (case / 'archive-resources.txt').read_text(),
                  'before': before, 'after_flush': after_flush,
                  'clock_contract': 'Manifest preparation inside archive time; detailed snapshots outside generation/archive/flush pipeline'}
        assert result['archive_device'] == c['archive_device'] != result['metadata_device']
        (case / 'result.json').write_text(json.dumps(result, indent=2))
        print('VERIFIED', json.dumps({k: result[k] for k in ['name', 'variant',
              'generation_seconds', 'archive_seconds', 'archive_fsync_seconds',
              'generation_archive_flush_seconds']}), flush=True)
    finally:
        for p in [source, archive]:
            p.unlink(missing_ok=True)
        os.sync()
        set_lazytime(c, 'lazytime' in c['mount']['options'].split(','))


def prepare():
    identity = json.loads((OUT / 'identity.json').read_text())
    assert identity['ip'] == '15.204.216.188' and os.cpu_count() == 4
    mounted = root_mount()
    assert mounted['target'] == '/' and mounted['fstype'] == 'ext4'
    flags = set(mounted['options'].split(','))
    assert 'lazytime' not in flags, 'Current baseline already has lazytime'
    assert not flags.intersection({'nobarrier', 'data=writeback', 'data=journal'})
    assert shutil.disk_usage(Path.cwd()).free > 12 * 1024**3
    work = Path(tempfile.mkdtemp(prefix='ovh-ext4-canary-', dir=Path.cwd()))
    (work / 'owner.json').write_text(json.dumps(identity))
    c = {'identity': identity, 'mount': mounted, 'work': str(work), 'archive_device': work.stat().st_dev,
         'cpus': os.cpu_count(), 'kernel': os.uname().release, 'cpu': command('lscpu'),
         'memory': read('/proc/meminfo'), 'superblock': command('tune2fs', '-l', mounted['source']),
         'dirty_settings': {str(p): read(p) for p in Path('/proc/sys/vm').glob('dirty*')},
         'plan': PLAN, 'archive_command_matches': 'GNU tar --posix -cf ... --use-compress-program zstdmt',
         'limits': ['Archive workload only; no upload/reservation in timing',
                    'Explicit fsync is a separate diagnostic, outside normal archive time',
                    'Preallocation wrapper cost is inside archive time; 16MiB size headroom',
                    'One VM with existing neighbors; interleaved variants and repeated baselines']}
    write('ext4-control.json', c)
    (OUT / 'preallocate-writer.py').write_text(PREALLOCATOR)
    for i, variant in enumerate(['baseline', 'combined'], 1):
        workload('smoke-' + str(i), variant, 16 * 1024**2)
    write('smoke-verified.json', {'two_variants_sha256_verified': True})


def cleanup():
    if not (OUT / 'ext4-control.json').exists():
        return
    c, work = load()
    actual = set_lazytime(c, 'lazytime' in c['mount']['options'].split(','))
    assert actual == c['mount']
    shutil.rmtree(work)
    write('ext4-cleanup.json', {'guest_mount_restored': True, 'owned_scratch_removed': True,
                              'host_settings_changed': False, 'mount': actual})


if __name__ == '__main__':
    assert os.geteuid() == 0, 'Run inside the disposable guest using sudo'
    def interrupted(*_):
        raise KeyboardInterrupt('Disposable VM diagnostic interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    mode = sys.argv[1]
    if mode == 'prepare':
        prepare()
    elif mode == 'trial':
        n = int(sys.argv[2])
        assert 1 <= n <= len(PLAN) and (OUT / 'smoke-verified.json').exists()
        workload(f'trial-{n:02d}', PLAN[n - 1], 4 * 1024**3)
    elif mode == 'cleanup':
        cleanup()
    else:
        raise ValueError(mode)
