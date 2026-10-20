# Cache restore rerun, October 19, 2026

[Run 39287129433](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433), after Celesto started downloading cache archives in parallel ranges with read-ahead. It replaces only the restore row of the [October 17 matched benchmark](../2026-10-17-matched/README.md); CPU and save numbers still come from that run.

## Setup

Same as October 17: GitHub `ubuntu-24.04` versus Celesto `celesto-large`, 4 vCPUs and 16 GiB RAM, 512 MiB random-byte cache, `actions/cache@v4`. Five cold/warm pairs per provider instead of three. Restore time is measured the same way: from the step before `actions/cache` to the step after it, on the warm (cache hit) job. All ten warm jobs hit.

## Result

| | GitHub Actions | Celesto Large |
| --- | ---: | ---: |
| Restore median | **3.93 s** | **5.33 s** |
| Range | 3.05–6.97 s | 2.49–5.62 s |
| October 17 median | 3.30 s | 6.23 s |

GitHub restored 1.36× faster, down from 1.89× on October 17. Celesto's median fell 0.90 s. Celesto Large jobs run on AWS or OVH hosts: four of the five landed on OVH (median 5.45 s) and one on AWS (2.49 s, the fastest restore of either provider).

## Per-job evidence

| Provider | Sample | Celesto host | CPU | Restore s | Job |
| --- | ---: | --- | --- | ---: | --- |
| celesto-large | 1 | ovh | AMD EPYC-Milan Processor | 5.621 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118181010558) |
| github-hosted | 1 | - | AMD EPYC 9V74 80-Core Processor | 5.635 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118181010382) |
| celesto-large | 2 | aws | Intel(R) Xeon(R) 6975P-C | 2.490 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118181754941) |
| github-hosted | 2 | - | AMD EPYC 7763 64-Core Processor | 6.965 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118181562156) |
| celesto-large | 3 | ovh | AMD EPYC-Milan Processor | 5.576 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118182421858) |
| github-hosted | 3 | - | AMD EPYC 9V74 80-Core Processor | 3.049 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118182019838) |
| celesto-large | 4 | ovh | AMD EPYC-Milan Processor | 4.979 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118183182439) |
| github-hosted | 4 | - | AMD EPYC 7763 64-Core Processor | 3.377 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118182847042) |
| celesto-large | 5 | ovh | AMD EPYC-Milan Processor | 5.333 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118183775576) |
| github-hosted | 5 | - | Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz | 3.930 | [logs](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433/job/118183252497) |

Raw values: [restore.json](restore.json).

## Limits

- Five samples per provider; GitHub's hardware varied across jobs and its own median moved from 3.30 s to 3.93 s between the two days.
- The restore includes download and extract. On OVH most of the remaining time is extract (`tar` + `zstd`), not download.
