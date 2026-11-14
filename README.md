# Celesto CI Benchmark

Open benchmarks for GitHub Actions runners. Real builds of public projects, pinned to a commit, run on a schedule. Every workflow, script and raw result is in this repository.

## Latest results

Latest available run per provider and suite. Provider run dates vary; the queue column is the p50 of the latest 15-job burst. Lower is faster.

![Latest-run workload and queue times by provider; lower is faster](results/2026-11-14-latest-run/summary-light-on-demand.svg#gh-light-mode-only)
![Latest-run workload and queue times by provider; lower is faster](results/2026-11-14-latest-run/summary-dark-on-demand.svg#gh-dark-mode-only)

| Suite | Workload |
| --- | --- |
| Rust | Cold `cargo test` and `clippy` of [spotify-player](https://github.com/aome510/spotify-player) |
| Node | Cold `bun install` and typecheck of [opencode](https://github.com/anomalyco/opencode) |
| Docker | `docker buildx build` of [PostHog](https://github.com/PostHog/posthog)'s production image, no cache |
| Cache | Save and restore a 4 GiB file with `actions/cache` |
| Queue | Wait from job creation to runner start when 15 jobs are queued at once |

All rows are 4 vCPU (x64). RunsOn is represented by its suggested 4-vCPU default, m8a.xlarge on EBS gp3. Celesto results come from this repository's [runner suites](docs/suites.md); other results come from the [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public).

Build and cache values use workload phase times; cache includes save and restore. Queue is measured from job creation to runner start. The price column shows published USD per running minute, not each job’s actual cost; RunsOn uses the on-demand (non-spot) rate of $0.0044/min for its 4-vCPU m8a.xlarge runner. The separate [rolling 30-day p50 archive](results/latest/README.md) is available for historical context.

**[Latest-run comparison (Nov 14, all providers; timings, hardware, and source run links) →](results/2026-11-14-latest-run/README.md)**

## Benchmarks in this repository

| Benchmark | What it measures | Guide |
| --- | --- | --- |
| Runner suites | Rust, Node and Docker builds, a 4 GiB cache, hardware tests and a burst of 15 jobs | [docs/suites.md](docs/suites.md) |
| Matched CPU and cache | CPU throughput and a 512 MiB cache on GitHub-hosted and Celesto side by side ([Nov 2 results](results/2026-11-02-matched/README.md)) | [docs/matched.md](docs/matched.md) |
| Docker | Image builds, layer caches, and a Python API with PostgreSQL ([Oct 17 results](results/docker-2026-10-17/README.md)) | [docker-bench/README.md](docker-bench/README.md) |

## Run it yourself

1. [Fork this repository](https://github.com/CelestoAI/ci-benchmarks/fork) and enable **Actions** in the fork.
2. Install the [Celesto CI app](https://github.com/apps/celesto-ci) on the fork, with a workspace that has credit for the **Large** runner.
3. Open **Actions**, pick a workflow, and click **Run workflow**.

To test another runner, change `runs-on` in the workflow. [docs/suites.md](docs/suites.md) explains the rest.

## License

[MIT](LICENSE)
