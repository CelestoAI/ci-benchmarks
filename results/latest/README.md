# Runner comparison

Updated 2026-11-11. All runners: 4 vCPU, x64. Values are medians.

- **Celesto:** this repository's [runner suites](../../docs/suites.md), latest run of each suite.
- **Other providers:** [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public), last 30 days. Same workloads and settings, measured by runs-on.com on their accounts.

![Speed relative to GitHub](summary-light.svg#gh-light-mode-only)
![Speed relative to GitHub](summary-dark.svg#gh-dark-mode-only)

## Rust

Build and test spotify-player.

![Rust: build and test spotify-player](rust-light.svg#gh-light-mode-only)
![Rust: build and test spotify-player](rust-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Celesto run: 2026-11-11.

## Node

Install and typecheck opencode.

![Node: install and typecheck opencode](node-light.svg#gh-light-mode-only)
![Node: install and typecheck opencode](node-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 13, Blacksmith 13, Namespace 13, WarpBuild 13, Ubicloud 13. Celesto run: 2026-11-11.

## Docker

Build the PostHog image.

![Docker: build the PostHog image](docker-light.svg#gh-light-mode-only)
![Docker: build the PostHog image](docker-dark.svg#gh-dark-mode-only)

Jobs: Celesto 2, GitHub 11, Blacksmith 11, Namespace 10, WarpBuild 10, Ubicloud 11. Celesto run: 2026-11-11.

## Cache

Save and restore 4 GiB.

![Cache: save and restore 4 GiB](cache-light.svg#gh-light-mode-only)
![Cache: save and restore 4 GiB](cache-dark.svg#gh-dark-mode-only)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Celesto run: 2026-11-11.

## Hardware

Higher is better, except `docker pull`. ↑ / ↓: better / worse than GitHub by more than 10 %.

| | **Celesto** | GitHub | Blacksmith | Namespace | WarpBuild | Ubicloud |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU single-thread (PassMark) | **2,489 ↓** | 3,142 | 4,264 ↑ | 4,634 ↑ | 4,218 ↑ | 2,898 |
| CPU all cores (PassMark CPU Mark) | **9,012 ↑** | 7,884 | 14,730 ↑ | 15,965 ↑ | 11,274 ↑ | 9,881 ↑ |
| CPU all cores (sysbench, events/s) | **16,504 ↑** | 9,542 | 24,328 ↑ | 27,147 ↑ | 13,348 ↑ | 16,892 ↑ |
| Memory read | **2,137 MiB/s ↓** | 26,429 MiB/s | 39,304 MiB/s ↑ | 45,831 MiB/s ↑ | 37,578 MiB/s ↑ | 21,655 MiB/s ↓ |
| Disk sequential read | **1,941 MiB/s ↑** | 394 MiB/s | 6,739 MiB/s ↑ | 5,077 MiB/s ↑ | 4,697 MiB/s ↑ | 2,640 MiB/s ↑ |
| Disk random write, 4 KiB | **3,932 IOPS ↓** | 11,026 IOPS | 218,915 IOPS ↑ | 556,952 IOPS ↑ | 70,585 IOPS ↑ | 16,879 IOPS ↑ |
| Disk write + fsync, 4 KiB | **1,892 IOPS ↓** | 4,347 IOPS | 17,729 IOPS ↑ | 28,162 IOPS ↑ | 2,362 IOPS ↓ | 1,771 IOPS ↓ |
| docker pull | **13 s ↑** | 16 s | 8 s ↑ | 3 s ↑ | 10 s ↑ | 18 s |
| PostgreSQL read-write (pgbench) | – | 4,464 TPS | 11,739 TPS ↑ | 12,873 TPS ↑ | 3,107 TPS ↓ | 2,097 TPS ↓ |

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10. Celesto run: 2026-11-11.
