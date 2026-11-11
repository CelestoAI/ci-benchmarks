# Runner comparison

Updated 2026-11-11. All runners: 4 vCPU, x64. Each bar is a median.

- **Celesto:** this repository's [runner suites](../../docs/suites.md), latest run of each suite (3 jobs; 15 for burst).
- **Other providers:** [runs-on.com public benchmark data](https://github.com/runs-on-demo/benchmark-public) from the last 30 days. Same workloads and settings; measured by runs-on.com on their accounts.

## Rust

Celesto run: 2026-11-11.

![Rust build and test (spotify-player)](rust-1.svg)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10.

## Node

Celesto run: 2026-11-11.

![Node install and typecheck (opencode)](node-1.svg)

![bun install](node-2.svg)

Jobs: Celesto 3, GitHub 13, Blacksmith 13, Namespace 13, WarpBuild 13, Ubicloud 13.

## Docker

Celesto run: 2026-11-11.

![Docker image build (PostHog)](docker-1.svg)

Jobs: Celesto 2, GitHub 11, Blacksmith 11, Namespace 10, WarpBuild 10, Ubicloud 11.

## Cache

Celesto run: 2026-11-11.

![Cache save, 4 GiB](cache-1.svg)

![Cache restore, 4 GiB](cache-2.svg)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10.

## Burst

Celesto run: 2026-11-11.

![Queue time, 15 jobs at once (median)](burst-1.svg)

![Queue time, 15 jobs at once (slowest)](burst-2.svg)

Jobs: Celesto 15, GitHub 120, Blacksmith 120, Namespace 120, WarpBuild 120, Ubicloud 120.

## Hardware

Celesto run: 2026-11-11.

![CPU single-thread (PassMark)](hardware-1.svg)

![CPU all cores (PassMark CPU Mark)](hardware-2.svg)

![Memory read](hardware-3.svg)

![Disk sequential read](hardware-4.svg)

![Disk random write, 4 KiB](hardware-5.svg)

![Disk write + fsync, 4 KiB](hardware-6.svg)

Jobs: Celesto 3, GitHub 10, Blacksmith 10, Namespace 10, WarpBuild 10, Ubicloud 10.
