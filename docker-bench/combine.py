"""Combine predeclared cohorts, keeping the quota-limited run as diagnostics."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import statistics
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--journal', required=True)
p.add_argument('--reports', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
journal = json.loads(Path(a.journal).read_text())
reports, out = Path(a.reports), Path(a.output)
out.mkdir(parents=True, exist_ok=True)
assert not (out / 'raw').exists(), 'Use a fresh output directory'
(out / 'raw').mkdir()
samples, observations, jobs, cohorts = [], [], [], []
selected = set()
audited_jobs=[]
environments={p:{'cpu_models':{},'kernels':{},'containerd_versions':{},'jobs':0} for p in ['github','celesto']}
source = '80cabc32e3888c5dadb9b177c94a35829f5b75cf'
assert journal['authentication']=='Docker Hub login on both providers'
entries = journal['runs']

for entry in entries:
    folder = reports / str(entry['databaseId'])
    read = lambda name: json.loads((folder / name).read_text())
    run = read('run.json')
    # Git verifies that orchestration changes did not change any measured fixture.
    unchanged = subprocess.check_output(['git','diff',source,run['headSha'],'--',
        'docker-bench/run.py','docker-bench/images.json','docker-bench/node',
        'docker-bench/python','docker-bench/rust'], text=True)
    assert not unchanged, 'Do not pool different workload implementations'
    these = read('samples.json')
    urls = {s['job_url'] for s in these}
    these_jobs = [j for j in run['jobs'] if j['url'] in urls]
    assert all(j['conclusion']=='success' for j in these_jobs)
    assert all(any(s['name']=='Log in to Docker Hub on both providers' and s['conclusion']=='success' for s in j['steps']) for j in these_jobs)
    audit = read('cache-log-audit.json')
    assert urls.issubset(set(audit['audited_jobs']))
    audited_jobs += sorted(urls)
    assert not any(w['job_name'] in {j['name'] for j in these_jobs} for w in read('cache-warnings.json'))
    assert run['conclusion']=='success' and not read('failures.json')
    for path in sorted((folder/'raw').glob('*/events.jsonl')):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        host = next((e['data'] for e in events if e['phase']=='host'),None)
        if not host:
            continue
        key = tuple(host[k] for k in ['provider','backend','scenario','repetition'])
        assert key not in selected, f'Duplicate selected sample: {key}'
        selected.add(key)
        environment=environments[host['provider']]
        environment['jobs']+=1
        docker=json.loads((path.parent/'docker-version.log').read_text())
        containerd=next(c['Version'] for c in docker['Server']['Components'] if c['Name']=='containerd')
        for field,value in [('cpu_models',host['cpu_model']),('kernels',host['kernel']),('containerd_versions',containerd)]:
            environment[field][value]=environment[field].get(value,0)+1
        shutil.copytree(path.parent, out/'raw'/f'{entry["databaseId"]}--{path.parent.name}')
    samples += these
    observations += read('cache-observations.json')
    jobs += [{**j,'headSha':run['headSha'],'run_id':entry['databaseId']} for j in these_jobs]
    cohorts.append({**entry,'url':run['url'],'headSha':run['headSha'],
                    'whole_run_conclusion':run['conclusion'], 'selected_jobs':len(these_jobs)})

assert len(selected)==120 and len(jobs)==120
groups = {}
for s in samples:
    groups.setdefault((s['backend'],s['scenario'],s['metric']),{}).setdefault(s['provider'],[]).append(s['seconds'])
summary=[]
for (backend,scenario,metric),providers in sorted(groups.items()):
    row={'backend':backend,'scenario':scenario,'metric':metric}
    for provider,values in providers.items():
        assert len(values)==5, (backend,scenario,metric,provider,len(values))
        row[provider]={'n':len(values),'median':statistics.median(values),'min':min(values),'max':max(values),'samples':values}
    if row['celesto']['median']:
        row['github_over_celesto']=row['github']['median']/row['celesto']['median']
    summary.append(row)
run={'status':'completed','conclusion':'success','selection':'quota-controlled 120-job matrix across documented cohorts',
     'authentication':journal['authentication'],
     'url':cohorts[0]['url'],'headSha':source,'jobs':jobs,'cohorts':cohorts}
for name,data in [('run',run),('samples',samples),('summary',summary),('failures',[]),('cache-observations',observations)]:
    (out/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
(out/'cache-log-audit.json').write_text(json.dumps({'audited_jobs':audited_jobs,'selected_job_cache_save_warnings':0},indent=2)+'\n')
(out/'environment-summary.json').write_text(json.dumps(environments,indent=2)+'\n')
with (out/'samples.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=list(samples[0]))
    writer.writeheader()
    writer.writerows(samples)
for run_id,name in zip(journal['diagnostic_runs'],['original-quota-run','unauthenticated-rate-limit-run']):
    diagnostic=out/'diagnostics'/name
    shutil.copytree(reports/str(run_id),diagnostic)
    original_failures=json.loads((diagnostic/'failures.json').read_text())
    for failure in original_failures:
        if failure.get('artifact'):
            failure['artifact']='/'.join(Path(failure['artifact']).parts[-3:])
    (diagnostic/'failures.json').write_text(json.dumps(original_failures,indent=2)+'\n')
(out/'interventions.json').write_text(json.dumps({
    'reason':'Original run reached cache quota; the unauthenticated continuation reached Docker Hub pull limits. All 120 selected jobs were rerun with Docker Hub login on both providers. Earlier samples are diagnostics only.',
    'scope':'Only task-owned Docker benchmark/pilot cache entries; unrelated caches and quotas unchanged.',
    'initial_cleanup_entries':18,'initial_cleanup_bytes':3295576525,
    'between_pair_cleanup':[{'repetition':c['repetition'],'entries':len(c['entries']),'bytes':sum(r['size_bytes'] for r in c['entries'])} for c in journal['cleanups']],
    'cohort_selection_fixed_before_rerun':True,
},indent=2)+'\n')
print(json.dumps({'selected_jobs':len(jobs),'samples':len(samples),'cohorts':cohorts},indent=2))
