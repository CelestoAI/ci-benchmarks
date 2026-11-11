# Celesto CI Benchmark

Open benchmarks for GitHub Actions runners. Real builds of public projects, pinned to a commit, run on a schedule. Every workflow, script and raw result is in this repository.

## Latest results

How fast each provider runs each suite, compared with GitHub-hosted runners (1.0×). Higher is faster.

![Speed of each provider relative to GitHub-hosted runners](results/latest/summary-light.svg#gh-light-mode-only)
![Speed of each provider relative to GitHub-hosted runners](results/latest/summary-dark.svg#gh-dark-mode-only)

| Suite | Workload |
| --- | --- |
| Rust | Cold `cargo test` and `clippy` of [spotify-player](https://github.com/aome510/spotify-player) |
| Node | Cold `bun install` and typecheck of [opencode](https://github.com/anomalyco/opencode) |
| Docker | `docker buildx build` of [PostHog](https://github.com/PostHog/posthog)'s production image, no cache |
| Cache | Save and restore a 4 GiB file with `actions/cache` |

All runners have 4 vCPU (x64). Celesto results come from this repository's [runner suites](docs/suites.md). Other providers' results come from the [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public), which uses the same workloads and settings. Updated daily.

**[Full results: time per phase and hardware →](results/latest/README.md)**

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
