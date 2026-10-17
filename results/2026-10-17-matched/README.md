# Matched four-core benchmark, October 17, 2026

[Successful experiment and downloadable artifacts](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058).

## Configuration and validation

GitHub `ubuntu-24.04` versus Celesto `celesto-large`, both configured for four vCPUs and 16 GiB RAM. Every job verified four available CPUs and at least 14 GiB usable RAM before benchmarking. Actual usable RAM was approximately 15.62 GiB on both providers. Both reported Ubuntu 24.04.5 LTS, x64, and Node 22.23.3.

The shared harness revision was `b1fbc9fe52fbcee35f44151d18310ef5b7564777`. Three independent cache namespaces per provider each received a cold run followed by one warm run, for twelve successful jobs total. All six cold runs missed, all six warm runs hit, and CPU checksums matched across every runner. Warm jobs waited for the entire cold phase. At most two matrix jobs ran concurrently.

CPU workload: two billion integer-mixing iterations per worker; one worker for single-core and four workers for all-core. Cache workload: 512 MiB cryptographically random bytes, incompressible, identical generation method and action versions. This is a synthetic benchmark rather than the blog's dependency workload.

## Results

CPU medians use six observations per provider (three cold plus three warm). Cache restore medians use three warm hits per provider; save medians use three cold saves. Higher CPU throughput is better; lower cache duration is better.

| Measurement | GitHub Actions | Celesto Large |
| --- | ---: | ---: |
| Single-core median, iterations/s | 199,372,003 | 233,163,848 |
| Four-core median, iterations/s | 786,689,857.5 | 927,536,852 |
| Single-core range, iterations/s | 186,810,052–256,244,370 | 232,797,135–233,738,385 |
| Four-core range, iterations/s | 681,597,060–980,271,768 | 923,658,213–931,117,488 |
| Cache-hit restore median | 3.295 s | 6.230 s |
| Cache save median | 2.495 s | 5.179 s |
| Cold lookup median (miss) | 0.273 s | 0.439 s |
| Instrumented cold wall median | 21.607 s | 23.552 s |
| Instrumented warm wall median | 23.787 s | 23.634 s |

Celesto Large's median single-core throughput was 16.9% higher and four-core throughput 17.9% higher. Celesto's cache restore took 1.89 times as long and save 2.08 times as long on median. Its CPU range was substantially narrower in this experiment.

Cache save samples were GitHub 2.322 / 2.495 / 2.633 s and Celesto 5.179 / 20.274 / 4.810 s. Restore samples were GitHub 3.143 / 6.640 / 3.295 s and Celesto 5.744 / 6.230 / 8.485 s. No outlier was removed.

## Remaining platform differences and limits

Capacity, distribution version, runtime and work are matched; underlying hardware and platform images are not identical. Celesto exposed AMD EPYC-Milan on every sample. GitHub exposed AMD EPYC 7763 on four samples, 9V45 on one, and 9V74 on one. GitHub's fastest four-core sample (980.3 million iterations/s) exceeded Celesto's fastest (931.1 million). The aggregate median depends on which hardware GitHub assigned in this small sample.

Kernels differed: Celesto 6.12.85 versus GitHub 6.17.0-1022-azure. Observed root filesystem sizes were approximately 63.3 GB versus 154.9 GB; disk capacity/performance is not identical. These differences remain relevant to cache timings. [GitHub documents the public Linux runner's nominal CPU/RAM configuration here](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Cache boundaries include action startup, transfer, compression/decompression and extraction. Instrumented wall time starts after checkout/runtime setup and ends before artifact upload; it excludes queue/provisioning and workflow matrix scheduling. It is not total CI latency. This experiment does not establish a general workload performance advantage or a cost comparison. Three cache observations per state provide an initial comparison, not tight confidence intervals.

## Per-job evidence

| Provider | State | Sample | Single-core iterations/s | Four-core iterations/s | Restore s | Save s | Job |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| celesto-large | cold | 1 | 233,129,644 | 929,942,506 | 0.458 | 5.179 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117442962258) |
| github-hosted | cold | 1 | 256,244,370 | 980,271,768 | 0.273 | 2.322 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117442962506) |
| github-hosted | cold | 2 | 199,306,815 | 781,927,285 | 0.241 | 2.495 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443058607) |
| celesto-large | cold | 2 | 233,014,434 | 925,570,572 | 0.419 | 20.274 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443169521) |
| github-hosted | cold | 3 | 243,303,614 | 810,160,437 | 0.348 | 2.633 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443187101) |
| celesto-large | cold | 3 | 232,797,135 | 928,442,693 | 0.439 | 4.810 | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443300324) |
| github-hosted | warm | 1 | 197,721,636 | 788,894,612 | 3.143 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443581266) |
| celesto-large | warm | 1 | 233,738,385 | 931,117,488 | 5.744 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443581331) |
| github-hosted | warm | 2 | 186,810,052 | 681,597,060 | 6.640 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443750935) |
| celesto-large | warm | 2 | 233,198,052 | 926,631,011 | 6.230 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443843783) |
| github-hosted | warm | 3 | 199,437,191 | 784,485,103 | 3.295 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117443907968) |
| celesto-large | warm | 3 | 233,602,759 | 923,658,213 | 8.485 | skipped | [logs](https://github.com/CelestoAI/celesto-ci-benchmarks/actions/runs/39048833058/job/117444022066) |

Full host fingerprints and raw timestamped events are in [samples.json](samples.json). CPU aggregate time accounting was corrected before this experiment to measure process CPU once rather than summing overlapping process measurements across threads.
