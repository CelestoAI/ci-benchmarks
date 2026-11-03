# Celesto CI cache tests

Workflows that check the Celesto CI cache end to end on Celesto runners: the
dependency cache (`actions/cache`, `setup-node`), the Docker layer cache
(BuildKit `type=gha`), and cache isolation between branches, pull requests and
repositories. Each check fails its job when the cache does the wrong thing.

Every job runs twice, side by side: on a GitHub-hosted runner
(`ubuntu-24.04`, GitHub's cache) and on a Celesto runner (Celesto's cache).
The same checks must pass on both. Set the `providers` input to
`["celesto"]` or `["github"]` to run only one.

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

| Workflow | Job | Checks |
| --- | --- | --- |
| Cache tests - dependency | VM cache | `setup-node` npm cache; exact restore; restore by prefix through `restore-keys`; restored content matches |
| | Job container cache | `actions/cache` inside `container: node:22` saves and restores |
| | Artifacts | upload in one job, download in a later job, with the cache on |
| Cache tests - Docker | build-push-action | save; every build step `CACHED` on verify |
| | run step | buildx from a `run:` step after `ghaction-github-runtime` |
| | parallel | four jobs save the same layers at once; all pass |
| | large layer | a 400 MB layer saves and restores `CACHED` |
| Cache tests - isolation | branch-scoped `actions/cache` | `main`, `cache-test-a`, `cache-test-b` save the same key; each restores only its own content (a branch may fall back to `main`) |
| | branch-scoped Docker layers | the same Docker cache scope on each branch; each image holds only its own branch's content |
| | another repository | a key saved only by another repository misses (`foreign_key`) |
| | pull request | a pull request saves under its own scope and still reads `main`; `main` never reads the pull request's entry |

These scoping rules are the same as GitHub's own Actions cache.

## Safety

The workflows run only from **Run workflow**, except the pull-request job,
which runs only for pull requests from branches of this repository; pull
requests from forks never reach Celesto runners.
