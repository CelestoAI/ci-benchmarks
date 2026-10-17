"""Real Docker workloads; monotonic timings and raw logs, never mock timings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
OUT = Path('docker-results')
OUT.mkdir(exist_ok=True)
IMAGES = json.loads((ROOT / 'images.json').read_text())
EVENTS = OUT / 'events.jsonl'

def emit(phase, **data):
    event = {'phase': phase, 'timestamp_ms': time.time_ns() // 1000000, 'data': data}
    with EVENTS.open('a') as f:
        f.write(json.dumps(event) + '\n')
    print('DOCKER_BENCH ' + json.dumps(event), flush=True)

def command(phase, args, *, cwd=None, env=None):
    started = time.monotonic()
    log = OUT / (phase + '.log')
    print('Running ' + phase, flush=True)
    with log.open('w') as f:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, text=True)
    output = log.read_text()
    emit(phase, seconds=time.monotonic() - started, exit_code=result.returncode,
         log=str(log), log_sha256=hashlib.sha256(output.encode()).hexdigest())
    print(output[-4000:], flush=True)
    if result.returncode:
        raise RuntimeError(f'{phase} failed: {result.returncode}')
    return output

def fingerprint():
    cpus = len(os.sched_getaffinity(0))
    memory = int(re.search(r'MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text()).group(1)) * 1024
    assert cpus == 4, f'Expected 4 CPUs, got {cpus}'
    assert 14 * 1024**3 <= memory <= 17 * 1024**3, f'Expected 16 GiB nominal RAM, got {memory}'
    model = re.search(r'model name\s*:\s*(.+)', Path('/proc/cpuinfo').read_text()).group(1)
    emit('host', cpus=cpus, memory_bytes=memory, cpu_model=model, kernel=platform.release(),
         os_release=Path('/etc/os-release').read_text(), disk_free_bytes=shutil.disk_usage('.').free,
         provider=os.environ['PROVIDER'], scenario=os.environ['SCENARIO'], backend=os.environ['BACKEND'],
         repetition=os.environ['REPETITION'], run_id=os.environ['GITHUB_RUN_ID'], commit=os.environ['GITHUB_SHA'],
         runner=os.environ['RUNNER_NAME'])
    version = command('docker-version', ['docker', 'version', '--format', '{{json .}}'])
    assert json.loads(version)['Server']['Version'] == '29.1.3'
    command('docker-info', ['docker', 'info'])
    command('buildx-version', ['docker', 'buildx', 'version'])
    command('compose-version', ['docker', 'compose', 'version'])

def context(app, scenario):
    target = Path('/tmp/docker-benchmark-context') / app
    shutil.copytree(ROOT / app, target)
    if app == 'node':
        source = target / 'src'
        source.mkdir()
        for i in range(800):
            (source / f'm{i}.ts').write_text(f'export function f{i}(x: number): number {{ return (x * {i+1} + {i}) % 1000003; }}\n')
        imports = '\n'.join(f'import {{ f{i} }} from "./m{i}";' for i in range(800))
        calls = ','.join(f'f{i}(42)' for i in range(800))
        (source / 'main.ts').write_text(imports + f'\nconst values = [{calls}];\nif (values.length !== 800) throw new Error("bad build");\nconsole.log(42);\n')
    if scenario == 'source':
        file = target / ('src/main.ts' if app == 'node' else 'app.py')
        with file.open('a') as f:
            f.write('\n' + ('console.log("source-change");' if app == 'node' else '# source-change') + '\n')
    if scenario == 'dependency':
        if app == 'node':
            for file in ['package.json', 'package-lock.json']:
                shutil.copyfile(target / 'dependency-change' / file, target / file)
        else:
            shutil.copyfile(target / 'requirements-dependency.txt', target / 'requirements.txt')
    # Build context includes only material actually copied by the Dockerfile.
    for extra in ['dependency-change', 'requirements-dependency.txt', 'requirements-dependency.in', 'requirements.in']:
        path = target / extra
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return target

def cache_options(app, scenario):
    backend = os.environ['BACKEND']
    namespace = os.environ['NAMESPACE']
    scope = f'{namespace}-{os.environ["PROVIDER"]}-{os.environ["REPETITION"]}-{app}'
    result = []
    if scenario == 'nocache':
        return ['--no-cache']
    if backend == 'registry':
        ref = 'ghcr.io/celestoai/ci-benchmarks-cache:' + scope
        if scenario != 'seed':
            result += ['--cache-from', 'type=registry,ref=' + ref]
        result += ['--cache-to', 'type=registry,ref=' + ref + ('' if scenario == 'seed' else '-' + scenario) + ',mode=max']
    else:
        if scenario != 'seed':
            result += ['--cache-from', 'type=gha,version=2,scope=' + scope]
        result += ['--cache-to', 'type=gha,version=2,scope=' + scope + ('' if scenario == 'seed' else '-' + scenario) + ',mode=max,timeout=120s']
    return result

def build(app, scenario, *, use_cache=True):
    ctx = context(app, scenario)
    args = ['docker', 'buildx', 'build', '--progress=plain', '--platform=linux/amd64', '--provenance=false',
            '--load', '--tag', f'bench-{app}:run', '--build-arg', 'BASE=' + IMAGES[app]]
    if use_cache:
        args += cache_options(app, scenario)
    output = command(app + '-build', args + [str(ctx)])
    cached = len(re.findall(r'^#\d+ CACHED\s*$', output, re.M))
    emit(app + '-cache-observation', cached_steps=cached,
         importing_cache='importing cache manifest' in output,
         exporting_cache=('exporting cache' in output or 'exporting to GitHub Actions Cache' in output))
    if use_cache and scenario in ['unchanged', 'source']:
        assert cached >= 2, f'{app}: expected reusable dependency layers, saw {cached} cached steps'
    check = ['docker', 'run', '--rm', f'bench-{app}:run']
    if app == 'python':
        check += ['python', 'app.py', '--self-test']
    assert command(app + '-verify', check).splitlines()[0] == '42'

def integration():
    key = 'YmVuY2htYXJrLXNtb2tlLWtleS1ub3QtYS1zZWNyZXQ='
    compose = {
        'services': {
            'postgres': {'image': IMAGES['postgres'], 'environment': {'POSTGRES_PASSWORD': 'benchmark-only'},
                         'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U postgres'], 'interval': '1s', 'timeout': '3s', 'retries': 60}},
            'azurite': {'image': IMAGES['azurite'], 'environment': {'AZURITE_ACCOUNTS': 'benchmark:' + key},
                        'command': 'azurite --blobHost 0.0.0.0 --queueHost 0.0.0.0 --tableHost 0.0.0.0 --skipApiVersionCheck'},
            'api': {'image': 'bench-python:run', 'ports': ['8080:8080'],
                    'environment': {'DATABASE_URL': 'postgresql://postgres:benchmark-only@postgres/postgres', 'AZURITE_KEY': key},
                    'depends_on': {'postgres': {'condition': 'service_healthy'}, 'azurite': {'condition': 'service_started'}}}
        }
    }
    path = OUT / 'compose.json'
    path.write_text(json.dumps(compose, indent=2))
    prefix = ['docker', 'compose', '-p', 'benchmark', '-f', str(path)]
    try:
        command('compose-up', prefix + ['up', '-d', '--wait', '--wait-timeout', '120'])
        started = time.monotonic()
        deadline = started + 60
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2) as response:
                    assert json.load(response) == {'ready': True}
                break
            except (OSError, AssertionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        emit('api-ready', seconds=time.monotonic() - started)
        started = time.monotonic()
        for _ in range(5):
            with urllib.request.urlopen('http://127.0.0.1:8080/exercise', timeout=30) as response:
                assert json.load(response) == {'rows': 1000, 'sum': 499500, 'blob_bytes': 1048576}
        emit('integration-tests', seconds=time.monotonic() - started, rounds=5, assertions='SQL migration + 1000 inserts + aggregate + 1 MiB Azure blob roundtrip + API')
    finally:
        command('compose-logs', prefix + ['logs', '--no-color'])
        command('compose-down', prefix + ['down', '-v'])

def cpu():
    work = Path('/tmp/docker-benchmark-rust')
    shutil.copytree(ROOT / 'rust', work)
    args = ['docker', 'run', '--rm', '--cpus=4', '--memory=16g', '-v', f'{work}:/app', '-w', '/app',
            '-e', 'CARGO_HOME=/app/.cargo']
    command('rust-fetch', args + [IMAGES['rust'], 'cargo', 'fetch', '--locked'])
    output = command('rust-compile', args + ['--network=none', IMAGES['rust'], 'bash', '-ec',
        'TIMEFORMAT="COMPILE_TIME real=%R user=%U sys=%S"; time cargo build --frozen --release -j4; cat /sys/fs/cgroup/memory.peak; ./target/release/ci-compile-fixture --rows 1000'])
    timing = re.search(r'COMPILE_TIME real=([\d.]+) user=([\d.]+) sys=([\d.]+)', output)
    assert timing and '"matched":1000' in output
    emit('rust-cpu', compile_seconds=float(timing[1]), user_seconds=float(timing[2]), system_seconds=float(timing[3]))

def runtime():
    for name in ['postgres', 'azurite', 'python', 'rust']:
        existing = subprocess.run(['docker', 'image', 'inspect', IMAGES[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        emit(name + '-preexisting', present=existing)
        assert not existing, f'{name} unexpectedly preloaded; cold-pull comparison invalid'
        command(name + '-pull', ['docker', 'pull', '--platform=linux/amd64', IMAGES[name]])
    # API image build is measured separately, not hidden inside test time.
    build('python', 'nocache', use_cache=False)
    integration()
    cpu()
    for name in ['postgres', 'azurite']:
        command(name + '-save', ['docker', 'save', '-o', str(OUT / f'{name}.tar'), IMAGES[name]])
        emit(name + '-image-tar', bytes=(OUT / f'{name}.tar').stat().st_size)
        command(name + '-remove', ['docker', 'image', 'rm', IMAGES[name]])
        command(name + '-load', ['docker', 'load', '-i', str(OUT / f'{name}.tar')])
    command('disk-end', ['docker', 'system', 'df', '-v'])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=['build', 'runtime'])
    args = parser.parse_args()
    fingerprint()
    started = time.monotonic()
    try:
        if args.task == 'build':
            for app in ['node', 'python']:
                build(app, os.environ['SCENARIO'])
        else:
            runtime()
        emit('suite-complete', seconds=time.monotonic() - started, success=True)
    except Exception:
        emit('suite-complete', seconds=time.monotonic() - started, success=False)
        raise

if __name__ == '__main__':
    main()
