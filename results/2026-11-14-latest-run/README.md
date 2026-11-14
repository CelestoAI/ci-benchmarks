# Latest-run provider comparison

Snapshot date: **November 14, 2026**. This archive uses the latest completed valid run available for each provider and suite, rather than a rolling p50.

Build and cache times are workload seconds. Cache includes save and restore. Burst is the median queue wait from the latest 15-job burst per provider. Hardware values are from each provider’s latest available hardware run. The comparisons use 4-vCPU x64 runners; RunsOn is its 4-vCPU `m8a.xlarge` EBS gp3 default.

Per-minute rates were checked on Nov 14, 2026. Celesto uses its published Large CI 4-vCPU/16-GB rate. Other providers use the RunsOn dashboard’s published x64 4-vCPU rates. These are published running rates, not the actual cost of the benchmark jobs.

RunsOn’s current cache bug window and obsolete Node typecheck samples are excluded, following its [published methodology](https://runs-on.com/benchmarks/methodology/). The public data is attributed to [runs-on-demo/benchmark-public](https://github.com/runs-on-demo/benchmark-public), source commit `5cbfb2c`.

![Latest-run build, cache, and queue times by provider](summary-light-2026-11-14.svg#gh-light-mode-only)
![Latest-run build, cache, and queue times by provider](summary-dark-2026-11-14.svg#gh-dark-mode-only)

## Latest workload runs

| Provider | Rust | Node | Docker | Cache save + restore | Burst queue p50 | Rate per minute |
|---|---:|---:|---:|---:|---:|---:|
| GitHub | 3m 35s | 1m 38s | 12m 59s | 1m 20s | 3s | $0.0120 |
| Celesto | 3m 28s | 1m 40s | 11m 10s | 47s | 16s | $0.00133333 |
| Blacksmith | 2m 02s | 50s | 5m 52s | 17s | 11s | $0.0080 |
| Namespace | 1m 31s | 44s | 4m 38s | 47s | 9s | $0.0120* |
| RunsOn | 1m 48s | 1m 03s | 9m 00s | 33s | 17s | $0.0012 spot |
| Ubicloud | 3m 04s | 1m 29s | 13m 11s | 1m 48s | 50s | $0.0025 |
| WarpBuild | 2m 35s | 1m 27s | 7m 26s | 32s | 10s | $0.0080 |

The burst p50 is computed over 15 jobs in that provider’s latest burst. Other suite values are one latest successful benchmark job per provider.

## Verified per-minute rate basis

| Provider | Published rate used | Source/method |
|---|---:|---|
| Celesto Large | $0.00133333/min | Large CI runner, 4 vCPU / 16 GB, on [Celesto CI pricing](https://celesto.ai/ci). |
| GitHub | $0.0120/min | 4 vCPU / 16 GB x64 on the [RunsOn provider price list](https://runs-on.com/benchmarks/?by=cost). |
| Blacksmith | $0.0080/min | 4 vCPU / 16 GB x64 on the RunsOn provider price list. |
| Namespace | $0.0120/min* | 4 vCPU x64 overage rate on the RunsOn provider price list. |
| RunsOn m8a.xlarge | $0.0012/min spot; $0.0044/min on-demand | The specific m8a.xlarge · EBS gp3 row in the RunsOn 4-vCPU x64 price table. Spot is the dashboard default; the chart shows spot. |
| Ubicloud | $0.0025/min | 4 vCPU / 16 GB x64 on the RunsOn provider price list. |
| WarpBuild | $0.0080/min | 4 vCPU / 16 GB x64 on the RunsOn provider price list. |

The m8a.xlarge-specific on-demand rate is `$0.0044/min`; `$0.0037/min` is RunsOn’s generic 4-vCPU x64 provider rate, not the price for this runner. Celesto Large is `$0.00133333/min` (equivalent to `$0.08/hour`). `*` Namespace is priced at its overage rate.

## Hardware: latest measurements

| Measurement | GitHub | Celesto | Blacksmith | Namespace | RunsOn | Ubicloud | WarpBuild |
|---|---:|---:|---:|---:|---:|---:|---:|
| CPU single-thread (PassMark) | 2,904 | 2,524 | 3,846 | 4,477 | 3,814 | 2,906 | 4,292 |
| CPU all-core (PassMark CPU Mark) | 7,318 | 9,521 | 13,601 | 15,090 | 13,515 | 7,611 | 11,113 |
| CPU all-core (sysbench) | 6,389 events/s | 16,958 events/s | 22,415 events/s | 26,027 events/s | 20,338 events/s | 9,574 events/s | 13,090 events/s |
| Memory read | 20,997 MiB/s | 1,979 MiB/s | 21,957 MiB/s | 42,433 MiB/s | 38,055 MiB/s | 20,712 MiB/s | 28,215 MiB/s |
| Disk sequential read | 394 MiB/s | 2,184 MiB/s | 7,653 MiB/s | 3,992 MiB/s | 401 MiB/s | 1,876 MiB/s | 4,180 MiB/s |
| Disk random write 4 KiB | 11,695 IOPS | 822 IOPS | 146,622 IOPS | 455,429 IOPS | 2,991 IOPS | 29,164 IOPS | 31,392 IOPS |
| Disk write + fsync 4 KiB | 3,423 IOPS | 1,708 IOPS | 14,080 IOPS | 19,603 IOPS | 536 IOPS | 1,314 IOPS | 3,436 IOPS |
| Docker image pull | 18 s | 13 s | 8 s | 4 s | 5 s | 22 s | 9 s |
| PostgreSQL read/write | 4,992 TPS | — | 9,463 TPS | 11,134 TPS | 3,244 TPS | 1,880 TPS | 4,701 TPS |

A dash means that the latest run did not produce that metric. Celesto’s latest hardware run recorded a PostgreSQL client error, so its PostgreSQL cell is unavailable.

## Source runs

| Provider | Rust | Node | Docker | Cache | Hardware | Burst |
|---|---:|---:|---:|---:|---:|---:|
| GitHub | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43244114191) |
| Celesto | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43541459727) | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43541883724) | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43542132511) | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43543299650) | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43543451248) | [2026-11-14](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43544242821) |
| Blacksmith | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43244114191) |
| Namespace | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43244114191) |
| RunsOn | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43245321021) |
| Ubicloud | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43244114191) |
| WarpBuild | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43350020470) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43363107291) | [2026-11-13](https://github.com/runs-on-demo/benchmark-public/actions/runs/43378009832) | [2026-11-11](https://github.com/runs-on-demo/benchmark-public/actions/runs/42957189372) | [2026-11-14](https://github.com/runs-on-demo/benchmark-public/actions/runs/43544990607) | [2026-11-12](https://github.com/runs-on-demo/benchmark-public/actions/runs/43244114191) |

Raw selected jobs, run IDs, phases, metrics, and timestamps are in [`snapshot.json`](snapshot.json).
