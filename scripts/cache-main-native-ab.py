"""One-VM, full actions/cache save/restore comparison; no secrets in receipts."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time

PIN = '55cc8345863c7cc4c66a329aec7e433d2d1c52a9'
ROOT = Path('/tmp/cache-main-native-ab-' + os.environ.get('GITHUB_RUN_ID', 'local') + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
SCRIPTS = {'save': 'save-only', 'restore': 'restore-only'}

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(chunk)
    return h.hexdigest()

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')

def root_call(mode, value):
    result = subprocess.run(['sudo', '-n', 'python3', str(Path(__file__).resolve()), mode], input=json.dumps(value), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Owned guest operation failed: ' + mode)
    return json.loads(result.stdout)

def proc_start(pid):
    return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]

def privileged(mode):
    value = json.load(sys.stdin)
    if mode == 'root-inspect':
        proxies = []
        workers = []
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():
                continue
            try:
                exe = os.readlink(p / 'exe').removesuffix(' (deleted)')
                if Path(exe).name == 'celesto-ci-cache-proxy':
                    argv = (p / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
                    proxies.append({'pid': int(p.name), 'start': proc_start(int(p.name)), 'args': [x.decode() for x in argv[1:]], 'binary_sha256': digest(p / 'exe')})
                if Path(exe).name == 'Runner.Worker':
                    workers.append(str(Path(exe).parent.parent))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        if len(proxies) != 1 or len(set(workers)) != 1:
            raise RuntimeError('Expected one CI worker and cache proxy')
        computer = None
        ticket = Path('/run/celesto-cache-entitlement')
        if ticket.exists():
            part = ticket.read_text().strip().split('.')[1]
            claimed = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))).get('sub')
            if isinstance(claimed, str) and re.fullmatch(r'cmp_[a-z0-9]+', claimed):
                computer = claimed
        print(json.dumps({**proxies[0], 'runner_root': workers[0], 'computer_id': computer}))
    elif mode == 'root-stop':
        pid = value['pid']
        if Path('/proc', str(pid)).exists():
            if proc_start(pid) != value['start']:
                raise RuntimeError('PID was reused; refusing to stop it')
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not Path('/proc', str(pid)).exists():
                    break
                stat = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[0]
                if stat == 'Z':
                    break
                time.sleep(.05)
            else:
                os.kill(pid, signal.SIGKILL)
        print('{}')
    elif mode == 'root-start':
        args = value['args']
        if '--listen' not in args or '--api-url' not in args:
            raise RuntimeError('Missing actual cache endpoint arguments')
        log = open(value['log'], 'ab')
        p = subprocess.Popen([value['binary'], *args], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root'})
        time.sleep(.1)
        print(json.dumps({'pid': p.pid, 'start': proc_start(p.pid)}))
    elif mode == 'root-proxy-proof':
        role, pair = value['role'], int(value['pair'])
        if role not in ['main', 'candidate'] or pair not in [1, 2, 3]:
            raise RuntimeError('Invalid case')
        text = (ROOT / 'private' / f'proxy-{pair}-{role}.log').read_text()
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        print(json.dumps({'create_seen': 'CreateCacheEntry' in text, 'finalize_seen': 'FinalizeCacheEntryUpload' in text, 'lookup_seen': 'GetCacheEntryDownloadURL' in text, 'download_seen': 'serving cache hit in ranges' in text, 'entry_ids': sorted(set(re.findall(r'entry_id[= ]+(\d+)', text)))}))
    elif mode == 'root-install-helper':
        subprocess.run(['install', '-m', '0755', value['binary'], value['destination']], check=True)
        print('{}')
    else:
        raise RuntimeError('Unknown privileged operation')

def action_path(action):
    return Path(os.environ['RUNNER_TEMP']).parent / '_actions/actions/cache' / PIN / 'dist' / SCRIPTS[action] / 'index.js'

def setup():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    (ROOT / 'private').mkdir(mode=0o700, exist_ok=True)
    (ROOT / 'results').mkdir(exist_ok=True)
    url = os.environ.pop('CACHE_AB_INPUT_URL')
    import urllib.request
    with urllib.request.urlopen(url, timeout=90) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != os.environ['CACHE_AB_INPUT_SHA256']:
        raise RuntimeError('Input checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        archive.extractall(ROOT / 'private', filter='data')
    del raw, url
    runtime = root_call('root-inspect', {})
    # Arguments contain endpoint locations only; credentials stay in their original protected files.
    if any('token=' in a.lower() or 'secret=' in a.lower() for a in runtime['args']):
        raise RuntimeError('Unexpected credential argument')
    write(ROOT / 'private/runtime.json', runtime)
    public = {'computer_id': runtime['computer_id'], 'runner_worker_sha256': digest(Path(runtime['runner_root']) / 'bin/Runner.Worker.dll'), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'hostname': socket.gethostname(), 'cpus': os.cpu_count(), 'memory': [x for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemTotal:')], 'root_disk_device': str(Path('/sys/class/block/vda/device').resolve()), 'refs': json.loads((ROOT / 'private/refs.json').read_text())}
    write(ROOT / 'results/machine.json', public)
    worker = (Path(runtime['runner_root']) / 'bin/Runner.Worker.dll').read_bytes()
    if b'CelestoResultsUrl' not in worker or b'CelestoCacheTransfer' in worker:
        raise RuntimeError('Published runner is not a compatible common main runner')
    originals = ROOT / 'private/originals'
    originals.mkdir(exist_ok=True)
    for action in SCRIPTS:
        p = action_path(action)
        if digest(p) != public['refs']['official_' + action + '_sha256']:
            raise RuntimeError('Downloaded action does not match the pinned source')
        shutil.copy2(p, originals / (action + '.js'))
    subprocess.run(['sudo', '-n', 'apt-get', 'update', '-qq'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['sudo', '-n', 'apt-get', 'install', '-y', '-qq', '--no-install-recommends', 'musl-tools'], check=True, stdout=subprocess.DEVNULL)
    os.environ['PATH'] = str(Path.home() / '.cargo/bin') + ':' + os.environ.get('PATH', '')
    with open(ROOT / 'private/toolchain.log', 'w') as log:
        if not shutil.which('rustup'):
            import urllib.request
            installer = ROOT / 'private/rustup-init.sh'
            with urllib.request.urlopen('https://sh.rustup.rs', timeout=60) as response:
                installer.write_bytes(response.read())
            subprocess.run(['sh', str(installer), '-y', '--profile', 'minimal', '--no-modify-path'], check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(['rustup', 'toolchain', 'install', 'stable', '--profile', 'minimal'], check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(['rustup', 'default', 'stable'], check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(['rustup', 'target', 'add', 'x86_64-unknown-linux-musl'], check=True, stdout=log, stderr=subprocess.STDOUT)
    public['rustc'] = subprocess.check_output(['rustc', '--version'], text=True).strip()
    write(ROOT / 'results/machine.json', public)
    if subprocess.run(['sudo', '-n', 'docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        with open(ROOT / 'private/docker.log', 'ab') as log:
            subprocess.Popen(['sudo', '-n', 'dockerd'], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(60):
            if subprocess.run(['sudo', '-n', 'docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Owned VM Docker daemon did not become ready')
    subprocess.run(['sudo', '-n', 'docker', 'pull', 'mcr.microsoft.com/dotnet/sdk:8.0'], check=True, stdout=subprocess.DEVNULL)
    for role in ['main', 'candidate']:
        source = ROOT / 'private' / role
        guest = source / 'guest'
        guest.mkdir(exist_ok=True)
        with tarfile.open(source / 'guest-source.tar') as archive:
            archive.extractall(guest, filter='data')
        build_env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ['TOKEN', 'SECRET', 'PASSWORD'])}
        build_env['PATH'] = str(Path.home() / '.cargo/bin') + ':' + build_env.get('PATH', '')
        with open(ROOT / 'private' / (role + '-rust.log'), 'w') as log:
            result = subprocess.run(['cargo', 'build', '--locked', '--release', '--target', 'x86_64-unknown-linux-musl', '--manifest-path', str(guest / 'dataplane/guest/Cargo.toml'), '--bin', 'celesto-ci-cache-proxy'], env=build_env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('Private Rust build failed for ' + role)
        with open(ROOT / 'private' / (role + '-prepare-build.log'), 'w') as log:
            result = subprocess.run(['sudo', '-n', 'docker', 'run', '--rm', '-v', str(ROOT) + ':/ab', '-w', '/ab/private/' + role, 'mcr.microsoft.com/dotnet/sdk:8.0', 'dotnet', 'build', 'Prepare.csproj', '-o', '/ab/private/build/' + role, '-v', 'quiet'], stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('Private preparation build failed for ' + role)
    binaries = {role: digest(ROOT / 'private' / role / 'guest/dataplane/guest/target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy') for role in ['main', 'candidate']}
    write(ROOT / 'results/binaries.json', binaries)
    print('Built both exact cache revisions; private build logs are not uploaded.')

def select(role, pair):
    runtime = json.loads((ROOT / 'private/runtime.json').read_text())
    current_path = ROOT / 'private/current-proxy.json'
    current = json.loads(current_path.read_text()) if current_path.exists() else runtime
    root_call('root-stop', current)
    binary = ROOT / 'private' / role / 'guest/dataplane/guest/target/x86_64-unknown-linux-musl/release/celesto-ci-cache-proxy'
    if role == 'candidate':
        root_call('root-install-helper', {'binary': str(binary), 'destination': str(Path(runtime['runner_root']) / 'externals/celesto-ci-cache-download')})
    running = root_call('root-start', {'binary': str(binary), 'args': runtime['args'], 'log': str(ROOT / 'private' / f'proxy-{pair}-{role}.log')})
    write(current_path, running)
    listen = runtime['args'][runtime['args'].index('--listen') + 1]
    host, port = listen.rsplit(':', 1)
    for _ in range(100):
        try:
            with socket.create_connection((host, int(port)), timeout=.2):
                break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Owned cache proxy failed readiness')
    prep = []
    for action in SCRIPTS:
        target = action_path(action)
        shutil.copy2(ROOT / 'private/originals' / (action + '.js'), target)
        output = target.parent / ('.bench-' + role + '-' + action + '.js')
        command = ['sudo', '-n', 'docker', 'run', '--rm', '--network', 'none', '-v', str(ROOT) + ':/ab', '-v', str(target.parent) + ':/action', 'mcr.microsoft.com/dotnet/sdk:8.0', 'dotnet', '/ab/private/build/' + role + '/Prepare.dll', '/action/index.js', '/action/' + output.name]
        before = time.monotonic()
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Source preparation failed')
        receipt = json.loads(result.stdout.strip().splitlines()[-1])
        if role == 'candidate' and not receipt['prepared']:
            raise RuntimeError('Candidate action was not recognized')
        shutil.copyfile(output, target)
        output.unlink()
        prep.append({'action': action, 'seconds': time.monotonic() - before, **receipt})
    machine = json.loads((ROOT / 'results/machine.json').read_text())
    if machine['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise RuntimeError('VM boot changed')
    write(ROOT / 'results' / f'prepared-{pair}-{role}.json', {'profile': role, 'pair': pair, 'proxy_binary_sha256': digest(binary), 'preparation': prep, 'boot_id': machine['boot_id']})
    print('Selected ' + role + ' cache components on the same CI VM.')

def generate(pair):
    before = time.monotonic()
    with open('cache-file', 'wb') as output, open('/dev/urandom', 'rb') as source:
        remaining = 4 * 1024**3
        while remaining:
            chunk = source.read(min(8 * 1024**2, remaining))
            output.write(chunk)
            remaining -= len(chunk)
    generation = time.monotonic() - before
    before = time.monotonic()
    sha = digest('cache-file')
    write(ROOT / 'results' / f'payload-{pair}.json', {'bytes': Path('cache-file').stat().st_size, 'sha256': sha, 'generation_seconds': generation, 'hash_seconds': time.monotonic() - before})
    print('Generated fresh 4 GiB input for pair ' + str(pair))

def verify(role, pair):
    before = time.monotonic()
    expected = json.loads((ROOT / 'results' / f'payload-{pair}.json').read_text())
    if Path('cache-file').stat().st_size != expected['bytes'] or digest('cache-file') != expected['sha256']:
        raise RuntimeError('Restored file failed size/SHA-256 verification')
    proxy_proof = root_call('root-proxy-proof', {'role': role, 'pair': pair})
    if not all(proxy_proof[k] for k in ['create_seen', 'finalize_seen', 'lookup_seen', 'download_seen']):
        raise RuntimeError('Real Celesto cache proxy roundtrip was not confirmed')
    write(ROOT / 'results' / f'proxy-proof-{pair}-{role}.json', proxy_proof)
    write(ROOT / 'results' / f'verified-{pair}-{role}.json', {'profile': role, 'pair': pair, 'bytes': expected['bytes'], 'sha256': expected['sha256'], 'hash_seconds': time.monotonic() - before, 'verified': True})
    print('Verified complete restored bytes for ' + role + ' pair ' + str(pair))

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode.startswith('root-'):
        privileged(mode)
    else:
        try:
            if mode == 'setup': setup()
            elif mode == 'select': select(sys.argv[2], int(sys.argv[3]))
            elif mode == 'generate': generate(int(sys.argv[2]))
            elif mode == 'verify': verify(sys.argv[2], int(sys.argv[3]))
            else: raise RuntimeError('Unknown benchmark command')
        except Exception as error:
            # Do not publish private source, URLs, credentials or raw build logs.
            print('Benchmark stopped: ' + type(error).__name__ + ' (inspect the owned private setup logs).', file=sys.stderr)
            raise SystemExit(1)
