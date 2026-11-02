#!/usr/bin/env bash
# Run every Celesto CI cache acceptance test in order and stop at the first
# failure. Needs `gh` with write access to the repository.
#
#   cache-tests/run.sh [owner/repo] [runner-label] [foreign-key]
#
# foreign-key: a key that only ANOTHER repository saved with
# `Cache tests - isolation` (phase=save); it must miss here. Optional.
set -euo pipefail
repo=${1:-CelestoAI/ci-benchmarks}
runner=${2:-celesto}
foreign=${3:-}
key=t$(date +%s)
echo "repository=$repo runner=$runner key=$key"

# Run one workflow on a ref and wait for its result.
run() {
  local workflow=$1 ref=$2; shift 2
  local before
  before=$(gh run list --repo "$repo" --workflow "$workflow" --branch "$ref" -L 1 --json databaseId --jq '.[0].databaseId // 0')
  gh workflow run "$workflow" --repo "$repo" --ref "$ref" -f runner="$runner" -f key="$key" "$@"
  local id=$before
  while [ "$id" = "$before" ]; do sleep 5; id=$(gh run list --repo "$repo" --workflow "$workflow" --branch "$ref" -L 1 --json databaseId --jq '.[0].databaseId // 0'); done
  gh run watch "$id" --repo "$repo" --exit-status >/dev/null && echo "PASS $workflow $ref $* (run $id)" || { echo "FAIL $workflow $ref $* (run $id)"; exit 1; }
}

# Dependency and Docker cache: save, then verify the restore.
run cache-dependency.yml main -f phase=save
run cache-dependency.yml main -f phase=verify
run cache-docker.yml main -f phase=save
run cache-docker.yml main -f phase=verify

# Isolation: main and two branches save the same key and Docker scope.
for branch in cache-test-a cache-test-b; do
  gh api -X POST "repos/$repo/git/refs" -f ref="refs/heads/$branch" -f sha="$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)" >/dev/null 2>&1 \
    || gh api -X PATCH "repos/$repo/git/refs/heads/$branch" -f sha="$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)" -F force=true >/dev/null
done
for ref in main cache-test-a cache-test-b; do run cache-isolation.yml "$ref" -f phase=save; done
for ref in cache-test-a cache-test-b; do run cache-isolation.yml "$ref" -f phase=verify; done
run cache-isolation.yml main -f phase=verify -f foreign_key="$foreign"

echo "All cache tests passed (key $key)."
echo "Pull request scope (manual): open a pull request from a branch of $repo whose"
echo "last line of cache-tests/pr-scope/marker.txt is: $key"
echo "When its 'Cache tests - isolation' run passes, verify that main cannot see it:"
echo "  gh workflow run cache-isolation.yml --repo $repo --ref main -f runner=$runner -f key=$key -f phase=verify"
