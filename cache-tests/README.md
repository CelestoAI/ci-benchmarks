# Celesto CI cache acceptance tests

Workflows that check the Celesto CI cache end to end on real Celesto runners:
the dependency cache (`actions/cache`, `setup-node`), the Docker layer cache
(BuildKit `type=gha`), and cache isolation between branches, pull requests and
repositories. Each check fails its job when the cache does the wrong thing.

The test plans are in the backend repository:
`docs/designs/ci-actions-cache.md` (dependency cache) and
`docs/designs/ci-docker-layer-cache.md` (Docker layer cache).

## Run everything

```sh
cache-tests/run.sh CelestoAI/ci-benchmarks celesto
```

The script uses a new key, runs each workflow in order (save, then verify),
creates the branches `cache-test-a` and `cache-test-b` from `main`, and stops
at the first failure. A full run takes about 30 minutes. Each workflow can
also be run alone from **Actions** with **Run workflow** (use the same `key`
for `save` and `verify`).

## What each workflow checks

| Workflow | Job | Checks | Plan item |
| --- | --- | --- | --- |
| Cache tests - dependency | VM cache | JavaScript actions get the proxy URL; runner self-update is off; `setup-node` npm cache; exact restore; restore by prefix through `restore-keys` | dependency A-01, A-02, A-04 |
| | Job container cache | `actions/cache` inside `container: node:22` saves and restores | Docker A-03 |
| | Artifacts | upload in one job, download in a later job, with the cache on | dependency A-06 |
| Cache tests - Docker | build-push-action | link-local proxy, firewall rule and hosts entry; save; every step `CACHED` on verify | Docker A-01, A-02 |
| | run step | buildx from a `run:` step after `ghaction-github-runtime` | Docker A-04 |
| | parallel | four jobs save the same layers at once; all pass | Docker A-05 |
| | large layer | a 400 MB layer saves (multi-part upload) and restores `CACHED` | Docker A-08 |
| | container access | a Docker action gets `ACTIONS_RESULTS_URL=http://169.254.77.1:8448/` | Docker A-03 |
| | no secret | 300 uploads without the reservation secret all get 403; restored data matches its hash | Docker A-09 |
| Cache tests - isolation | branch-scoped `actions/cache` | `main`, `cache-test-a`, `cache-test-b` save the same key; each restores only its own content (a branch may fall back to `main`) | dependency A-05 |
| | branch-scoped Docker layers | the same Docker scope on each branch; each image holds only its own branch's content | Docker isolation |
| | tampered token | a runtime token edited to claim another branch gets no entry | isolation |
| | another repository | a key saved only by another repository misses (`foreign_key`) | isolation |
| | pull request | a pull request saves under its own scope and still reads `main`; `main` never reads the pull request's entry | dependency A-05 |

Not covered here (operator or control-plane checks): cache API outage, provider
safety valve, the storage sweep, the runner-release alert, the save rate limit
(it needs `RATE_LIMIT_ENABLED=true` on the control plane), and an index that
names a deleted layer (it needs an operator to delete one entry).

## Evidence in Axiom

Every cache call logs one `CI cache call` line on the control plane, with
`operation`, `outcome` and `reason`. For example, after the isolation workflow
the tampered tokens show as `reason = invalid_token`:

```
['controlplane-prod']
| where body == "CI cache call"
| summarize count() by tostring(['attributes.celesto']['operation']),
    tostring(['attributes.celesto']['outcome']), tostring(['attributes.celesto']['reason'])
```

## Safety

The workflows run only from **Run workflow**, except the pull-request job,
which runs only for pull requests from branches of this repository; pull
requests from forks never reach Celesto runners.
