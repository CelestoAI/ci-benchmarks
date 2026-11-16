# Runner comparison

Updated 2026-11-16. All runners: 4 vCPU, x64. Values are p50 (medians).

The summary shows p50 times across successful jobs, in minutes and seconds. Lower is faster. Cache time includes save and restore. Workload times exclude queue time and runner overhead. Queue shows the wait from job creation to runner start for a burst of 15 jobs. Price / min is each provider’s published USD rate per running minute for a 4 vCPU x64 runner, not the cost of a job; Namespace is its overage rate.

RunsOn’s [public dashboard](https://runs-on.com/benchmarks/runners/) lets readers choose build-step, whole-job, or wait-plus-job timing. These build columns use workload phases only; they exclude queue time and runner overhead.

- **Celesto:** this repository's [runner suites](../../docs/suites.md), last 30 days of runs.
- **RunsOn:** its suggested 4 vCPU x64 default, m8a.xlarge on EBS gp3, from [public benchmark data](https://github.com/runs-on-demo/benchmark-public), last 30 days.
- **Other providers:** [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public), last 30 days. Same workloads and settings, measured by runs-on.com on their accounts.

![p50 workload and queue times by provider; lower is faster](summary-light.svg#gh-light-mode-only)
![p50 workload and queue times by provider; lower is faster](summary-dark.svg#gh-dark-mode-only)

## Cost per run

Estimated cost of one run: the provider’s published price per running minute times its p50 workload time. Lower is cheaper. Billing rounding, queue time and runner overhead are not included, so real invoices differ. *Namespace is its overage rate. RunsOn is its on-demand rate; its benchmark jobs mostly run on cheaper spot instances.

| Provider | Price / min | Rust | Node | Docker | Cache |
| --- | ---: | ---: | ---: | ---: | ---: |
| GitHub | $0.0120 | $0.0436 | $0.0208 | $0.1562 | $0.0148 |
| **Celesto** | $0.0013 | $0.0040 | $0.0018 | $0.0120 | $0.0006 |
| Blacksmith | $0.0080 | $0.0146 | $0.0105 | $0.0422 | $0.0024 |
| Namespace | $0.0120* | $0.0190 | $0.0090 | $0.0568 | $0.0076 |
| RunsOn m8a.xlarge | $0.0044 | $0.0079 | $0.0046 | $0.0396 | $0.0024 |
| Ubicloud | $0.0025 | $0.0063 | $0.0040 | $0.0300 | $0.0051 |
| WarpBuild | $0.0080 | $0.0184 | $0.0097 | $0.0595 | $0.0053 |

## Rust

Build and test spotify-player.

![Rust: build and test spotify-player](rust-light.svg#gh-light-mode-only)
![Rust: build and test spotify-player](rust-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 10, RunsOn m8a.xlarge 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Latest Celesto run: 2026-11-16.

## Node

Install and typecheck opencode.

![Node: install and typecheck opencode](node-light.svg#gh-light-mode-only)
![Node: install and typecheck opencode](node-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 7, RunsOn m8a.xlarge 7, Blacksmith 7, Namespace 7, WarpBuild 7, Ubicloud 7. Latest Celesto run: 2026-11-16.

## Docker

Build the PostHog image.

![Docker: build the PostHog image](docker-light.svg#gh-light-mode-only)
![Docker: build the PostHog image](docker-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 9, Ubicloud 10, RunsOn m8a.xlarge 9. Latest Celesto run: 2026-11-16.

## Cache

Save and restore 4 GiB.

![Cache: save and restore 4 GiB](cache-light.svg#gh-light-mode-only)
![Cache: save and restore 4 GiB](cache-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 9, Blacksmith 9, Namespace 9, WarpBuild 9, Ubicloud 9, RunsOn m8a.xlarge 6. Latest Celesto run: 2026-11-16.

## Hardware

Higher is better, except `docker pull`. ↑ / ↓: better / worse than GitHub by more than 10 %.

| | **Celesto** | GitHub | RunsOn m8a.xlarge | Blacksmith | Namespace | WarpBuild | Ubicloud |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU single-thread (PassMark) | **2,411 ↓** | 2,904 | 3,809 ↑ | 4,297 ↑ | 4,627 ↑ | 4,225 ↑ | 2,899 |
| CPU all cores (PassMark CPU Mark) | **8,823 ↑** | 7,522 | 13,455 ↑ | 14,701 ↑ | 15,926 ↑ | 11,244 ↑ | 7,659 |
| CPU all cores (sysbench, events/s) | **11,796 ↑** | 9,540 | 20,220 ↑ | 24,684 ↑ | 27,088 ↑ | 13,145 ↑ | 9,598 |
| Memory read | **21,814 MiB/s ↓** | 26,204 MiB/s | 37,492 MiB/s ↑ | 41,649 MiB/s ↑ | 45,671 MiB/s ↑ | 36,925 MiB/s ↑ | 21,065 MiB/s ↓ |
| Disk sequential read | **4,713 MiB/s ↑** | 394 MiB/s | 401 MiB/s | 6,780 MiB/s ↑ | 5,081 MiB/s ↑ | 4,389 MiB/s ↑ | 2,569 MiB/s ↑ |
| Disk random write, 4 KiB | **246,806 IOPS ↑** | 11,256 IOPS | 2,991 IOPS ↓ | 217,634 IOPS ↑ | 559,921 IOPS ↑ | 71,139 IOPS ↑ | 21,529 IOPS ↑ |
| Disk write + fsync, 4 KiB | **18,846 IOPS ↑** | 4,203 IOPS | 540 IOPS ↓ | 17,586 IOPS ↑ | 28,491 IOPS ↑ | 2,542 IOPS ↓ | 1,715 IOPS ↓ |
| docker pull | **9 s ↑** | 17 s | 5 s ↑ | 8 s ↑ | 3 s ↑ | 10 s ↑ | 18 s |
| PostgreSQL read-write (pgbench) | **5,601 TPS ↑** | 4,992 TPS | 3,262 TPS ↓ | 11,720 TPS ↑ | 13,386 TPS ↑ | 3,542 TPS ↓ | 2,052 TPS ↓ |

Jobs: Celesto 3, GitHub 9, RunsOn m8a.xlarge 9, Blacksmith 9, Namespace 9, WarpBuild 9, Ubicloud 9. Latest Celesto run: 2026-11-16.
