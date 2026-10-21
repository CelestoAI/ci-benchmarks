"""Setup C: run Django's split CI on Celesto computers created from a template.

Runs inside the GitHub job of django-template-celesto.yml, which a push to
bench/django starts. It does what boxd's automation does on each push, with a
Celesto custom template in place of boxd's snapshot of main:

  1. create 9 computers from the template at once (1 checks + 8 test shards),
  2. on each, fetch the commit and run its job as the template's normal user,
  3. report every computer's timings, then delete all 9.

The template (see the "Template" section of the report) already holds
Python 3.14t, Django at DJANGO_SHA with its test requirements and linters,
and compiled Python files, so a job installs nothing.

Environment: CELESTO_API_KEY (repository secret), TEMPLATE_ID (tpl_...).
Output: one "BENCH {json}" line per computer in the log, the same lines in
bench-results.jsonl, and a table in the job summary. Exits 1 if any job
failed, so the run shows red.

Standard library only, so the GitHub job needs no install step.
"""

import concurrent.futures
import json
import os
import shlex
import sys
import time
import urllib.error
import urllib.request

API = "https://api.celesto.ai/v1"
SIZE = "memory"  # 2 vCPU / 8 GiB, the size of boxd's machines
SHARDS = 8
STARTUP_TIMEOUT_S = 900
EXEC_TIMEOUT_S = 300  # the API's maximum per command

here = os.path.dirname(os.path.abspath(__file__))
env = dict(
    line.strip().split("=", 1)
    for line in open(os.path.join(here, "bench.env"))
    if line.strip() and not line.startswith("#")
)
DJANGO_SHA = env["DJANGO_SHA"]

# The job each computer runs, as the template's normal user (ohm). The test
# shard list mirrors shard.py: Django's top-level test packages, sorted and
# dealt round-robin, minus the ones runtests skips and GIS (no GDAL).
JOB = r"""
set -uo pipefail
now() { date +%s.%N; }
cd /opt/django
export PATH=/opt/venv/bin:$PATH
t_start=$(now)
# The commit is already in the template (it is main's), so the fetch only
# asks GitHub for new objects, as a boxd job does after its restore.
git fetch -q origin "$SHA" && git checkout -q -f "$SHA"
t_fetched=$(now)
if [ "$ROLE" = checks ]; then
  { flake8 && isort --check --diff django tests scripts && black --check --diff . ; } > /tmp/job.log 2>&1
else
  modules=$(python - "$SHARD" "$SHARDS" <<'PY'
import os, sys
skip = {"import_error_package", "playwright_tests", "test_runner_apps", "gis_tests"}
mods = sorted(
    e.name for e in os.scandir("tests")
    if e.is_dir() and "." not in e.name and e.name not in skip
    and os.path.exists(os.path.join(e.path, "__init__.py"))
)
i, n = int(sys.argv[1]), int(sys.argv[2])
print(" ".join(mods[i - 1::n]))
PY
)
  python -Wall tests/runtests.py -v2 $modules > /tmp/job.log 2>&1
fi
status=$?
t_done=$(now)
tail -n 15 /tmp/job.log
python3 -c 'import json,sys; a=sys.argv; print("JOB " + json.dumps({"exit_code": int(a[1]), "fetch_s": round(float(a[3])-float(a[2]), 2), "work_s": round(float(a[4])-float(a[3]), 2)}))' "$status" "$t_start" "$t_fetched" "$t_done"
exit $status
"""


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None, timeout: float = 60):
    """One API call; returns (status, parsed JSON or None). Retries network errors and 5xx."""
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(5):
        req = urllib.request.Request(API + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + os.environ["CELESTO_API_KEY"])
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            if err.code < 500 or attempt == 4:
                return err.code, {"error": err.read().decode(errors="replace")[:500]}
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == 4:
                return 0, {"error": str(err)}
        time.sleep(2 * (attempt + 1))
    return 0, None


def run_one(name: str, role: str, shard: int | None, run_key: str) -> dict:
    """Create one computer from the template, run its job, delete it. Never raises."""
    result: dict = {"name": name, "role": role, "shard": shard}
    t0 = time.time()
    status, body = call(
        "POST",
        "/computers",
        {"size_id": SIZE, "template_id": os.environ["TEMPLATE_ID"]},
        headers={"Idempotency-Key": f"{run_key}-{name}", "X-Celesto-Client": "sdk"},
    )
    if status not in (200, 201, 202) or not body:
        return {**result, "error": f"create returned {status}: {body}"}
    computer_id = body["id"]
    result["computer_id"] = computer_id
    try:
        # 1. Wait until the computer is running: the start-up a snapshot restore replaces.
        while body.get("status") != "running":
            if body.get("status") not in {"creating", "starting", "restoring", "pending", "queued", None}:
                return {**result, "error": f"computer went {body.get('status')}"}
            if time.time() - t0 > STARTUP_TIMEOUT_S:
                return {**result, "error": "not running after the start-up timeout"}
            time.sleep(1)
            _, body = call("GET", f"/computers/{computer_id}")
            body = body or {}
        result["running_s"] = round(time.time() - t0, 2)

        # 2. The job. /dev/shm is made writable for Python multiprocessing,
        #    then the job runs as the template's normal user.
        env_vars = f"SHA={DJANGO_SHA} ROLE={role} SHARD={shard or 0} SHARDS={SHARDS}"
        command = (
            "chmod 1777 /dev/shm; "
            f"runuser -u ohm -- env {env_vars} bash -c {shlex.quote(JOB)}"
        )
        t1 = time.time()
        status, out = call(
            "POST",
            f"/computers/{computer_id}/exec",
            {"command": command, "timeout": EXEC_TIMEOUT_S},
            timeout=EXEC_TIMEOUT_S + 60,
        )
        result["exec_s"] = round(time.time() - t1, 2)
        out = out or {}
        stdout = out.get("stdout", "")
        job = next((json.loads(l[4:]) for l in stdout.splitlines() if l.startswith("JOB ")), None)
        if status != 200 or job is None:
            return {**result, "error": f"exec returned {status}", "stdout_tail": stdout[-1500:], "stderr_tail": out.get("stderr", "")[-800:]}
        result.update(job)
        result["total_s"] = round(time.time() - t0, 2)
        if job["exit_code"] != 0:
            result["log_tail"] = stdout[-1500:]
        return result
    finally:
        # 3. Delete it whatever happened, as boxd deletes each job's machine.
        call("DELETE", f"/computers/{computer_id}")


def main() -> None:
    run_key = f"django-bench-{os.environ.get('GITHUB_RUN_ID', int(time.time()))}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    jobs = [("checks", "checks", None)] + [(f"shard-{i}", "shard", i) for i in range(1, SHARDS + 1)]
    # All 9 at once, as boxd creates its machines together.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda j: run_one(j[0], j[1], j[2], run_key), jobs))

    with open("bench-results.jsonl", "w") as f:
        for r in results:
            line = json.dumps(r)
            print("BENCH " + line, flush=True)
            f.write(line + "\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("| Computer | Running after | Fetch | Work | Result |\n| --- | ---: | ---: | ---: | --- |\n")
            for r in results:
                ok = "ok" if r.get("exit_code") == 0 else r.get("error", f"exit {r.get('exit_code')}")
                f.write(f"| {r['name']} | {r.get('running_s', '—')} s | {r.get('fetch_s', '—')} s | {r.get('work_s', '—')} s | {ok} |\n")

    failed = [r["name"] for r in results if r.get("exit_code") != 0]
    if failed:
        print("failed: " + ", ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
