"""Run the Django benchmark's workflow setups (A and B) and record timings.

Usage: python django-bench/drive.py <out.jsonl> <config>:<change> [...]
  config  github-single, github-sharded, celesto-single or celesto-sharded
  change  none or deps-N (see apply-change.sh)

Each run is a push to the bench/django branch that rewrites one trigger file,
so the timing starts from a real push event, as in boxd's benchmark. Runs
are done one after another, in the order given. For each run the script
waits for the workflow to finish and appends one JSON line:

  event_at      when GitHub created the run (the push event)
  done_at       when the last job finished (the result)
  wall_s        done_at - event_at, the number the report uses
  jobs          per-job start/finish, to see queueing and the slowest shard

Several drivers can run at once (one per provider): pushes are serialised
with a lock directory and rebased onto the branch before pushing.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time

REPO = "CelestoAI/ci-benchmarks"
BRANCH = "bench/django"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, ".git", "django-bench-push.lock")


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def gh_api(path: str):
    return json.loads(sh("gh", "api", path))


def ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def push_trigger(config: str, change: str, label: str) -> str:
    """Rewrite the trigger file, commit and push. Returns the commit SHA."""
    # mkdir is atomic, so it works as a lock between concurrent drivers.
    while True:
        try:
            os.mkdir(LOCK)
            break
        except FileExistsError:
            time.sleep(1)
    try:
        sh("git", "pull", "-q", "--rebase", "origin", BRANCH)
        path = f"django-bench/triggers/{config}"
        with open(os.path.join(ROOT, path), "w") as f:
            f.write(f"{change}\n# {label}\n")
        sh("git", "add", path)
        sh("git", "commit", "-q", "-m", f"bench: {config} {change} ({label})")
        sh("git", "push", "-q", "origin", BRANCH)
        return sh("git", "rev-parse", "HEAD")
    finally:
        os.rmdir(LOCK)


def find_run(sha: str, config: str) -> dict:
    """Wait for the workflow run that the push of `sha` started."""
    workflow = f".github/workflows/django-{config}.yml"
    for _ in range(120):
        runs = gh_api(f"repos/{REPO}/actions/runs?head_sha={sha}&event=push&per_page=20")
        for run in runs["workflow_runs"]:
            if run["path"].split("@")[0] == workflow:
                return run
        time.sleep(5)
    raise RuntimeError(f"no {config} run appeared for {sha}")


def wait_for(run_id: int) -> dict:
    while True:
        run = gh_api(f"repos/{REPO}/actions/runs/{run_id}")
        if run["status"] == "completed":
            return run
        time.sleep(15)


def record(config: str, change: str, label: str) -> dict:
    sha = push_trigger(config, change, label)
    run = wait_for(find_run(sha, config)["id"])
    jobs = gh_api(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=50")["jobs"]
    event_at = ts(run["created_at"])
    done_at = max(ts(j["completed_at"]) for j in jobs)
    return {
        "config": config,
        "change": change,
        "label": label,
        "sha": sha,
        "run_id": run["id"],
        "url": run["html_url"],
        "conclusion": run["conclusion"],
        "event_at": run["created_at"],
        "done_at": done_at.isoformat(),
        "wall_s": round((done_at - event_at).total_seconds(), 1),
        "jobs": [
            {
                "name": j["name"],
                "conclusion": j["conclusion"],
                "created_at": j["created_at"],
                "started_at": j["started_at"],
                "completed_at": j["completed_at"],
            }
            for j in jobs
        ],
    }


def main() -> None:
    out, specs = sys.argv[1], sys.argv[2:]
    for n, spec in enumerate(specs, 1):
        config, change = spec.split(":")
        label = f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}-{n}"
        result = record(config, change, label)
        with open(out, "a") as f:
            f.write(json.dumps(result) + "\n")
        print(f"{config} {change}: {result['wall_s']}s {result['conclusion']} {result['url']}", flush=True)


if __name__ == "__main__":
    main()
