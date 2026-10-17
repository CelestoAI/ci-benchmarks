# Benchmark results, October 17, 2026

Revision: e28d207d03baffc37ce90c5d3399bac638484d16. Cache payload: 512 MiB cryptographically random bytes. Node: 22.23.3. CPU workload: 250,000,000 integer-mixing iterations per worker. GitHub: ubuntu-latest, four available CPUs. Celesto: celesto-micro, one available CPU.

| Measurement | GitHub cold | GitHub warm | Celesto cold | Celesto warm |
| --- | ---: | ---: | ---: | ---: |
| Cache hit | false | true | false | true |
| Cache lookup/restore boundary | 0.438 s (miss) | 4.186 s (hit) | 0.400 s (miss) | 12.395 s (hit) |
| Cache save boundary | 3.638 s | skipped | 7.731 s | skipped |
| Single-core throughput, iterations/s | 191,190,584 | 169,629,727 | 225,347,844 | 222,489,750 |
| All-core throughput, iterations/s | 646,746,114 | 617,852,065 | 211,751,099 | 224,301,895 |
| All-core workers | 4 | 4 | 1 | 1 |
| Instrumented wall time | 7.606 s | 7.729 s | 11.225 s | 14.990 s |
| GitHub job execution duration (UI) | 15 s | 14 s | 21 s | 26 s |
| Total workflow duration (UI, includes queue/setup) | 21 s | 19 s | 4m 31s | 1m 42s |

## Interpretation

Celesto single-core throughput was 17.9% higher on the cold sample and 31.2% higher on the warm sample. GitHub's four-core total throughput exceeded Celesto Micro's one-core total throughput. The 512 MiB cache hit restore took 2.96 times as long on Celesto; its cache save took 2.13 times as long.

Celesto's total durations include queue/provisioning and runner reassignment: the runner initially created for the cold run served another eligible job, its replacement served an older defective benchmark, and the next benchmark's runner served the corrected cold run. The warm run then received replacement capacity. Do not attribute these total durations to CPU execution.

These are one cold and one warm sample per provider, not medians or a general performance conclusion. CPU is a short synthetic JavaScript integer workload. Cache boundaries include action overhead, compression and extraction. This incompressible synthetic cache differs from the blog's dependency workload. Matching cache keys use separate provider cache stores; both cold misses and warm hits were verified.

Aggregate CPU time in raw events is not usable for multiple workers because process.cpuUsage measures the entire process and is duplicated across workers. Throughput, checksums and wall time remain usable. Failed initial runs are excluded.

## Evidence

- [GitHub cold](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39045911757)
- [GitHub warm](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39045970995)
- [Celesto cold](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39046141097)
- [Celesto warm](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39046406958)

Each successful run contains a downloadable artifact with benchmark-summary.md and benchmark-events.jsonl. Raw events extracted from the job logs are also retained beside this report.
