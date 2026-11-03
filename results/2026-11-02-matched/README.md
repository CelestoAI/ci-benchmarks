# Matched four-core benchmark, November 2, 2026

Three runs of the [Matched 4-core benchmark](../../.github/workflows/matched.yml) on `main`: [41466558988](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988), [41468972899](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899) and [41469012973](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973). This report replaces the [October 17](../2026-10-17-matched/README.md) and [October 19](../2026-10-19-readahead-restore/README.md) numbers in the main README. Those reports stay as history.

## Setup

Same as October 17: GitHub `ubuntu-24.04` versus Celesto `celesto-large`, 4 vCPUs and 16 GiB RAM, Ubuntu 24.04.5, Node 22.23.3. Each run has three cold/warm pairs per provider, so the three runs give 36 jobs. All 36 jobs passed. All 18 cold jobs missed the cache and all 18 warm jobs hit it.

- **CPU:** 18 samples per provider (cold and warm jobs).
- **Restore:** 9 warm (cache hit) jobs per provider.
- **Save:** 9 cold (cache miss) jobs per provider.

The first run ran alone. The second and third runs ran at the same time.

## Result

| Median | GitHub Actions | Celesto Large | Better |
| --- | ---: | ---: | --- |
| Single-core CPU ↑, million iterations/s | 221.5 | 234.3 | Celesto +5.8% |
| Four-core CPU ↑, million iterations/s | 827.7 | 924.1 | Celesto +11.6% |
| Restore a 512 MiB cache ↓ | 4.04 s | 3.60 s | Celesto 1.12× faster |
| Save a 512 MiB cache ↓ | 3.01 s | 6.09 s | GitHub 2.02× faster |

| Range | GitHub Actions | Celesto Large |
| --- | ---: | ---: |
| Single-core, million iterations/s | 188.3–269.9 | 231.5–235.0 |
| Four-core, million iterations/s | 733.3–1053.8 | 916.7–929.8 |
| Restore | 2.71–9.56 s | 3.35–4.06 s |
| Save | 2.56–10.90 s | 4.46–28.47 s |

### CPU depends on the GitHub hardware

Celesto ran every job on AMD EPYC-Milan. GitHub ran jobs on three CPU models:

| CPU | Jobs | Single-core median | Four-core median |
| --- | ---: | ---: | ---: |
| Celesto: AMD EPYC-Milan | 18 | 234.3 | 924.1 |
| GitHub: AMD EPYC 9V45 | 7 | 268.8 | 1003.9 |
| GitHub: AMD EPYC 7763 | 6 | 199.6 | 776.4 |
| GitHub: AMD EPYC 9V74 | 5 | 188.5 | 736.8 |

Celesto is faster than GitHub's 7763 and 9V74 jobs and slower than its 9V45 jobs. The GitHub median moves with the hardware mix. On October 17 most GitHub jobs ran on 7763, and Celesto led by about 17%. On November 2 more jobs ran on 9V45, and the lead is smaller. Celesto's CPU result is almost the same in every job.

### Cache

- **Restore:** Celesto now restores faster than GitHub, and every Celesto restore took 3.35–4.06 s. GitHub's restores took 2.71–9.56 s. On October 19 GitHub was 1.36× faster.
- **Save:** GitHub is still about 2× faster. Celesto's saves vary more: 4.46–8.91 s, plus one 28.47 s outlier. The run that ran alone had a Celesto save median of 4.68 s. The two runs that ran at the same time had medians of 6.09 s and 7.89 s. Three runs are not enough to show whether running at the same time causes the slower saves. No outlier was removed.

## Limits

- The CPU models, kernels (GitHub `7.0.0-1017-azure`, Celesto `7.3.0`) and disks are different.
- Cache times include action startup, transfer, compression and extraction.
- These are synthetic workloads. They do not predict the speed of a real build.

## Per-job evidence

| Run | Provider | State | Sample | CPU | Single-core iterations/s | Four-core iterations/s | Restore s | Save s | Job |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 41466558988 | celesto-large | cold | 1 | AMD EPYC-Milan | 234,327,425 | 924,363,179 | 0.410 | 4.456 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125348890005) |
| 41466558988 | celesto-large | warm | 1 | AMD EPYC-Milan | 234,186,066 | 922,432,164 | 3.717 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125351800383) |
| 41466558988 | celesto-large | cold | 2 | AMD EPYC-Milan | 233,134,453 | 922,133,854 | 0.391 | 8.906 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125349663236) |
| 41466558988 | celesto-large | warm | 2 | AMD EPYC-Milan | 234,528,000 | 924,051,451 | 3.350 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125352306700) |
| 41466558988 | celesto-large | cold | 3 | AMD EPYC-Milan | 234,404,981 | 918,568,765 | 0.392 | 4.676 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125350540558) |
| 41466558988 | celesto-large | warm | 3 | AMD EPYC-Milan | 234,100,138 | 921,756,126 | 3.500 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125352756281) |
| 41466558988 | github-hosted | cold | 1 | AMD EPYC 9V45 96-Core | 245,612,484 | 958,976,213 | 0.330 | 2.967 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125348889446) |
| 41466558988 | github-hosted | warm | 1 | AMD EPYC 9V45 96-Core | 268,756,743 | 887,303,568 | 3.833 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125351800637) |
| 41466558988 | github-hosted | cold | 2 | AMD EPYC 9V45 96-Core | 255,139,033 | 994,362,177 | 0.270 | 2.559 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125349307940) |
| 41466558988 | github-hosted | warm | 2 | AMD EPYC 7763 64-Core | 199,795,092 | 769,419,701 | 4.829 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125352118989) |
| 41466558988 | github-hosted | cold | 3 | AMD EPYC 7763 64-Core | 199,557,415 | 783,909,441 | 0.314 | 3.298 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125350142430) |
| 41466558988 | github-hosted | warm | 3 | AMD EPYC 9V74 80-Core | 243,307,281 | 889,830,427 | 2.712 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41466558988/job/125352511911) |
| 41468972899 | celesto-large | cold | 1 | AMD EPYC-Milan | 234,364,670 | 923,371,126 | 0.377 | 8.829 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125357228101) |
| 41468972899 | celesto-large | warm | 1 | AMD EPYC-Milan | 234,426,800 | 927,811,851 | 3.755 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125358855608) |
| 41468972899 | celesto-large | cold | 2 | AMD EPYC-Milan | 234,531,136 | 924,992,155 | 0.373 | 4.896 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125357874134) |
| 41468972899 | celesto-large | warm | 2 | AMD EPYC-Milan | 233,752,502 | 922,733,437 | 4.063 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125359360055) |
| 41468972899 | celesto-large | cold | 3 | AMD EPYC-Milan | 234,424,605 | 916,726,328 | 0.384 | 6.088 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125358358937) |
| 41468972899 | celesto-large | warm | 3 | AMD EPYC-Milan | 234,956,351 | 925,924,807 | 3.517 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125359898414) |
| 41468972899 | github-hosted | cold | 1 | AMD EPYC 7763 64-Core | 199,584,020 | 759,925,846 | 0.251 | 3.008 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125357228440) |
| 41468972899 | github-hosted | warm | 1 | AMD EPYC 9V74 80-Core | 188,437,027 | 736,751,393 | 4.038 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125358855431) |
| 41468972899 | github-hosted | cold | 2 | AMD EPYC 9V74 80-Core | 188,256,308 | 733,310,114 | 0.363 | 3.061 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125357608513) |
| 41468972899 | github-hosted | warm | 2 | AMD EPYC 7763 64-Core | 199,657,022 | 788,254,676 | 3.328 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125359251404) |
| 41468972899 | github-hosted | cold | 3 | AMD EPYC 9V74 80-Core | 243,285,006 | 867,171,495 | 0.279 | 2.919 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125358012568) |
| 41468972899 | github-hosted | warm | 3 | AMD EPYC 9V74 80-Core | 188,493,647 | 733,738,874 | 6.444 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41468972899/job/125359611709) |
| 41469012973 | celesto-large | cold | 1 | AMD EPYC-Milan | 234,748,469 | 924,083,178 | 0.409 | 7.885 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125357360470) |
| 41469012973 | celesto-large | warm | 1 | AMD EPYC-Milan | 234,189,981 | 927,513,397 | 3.604 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125359324012) |
| 41469012973 | celesto-large | cold | 2 | AMD EPYC-Milan | 231,513,672 | 924,878,560 | 0.351 | 5.977 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125358096646) |
| 41469012973 | celesto-large | warm | 2 | AMD EPYC-Milan | 234,054,877 | 927,360,912 | 3.811 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125359825157) |
| 41469012973 | celesto-large | cold | 3 | AMD EPYC-Milan | 234,243,531 | 923,405,856 | 0.368 | 28.469 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125358605789) |
| 41469012973 | celesto-large | warm | 3 | AMD EPYC-Milan | 234,763,238 | 929,836,277 | 3.571 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125360292429) |
| 41469012973 | github-hosted | cold | 1 | AMD EPYC 9V45 96-Core | 269,517,251 | 1,053,849,209 | 0.310 | 3.019 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125357359883) |
| 41469012973 | github-hosted | warm | 1 | AMD EPYC 9V45 96-Core | 268,960,624 | 1,029,768,864 | 4.219 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125359323889) |
| 41469012973 | github-hosted | cold | 2 | AMD EPYC 7763 64-Core | 199,529,693 | 783,367,050 | 0.250 | 2.905 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125357724368) |
| 41469012973 | github-hosted | warm | 2 | AMD EPYC 9V45 96-Core | 255,873,032 | 1,003,896,055 | 3.881 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125359666236) |
| 41469012973 | github-hosted | cold | 3 | AMD EPYC 9V45 96-Core | 269,873,785 | 1,033,522,254 | 0.234 | 10.896 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125358406819) |
| 41469012973 | github-hosted | warm | 3 | AMD EPYC 7763 64-Core | 199,760,401 | 740,173,206 | 9.563 | skipped | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/41469012973/job/125360011023) |

Raw values and host details: [samples.json](samples.json).
