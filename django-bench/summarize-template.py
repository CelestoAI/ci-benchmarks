"""Summarise setup C (django-template-celesto.yml): Django's split CI on Celesto
computers created from a custom template, started by a push.

Usage: python django-bench/summarize-template.py <results dir>

Reads runs.jsonl (drive.py, config template-celesto) for GitHub's timings,
and each run's log for the "BENCH {json}" lines template-run.py prints, one
per computer. Saves those per-computer lines to computers.jsonl beside
runs.jsonl, then prints Markdown:

  Push -> result       run created (the push) -> the orchestrating job's end,
                       which is after the last of the 9 computers is deleted.
  Computer start-up    create request -> the computer is running, from the
                       template (the step a snapshot restore replaces).
  Work only            the slowest computer's job alone (no start-up, no fetch).
"""

import json
import os
import statistics
import subprocess
import sys

REPO = "CelestoAI/ci-benchmarks"


def fmt(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def cell(values: list[float]) -> str:
    if not values:
        return "—"
    return f"**{fmt(statistics.median(values))}** ({fmt(min(values))}–{fmt(max(values))})"


def bench_lines(run_id: int) -> list[dict]:
    """The per-computer results a run printed, read back from its log."""
    log = subprocess.run(
        ["gh", "run", "view", str(run_id), "-R", REPO, "--log"], capture_output=True, text=True, check=True
    ).stdout
    out = []
    for line in log.splitlines():
        if "BENCH {" in line:
            out.append(json.loads(line.split("BENCH ", 1)[1]))
    return out


def main() -> None:
    results = sys.argv[1]
    with open(os.path.join(results, "runs.jsonl")) as f:
        runs = [json.loads(line) for line in f if line.strip()]

    m: dict[str, list[float]] = {k: [] for k in ("push", "startup_max", "startup_med", "fetch", "work", "checks", "shard")}
    green = 0
    with open(os.path.join(results, "computers.jsonl"), "w") as saved:
        for r in runs:
            green += r["conclusion"] == "success"
            computers = bench_lines(r["run_id"])
            for c in computers:
                saved.write(json.dumps({"run_id": r["run_id"], **c}) + "\n")
            ok = [c for c in computers if c.get("exit_code") == 0]
            m["push"].append(r["wall_s"])
            if len(ok) != len(computers) or not ok:
                continue
            startups = [c["running_s"] for c in ok]
            m["startup_max"].append(max(startups))
            m["startup_med"].append(statistics.median(startups))
            m["fetch"].append(max(c["fetch_s"] for c in ok))
            m["work"].append(max(c["work_s"] for c in ok))
            m["checks"].append(next(c["work_s"] for c in ok if c["role"] == "checks"))
            m["shard"].append(max(c["work_s"] for c in ok if c["role"] == "shard"))

    print(f"Median (min–max) over {len(runs)} runs; {green} green.")
    print()
    print("| | Celesto computers from template `memory` |")
    print("| --- | ---: |")
    for key, label in (
        ("push", "**Push → result**"),
        ("startup_max", "Computer start-up from the template, slowest of 9"),
        ("startup_med", "Computer start-up from the template, median of 9"),
        ("fetch", "Fetch the commit, slowest"),
        ("work", "**Work only** (slowest computer)"),
        ("checks", "Checks work (flake8 + isort + black)"),
        ("shard", "Slowest test shard's work"),
    ):
        print(f"| {label} | {cell(m[key])} |")


if __name__ == "__main__":
    main()
