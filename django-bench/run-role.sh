#!/usr/bin/env bash
# Run one job's work against an installed Django checkout. The same script
# runs on GitHub runners, Celesto runners and warm Celesto computers, so the
# commands are identical everywhere.
#
# Usage: run-role.sh <django_dir> <role> [shard_index]
#   checks  Django's Python linters: flake8, isort, black (in sequence).
#   tests   The whole test suite (the single-job setup).
#   shard   One shard of the test suite (needs shard_index).
#   all     checks, then tests (the single-job setup).
#
# Everything runs pinned to two CPUs with taskset. ci-benchmarks is a public
# repository, where GitHub's standard runner has 4 vCPUs; boxd compared 2
# vCPU machines, so the GitHub jobs are held to 2 cores. On a 2 vCPU Celesto
# machine the pin changes nothing.
set -euo pipefail

django_dir=$1
role=$2
shard=${3:-}
here=$(cd "$(dirname "$0")" && pwd)
source "$here/bench.env"

# Two runner-image differences break Django's own tests (found on Celesto's
# github-ci image). Both fixes do nothing on GitHub's runners.
#
# 1. No system time-zone data: point glibc at the zoneinfo files shipped in
#    the tzdata wheel, which Django's requirements already install.
if [ ! -d /usr/share/zoneinfo ] && [ -z "${TZDIR:-}" ]; then
  TZDIR=$(python -c 'import os, tzdata; print(os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo"))')
  export TZDIR
fi
# 2. The job runs as root, so Django's "file is not writable" tests cannot
#    fail the way they expect. Re-run this script as a normal user, keeping
#    the job's PATH (setup-python's interpreter) and TZDIR.
if [ "$(id -u)" = 0 ]; then
  chmod 1777 /dev/shm
  id ciuser >/dev/null 2>&1 || useradd -m ciuser
  chown -R ciuser: "$django_dir" "$here"
  env_args=(PATH="$PATH" HOME=/home/ciuser)
  [ -n "${TZDIR:-}" ] && env_args+=(TZDIR="$TZDIR")
  exec runuser -u ciuser -- env "${env_args[@]}" bash "$here/run-role.sh" "$@"
fi

cd "$django_dir"

pin() { taskset -c 0,1 "$@"; }

checks() {
  # Same commands as Django's .github/workflows/linters.yml.
  pin flake8
  pin isort --check --diff django tests scripts
  pin black --check --diff .
}

tests() {
  # --parallel 2 matches the two pinned CPUs. Django's CI also runs -Wall.
  # $* is the list of test modules; empty means the whole suite.
  pin python -Wall tests/runtests.py --parallel 2 -v1 "$@"
}

case "$role" in
  checks) checks ;;
  tests) tests ;;
  shard)
    # shellcheck disable=SC2046  # the module list is meant to word-split
    tests $(python "$here/shard.py" "$django_dir" "$shard" "$SHARDS")
    ;;
  all) checks; tests ;;
  *) echo "unknown role: $role" >&2; exit 2 ;;
esac
