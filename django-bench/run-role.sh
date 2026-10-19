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
