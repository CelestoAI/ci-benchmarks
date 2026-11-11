# CI benchmarks

Benchmarks for GitHub Actions runners. Every workflow, script and raw result is in this repository, so you can check the numbers or run them on your own runners.

## Benchmarks

| Benchmark | What it measures | Guide | Results |
| --- | --- | --- | --- |
| Runner suites | Real builds of public projects (Rust, Node, Docker), a 4 GiB cache, hardware tests and a burst of 15 jobs | [docs/suites.md](docs/suites.md) | Each run's summary and artifacts |
| Matched CPU and cache | CPU throughput and a 512 MiB cache, GitHub-hosted and Celesto Large side by side | [docs/matched.md](docs/matched.md) | [Nov 2, 2026](results/2026-11-02-matched/README.md) |
| Docker | Image builds, layer caches and a Python API with PostgreSQL | [docker-bench/README.md](docker-bench/README.md) | [Oct 17, 2026](results/docker-2026-10-17/README.md) |

## Run a benchmark

1. [Fork this repository](https://github.com/CelestoAI/ci-benchmarks/fork) and enable **Actions** in the fork.
2. Install the [Celesto CI app](https://github.com/apps/celesto-ci) on the fork and connect it to a workspace with credit for the **Large** runner.
3. Open **Actions**, pick a workflow, and click **Run workflow** on `main`.

To use a different runner, change `runs-on` in the workflow. Each guide says what else to change.

## Problems

| Symptom | Check |
| --- | --- |
| No **Run workflow** button | You need write access. In a fork, enable Actions first. |
| Celesto job stays queued | Open the commit's **Celesto runner setup** check: app access, workspace connection, Large credit. |
| Host check fails | The runner must have 4 CPUs and at least 14 GiB RAM. |

[Open an issue](https://github.com/CelestoAI/ci-benchmarks/issues/new) with the run URL, job name and error.

## License

[MIT](LICENSE)
