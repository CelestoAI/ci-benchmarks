#!/usr/bin/env python3
"""Append hill-climb results to results/disk-hillclimb/runs.jsonl and rebuild README.md.

usage: aggregate.py <download-dir> <iteration.json> [--run-id N]
"""
import json, math, pathlib, statistics, sys

ROOT = pathlib.Path(__file__).resolve().parents[2] / "results" / "disk-hillclimb"
RUNS = ROOT / "runs.jsonl"


def load_runs():
    if not RUNS.exists():
        return []
    return [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()]


def add(download_dir, iteration_file):
    it = json.loads(pathlib.Path(iteration_file).read_text())
    runs = load_runs()
    seen = {(r["run_id"], r["id"], r["class"], r["rep"]) for r in runs}
    added = 0
    for f in sorted(pathlib.Path(download_dir).glob("*/result.json")):
        r = json.loads(f.read_text())
        r["iteration"] = it["iteration"]
        r["iteration_note"] = it.get("note", "")
        k = (r["run_id"], r["id"], r["class"], r["rep"])
        if k not in seen:
            runs.append(r); seen.add(k); added += 1
    RUNS.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in runs))
    return added


def g(r, *path):
    v = r
    for p in path:
        v = v.get(p) if isinstance(v, dict) else None
    return v


METRICS = [  # (column, getter, higher_is_better, fmt)
    ("fresh 4K IOPS", lambda r: g(r, "suite", "fresh_rand", "iops"), True, "{:.0f}"),
    ("fresh worst s", lambda r: (g(r, "suite", "fresh_rand", "max_us") or 0) / 1e6, False, "{:.1f}"),
    ("fresh I/Os >1s", lambda r: g(r, "suite", "fresh_rand", "over1s"), False, "{:.0f}"),
    ("rewrite 4K IOPS", lambda r: g(r, "suite", "written_rand", "iops"), True, "{:.0f}"),
    ("rewrite worst s", lambda r: (g(r, "suite", "written_rand", "max_us") or 0) / 1e6, False, "{:.1f}"),
    ("seq write MiB/s", lambda r: g(r, "suite", "seq_fresh", "mib_s"), True, "{:.0f}"),
    ("50k files s", lambda r: (g(r, "suite", "smallfiles", "write_s") or 0) + (g(r, "suite", "smallfiles", "sync_s") or 0), False, "{:.2f}"),
    ("fsync IOPS", lambda r: g(r, "suite", "qd1_fdatasync", "iops"), True, "{:.0f}"),
    ("pgbench TPS", lambda r: g(r, "suite", "pgbench", "tps"), True, "{:.0f}"),
    ("base read MiB/s", lambda r: (g(r, "suite", "base_read", "mib") or 0) / max(g(r, "suite", "base_read", "s") or 1e9, 1e-3), True, "{:.0f}"),
    ("VM stop s", lambda r: r.get("exit_s"), False, "{:.2f}"),
    ("host GiB written", lambda r: r.get("host_gib_written"), False, "{:.1f}"),
]
# Metrics in the score (ratio vs base, geometric mean). Worst-latency columns are
# shown, not scored: a config that freezes is rejected, not averaged away.
SCORED = {"fresh 4K IOPS", "rewrite 4K IOPS", "seq write MiB/s", "50k files s", "fsync IOPS", "pgbench TPS", "base read MiB/s", "VM stop s"}


def med(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return statistics.median(vals) if vals else None


def table(rows, base_key):
    by = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    meds = {k: {m[0]: med([m[1](r) for r in v if r["status"] == "ok"]) for m in METRICS} for k, v in by.items()}
    base = meds.get(base_key, {})
    out = ["| config | ok | score | " + " | ".join(m[0] for m in METRICS) + " |",
           "|---|---|---|" + "---|" * len(METRICS)]
    scored = []
    for k, v in by.items():
        ratios = []
        for name, _, hib, _ in METRICS:
            if name in SCORED and v and meds[k][name] and base.get(name):
                a, b = meds[k][name], base[name]
                ratios.append(a / b if hib else b / max(a, 1e-3))
        score = math.exp(sum(map(math.log, ratios)) / len(ratios)) if ratios else None
        scored.append((score or 0, k))
    for score, k in sorted(scored, reverse=True):
        v = by[k]; ok = sum(r["status"] == "ok" for r in v)
        cells = [(fmt.format(meds[k][name]) if meds[k][name] is not None else "–") for name, _, _, fmt in METRICS]
        out.append(f"| {k} | {ok}/{len(v)} | {score:.2f} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def render():
    runs = load_runs()
    lines = ["# CI VM disk hill-climb", "",
             "Each run boots the prod CI microvm command line (QEMU 8.2.2, Celesto CI kernel `kernels-2026.10.28.0`,",
             "virtio-mmio, 2 vCPU / 4 GiB) on a fresh GitHub-hosted runner and runs `scripts/hillclimb/guest-bench.sh`.",
             "", "- **local**: the runner's local temp SSD, XFS with reflink (stand-in for local NVMe).",
             "- **network**: an XFS loop file (direct I/O) on the runner's network OS disk (stand-in for EBS / OVH volumes).",
             "- Values are medians over repeats. **score** = geometric mean of each scored metric's ratio to `base` in the",
             "  same disk class (above 1 is better). Worst-latency columns are not scored: a config that freezes is rejected.",
             "- Single VM per runner: no neighbor load. Finalists must still be checked on real hosts.",
             "- Raw per-run records (config, QEMU drive string, every metric): `runs.jsonl`.", ""]
    for itn in sorted({r["iteration"] for r in runs}, reverse=True):
        rs = [r for r in runs if r["iteration"] == itn]
        runs_ids = sorted({r["run_id"] for r in rs})
        lines += [f"## Iteration {itn}", "", rs[0].get("iteration_note", ""), "",
                  "Runs: " + ", ".join(f"[{i}](https://github.com/CelestoAI/ci-benchmarks/actions/runs/{i})" for i in runs_ids), ""]
        cfgs = {}
        for r in rs:
            cfgs.setdefault(r["id"], r["config"])
        lines += ["Configs:", ""] + [f"- `{k}`: `{json.dumps({a: b for a, b in c.items() if a not in ('id', 'why')})}`" + (f" — {c['why']}" if c.get("why") else "") for k, c in cfgs.items()] + [""]
        for cls in ("local", "network"):
            cr = [r for r in rs if r["class"] == cls]
            if cr:
                lines += [f"### {cls}", "", table(cr, "base"), ""]
        bad = [r for r in rs if r["status"] != "ok"]
        if bad:
            lines += ["Failures:", ""] + [f"- `{r['id']}` {r['class']} rep {r['rep']}: {r['status']} {(r.get('qemu_err') or '')[-200:].strip()}" for r in bad] + [""]
    (ROOT / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    n = add(sys.argv[1], sys.argv[2])
    render()
    print(f"added {n} runs; {RUNS} now has {len(load_runs())}")
