"""Collect public Actions evidence; report all observed samples, not winners."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('run_id')
parser.add_argument('--output', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
repo = 'CelestoAI/ci-benchmarks'
run = json.loads(subprocess.check_output(['gh', 'run', 'view', args.run_id, '--repo', repo, '--json', 'status,conclusion,jobs,url,headSha,createdAt,updatedAt'], text=True))
assert run['status'] == 'completed', 'Do not summarize an incomplete experiment as final'
(out / 'run.json').write_text(json.dumps(run, indent=2) + '\n')
subprocess.run(['gh', 'run', 'download', args.run_id, '--repo', repo, '--dir', str(out / 'raw')], check=True)
samples = []
failures = []
cache_observations = []
observed_jobs = set()

def add(host, metric, seconds, job):
    samples.append({**{k: host[k] for k in ['provider', 'backend', 'scenario', 'repetition', 'commit', 'runner']},
                    'metric': metric, 'seconds': seconds, 'job_url': job['url']})

for file in sorted((out / 'raw').glob('*/events.jsonl')):
    events = [json.loads(line) for line in file.read_text().splitlines()]
    host = next((e['data'] for e in events if e['phase'] == 'host'), None)
    if not host:
        failures.append({'artifact': str(file), 'reason': 'missing host fingerprint'})
        continue
    suffix = '{provider}-{backend}-{scenario}-{repetition}'.format(**host)
    job = next(j for j in run['jobs'] if j['name'].endswith(suffix))
    observed_jobs.add(job['databaseId'])
    by_phase = {e['phase']: e for e in events}
    complete = by_phase.get('suite-complete', {}).get('data', {})
    if not complete.get('success') or job['conclusion'] != 'success':
        failures.append({'artifact': str(file), 'job_url': job['url'], 'conclusion': job['conclusion']})
        continue
    assert host['cpus'] == 4 and 14 * 1024**3 <= host['memory_bytes'] <= 17 * 1024**3
    assert host['commit'] == run['headSha']
    def sec(phase):
        return by_phase[phase]['data']['seconds']
    def boundary(prefix):
        if prefix + '-start' not in by_phase:
            return 0
        return (by_phase[prefix + '-end']['timestamp_ms'] - by_phase[prefix + '-start']['timestamp_ms']) / 1000
    scenario = host['scenario']
    if scenario in ['seed', 'unchanged', 'source', 'dependency', 'nocache']:
        for app in ['node', 'python']:
            add(host, app + ' image build/load', sec(app + '-build'), job)
            observation = by_phase[app + '-cache-observation']['data']
            cache_observations.append({**host, 'app': app, **observation, 'job_url': job['url']})
            vertices = by_phase[app + '-buildkit-vertices']['data']['vertices'].values()
            for vertex in vertices:
                desc = vertex['description']
                if 'RUN npm ci' in desc or 'RUN pip install' in desc:
                    add(host, app + ' dependency install', vertex.get('seconds', 0) if not vertex.get('cached') else 0, job)
                if 'RUN npm run build' in desc:
                    add(host, 'node compilation', vertex.get('seconds', 0) if not vertex.get('cached') else 0, job)
            # Vertex timings may overlap: keep individual exports, never sum them.
            exports = [v for v in vertices if v['description'].startswith(('exporting cache', 'exporting to GitHub Actions Cache'))]
            if exports:
                assert len(exports) == 1
                if 'seconds' in exports[0]:
                    add(host, app + ' BuildKit cache export', exports[0]['seconds'], job)
        restore, save = boundary('build-cache-restore'), boundary('build-cache-save')
        add(host, 'two-image workload incl cache transfer', complete['seconds'] + restore + save, job)
        if host['backend'] == 'portable':
            if scenario != 'seed':
                assert by_phase['build-cache-restore-end']['data']['cache_hit'] == 'true'
                add(host, 'portable cache restore', restore, job)
            add(host, 'portable cache save', save, job)
    elif scenario == 'runtime':
        add(host, 'Rust offline compilation', by_phase['rust-cpu']['data']['compile_seconds'], job)
        add(host, 'Rust dependency fetch', sec('rust-fetch'), job)
        stack = sec('compose-up') + sec('api-ready') + sec('integration-tests') + sec('compose-down')
        add(host, 'Compose tests incl startup/cleanup; images ready', stack, job)
        add(host, 'Compose SQL/blob/API tests only', sec('integration-tests'), job)
        total = stack + sum(sec(name + '-pull') for name in ['postgres', 'azurite', 'python']) + sec('python-build') + sec('python-verify')
        add(host, 'Python CI: pulls + image build + Compose tests', total, job)
        for name in ['postgres', 'azurite', 'python', 'rust']:
            add(host, name + ' cold pull', sec(name + '-pull'), job)
    elif scenario == 'image-seed':
        for name in ['postgres', 'azurite']:
            add(host, name + ' direct pull', sec(name + '-direct-pull'), job)
            add(host, name + ' docker save', sec(name + '-cache-save-tar'), job)
        add(host, 'two images: direct pull', sum(sec(n + '-direct-pull') for n in ['postgres', 'azurite']), job)
        add(host, 'two images: cache save', boundary('image-cache-save'), job)
    elif scenario == 'image-warm':
        assert by_phase['image-cache-restore-end']['data']['cache_hit'] == 'true'
        restore = boundary('image-cache-restore')
        add(host, 'two images: cache restore', restore, job)
        add(host, 'two images: cache restore + docker load', restore + sum(sec(n + '-cache-load-tar') for n in ['postgres', 'azurite']), job)
    add(host, 'Actions job including setup and post-cleanup',
        (__import__('datetime').datetime.fromisoformat(job['completedAt'].replace('Z', '+00:00')) - __import__('datetime').datetime.fromisoformat(job['startedAt'].replace('Z', '+00:00'))).total_seconds(), job)

for job in run['jobs']:
    concrete = job['name'].split('/')[-1].strip().startswith(('github-', 'celesto-'))
    if concrete and job['databaseId'] not in observed_jobs:
        failures.append({'job_url': job['url'], 'conclusion': job['conclusion'], 'reason': 'no usable host artifact'})

(out / 'samples.json').write_text(json.dumps(samples, indent=2) + '\n')
(out / 'failures.json').write_text(json.dumps(failures, indent=2) + '\n')
(out / 'cache-observations.json').write_text(json.dumps(cache_observations, indent=2) + '\n')
with (out / 'samples.csv').open('w') as f:
    writer = csv.DictWriter(f, fieldnames=list(samples[0]))
    writer.writeheader()
    writer.writerows(samples)
groups = {}
for row in samples:
    key = (row['backend'], row['scenario'], row['metric'])
    groups.setdefault(key, {}).setdefault(row['provider'], []).append(row['seconds'])
summary = []
for (backend, scenario, metric), providers in sorted(groups.items()):
    row = {'backend': backend, 'scenario': scenario, 'metric': metric}
    for provider, values in providers.items():
        row[provider] = {'n': len(values), 'median': statistics.median(values), 'min': min(values), 'max': max(values), 'samples': values}
    if 'github' in row and 'celesto' in row and row['celesto']['median']:
        row['github_over_celesto'] = row['github']['median'] / row['celesto']['median']
    summary.append(row)
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({'run': run['url'], 'conclusion': run['conclusion'], 'observed_jobs': len(observed_jobs), 'samples': len(samples), 'failures': failures, 'summary_rows': len(summary)}, indent=2))
