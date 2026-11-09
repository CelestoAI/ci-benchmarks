#!/usr/bin/env python3
# Small-file copy rounds inside a Celesto computer, with the kernel block trace,
# reporting per round: copy rate and the longest single disk request (issue -> complete).
import os, re, shutil, subprocess, sys, time, threading
T = '/sys/kernel/tracing'
subprocess.run(f'mountpoint -q {T} || mount -t tracefs nodev {T}', shell=True)
dev = os.path.basename(subprocess.run("findmnt -no SOURCE /", shell=True, capture_output=True, text=True).stdout.strip())
mj, mn = open(f'/sys/block/{dev}/dev').read().strip().split(':')
w = lambda f, v: open(f'{T}/{f}', 'w').write(v)
w('trace', ''); w('buffer_size_kb', '65536'); w('trace_clock', 'mono')
for e in ('block_rq_issue', 'block_rq_complete'):
    w(f'events/block/{e}/filter', f'dev == {(int(mj) << 20) | int(mn)}'); w(f'events/block/{e}/enable', '1')
lines = []; stop = False
def reader():
    with open(f'{T}/trace_pipe') as p:
        while not stop: lines.append(p.readline())
threading.Thread(target=reader, daemon=True).start()
print('irqs', [l.strip()[:90] for l in open('/proc/interrupts') if 'virtio' in l])
rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
res = []
for r in range(1, rounds + 1):
    base = os.path.join(os.environ.get('GITHUB_WORKSPACE', '/root'), f'vmstall-{r}'); src, dst = base + '/a', base + '/b'
    t0 = time.monotonic(); e0 = time.time()
    for d in range(200):
        os.makedirs(f'{src}/d{d}', exist_ok=True)
        for f in range(100):
            with open(f'{src}/d{d}/f{f}.js', 'wb') as fh: fh.write(b'\7' * 4096)
    t1 = time.monotonic(); subprocess.run('sync', shell=True); t2 = time.monotonic()
    for d in range(200):
        os.makedirs(f'{dst}/d{d}', exist_ok=True)
        for f in range(100): shutil.copyfile(f'{src}/d{d}/f{f}.js', f'{dst}/d{d}/f{f}.js')
    subprocess.run('sync', shell=True); t3 = time.monotonic()
    shutil.rmtree(base); subprocess.run('sync', shell=True)
    res.append((r, t0 * 1000, time.monotonic() * 1000, round(20000 / (t3 - t2)), round(t3 - t2, 1), int(e0 * 1000), int(time.time() * 1000)))
    print(f'round {r}: copy+sync {round(t3 - t2, 1)} s = {round(20000 / (t3 - t2))} files/s', flush=True)
stop = True
for e in ('block_rq_issue', 'block_rq_complete'): w(f'events/block/{e}/enable', '0')
iss = {}; reqs = []
for l in lines:
    m = re.search(r'\s(\d+\.\d+): block_rq_(issue|complete): \d+,\d+ (\S+) (?:(\d+) )?\(.*?\) (\d+) \+ (\d+)', l)
    if not m: continue
    t = float(m.group(1)) * 1000; key = (m.group(5), m.group(6))
    if m.group(2) == 'issue': iss[key] = t
    elif key in iss: reqs.append((iss.pop(key), t))
for r, a, b, rate, secs, ea, eb in res:
    d = sorted(y - x for x, y in reqs if a <= y <= b)
    # stalls: requests > 500 ms, as epoch ms (issue, complete) so host logs can be matched
    stalls = sorted(set((round(x - a + ea), round(y - a + ea)) for x, y in reqs if a <= y <= b and y - x > 500))
    print(f'STALLS round {r}: {stalls[:20]}')
    print(f'round {r} epoch {ea}-{eb}: {rate} files/s, requests={len(d)}, p50={d[len(d)//2] if d else 0:.3f} ms, max={d[-1] if d else 0:.0f} ms, stuck>500ms={sum(1 for x in d if x > 500)}')
