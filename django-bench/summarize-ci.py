"""Summarise the Django CI benchmark (django-ci.yml) into the report's tables.

Usage: python django-bench/summarize-ci.py <results dir>

Reads runs.jsonl (from drive.py, configs ci-github and ci-celesto) and
prints Markdown. Times come from GitHub's own records for each run:

  push        when GitHub created the run (the push event)
  job start   when a runner started executing a job
  job end     when that job finished

Headline: "CI time" = first job start -> last job end. It begins when the
CI starts running the 4 jobs, so the wait for a runner before that is not
in it; that wait is reported on its own, as is push -> last job end.
"""

import datetime as dt
import json
import os
import statistics
import sys
from collections import defaultdict

PROVIDERS = [("ci-github", "GitHub `ubuntu-latest`"), ("ci-celesto", "Celesto `celesto-large`")]
JOBS = ["flake8", "isort", "black", "Ubuntu, SQLite, Python 3.14t"]
TEST_STEPS = [
    ("Checkout", "Checkout"),
    ("Set up Python", "Set up Python (with pip cache)"),
    ("Install and upgrade packaging tools", "Upgrade pip and wheel"),
    ("Run python -m pip install -r", "Install Django's requirements"),
    ("Runner image fix", "Runner image fix steps (Celesto only)"),
    ("Run tests", "Run the test suite"),
]


def ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def secs(a: str, b: str) -> float:
    return (ts(b) - ts(a)).total_seconds()


def fmt(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def cell(values: list[float]) -> str:
    if not values:
        return "—"
    return f"**{fmt(statistics.median(values))}** ({fmt(min(values))}–{fmt(max(values))})"


def job_short(name: str) -> str:
    # Reusable-workflow jobs are named "django / <job>".
    return name.split(" / ", 1)[-1]


def main() -> None:
    path = os.path.join(sys.argv[1], "runs.jsonl")
    with open(path) as f:
        runs = [json.loads(line) for line in f if line.strip()]

    metrics: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [runs, green]
    for r in runs:
        p = r["config"]
        if p not in dict(PROVIDERS):
            continue
        counts[p][0] += 1
        counts[p][1] += r["conclusion"] == "success"
        jobs = r["jobs"]
        first_start = min(j["started_at"] for j in jobs)
        last_start = max(j["started_at"] for j in jobs)
        last_end = max(j["completed_at"] for j in jobs)
        m = metrics[p]
        m["ci"].append(secs(first_start, last_end))
        m["push_to_end"].append(secs(r["event_at"], last_end))
        m["wait_first"].append(secs(r["event_at"], first_start))
        m["wait_last"].append(secs(r["event_at"], last_start))
        for j in jobs:
            m["job:" + job_short(j["name"])].append(secs(j["started_at"], j["completed_at"]))
            if "SQLite" in j["name"]:
                for prefix, _ in TEST_STEPS:
                    total = sum(
                        secs(s["started_at"], s["completed_at"])
                        for s in j["steps"]
                        if s["name"].startswith(prefix) and s["started_at"] and s["completed_at"]
                    )
                    m["step:" + prefix].append(total)

    names = dict(PROVIDERS)
    header = "| | " + " | ".join(names[p] for p, _ in PROVIDERS) + " |"
    rule = "| --- |" + " ---: |" * len(PROVIDERS)

    print("Median (min–max) over the measured runs.")
    print()
    print(header)
    print(rule)
    print("| Runs (green) | " + " | ".join(f"{counts[p][0]} ({counts[p][1]})" for p, _ in PROVIDERS) + " |")
    rows = [
        ("ci", "**CI time: first job start → last job end**"),
        ("wait_first", "Wait: push → first job start"),
        ("wait_last", "Wait: push → last job start"),
        ("push_to_end", "Push → last job end"),
    ]
    for key, label in rows:
        print(f"| {label} | " + " | ".join(cell(metrics[p][key]) for p, _ in PROVIDERS) + " |")

    print()
    print("Each job, start → end:")
    print()
    print(header)
    print(rule)
    for job in JOBS:
        print(f"| {job} | " + " | ".join(cell(metrics[p]["job:" + job]) for p, _ in PROVIDERS) + " |")

    print()
    print("Test job, by step:")
    print()
    print(header)
    print(rule)
    for prefix, label in TEST_STEPS:
        print(f"| {label} | " + " | ".join(cell(metrics[p]["step:" + prefix]) for p, _ in PROVIDERS) + " |")


if __name__ == "__main__":
    main()
