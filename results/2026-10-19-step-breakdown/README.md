# Step breakdown: where cache time goes

October 19, 2026. Same 512 MiB random-byte cache as the [matched benchmark](../2026-10-17-matched/README.md), with each restore and save split into steps, plus isolated disk, network, and compression probes on every runner.

Two runs of the [matched workflow](../../.github/workflows/matched.yml) on the `step-breakdown` branch:

- **Before:** [run 39228751745](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39228751745), Celesto restores downloaded the archive over one stream.
- **After:** [run 39287129433](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39287129433), Celesto restores download in parallel ranges with read-ahead.

Celesto jobs land on either an AWS or an OVH host, shown as separate columns. Values are medians in seconds (CPU in million iterations/s), with the range and sample count in brackets.

## Download: before and after

| Restore step | Before, OVH | After, OVH | Change |
| --- | ---: | ---: | ---: |
| Download | 4.59 (n=2) | **2.96** (n=4) | −1.63 s (−35%) |
| Extract | 1.56 | 1.78 | within noise |
| Total | 6.51 | **5.30** | −1.21 s |
| Gap to GitHub, download | +2.37 | **−0.29** | OVH now level with GitHub |
| Gap to GitHub, total | +3.39 | +1.34 | gap down 60% |

The one AWS restore in the after run downloaded in 1.52 s, the fastest of all runners. GitHub's own download moved from 2.22 s to 3.14 s between the runs, so compare each run's gap rather than raw GitHub numbers.

## What is left: extract on OVH

Extract (`tar` + `zstd -d --long=30`) takes 1.78 s on OVH against 0.6 s on GitHub and AWS. Pure CPU is faster on OVH, so the cost is in the guest kernel: on OVH guests a read+write syscall pair takes about 1,100 ns against 230 ns on AWS, and pipes and page faults are 2–2.5× slower. Extract is mostly syscalls, pipes, and page-cache writes. OVH guests are nested and run AMD speculative-execution mitigations in software (SRSO "Safe RET", TSA, no microcode); AWS guests are not affected by those.

AWS has the opposite weak spot: flushing writes to disk (`disk_write_fsync`, `tar_extract_sync`) takes 3.5–5.9 s. Cache restore does not flush, so it does not slow the restore.

## After: run 39287129433

| Metric | github | celesto/aws | celesto/ovh | Celesto − GitHub (median) |
| --- | ---: | ---: | ---: | ---: |
| cpu: all_cores M iter/s | 781.18 (613.62-1026.42; n=10) | 854.63 (853.36-855.91; n=2) | 927.86 (915.77-930.61; n=8) | +146.09 |
| cpu: single_core M iter/s | 198.99 (177.86-264.97; n=10) | 217.58 (216.81-218.34; n=2) | 232.94 (231.78-233.18; n=8) | +33.67 |
| probe: disk_read_cold | 1.05 (1.00-2.15; n=10) | 0.16 (0.14-0.17; n=2) | 0.15 (0.14-0.34; n=8) | -0.89 |
| probe: disk_write_fsync | 1.29 (1.15-3.17; n=10) | 4.62 (3.57-5.68; n=2) | 1.00 (0.84-1.28; n=8) | -0.21 |
| probe: tar_create_warm | 0.53 (0.23-0.58; n=10) | 0.32 (0.31-0.32; n=2) | 0.89 (0.80-0.93; n=8) | +0.34 |
| probe: tar_extract_cold | 1.20 (1.11-2.16; n=10) | 0.60 (0.53-0.68; n=2) | 1.69 (1.49-1.93; n=8) | +0.46 |
| probe: tar_extract_sync | 1.23 (1.13-2.90; n=10) | 4.56 (3.26-5.86; n=2) | 0.61 (0.57-0.88; n=8) | -0.61 |
| probe: zstd_compress_mem | 0.31 (0.14-0.36; n=10) | 0.19 (0.18-0.19; n=2) | 0.37 (0.33-0.50; n=8) | +0.05 |
| probe: zstd_decompress_mem | 0.10 (0.06-0.16; n=10) | 0.16 (0.16-0.16; n=2) | 0.31 (0.27-0.39; n=8) | +0.20 |
| restore: download | 3.14 (1.97-5.76; n=5) | 1.52 (1.52-1.52; n=1) | 2.96 (2.70-3.27; n=4) | -0.29 |
| restore: extract | 0.61 (0.44-0.71; n=5) | 0.59 (0.59-0.59; n=1) | 1.78 (1.69-1.97; n=4) | +1.13 |
| restore: lookup | 0.25 (0.15-0.38; n=5) | 0.28 (0.28-0.28; n=1) | 0.43 (0.37-0.51; n=4) | +0.18 |
| restore: total | 3.84 (2.73-6.85; n=5) | 2.39 (2.39-2.39; n=1) | 5.30 (4.82-5.45; n=4) | +1.34 |
| save: commit | 0.17 (0.15-0.28; n=5) | 0.47 (0.47-0.47; n=1) | 1.07 (0.51-1.74; n=4) | +0.74 |
| save: compress | 0.76 (0.39-0.89; n=5) | 0.99 (0.99-0.99; n=1) | 1.57 (1.48-1.87; n=4) | +0.81 |
| save: reserve+upload | 1.60 (1.40-2.28; n=5) | 1.99 (1.99-1.99; n=1) | 3.49 (2.99-5.99; n=4) | +1.39 |
| save: total | 2.62 (2.21-3.58; n=5) | 3.54 (3.54-3.54; n=1) | 5.99 (5.88-9.43; n=4) | +3.28 |

## Before: run 39228751745

Six of eight Celesto saves in this run were refused by the workspace's cache size limit (`save: failed`), so only two OVH restores hit and AWS has no restore samples.

| Metric | github | celesto/aws | celesto/ovh | Celesto − GitHub (median) |
| --- | ---: | ---: | ---: | ---: |
| cpu: all_cores M iter/s | 732.55 (636.20-1053.78; n=10) | 856.18 (856.18-856.18; n=1) | 925.87 (905.24-931.19; n=9) | +193.06 |
| cpu: single_core M iter/s | 198.94 (178.38-270.08; n=10) | 215.81 (215.81-215.81; n=1) | 233.28 (231.36-233.51; n=9) | +34.25 |
| probe: disk_read_cold | 1.02 (1.01-4.65; n=10) | 0.15 (0.15-0.15; n=1) | 0.16 (0.15-0.20; n=9) | -0.87 |
| probe: disk_write_fsync | 1.23 (1.16-3.32; n=10) | 3.69 (3.69-3.69; n=1) | 0.93 (0.81-1.18; n=9) | -0.29 |
| probe: net_ranged | 1.19 (0.58-2.34; n=10) | 0.76 (0.76-0.76; n=1) | 2.46 (2.04-3.06; n=9) | +1.24 |
| probe: net_single_stream | 5.06 (1.63-10.53; n=10) | 1.58 (1.58-1.58; n=1) | 2.92 (2.36-9.72; n=9) | -2.15 |
| probe: tar_create_warm | 0.53 (0.23-0.55; n=10) | 0.32 (0.32-0.32; n=1) | 0.84 (0.83-0.93; n=9) | +0.31 |
| probe: tar_extract_cold | 1.21 (1.15-5.51; n=10) | 0.64 (0.64-0.64; n=1) | 1.62 (1.48-1.72; n=9) | +0.41 |
| probe: tar_extract_sync | 1.22 (1.18-4.76; n=10) | 3.80 (3.80-3.80; n=1) | 0.72 (0.53-1.16; n=9) | -0.40 |
| probe: zstd_compress_mem | 0.32 (0.12-0.33; n=10) | 0.19 (0.19-0.19; n=1) | 0.36 (0.32-0.42; n=9) | +0.04 |
| probe: zstd_decompress_mem | 0.12 (0.07-0.15; n=10) | 0.16 (0.16-0.16; n=1) | 0.26 (0.24-0.31; n=9) | +0.14 |
| restore: download | 2.22 (2.11-5.55; n=5) | - | 4.59 (4.41-4.77; n=2) | +2.37 |
| restore: extract | 0.71 (0.65-0.74; n=5) | - | 1.56 (1.54-1.57; n=2) | +0.85 |
| restore: lookup | 0.19 (0.17-0.37; n=5) | - | 0.36 (0.33-0.39; n=2) | +0.17 |
| restore: total | 3.12 (3.02-6.66; n=5) | - | 6.51 (6.32-6.71; n=2) | +3.39 |
| save: commit | 0.17 (0.15-0.25; n=5) | - | 0.84 (0.54-1.14; n=2) | +0.67 |
| save: compress | 0.69 (0.37-0.74; n=5) | - | 1.96 (1.69-2.24; n=2) | +1.27 |
| save: failed (count) | - | 1.00 (1.00-1.00; n=1) | 1.00 (1.00-1.00; n=5) | - |
| save: reserve+upload | 2.05 (1.56-2.13; n=5) | - | 4.99 (2.99-6.99; n=2) | +2.94 |
| save: total | 3.00 (2.18-3.19; n=5) | - | 7.92 (5.34-10.50; n=2) | +4.92 |

## Raw data and regenerating

Per-sample timings: [`samples-before-39228751745.json`](samples-before-39228751745.json) and [`samples-after-39287129433.json`](samples-after-39287129433.json).

Rebuild a table from a run's artifacts:

```sh
python3 scripts/breakdown-report.py <run-id> --output <dir>
```

Small samples: one AWS restore after, two OVH restores before. Treat single-sample columns as indicative.
