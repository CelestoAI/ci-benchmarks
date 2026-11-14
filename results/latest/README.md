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
| CPU single-thread (PassMark) | **2,559 ↓** | 2,886 | 3,809 ↑ | 4,297 ↑ | 4,629 ↑ | 4,225 ↑ | 2,899 |
| CPU all cores (PassMark CPU Mark) | **9,469 ↑** | 7,522 | 13,455 ↑ | 14,701 ↑ | 15,926 ↑ | 11,304 ↑ | 9,972 ↑ |
| CPU all cores (sysbench, events/s) | **16,575 ↑** | 9,540 | 20,197 ↑ | 24,684 ↑ | 27,132 ↑ | 13,287 ↑ | 16,957 ↑ |
| Memory read | **2,152 MiB/s ↓** | 26,204 MiB/s | 37,492 MiB/s ↑ | 41,649 MiB/s ↑ | 45,820 MiB/s ↑ | 38,231 MiB/s ↑ | 21,174 MiB/s ↓ |
| Disk sequential read | **2,961 MiB/s ↑** | 394 MiB/s | 401 MiB/s | 6,780 MiB/s ↑ | 5,081 MiB/s ↑ | 4,686 MiB/s ↑ | 2,569 MiB/s ↑ |
| Disk random write, 4 KiB | **4,263 IOPS ↓** | 11,256 IOPS | 2,991 IOPS ↓ | 220,196 IOPS ↑ | 559,921 IOPS ↑ | 71,139 IOPS ↑ | 19,414 IOPS ↑ |
| Disk write + fsync, 4 KiB | **1,800 IOPS ↓** | 4,328 IOPS | 540 IOPS ↓ | 17,872 IOPS ↑ | 28,491 IOPS ↑ | 2,395 IOPS ↓ | 1,826 IOPS ↓ |
| docker pull | **12 s ↑** | 16 s | 5 s ↑ | 8 s ↑ | 3 s ↑ | 10 s ↑ | 17 s |
| PostgreSQL read-write (pgbench) | – | 3,925 TPS | 3,304 TPS ↓ | 11,759 TPS ↑ | 13,386 TPS ↑ | 3,236 TPS ↓ | 2,079 TPS ↓ |

Jobs: Celesto 6, GitHub 9, RunsOn m8a.xlarge 9, Blacksmith 9, Namespace 9, WarpBuild 9, Ubicloud 9. Latest Celesto run: 2026-11-14.
