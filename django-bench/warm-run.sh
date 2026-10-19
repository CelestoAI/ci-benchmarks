#!/usr/bin/env bash
# Setup C: one job on a warm Celesto computer, boxd-style.
#
# The computer was set up once with Django checked out at DJANGO_SHA, a
# virtualenv with every dependency installed, and one warm-up run (see
# warm-setup.sh). A job then only does what a boxd job does after its
# machine is created from the snapshot:
#   1. fetch and check out the commit
#   2. reinstall dependencies only if the requirements file changed
#   3. run its checks or its test shard
# and prints one JSON line with the time of each step, measured with this
# computer's own clock.
#
# Usage (as the user in /opt/bench-user): warm-run.sh <role> <shard or -> <change> <label>
set -uo pipefail

role=$1
shard=$2
change=$3
label=$4
here=$(cd "$(dirname "$0")" && pwd)
source "$here/bench.env"
source /opt/venv/bin/activate
django=/opt/django
cd "$django"

now() { date +%s.%N; }
t_start=$(now)

# 1. Fetch and check out. The commit is already on disk (it is the warm
# state), so like boxd's fetch this only asks GitHub for new objects.
git fetch -q origin "$DJANGO_SHA" && git checkout -q -f "$DJANGO_SHA"
t_fetched=$(now)

# 2. Apply the change under test, then reinstall only when the requirements
# file differs from the commit, the way boxd's setup step skips the install
# when the lockfile is unchanged.
bash "$here/apply-change.sh" "$django" "$change" >/dev/null
installed=false
if ! git diff --quiet HEAD -- "$REQUIREMENTS"; then
  taskset -c 0,1 python -m pip install -q -r "$REQUIREMENTS"
  installed=true
fi
t_setup=$(now)

# 3. The job's work, with the same script as the workflow jobs.
if [ "$role" = shard ]; then
  bash "$here/run-role.sh" "$django" shard "$shard" > "/tmp/job-$label.log" 2>&1
else
  bash "$here/run-role.sh" "$django" "$role" > "/tmp/job-$label.log" 2>&1
fi
status=$?
t_done=$(now)

# Put the computer back in its warm state so the next run starts like a
# fresh copy of the snapshot: drop the change and any package it added.
added=$(git diff HEAD -- "$REQUIREMENTS" | sed -n 's/^+\([A-Za-z][A-Za-z0-9_.-]*\)$/\1/p')
git checkout -q -- .
if [ -n "$added" ]; then python -m pip uninstall -q -y $added; fi

python3 - "$role" "$shard" "$change" "$label" "$status" "$installed" \
  "$t_start" "$t_fetched" "$t_setup" "$t_done" <<'EOF'
import json, sys
role, shard, change, label, status, installed, t0, t1, t2, t3 = sys.argv[1:]
t0, t1, t2, t3 = map(float, (t0, t1, t2, t3))
print(json.dumps({
    "role": role, "shard": None if shard == "-" else int(shard),
    "change": change, "label": label, "exit_code": int(status),
    "installed": installed == "true",
    "fetch_s": round(t1 - t0, 2), "setup_s": round(t2 - t1, 2),
    "work_s": round(t3 - t2, 2), "total_s": round(t3 - t0, 2),
}))
EOF
