# Runner comparison

Updated 2026-11-14. All runners: 4 vCPU, x64. Values are p50 (medians).

The summary shows p50 times across successful jobs, in minutes and seconds. Lower is faster. Cache time includes save and restore. Workload times exclude queue time and runner overhead. Queue shows the wait from job creation to runner start for a burst of 15 jobs.

RunsOn’s [public dashboard](https://runs-on.com/benchmarks/runners/) lets readers choose build-step, whole-job, or wait-plus-job timing. These build columns use workload phases only; they exclude queue time and runner overhead.

- **Celesto:** this repository's [runner suites](../../docs/suites.md), last 30 days of runs.
- **RunsOn:** its suggested 4 vCPU x64 default, m8a.xlarge on EBS gp3, from [public benchmark data](https://github.com/runs-on-demo/benchmark-public), last 30 days.
- **Other providers:** [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public), last 30 days. Same workloads and settings, measured by runs-on.com on their accounts.

![p50 workload and queue times by provider; lower is faster](summary-light.svg#gh-light-mode-only)
![p50 workload and queue times by provider; lower is faster](summary-dark.svg#gh-dark-mode-only)

## Rust

Build and test spotify-player.

![Rust: build and test spotify-player](rust-light.svg#gh-light-mode-only)
![Rust: build and test spotify-player](rust-dark.svg#gh-dark-mode-only)

Jobs: Celesto 10, GitHub 10, RunsOn m8a.xlarge 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Latest Celesto run: 2026-11-14.

## Node

Install and typecheck opencode.

![Node: install and typecheck opencode](node-light.svg#gh-light-mode-only)
![Node: install and typecheck opencode](node-dark.svg#gh-dark-mode-only)

Jobs: Celesto 7, GitHub 6, RunsOn m8a.xlarge 6, Blacksmith 6, Namespace 6, WarpBuild 6, Ubicloud 6. Latest Celesto run: 2026-11-14.

## Docker

Build the PostHog image.

![Docker: build the PostHog image](docker-light.svg#gh-light-mode-only)
![Docker: build the PostHog image](docker-dark.svg#gh-dark-mode-only)

Jobs: Celesto 5, GitHub 11, RunsOn m8a.xlarge 10, Blacksmith 11, WarpBuild 10, Ubicloud 11, Namespace 10. Latest Celesto run: 2026-11-14.

## Cache

Save and restore 4 GiB.

![Cache: save and restore 4 GiB](cache-light.svg#gh-light-mode-only)
![Cache: save and restore 4 GiB](cache-dark.svg#gh-dark-mode-only)

Jobs: Celesto 15, GitHub 9, Blacksmith 9, Namespace 9, WarpBuild 9, Ubicloud 9, RunsOn m8a.xlarge 5. Latest Celesto run: 2026-11-14.

## Hardware

Higher is better, except `docker pull`. ↑ / ↓: better / worse than GitHub by more than 10 %.

| | **Celesto** | GitHub | RunsOn m8a.xlarge | Blacksmith | Namespace | WarpBuild | Ubicloud |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU single-thread (PassMark) | **2,559 ↓** | 2,895 | 3,809 ↑ | 4,174 ↑ | 4,628 ↑ | 4,255 ↑ | 2,903 |
| CPU all cores (PassMark CPU Mark) | **9,469 ↑** | 7,511 | 13,481 ↑ | 14,348 ↑ | 15,902 ↑ | 11,274 ↑ | 8,815 ↑ |
| CPU all cores (sysbench, events/s) | **16,575 ↑** | 8,872 | 20,209 ↑ | 23,947 ↑ | 27,110 ↑ | 13,216 ↑ | 13,277 ↑ |
| Memory read | **2,152 MiB/s ↓** | 24,633 MiB/s | 37,495 MiB/s ↑ | 39,304 MiB/s ↑ | 45,745 MiB/s ↑ | 37,578 MiB/s ↑ | 21,119 MiB/s ↓ |
| Disk sequential read | **2,961 MiB/s ↑** | 394 MiB/s | 401 MiB/s | 7,216 MiB/s ↑ | 5,077 MiB/s ↑ | 4,537 MiB/s ↑ | 2,553 MiB/s ↑ |
| Disk random write, 4 KiB | **4,263 IOPS ↓** | 11,446 IOPS | 2,991 IOPS ↓ | 218,915 IOPS ↑ | 556,952 IOPS ↑ | 70,585 IOPS ↑ | 20,472 IOPS ↑ |
| Disk write + fsync, 4 KiB | **1,800 IOPS ↓** | 4,266 IOPS | 540 IOPS ↓ | 17,729 IOPS ↑ | 28,162 IOPS ↑ | 2,469 IOPS ↓ | 1,771 IOPS ↓ |
| docker pull | **12 s ↑** | 16 s | 5 s ↑ | 8 s ↑ | 3 s ↑ | 10 s ↑ | 18 s |
| PostgreSQL read-write (pgbench) | – | 4,458 TPS | 3,283 TPS ↓ | 11,739 TPS ↑ | 12,873 TPS ↑ | 3,389 TPS ↓ | 2,066 TPS ↓ |

Jobs: Celesto 6, GitHub 10, RunsOn m8a.xlarge 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Latest Celesto run: 2026-11-14.
