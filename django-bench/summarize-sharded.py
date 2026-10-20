"""Summarise the boxd-style Django runs (django-sharded.yml) against boxd.

Usage: python django-bench/summarize-sharded.py <results dir>

Reads runs.jsonl (drive.py configs sharded-github and sharded-celesto) and
prints Markdown tables. Times are GitHub's own timestamps:

  Push -> result   run created (push event) -> last job end. boxd's metric.
  CI time          first job start -> last job end (no wait for runners).
  Work only        the slowest job's work steps alone: flake8 + isort +
                   black on the checks job, "Run tests" on each shard. It
                   leaves out runner start, checkout, Python setup and
                   install, which a boxd machine restored from a warm
                   snapshot also skips.
"""

import datetime as dt
import json
import os
import statistics
import sys
from collections import defaultdict

PROVIDERS = [("sharded-github", "GitHub, 2 cores"), ("sharded-celesto", "Celesto `celesto-memory`")]
CHECK_STEPS = ("flake8", "isort", "black")
# boxd's published Django numbers (docs.boxd.sh/use-cases/ci-runners,
# read 19 October 2026): push -> result, medians; 2 vCPU machines.
BOXD = {"GitHub, one job": 12 * 60 + 54, "GitHub, sharded": 3 * 60 + 6, "boxd": 62}


def ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def secs(step_or_job: dict) -> float:
    return (ts(step_or_job["completed_at"]) - ts(step_or_job["started_at"])).total_seconds()


def fmt(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def cell(values: list[float]) -> str:
    if not values:
        return "—"
    return f"**{fmt(statistics.median(values))}** ({fmt(min(values))}–{fmt(max(values))})"


def work_seconds(job: dict) -> float:
    names = CHECK_STEPS if job["name"].endswith("checks") else ("Run tests",)
    return sum(secs(s) for s in job["steps"] if s["name"] in names)


def main() -> None:
    with open(os.path.join(sys.argv[1], "runs.jsonl")) as f:
        runs = [json.loads(line) for line in f if line.strip()]

    m: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    green: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in runs:
        p = r["config"]
        green[p][0] += 1
        green[p][1] += r["conclusion"] == "success"
        jobs = r["jobs"]
        event = ts(r["event_at"])
        first_start = min(ts(j["started_at"]) for j in jobs)
        last_end = max(ts(j["completed_at"]) for j in jobs)
        m[p]["push"].append((last_end - event).total_seconds())
        m[p]["ci"].append((last_end - first_start).total_seconds())
        m[p]["wait"].append((max(ts(j["started_at"]) for j in jobs) - event).total_seconds())
        works = [work_seconds(j) for j in jobs]
        m[p]["work"].append(max(works))
        m[p]["setup"].append(statistics.median(secs(j) - work_seconds(j) for j in jobs))
        m[p]["checks"].append(next(work_seconds(j) for j in jobs if j["name"].endswith("checks")))
        m[p]["shard"].append(max(work_seconds(j) for j in jobs if not j["name"].endswith("checks")))

    header = "| | " + " | ".join(n for _, n in PROVIDERS) + " |"
    rule = "| --- |" + " ---: |" * len(PROVIDERS)
    print("Median (min–max) over the measured runs.")
    print()
    print(header)
    print(rule)
    print("| Runs (green) | " + " | ".join(f"{green[p][0]} ({green[p][1]})" for p, _ in PROVIDERS) + " |")
    for key, label in (
        ("push", "**Push → result**"),
        ("ci", "CI time: first job start → last job end"),
        ("wait", "Wait: push → last job start"),
        ("work", "**Work only** (slowest job, setup removed)"),
        ("checks", "Checks job work (flake8 + isort + black)"),
        ("shard", "Slowest test shard's work"),
        ("setup", "Setup per job, removed above (median job)"),
    ):
        print(f"| {label} | " + " | ".join(cell(m[p][key]) for p, _ in PROVIDERS) + " |")

    print()
    print("Next to boxd's published Django numbers (push → result):")
    print()
    print("| Setup | Push → result | Work only |")
    print("| --- | ---: | ---: |")
    for name, value in BOXD.items():
        print(f"| {name} (boxd's page) | {fmt(value)} | — |")
    for p, name in PROVIDERS:
        if m[p]["push"]:
            print(
                f"| {name} (this run) | {fmt(statistics.median(m[p]['push']))} "
                f"| {fmt(statistics.median(m[p]['work']))} |"
            )


if __name__ == "__main__":
    main()
