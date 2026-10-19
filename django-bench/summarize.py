"""Summarise the Django benchmark's raw timings into the report's tables.

Usage: python django-bench/summarize.py <results dir>

Reads runs.jsonl (setups A and B, from drive.py) and warm.jsonl (setup C,
one line per computer per run, from warm-run.sh) and prints Markdown:

- Push to result per setup and change: median, with min-max and run count.
  For A and B that is the workflow run's creation (the push event) to its
  last job's finish. For C it is the slowest computer's total, since all
  computers start together and the run ends when the last one finishes.
- Where the time goes in the sharded workflow runs: how long after the push
  the jobs started, and how long the slowest job ran.
"""

import datetime as dt
import json
import os
import statistics
import sys
from collections import defaultdict

SETUPS = [
    ("github-single", "A. GitHub, one job"),
    ("github-sharded", "B. GitHub, 1 checks + 8 shard jobs"),
    ("celesto-single", "A. Celesto runner, one job"),
    ("celesto-sharded", "B. Celesto runner, 1 checks + 8 shard jobs"),
    ("warm", "C. Warm Celesto computers, 1 checks + 8 shards"),
]


def ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    results = sys.argv[1]
    runs = load(os.path.join(results, "runs.jsonl"))
    warm = load(os.path.join(results, "warm.jsonl"))

    # (setup, change kind) -> list of (seconds, all green?)
    walls: dict[tuple[str, str], list[tuple[float, bool]]] = defaultdict(list)
    for r in runs:
        kind = "none" if r["change"] == "none" else "deps"
        walls[(r["config"], kind)].append((r["wall_s"], r["conclusion"] == "success"))

    # Setup C: group the per-computer lines of one run by label.
    by_label: dict[str, list[dict]] = defaultdict(list)
    for w in warm:
        by_label[w["label"]].append(w)
    for label, lines in by_label.items():
        kind = "none" if lines[0]["change"] == "none" else "deps"
        green = all(x["exit_code"] == 0 for x in lines)
        walls[("warm", kind)].append((max(x["total_s"] for x in lines), green))

    print("| Setup | No-change push | Dependency change |")
    print("| --- | ---: | ---: |")
    for key, name in SETUPS:
        cells = []
        for kind in ("none", "deps"):
            samples = walls.get((key, kind), [])
            if not samples:
                cells.append("—")
                continue
            secs = [s for s, _ in samples]
            red = sum(1 for _, ok in samples if not ok)
            cell = f"**{fmt(statistics.median(secs))}** ({fmt(min(secs))}–{fmt(max(secs))}, n={len(secs)})"
            if red:
                cell += f" ⚠ {red} red"
            cells.append(cell)
        print(f"| {name} | {cells[0]} | {cells[1]} |")

    print()
    print("Sharded workflow runs: when jobs started after the push, and the slowest job.")
    print()
    print("| Setup | Change | Push to result | First job started | Last job started | Slowest job ran |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for r in runs:
        if "sharded" not in r["config"]:
            continue
        event = ts(r["event_at"])
        starts = [(ts(j["started_at"]) - event).total_seconds() for j in r["jobs"]]
        durations = [(ts(j["completed_at"]) - ts(j["started_at"])).total_seconds() for j in r["jobs"]]
        print(
            f"| {r['config']} | {r['change']} | {fmt(r['wall_s'])} | {fmt(min(starts))} "
            f"| {fmt(max(starts))} | {fmt(max(durations))} |"
        )

    if warm:
        print()
        print("Setup C, median seconds per step across all runs and computers:")
        print()
        print("| Step | Median | Max |")
        print("| --- | ---: | ---: |")
        for step, label in (("fetch_s", "Fetch and check out"), ("setup_s", "Install (only if requirements changed)")):
            vals = [w[step] for w in warm]
            print(f"| {label} | {statistics.median(vals):.2f}s | {max(vals):.2f}s |")
        checks = [w["work_s"] for w in warm if w["role"] == "checks"]
        shards = [w["work_s"] for w in warm if w["role"] == "shard"]
        print(f"| flake8 + isort + black (checks computer) | {statistics.median(checks):.1f}s | {max(checks):.1f}s |")
        print(f"| One test shard | {statistics.median(shards):.1f}s | {max(shards):.1f}s |")


if __name__ == "__main__":
    main()
