"""Per-step GitHub vs Celesto report for a step-breakdown.yml run.

Usage: python3 scripts/breakdown-report.py RUN_ID [--output results/DIR]

Needs Python 3.10+ and an authenticated `gh`. It downloads the run's job logs
and artifacts, then reports medians (min-max; n) for:

- actions/cache phases, split from the timestamped milestone lines the action
  prints (see PHASES below);
- the isolated probes from scripts/step-probes.sh;
- CPU throughput from scripts/cpu-benchmark.mjs.

Celesto jobs are grouped by host provider (aws, ovh, ...) as reported by the
Celesto cache proxy, so differences between pools stay visible.
"""
import argparse
import json
import re
import statistics
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = 'CelestoAI/ci-benchmarks'
JOB = re.compile(r'^(cold|warm) \((\d+), ([a-z-]+),')

# restore: step start -> "Cache hit for"            lookup
#          "Cache hit for" -> "Cache Size:"         download (whole archive received)
#          tar -xf -> "Cache restored successfully" extract
# save:    tar --posix -> first url.parse warning   compress (warning fires on the
#                                                   first HTTP call after tar exits)
#          warning -> "Sent N of N (100.0%)"        reserve + upload
#          100% -> "Cache saved with key"           commit
PHASES = {
    'warm': [('restore: lookup', 'r_start', 'r_hit'), ('restore: download', 'r_hit', 'r_size'),
             ('restore: extract', 'r_tar', 'r_done'), ('restore: total', 'r_start', 'r_done')],
    'cold': [('save: compress', 's_tar', 's_http'), ('save: reserve+upload', 's_http', 's_sent'),
             ('save: commit', 's_sent', 's_done'), ('save: total', 's_start', 's_done')],
}


def gh(*args: str) -> str:
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def milestones(lines: list[tuple[float, str]]) -> dict[str, float]:
    """Timestamp of each actions/cache milestone in one job's log."""
    marks: dict[str, float] = {}
    step = None
    for t, message in lines:
        if 'Run actions/cache/restore' in message:
            step, marks['r_start'] = 'r', t
        elif 'Run actions/cache/save' in message:
            step, marks['s_start'] = 's', t
        elif step == 'r' and message.startswith('Cache hit for'):
            marks['r_hit'] = t
        elif step == 'r' and message.startswith('Cache Size:'):
            marks['r_size'] = t
        elif step == 'r' and message.startswith('[command]/usr/bin/tar -xf'):
            marks['r_tar'] = t
        elif step == 'r' and message.startswith('Cache restored successfully'):
            marks['r_done'] = t
        elif step == 's' and message.startswith('[command]/usr/bin/tar --posix'):
            marks['s_tar'] = t
        elif step == 's' and 'DEP0169' in message and 's_tar' in marks and 's_http' not in marks:
            marks['s_http'] = t
        elif step == 's' and re.match(r'Sent (\d+) of \1 \(100\.0%\)', message):
            marks['s_sent'] = t
        elif step == 's' and message.startswith('Cache saved with key'):
            marks['s_done'] = t
    return marks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    # 1. Job logs: one line per log line, "<job>\t<step>\t<timestamp> <message>".
    logs: dict[tuple[str, str, str], list[tuple[float, str]]] = defaultdict(list)
    for raw in gh('run', 'view', args.run_id, '--repo', REPO, '--log').splitlines():
        job, _, rest = raw.partition('\t')
        match = JOB.match(job)
        stamp, _, message = rest.partition('\t')[2].partition(' ')
        if match and stamp[:2] == '20':
            phase, sample, provider = match.groups()
            logs[(phase, sample, provider)].append((datetime.fromisoformat(stamp[:26]).timestamp(), message))

    # 2. Artifacts: events per job, keyed the same way as the logs.
    events: dict[tuple[str, str, str], list[dict]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        gh('run', 'download', args.run_id, '--repo', REPO, '--dir', tmp)
        for path in Path(tmp).glob('*/benchmark-events.jsonl'):
            name = re.match(r'^([a-z-]+)-breakdown-\d+-.*-sample-(\d+)-(cold|warm)$', path.parent.name)
            if name:
                provider, sample, phase = name.groups()
                events[(phase, sample, provider)] = [json.loads(line) for line in path.open()]

    # 3. One row per (group, metric, sample).
    samples = []
    for key, lines in sorted(logs.items()):
        phase, sample, provider = key
        job_events = events.get(key, [])
        host = next((e['data'] for e in job_events if e['phase'] == 'probe_host'), {})
        fingerprint = next((e['data'] for e in job_events if e['phase'] == 'host_fingerprint'), {})
        group = 'github' if provider.startswith('github') else f"celesto/{host.get('host_provider') or '?'}"
        base = {'group': group, 'phase': phase, 'sample': sample, 'cpu_model': fingerprint.get('cpu_model')}
        marks = milestones(lines)
        for metric, start, end in PHASES[phase]:
            if start in marks and end in marks:
                samples.append({**base, 'metric': metric, 'value': marks[end] - marks[start]})
        for e in job_events:
            if e['phase'] == 'probe' and e['data'].get('exit_code') == 0:
                samples.append({**base, 'metric': f"probe: {e['data']['probe']}", 'value': e['data']['seconds']})
            elif e['phase'].startswith('cpu_') and e['phase'].endswith('_end'):
                label = e['phase'][4:-4]
                samples.append({**base, 'metric': f'cpu: {label} M iter/s', 'value': e['data']['iterations_per_second'] / 1e6})

    # 4. Medians per group, and the Celesto - GitHub gap per metric.
    table: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s in samples:
        table[s['metric']][s['group']].append(s['value'])
    groups = ['github'] + sorted({s['group'] for s in samples} - {'github'})
    cell = lambda v: f'{statistics.median(v):.2f} ({min(v):.2f}-{max(v):.2f}; n={len(v)})' if v else '-'
    out = ['| Metric | ' + ' | '.join(groups) + ' | Celesto − GitHub (median) |',
           '| --- |' + ' ---: |' * (len(groups) + 1)]
    for metric in sorted(table):
        row = table[metric]
        celesto = [v for g in groups[1:] for v in row.get(g, [])]
        gap = f'{statistics.median(celesto) - statistics.median(row["github"]):+.2f}' if celesto and row.get('github') else '-'
        out.append(f'| {metric} | ' + ' | '.join(cell(row.get(g, [])) for g in groups) + f' | {gap} |')
    report = '\n'.join(out)
    print(report)

    cpu_models = defaultdict(lambda: defaultdict(set))
    for s in samples:
        cpu_models[s['group']][s['cpu_model']].add((s['phase'], s['sample']))
    for group, models in cpu_models.items():
        print(f'{group}: ' + ', '.join(f'{m} ×{len(j)}' for m, j in models.items()))

    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'samples.json').write_text(json.dumps(samples, indent=2) + '\n')
        (args.output / 'breakdown.md').write_text(report + '\n')


if __name__ == '__main__':
    main()
