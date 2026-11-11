# Runner suites

Six GitHub Actions workflows that measure a CI runner on real work. Each one builds or tests a public project at a pinned commit, so a change in the numbers comes from the runner, not from the code.

## Suites

| Suite | What runs | Jobs | Typical time |
| --- | --- | ---: | --- |
| [Hardware](../.github/workflows/suite-hardware.yml) | CPU (sysbench, 7-Zip, PassMark), memory bandwidth, disk (fio), downloads, `docker pull`, PostgreSQL (pgbench) | 3 | 10 min |
| [Cache](../.github/workflows/suite-cache.yml) | Save a 4 GiB file with `actions/cache`, delete it, restore it | 3 | 3 min |
| [Rust](../.github/workflows/suite-rust.yml) | [aome510/spotify-player](https://github.com/aome510/spotify-player) `7dc9d17`: `cargo fmt`, `cargo test`, two `cargo clippy` passes, Rust 1.98.1 | 3 | 5 min |
| [Node](../.github/workflows/suite-node.yml) | [anomalyco/opencode](https://github.com/anomalyco/opencode) `08fb473`: `bun install`, `turbo typecheck`, Bun 1.3.14 | 3 | 3 min |
| [Docker](../.github/workflows/suite-docker.yml) | [PostHog](https://github.com/PostHog/posthog) `ba81ecf`: `docker buildx build` of the production Dockerfile, no build cache | 3 | 15 min |
| [Burst](../.github/workflows/suite-burst.yml) | 15 jobs queued at the same moment, each holds its runner for 60 s | 15 | 5 min |

Every job starts cold: no cache, no previous build. Each job checks that the runner has 4 CPUs and at least 14 GiB RAM, and fails if not.

## Schedule

Each suite runs every three days at a fixed time (UTC):

| Day 1, 4, 7, … | Day 2, 5, 8, … | Day 3, 6, 9, … |
| --- | --- | --- |
| Rust 02:00, Node 04:00, Docker 06:00 | Hardware 02:00, Cache 04:00 | Burst 15:00 |

Every day at 18:00, the [Comparison](../.github/workflows/compare.yml) workflow pools the last 30 days of results for Celesto and other providers and updates [results/latest](../results/latest/README.md).

## Run a suite

1. [Fork this repository](https://github.com/CelestoAI/ci-benchmarks/fork) and enable **Actions** in the fork.
2. Install the [Celesto CI app](https://github.com/apps/celesto-ci) on the fork. The workspace needs credit for the **Large** runner.
3. Open **Actions**, select a suite (for example **Rust benchmark**), and click **Run workflow** on `main`.

Rust, Node, Docker, Cache and Hardware default to three benchmark jobs per run. For manual runs, **Number of benchmark jobs** can be set to one or two to fill a sample-count gap. Burst always queues 15 jobs together.

Run one suite at a time. Suites that run together share the same runner capacity and slow each other down.

### Run on a different runner

In the workflow, change `runs-on` in both jobs (`bench` and `collect`) to your runner's labels, and `provider` to a name for the runner. The name labels the jobs and the results.

```yaml
      matrix:
        provider: [github]
        iteration: [1, 2, 3]
    runs-on: ubuntu-24.04
```

Use a runner with 4 vCPU and 16 GiB RAM, or change the check in [`scripts/record-event.mjs`](../scripts/record-event.mjs). On GitHub-hosted runners, only public repositories get 4 vCPU on `ubuntu-24.04`.

## Results

Each run has a `collect` job at the end. It writes:

- **Run summary:** a table with the median time of each phase.
- **Artifact `results-<suite>.json`:** every job's raw data.

```jsonc
{
  "suite": "rust",
  "run": { "id": 123, "attempt": 1, "repository": "you/ci-benchmarks", "date": "2026-11-11" },
  "results": [
    {
      "provider": "celesto",
      "iteration": 1,
      "status": "success",          // success, failure, cancelled or unavailable
      "failedAt": null,             // first phase that failed
      "runner": "…",
      "queueSeconds": 19,           // job created → job started
      "jobSeconds": 205,            // job started → job finished
      "workloadSeconds": 177,       // sum of the phases
      "phases": [{ "name": "cargo test", "seconds": 99, "status": "success" }],
      "metrics": null               // hardware suite only
    }
  ]
}
```

### How times are measured

Times come from the GitHub Jobs API, not from inside the job, so a runner cannot misreport its own speed.

- **Queue:** from when GitHub created the job to when a runner started it.
- **Phase:** each step named `phase: …`, from its start to its end.
- **Workload:** the sum of the phases. Setup steps (host check, uploads) are not counted.

The hardware suite also writes its measurements to `metrics`. If one test group fails (for example, `pgbench` is missing), the job stays green, the run shows a warning, and the other groups keep their numbers.

## Hardware tests

| Group | Tool and settings | Unit |
| --- | --- | --- |
| cpu | `sysbench cpu`, 20 s, 1 thread and all threads; `7z b` | events/s, MIPS |
| passmark | PassMark PerformanceTest V11, `pt_linux -r 1 -i 2 -p <vCPUs> -d 2` | single-thread score, CPU Mark |
| memory | `sysbench memory`, read and write, all threads, 15 s | MiB/s |
| disk | fio in the job workspace, `direct=1`, 20 s each: sequential 1 MiB (QD32), random 4 KiB (QD32 × 4 jobs), random 4 KiB read (QD1), 4 KiB write + `fdatasync` | MiB/s, IOPS, p99 µs |
| network | `curl` download of a Linux kernel tarball (CDN) and a Bun release (GitHub) | MiB/s |
| docker | `docker pull node:24-bookworm`, then `docker run` | seconds |
| postgres | PostgreSQL 16 in Docker, `pgbench -s 50`, 10 clients, 30 s, read-only and read-write | TPS |

## Limits

- Three jobs per suite. Repeat runs on different days before you draw a conclusion.
- Results depend on the runner's region, time of day and load.
- The workloads are cold builds. They do not show how a provider's cache speeds up repeat builds.
