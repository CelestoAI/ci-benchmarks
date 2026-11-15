# CI VM disk hill-climb

Each run boots the prod CI microvm command line (QEMU 8.2.2, Celesto CI kernel `kernels-2026.10.28.0`,
virtio-mmio, 2 vCPU / 3 GiB guest) on a fresh GitHub-hosted runner (4 vCPU, 16 GiB, nested KVM) and runs `scripts/hillclimb/guest-bench.sh`.

- **local**: XFS (reflink) on a RAM-backed `null_blk` device with 20 us completions (stand-in for local NVMe;
  the runners have no local SSD).
- **network**: an XFS loop file (direct I/O) on the runner's only disk, a remote Azure disk attached over NVMe
  (stand-in for EBS / OVH volumes).
- Values are medians over repeats. **score** = geometric mean of each scored metric's ratio to the iteration's
  baseline config (named in each iteration) in the same disk class (above 1 is better).
- From iteration 3 on, each job also runs the baseline on the same runner (order alternates by repeat), and
  **score (paired)** uses the median of those same-runner ratios. GitHub runners come in different speeds
  (iteration 2 pgbench ranged 3,400 to 8,300 TPS on one config), so unpaired scores in iterations 1-2 carry
  that noise; trust only large differences there.
- Worst-latency columns are not scored: a config that freezes is rejected. **ok** counts runs that finished;
  a run that hangs past its timeouts is not ok.
- Single VM per runner: no neighbor load. Finalists must still be checked on real hosts.
- Raw per-run records (config, QEMU drive string, every metric): `runs.jsonl`.
- Conclusions so far, with the reasoning: `FINDINGS.md`.

## Iteration 7

Iteration 6 found the fresh-write regression starts in QEMU 10.1 (10.0.6 is fine). Suspect: commit a6a0a7fb0e, which makes bdrv_co_is_zero_fast() lseek the sparse raw base, so qcow2 handle_alloc_space() zeroes every new cluster with write_zeroes (fallocate on XFS) instead of copying. This iteration tests it two ways: the qcow2_skip_cow trace event counts how often qcow2 took that path, and 10.1.5 is rebuilt with only that commit reverted.

Baseline: `pci-iothread`

Runs: [43689421004](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43689421004)

Configs:

- `src-10.0.6-trace`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.0.6", "queues": 2, "trace": "qcow2_skip_cow"}` — last good release; expect no qcow2_skip_cow events
- `src-10.1.5-revert`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.1.5+revert-a6a0a7fb0e", "queues": 2, "trace": "qcow2_skip_cow"}` — 10.1.5 minus the suspect commit; if it is the cause, speed returns and events drop to 0
- `src-10.1.5-trace`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.1.5", "queues": 2, "trace": "qcow2_skip_cow"}` — first slow release; expect one qcow2_skip_cow event per new cluster

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| src-10.0.6-trace | 3/3 | 0.98 (paired) | 174719 | 0.0 | 0 | 175029 | 0.0 | 3946 | 1.91 | 65380 | 7092 | 617 | 0.12 | 34.8 |
| src-10.1.5-revert | 3/3 | 0.97 (paired) | 157890 | 0.0 | 0 | 156159 | 0.0 | 4000 | 2.11 | 57091 | 5710 | 558 | 0.12 | 31.9 |
| src-10.1.5-trace | 3/3 | 0.79 (paired) | 26761 | 3.8 | 67 | 151692 | 0.0 | 2147 | 1.82 | 63407 | 5251 | 479 | 0.12 | 19.2 |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| src-10.0.6-trace | 3/3 | 1.09 (paired) | 109954 | 0.3 | 0 | 94162 | 0.1 | 1724 | 3.21 | 38626 | 3946 | 365 | 0.12 | 17.8 |
| src-10.1.5-revert | 3/3 | 1.07 (paired) | 138279 | 0.4 | 0 | 103404 | 0.5 | 850 | 1.95 | 67899 | 9315 | 598 | 0.12 | 12.7 |
| src-10.1.5-trace | 3/3 | 0.91 (paired) | 122013 | 1.3 | 8 | 102335 | 0.5 | 234 | 2.83 | 59310 | 5586 | 442 | 0.12 | 12.4 |

## Iteration 6

Iteration 5: QEMU 11.1.3 (our source build) cut fresh writes to 0.15-0.2x of distro 8.2.2 with multi-second stalls, and still hung on virtio-mmio with event_idx on. This iteration separates build from version (8.2.2 built from source the same way, Ubuntu's prebuilt 10.2.1 and 11.0.3, source 9.2.4 and 10.2.4), and adds dm-thin: each VM disk is an LVM thin snapshot of a base volume, used as a raw block device (64K chunks, zeroing on).

Baseline: `pci-iothread`

Runs: [43683396957](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43683396957), [43684525170](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43684525170)

Configs:

- `pci-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "queues": 2}` — iteration 4-5 winner, distro QEMU 8.2.2
- `src-10.2.4`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.2.4", "queues": 2}`
- `src-8.2.2`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "8.2.2", "queues": 2}` — same version, our source build: is the build the problem?
- `src-9.2.4`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "9.2.4", "queues": 2}`
- `thin-none-native`: `{"aio": "native", "cache": "none", "dev": "pci", "iothread": 1, "layout": "thin", "queues": 2}` — dm-thin snapshot, O_DIRECT, Linux AIO
- `thin-none-uring`: `{"aio": "io_uring", "cache": "none", "dev": "pci", "iothread": 1, "layout": "thin", "queues": 2}` — dm-thin snapshot, O_DIRECT
- `thin-prod`: `{"aio": "threads", "cache": "writeback", "dev": "pci", "layout": "thin", "queues": 2}` — dm-thin with today's prod cache settings (sandbox-safe)
- `thin-unsafe`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "layout": "thin", "queues": 2}` — dm-thin snapshot, host page cache
- `ubuntu-26.04`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "ubuntu-26.04", "queues": 2}` — Ubuntu 26.04 LTS prebuilt QEMU 10.2.1
- `src-10.0.6`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.0.6", "queues": 2}`
- `src-10.1.5`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "10.1.5", "queues": 2}`
- `ubuntu-26.10`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "ubuntu-26.10", "queues": 2}` — Ubuntu 26.10 prebuilt QEMU 11.0.3

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pci-iothread | 3/3 | 1.00 | 197002 | 0.0 | 0 | 200887 | 0.0 | 4433 | 1.71 | 68794 | 7508 | 523 | 0.13 | 38.9 |
| src-10.0.6 | 3/3 | 0.99 (paired) | 145168 | 0.0 | 0 | 150903 | 0.0 | 2688 | 1.90 | 63317 | 4788 | 450 | 0.13 | 30.6 |
| src-9.2.4 | 3/3 | 0.99 (paired) | 108370 | 0.0 | 0 | 116467 | 0.0 | 3828 | 3.17 | 32461 | 3982 | 251 | 0.12 | 24.2 |
| src-8.2.2 | 3/3 | 0.97 (paired) | 152844 | 0.0 | 0 | 150212 | 0.0 | 4633 | 2.03 | 55304 | 5701 | 449 | 0.12 | 31.0 |
| src-10.1.5 | 3/3 | 0.79 (paired) | 31795 | 4.9 | 72 | 144355 | 0.0 | 3098 | 2.19 | 57476 | 5730 | 509 | 0.12 | 18.9 |
| ubuntu-26.04 | 3/3 | 0.73 (paired) | 18033 | 2.7 | 21 | 101293 | 0.0 | 3038 | 3.25 | 21529 | 3925 | 258 | 0.12 | 14.2 |
| src-10.2.4 | 3/3 | 0.71 (paired) | 18992 | 9.9 | 52 | 114259 | 0.0 | 2691 | 3.24 | 25333 | 4046 | 268 | 0.12 | 15.0 |
| ubuntu-26.10 | 3/3 | 0.70 (paired) | 30147 | 1.4 | 86 | 155185 | 0.0 | 2176 | 1.53 | 41019 | 6113 | 450 | 0.12 | 19.5 |
| thin-none-native | 2/3 | 0.64 (paired) | 90927 | 0.0 | 0 | 92589 | 0.0 | 2199 | 2.71 | 13530 | 4802 | 150 | 0.12 | 22.3 |
| thin-none-uring | 2/3 | 0.59 (paired) | 95502 | 0.0 | 0 | 101514 | 0.0 | 1983 | 2.67 | 8334 | 4507 | 141 | 0.12 | 22.8 |
| thin-unsafe | 2/3 | 0.56 (paired) | 117435 | 0.3 | 0 | 91298 | 0.8 | 1355 | 2.49 | 28612 | 6339 | 198 | 0.49 | 27.0 |
| thin-prod | 2/3 | 0.40 (paired) | 73828 | 0.0 | 0 | 34896 | 5.0 | 971 | 2.39 | 10273 | 4572 | 155 | 0.69 | 20.7 |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| src-9.2.4 | 3/3 | 1.08 (paired) | 144495 | 0.3 | 0 | 112430 | 0.6 | 762 | 1.92 | 57424 | 8891 | 517 | 0.12 | 12.3 |
| src-8.2.2 | 3/3 | 1.06 (paired) | 125194 | 0.5 | 0 | 92043 | 0.1 | 1694 | 2.62 | 37709 | 4395 | 270 | 0.12 | 18.0 |
| src-10.0.6 | 3/3 | 1.06 (paired) | 133349 | 0.4 | 0 | 108374 | 0.6 | 813 | 1.71 | 67670 | 6890 | 548 | 0.12 | 11.9 |
| pci-iothread | 3/3 | 1.00 | 150866 | 0.3 | 0 | 86206 | 0.6 | 565 | 1.91 | 65782 | 9050 | 529 | 0.12 | 12.6 |
| src-10.1.5 | 3/3 | 1.00 (paired) | 169627 | 4.8 | 21 | 126091 | 0.5 | 308 | 2.09 | 67612 | 9048 | 591 | 0.11 | 12.3 |
| ubuntu-26.10 | 3/3 | 0.81 (paired) | 74308 | 0.4 | 0 | 97161 | 0.2 | 623 | 3.20 | 26681 | 4081 | 273 | 0.12 | 14.0 |
| src-10.2.4 | 3/3 | 0.79 (paired) | 49914 | 0.1 | 0 | 82842 | 0.3 | 699 | 3.27 | 22975 | 3876 | 264 | 0.12 | 13.2 |
| ubuntu-26.04 | 3/3 | 0.76 (paired) | 61236 | 4.8 | 21 | 67317 | 0.3 | 294 | 3.04 | 35490 | 5537 | 387 | 0.12 | 11.1 |
| thin-none-uring | 3/3 | 0.28 (paired) | 14433 | 0.1 | 0 | 19558 | 0.1 | 110 | 5.97 | 5484 | 3824 | 79 | 0.12 | 11.0 |
| thin-none-native | 3/3 | 0.24 (paired) | 14104 | 0.1 | 0 | 19558 | 0.1 | 119 | 5.60 | 5358 | 4765 | 76 | 0.12 | 11.0 |
| thin-prod | 3/3 | 0.19 (paired) | 10133 | 1.5 | 213 | 494 | 5.6 | 351 | 3.16 | 8379 | 3766 | 137 | 2.05 | 13.7 |
| thin-unsafe | 3/3 | 0.13 (paired) | 17290 | 0.4 | 0 | 128 | 2.8 | 140 | 1.91 | 11125 | 7997 | 134 | 1.75 | 14.4 |

Failures:

- `thin-unsafe` local rep 2: runner_lost runner lost communication (no artifact, no log); the dm-thin VM ran before the baseline in even repeats. Likely RAM exhaustion: the local class is a 22 GiB RAM-backed null_blk on a 16 GiB runner, and deleted thin volumes do not discard their chunks back to null_blk the way XFS deletes do. Cancelled at ~40 min.
- `thin-none-uring` local rep 2: runner_lost runner lost communication (no artifact, no log); the dm-thin VM ran before the baseline in even repeats. Likely RAM exhaustion: the local class is a 22 GiB RAM-backed null_blk on a 16 GiB runner, and deleted thin volumes do not discard their chunks back to null_blk the way XFS deletes do. Cancelled at ~40 min.
- `thin-prod` local rep 2: runner_lost runner lost communication (no artifact, no log); the dm-thin VM ran before the baseline in even repeats. Likely RAM exhaustion: the local class is a 22 GiB RAM-backed null_blk on a 16 GiB runner, and deleted thin volumes do not discard their chunks back to null_blk the way XFS deletes do. Cancelled at ~40 min.
- `thin-none-native` local rep 2: runner_lost runner lost communication (no artifact, no log); the dm-thin VM ran before the baseline in even repeats. Likely RAM exhaustion: the local class is a 22 GiB RAM-backed null_blk on a 16 GiB runner, and deleted thin volumes do not discard their chunks back to null_blk the way XFS deletes do. Cancelled at ~40 min.

## Iteration 5

Iteration 4 winner `pci-iothread` (virtio-blk-pci, 2 queues, 1 iothread, event_idx on, cache=unsafe, aio=io_uring, qcow2) is the baseline. This iteration tries QEMU 11.1.3 (latest stable, source build) against the distro 8.2.2 the hosts run: same config, per-queue iothreads (iothread-vq-mapping, 9.0+), whether the virtio-mmio event_idx hang is fixed upstream, and whether today's prod cache settings still freeze on network disks.

Baseline: `pci-iothread`

Runs: [43681437433](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43681437433)

Configs:

- `pci-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "queues": 2}` — iteration 4 winner, QEMU 8.2.2
- `pci-iothread-smp4`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "queues": 4, "smp": 4}` — 4 vCPUs, QEMU 8.2.2 (control for the next one)
- `q11-mmio-eidx-on`: `{"aio": "io_uring", "cache": "unsafe", "qemu": "latest"}` — is the virtio-mmio + event_idx hang fixed in QEMU 11?
- `q11-pci-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "latest", "queues": 2}` — same config on QEMU 11.1.3
- `q11-pci-iothreads2`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothreads": 2, "qemu": "latest", "queues": 2}` — one iothread per queue (iothread-vq-mapping)
- `q11-pci-iothreads2-smp4`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothreads": 2, "qemu": "latest", "queues": 4, "smp": 4}` — 4 vCPUs, 4 queues over 2 iothreads
- `q11-pci`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "qemu": "latest", "queues": 2}` — QEMU 11 without an iothread
- `q11-pci-prod`: `{"aio": "threads", "cache": "writeback", "dev": "pci", "qemu": "latest", "queues": 2}` — prod cache settings on PCI froze on network disks with 8.2 (7.5 s); sandbox-relevant
- `q11-pci-threads`: `{"aio": "threads", "cache": "unsafe", "dev": "pci", "iothread": 1, "qemu": "latest", "queues": 2}` — io_uring was slow on network sequential writes on 8.2; does threads win on 11?

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pci-iothread-smp4 | 3/3 | 1.00 (paired) | 144081 | 0.0 | 0 | 149090 | 0.0 | 4063 | 2.08 | 52624 | 6487 | 424 | 0.12 | 29.8 |
| pci-iothread | 3/3 | 1.00 | 160224 | 0.0 | 0 | 171774 | 0.0 | 5120 | 2.02 | 55517 | 5890 | 423 | 0.12 | 33.0 |
| q11-pci-iothread | 3/3 | 0.74 (paired) | 33102 | 7.4 | 58 | 187346 | 0.0 | 3330 | 1.92 | 46829 | 9455 | 541 | 0.12 | 22.2 |
| q11-pci-iothreads2-smp4 | 3/3 | 0.74 (paired) | 25170 | 3.1 | 214 | 145289 | 0.0 | 2926 | 2.05 | 33458 | 6863 | 423 | 0.12 | 17.7 |
| q11-pci-iothreads2 | 3/3 | 0.72 (paired) | 28111 | 3.1 | 174 | 148885 | 0.0 | 2840 | 2.04 | 37202 | 5935 | 413 | 0.12 | 18.4 |
| q11-pci | 3/3 | 0.68 (paired) | 28406 | 1.3 | 29 | 137810 | 0.0 | 3075 | 2.07 | 26908 | 5890 | 363 | 0.12 | 17.4 |
| q11-pci-threads | 3/3 | 0.58 (paired) | 26697 | 7.2 | 158 | 104360 | 0.0 | 1943 | 1.86 | 23016 | 5543 | 320 | 0.12 | 15.2 |
| q11-pci-prod | 3/3 | 0.53 (paired) | 23303 | 4.8 | 130 | 95172 | 0.2 | 2560 | 2.15 | 16473 | 5400 | 269 | 0.22 | 14.3 |
| q11-mmio-eidx-on | 0/3 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pci-iothread-smp4 | 3/3 | 1.06 (paired) | 126459 | 0.1 | 0 | 93858 | 0.1 | 1041 | 3.19 | 31645 | 4550 | 262 | 0.12 | 18.0 |
| pci-iothread | 3/3 | 1.00 | 123765 | 0.3 | 0 | 101847 | 0.4 | 602 | 2.02 | 58427 | 5858 | 432 | 0.12 | 12.6 |
| q11-pci-iothread | 3/3 | 0.84 (paired) | 54131 | 4.8 | 18 | 92112 | 0.3 | 631 | 3.22 | 25753 | 4148 | 274 | 0.12 | 14.1 |
| q11-pci | 3/3 | 0.78 (paired) | 134616 | 2.0 | 5 | 87005 | 0.8 | 271 | 1.64 | 26864 | 6072 | 391 | 0.12 | 12.2 |
| q11-pci-iothreads2 | 3/3 | 0.77 (paired) | 97547 | 1.4 | 14 | 59208 | 0.3 | 247 | 1.85 | 43825 | 6087 | 473 | 0.12 | 10.5 |
| q11-pci-iothreads2-smp4 | 3/3 | 0.77 (paired) | 52733 | 2.5 | 194 | 83014 | 0.5 | 218 | 2.14 | 35733 | 6910 | 412 | 0.12 | 9.7 |
| q11-pci-threads | 3/3 | 0.64 (paired) | 48439 | 2.0 | 12 | 68486 | 0.1 | 482 | 3.29 | 13709 | 3890 | 202 | 0.12 | 12.9 |
| q11-pci-prod | 3/3 | 0.33 (paired) | 20266 | 10.1 | 149 | 66208 | 0.2 | 188 | 4.11 | 14407 | 5685 | 281 | 1.44 | 11.7 |
| q11-mmio-eidx-on | 0/3 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

Failures:

- `q11-mmio-eidx-on` local rep 1: timeout D fresh_rand rc=137 inflight= 0 142
- `q11-mmio-eidx-on` local rep 2: timeout D fresh_rand rc=137 inflight= 0 131
- `q11-mmio-eidx-on` local rep 3: timeout 
- `q11-mmio-eidx-on` network rep 1: timeout D fresh_rand rc=137 inflight= 0 176
- `q11-mmio-eidx-on` network rep 2: timeout D fresh_rand rc=137 inflight= 0 166
- `q11-mmio-eidx-on` network rep 3: timeout D fresh_rand rc=137 inflight= 0 144

## Iteration 4

Iteration 3: moving the disk from virtio-mmio to virtio-blk-pci (2 queues) gave 2-5x fsync and random IOPS on both disk classes, and PCI with event_idx left on never hung (6/6), so the hang is specific to virtio-mmio. Baseline is now PCI + 2 queues + event_idx on + cache=unsafe + aio=io_uring. This iteration splits the PCI gain (queues, iothread, aio, cache), tests 4 vCPUs, and re-asks raw vs qcow2 with pairing, including raw with a 1 MiB XFS extent size hint.

Baseline: `pci`

Runs: [43680808711](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43680808711)

Configs:

- `mmio-uring`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off"}` — iteration 3 baseline (virtio-mmio), links the iterations
- `pci-iothread-eidx-off`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "dev_extra": "event_idx=off", "iothread": 1, "queues": 2}` — iteration 3 best score; does event_idx matter on PCI?
- `pci-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "iothread": 1, "queues": 2}`
- `pci`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "queues": 2}` — iteration 3 PCI winner with event_idx on
- `pci-mq1`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "queues": 1}` — is the PCI gain from MSI-X interrupts or from 2 queues?
- `pci-prod`: `{"aio": "threads", "cache": "writeback", "dev": "pci", "queues": 2}` — today's prod disk settings with only the transport moved to PCI (sandbox-safe)
- `pci-raw-extsize`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "layout": "reflink", "queues": 2, "xfs_extsize": "1m"}` — raw with a 1 MiB XFS extent size hint against fragmentation
- `pci-raw`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "layout": "reflink", "queues": 2}` — raw reflink copy instead of qcow2
- `pci-smp4-mq1`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "queues": 1, "smp": 4}` — 4 vCPUs sharing one queue: the multiqueue control
- `pci-smp4-mq4`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "queues": 4, "smp": 4}` — 4 vCPUs, one queue each (runner has 4 CPUs)
- `pci-threads`: `{"aio": "threads", "cache": "unsafe", "dev": "pci", "queues": 2}` — does io_uring still matter on PCI?

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pci-iothread-eidx-off | 3/3 | 1.12 (paired) | 166505 | 0.0 | 0 | 169270 | 0.0 | 3103 | 1.50 | 64017 | 5681 | 454 | 0.12 | 33.7 |
| pci-iothread | 3/3 | 1.09 (paired) | 170024 | 0.0 | 0 | 188620 | 0.0 | 5265 | 1.92 | 62519 | 8587 | 554 | 0.12 | 35.0 |
| pci | 3/3 | 1.00 | 195491 | 0.0 | 0 | 202909 | 0.0 | 5361 | 1.83 | 34228 | 9002 | 507 | 0.12 | 36.9 |
| pci-smp4-mq4 | 3/3 | 0.96 (paired) | 168925 | 0.0 | 0 | 175731 | 0.0 | 5133 | 1.82 | 33761 | 9699 | 489 | 0.12 | 33.1 |
| pci-mq1 | 3/3 | 0.93 (paired) | 133803 | 0.0 | 0 | 146694 | 0.0 | 4072 | 1.84 | 20603 | 6039 | 392 | 0.12 | 28.1 |
| pci-smp4-mq1 | 3/3 | 0.92 (paired) | 119518 | 0.0 | 0 | 130486 | 0.0 | 4214 | 2.17 | 19425 | 6180 | 340 | 0.12 | 25.9 |
| pci-threads | 3/3 | 0.79 (paired) | 110943 | 0.0 | 0 | 102755 | 0.0 | 4665 | 1.88 | 21096 | 8154 | 348 | 0.12 | 23.3 |
| pci-prod | 3/3 | 0.77 (paired) | 116144 | 0.0 | 0 | 107099 | 0.0 | 3385 | 1.86 | 21160 | 8455 | 355 | 0.12 | 24.3 |
| pci-raw | 3/3 | 0.67 (paired) | 17960 | 0.1 | 0 | 86777 | 0.0 | 4654 | 2.01 | 26124 | 5942 | 278 | 0.12 | 14.4 |
| pci-raw-extsize | 3/3 | 0.64 (paired) | 22031 | 0.1 | 0 | 83819 | 0.0 | 3923 | 2.10 | 17172 | 5443 | 266 | 0.12 | 13.2 |
| mmio-uring | 3/3 | 0.60 (paired) | 43992 | 0.1 | 0 | 58064 | 0.1 | 3580 | 1.80 | 9679 | 5174 | 204 | 0.12 | 14.5 |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pci-iothread-eidx-off | 3/3 | 1.14 (paired) | 125921 | 0.4 | 0 | 87736 | 0.6 | 704 | 2.02 | 55318 | 5899 | 435 | 0.12 | 11.7 |
| pci-iothread | 3/3 | 1.12 (paired) | 133033 | 0.3 | 0 | 90723 | 0.5 | 783 | 2.03 | 57461 | 5778 | 404 | 0.12 | 12.1 |
| pci-smp4-mq4 | 3/3 | 1.09 (paired) | 131784 | 0.3 | 0 | 112867 | 0.5 | 879 | 2.04 | 28754 | 6626 | 364 | 0.12 | 11.8 |
| pci | 3/3 | 1.00 | 118697 | 0.3 | 0 | 95775 | 0.4 | 589 | 2.01 | 29535 | 5869 | 398 | 0.12 | 11.7 |
| pci-mq1 | 3/3 | 0.97 (paired) | 90362 | 0.3 | 0 | 83533 | 0.1 | 1680 | 3.06 | 12876 | 4059 | 252 | 0.12 | 16.6 |
| pci-smp4-mq1 | 3/3 | 0.97 (paired) | 88322 | 0.3 | 0 | 83292 | 0.1 | 1762 | 3.17 | 11669 | 4340 | 237 | 0.12 | 16.8 |
| pci-threads | 3/3 | 0.95 (paired) | 67412 | 0.7 | 0 | 66782 | 1.2 | 2876 | 2.02 | 15642 | 5475 | 291 | 0.12 | 11.6 |
| pci-raw | 3/3 | 0.90 (paired) | 51904 | 0.0 | 0 | 75636 | 0.3 | 1692 | 3.11 | 16448 | 3939 | 178 | 0.12 | 12.5 |
| pci-raw-extsize | 3/3 | 0.79 (paired) | 118044 | 0.2 | 0 | 61650 | 0.5 | 853 | 2.05 | 16377 | 5451 | 172 | 0.12 | 11.7 |
| mmio-uring | 3/3 | 0.62 (paired) | 28229 | 0.1 | 0 | 35625 | 0.3 | 888 | 2.06 | 10356 | 5161 | 194 | 0.12 | 10.2 |
| pci-prod | 3/3 | 0.44 (paired) | 67322 | 7.5 | 252 | 82911 | 0.4 | 198 | 4.00 | 16786 | 7251 | 305 | 2.04 | 15.3 |

## Iteration 3

Iteration 2 winner `unsafe-uring` (event_idx=off + cache=unsafe + aio=io_uring: best local score, no >1 s freezes on network) is the baseline. New: disk front ends (virtio-blk on PCI with 2 queues, virtio-scsi), guest I/O scheduler, raw + cache=none + aio=native, and a PCI run with event_idx left on to test whether the lost-notification hang is specific to virtio-mmio. Paired: every job also runs the baseline on the same runner.

Baseline: `unsafe-uring`

Runs: [43680144129](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43680144129)

Configs:

- `raw-none-native`: `{"aio": "native", "cache": "none", "dev_extra": "event_idx=off", "layout": "reflink"}` — raw reflink copy, O_DIRECT, Linux AIO
- `unsafe-uring`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off"}` — iteration 2 winner
- `uring-extl2-128k`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=131072,extended_l2=on"}` — no fresh freezes on network in iteration 2; recheck with pairing
- `uring-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off", "iothread": 1}` — best random IOPS in iteration 2; recheck pgbench with pairing
- `uring-pci-eidx-on`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "queues": 2}` — does the event_idx hang happen on PCI too?
- `uring-pci-mq2-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "dev_extra": "event_idx=off", "iothread": 1, "queues": 2}`
- `uring-pci-mq2`: `{"aio": "io_uring", "cache": "unsafe", "dev": "pci", "dev_extra": "event_idx=off", "queues": 2}` — virtio-blk-pci, one queue per vCPU
- `uring-sched-none`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off", "guest_sched": "none"}` — guest scheduler none instead of the default
- `uring-scsi-iothread`: `{"aio": "io_uring", "cache": "unsafe", "dev": "scsi", "dev_extra": "event_idx=off", "iothread": 1}`
- `uring-scsi`: `{"aio": "io_uring", "cache": "unsafe", "dev": "scsi", "dev_extra": "event_idx=off"}` — virtio-scsi on virtio-mmio

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| uring-pci-mq2-iothread | 3/3 | 1.80 (paired) | 113108 | 0.0 | 0 | 118135 | 0.0 | 4121 | 3.23 | 31578 | 3911 | 273 | 0.13 | 24.4 |
| uring-pci-eidx-on | 3/3 | 1.60 (paired) | 156645 | 0.0 | 0 | 162686 | 0.0 | 3368 | 1.81 | 31044 | 5768 | 396 | 0.12 | 30.7 |
| uring-pci-mq2 | 3/3 | 1.44 (paired) | 87724 | 0.0 | 0 | 93516 | 0.0 | 4357 | 2.02 | 29057 | 5746 | 401 | 0.12 | 21.4 |
| uring-iothread | 3/3 | 1.21 (paired) | 106940 | 0.0 | 0 | 134682 | 0.0 | 3531 | 2.09 | 9189 | 4828 | 187 | 0.12 | 24.8 |
| uring-sched-none | 3/3 | 1.03 (paired) | 45237 | 0.1 | 0 | 59251 | 0.1 | 3448 | 2.07 | 11067 | 5051 | 223 | 0.12 | 15.2 |
| unsafe-uring | 3/3 | 1.00 | 42716 | 0.1 | 0 | 56061 | 0.1 | 4163 | 1.99 | 10856 | 5110 | 213 | 0.13 | 14.4 |
| uring-scsi | 3/3 | 0.99 (paired) | 54410 | 0.1 | 0 | 64617 | 0.1 | 4472 | 1.78 | 10958 | 7237 | 250 | 0.12 | 16.2 |
| uring-scsi-iothread | 3/3 | 0.97 (paired) | 28751 | 0.1 | 0 | 42060 | 0.0 | 3772 | 3.22 | 6059 | 3469 | 130 | 0.12 | 12.6 |
| uring-extl2-128k | 3/3 | 0.91 (paired) | 20175 | 0.1 | 0 | 55017 | 0.1 | 4214 | 2.03 | 10976 | 5102 | 214 | 0.12 | 11.1 |
| raw-none-native | 3/3 | 0.84 (paired) | 11615 | 0.0 | 0 | 65424 | 0.1 | 3961 | 2.21 | 7091 | 4659 | 146 | 0.12 | 11.8 |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| uring-pci-mq2-iothread | 3/3 | 2.03 (paired) | 169423 | 0.4 | 0 | 108362 | 0.3 | 903 | 1.71 | 60968 | 7738 | 428 | 0.12 | 11.8 |
| uring-pci-eidx-on | 3/3 | 1.76 (paired) | 160413 | 0.1 | 0 | 92866 | 0.8 | 913 | 1.81 | 34067 | 9246 | 498 | 0.12 | 11.9 |
| uring-pci-mq2 | 3/3 | 1.53 (paired) | 66446 | 0.2 | 0 | 80343 | 0.8 | 911 | 1.76 | 30641 | 5769 | 423 | 0.12 | 12.3 |
| uring-iothread | 3/3 | 1.27 (paired) | 67586 | 0.3 | 0 | 77198 | 0.3 | 941 | 2.05 | 9202 | 4997 | 189 | 0.12 | 12.5 |
| uring-sched-none | 3/3 | 1.11 (paired) | 31816 | 0.3 | 0 | 57403 | 0.3 | 1649 | 1.90 | 10448 | 4782 | 215 | 0.12 | 11.2 |
| uring-extl2-128k | 3/3 | 1.04 (paired) | 26457 | 0.1 | 0 | 34665 | 0.2 | 1142 | 3.15 | 6958 | 3507 | 157 | 0.12 | 9.0 |
| uring-scsi | 3/3 | 1.03 (paired) | 35249 | 0.1 | 0 | 50593 | 0.5 | 778 | 2.07 | 9489 | 5064 | 190 | 0.12 | 10.5 |
| uring-scsi-iothread | 3/3 | 1.03 (paired) | 32478 | 0.2 | 0 | 56011 | 0.1 | 1043 | 1.73 | 9018 | 5021 | 191 | 0.12 | 10.4 |
| unsafe-uring | 3/3 | 1.00 | 30824 | 0.1 | 0 | 38388 | 0.1 | 1098 | 1.80 | 10422 | 4712 | 213 | 0.12 | 10.6 |
| raw-none-native | 3/3 | 0.58 (paired) | 9730 | 0.1 | 0 | 19546 | 0.1 | 413 | 3.34 | 3591 | 3286 | 63 | 0.12 | 8.2 |

## Iteration 2

Iteration 1 winner `unsafe` (event_idx=off + cache=unsafe) is the new baseline; combine it with the other knobs that helped on either disk class. 3 repeats.

Baseline: `unsafe`

Runs: [43679492159](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43679492159)

Configs:

- `eidx-off`: `{"dev_extra": "event_idx=off"}` — iteration 1 baseline, for reference
- `unsafe-cluster-2m`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=2097152"}`
- `unsafe-extl2-128k`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=131072,extended_l2=on"}`
- `unsafe-extl2-prealloc`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=131072,extended_l2=on,preallocation=metadata"}`
- `unsafe-iothread`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "iothread": 1}`
- `unsafe-iothread-uring`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off", "iothread": 1}`
- `unsafe-lazy-refcounts`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "qcow2_opts": "lazy_refcounts=on"}`
- `unsafe`: `{"cache": "unsafe", "dev_extra": "event_idx=off"}` — event_idx=off + cache=unsafe
- `unsafe-mmio-modern`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "globals": "virtio-mmio.force-legacy=false"}`
- `unsafe-reflink-raw`: `{"cache": "unsafe", "dev_extra": "event_idx=off", "layout": "reflink"}`
- `unsafe-uring`: `{"aio": "io_uring", "cache": "unsafe", "dev_extra": "event_idx=off"}`

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unsafe-uring | 3/3 | 1.25 | 46735 | 0.1 | 0 | 60536 | 0.0 | 5447 | 1.98 | 12765 | 7463 | 234 | 0.12 | 15.3 |
| unsafe-iothread | 3/3 | 1.12 | 77471 | 0.0 | 0 | 80362 | 0.0 | 3894 | 1.91 | 7772 | 4899 | 157 | 0.13 | 18.1 |
| unsafe-mmio-modern | 3/3 | 1.04 | 42110 | 0.1 | 0 | 55086 | 0.0 | 4830 | 2.03 | 9073 | 4880 | 177 | 0.14 | 14.1 |
| unsafe-cluster-2m | 3/3 | 1.01 | 43027 | 0.0 | 0 | 56352 | 0.0 | 2817 | 1.62 | 8999 | 4929 | 174 | 0.13 | 14.9 |
| unsafe | 3/3 | 1.00 | 39590 | 0.1 | 0 | 53677 | 0.0 | 4146 | 2.06 | 8845 | 4829 | 171 | 0.13 | 13.8 |
| unsafe-iothread-uring | 3/3 | 0.98 | 72938 | 0.0 | 0 | 109080 | 0.0 | 4223 | 3.23 | 6077 | 3476 | 127 | 0.13 | 20.0 |
| unsafe-extl2-128k | 3/3 | 0.94 | 22249 | 0.5 | 0 | 55182 | 0.0 | 4357 | 2.05 | 8780 | 4912 | 175 | 0.14 | 11.0 |
| unsafe-extl2-prealloc | 3/3 | 0.93 | 21859 | 0.4 | 0 | 53928 | 0.0 | 4047 | 2.07 | 8984 | 4900 | 172 | 0.13 | 10.6 |
| unsafe-reflink-raw | 3/3 | 0.92 | 20705 | 0.1 | 0 | 50471 | 2.3 | 4521 | 2.03 | 8729 | 4946 | 146 | 0.12 | 10.1 |
| unsafe-lazy-refcounts | 3/3 | 0.73 | 23331 | 0.0 | 0 | 36476 | 0.0 | 4137 | 3.22 | 5932 | 3418 | 122 | 0.14 | 11.3 |
| eidx-off | 3/3 | 0.62 | 22432 | 0.1 | 0 | 35779 | 0.0 | 2226 | 3.40 | 5948 | 3406 | 117 | 0.24 | 11.7 |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unsafe-iothread | 3/3 | 1.46 | 42325 | 2.4 | 380 | 64327 | 1.1 | 3061 | 2.07 | 7908 | 4872 | 165 | 0.13 | 10.9 |
| unsafe-iothread-uring | 3/3 | 1.38 | 65716 | 0.2 | 0 | 92500 | 0.5 | 602 | 2.06 | 9213 | 4953 | 188 | 0.12 | 11.7 |
| unsafe-mmio-modern | 3/3 | 1.34 | 20837 | 2.2 | 252 | 40110 | 1.3 | 2528 | 1.56 | 8984 | 5633 | 180 | 0.12 | 9.7 |
| unsafe-lazy-refcounts | 3/3 | 1.28 | 22614 | 2.3 | 380 | 39756 | 0.5 | 2646 | 2.02 | 8579 | 4908 | 178 | 0.13 | 9.9 |
| unsafe-extl2-128k | 3/3 | 1.27 | 38518 | 0.1 | 0 | 28609 | 0.4 | 2738 | 1.88 | 8439 | 4595 | 123 | 0.12 | 9.6 |
| unsafe-uring | 3/3 | 1.19 | 29688 | 0.2 | 0 | 33962 | 0.1 | 557 | 1.96 | 11985 | 6429 | 234 | 0.13 | 10.7 |
| unsafe-reflink-raw | 3/3 | 1.19 | 39341 | 0.1 | 0 | 38346 | 1.3 | 2301 | 2.08 | 8542 | 4913 | 72 | 0.13 | 9.4 |
| unsafe-cluster-2m | 3/3 | 1.05 | 6455 | 4.7 | 450 | 39424 | 0.8 | 1947 | 2.08 | 8539 | 4987 | 177 | 0.13 | 9.8 |
| unsafe-extl2-prealloc | 3/3 | 1.02 | 20215 | 0.1 | 0 | 26978 | 0.3 | 3066 | 3.18 | 5740 | 3499 | 122 | 0.12 | 8.2 |
| unsafe | 3/3 | 1.00 | 20000 | 2.2 | 128 | 28560 | 0.4 | 3108 | 3.22 | 5613 | 3415 | 119 | 0.13 | 10.1 |
| eidx-off | 3/3 | 0.56 | 19471 | 7.3 | 128 | 28318 | 0.3 | 201 | 4.69 | 8458 | 4695 | 150 | 1.54 | 11.2 |

## Iteration 1

One knob at a time on top of `eidx-off` (today's prod config plus `event_idx=off`, the iteration 0 fix). `prod-today` is kept for reference.

Baseline: `eidx-off`

Runs: [43678086652](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43678086652)

Configs:

- `cluster-2m`: `{"dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=2097152"}`
- `discard-unmap`: `{"dev_extra": "event_idx=off", "discard": "unmap"}`
- `eidx-off`: `{"dev_extra": "event_idx=off"}` — prod-today + virtio-blk event_idx=off
- `extl2-128k`: `{"dev_extra": "event_idx=off", "qcow2_opts": "cluster_size=131072,extended_l2=on"}`
- `guest-noatime-commit60`: `{"dev_extra": "event_idx=off", "guest_fsopt": "noatime:commit=60"}`
- `iothread`: `{"dev_extra": "event_idx=off", "iothread": 1}`
- `lazy-refcounts`: `{"dev_extra": "event_idx=off", "qcow2_opts": "lazy_refcounts=on"}`
- `mmio-modern`: `{"dev_extra": "event_idx=off", "globals": "virtio-mmio.force-legacy=false"}`
- `none-uring`: `{"aio": "io_uring", "cache": "none", "dev_extra": "event_idx=off"}`
- `prealloc-meta`: `{"dev_extra": "event_idx=off", "qcow2_opts": "preallocation=metadata"}`
- `prod-today`: `{}` — qcow2 overlay (64K clusters), cache=writeback, aio=threads, no iothread, legacy virtio-mmio, guest write-through
- `reflink-raw`: `{"dev_extra": "event_idx=off", "layout": "reflink"}`
- `unsafe`: `{"cache": "unsafe", "dev_extra": "event_idx=off"}`
- `uring`: `{"aio": "io_uring", "dev_extra": "event_idx=off"}`

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unsafe | 2/2 | 1.33 | 49354 | 0.1 | 0 | 62594 | 0.0 | 5276 | 1.80 | 11003 | 7605 | 233 | 0.12 | 15.6 |
| cluster-2m | 2/2 | 1.04 | 38137 | 0.0 | 0 | 51298 | 0.0 | 4027 | 2.49 | 8428 | 5504 | 175 | 0.13 | 14.4 |
| eidx-off | 2/2 | 1.00 | 40538 | 0.1 | 0 | 55469 | 0.0 | 2448 | 1.76 | 8975 | 5351 | 179 | 0.18 | 14.4 |
| lazy-refcounts | 2/2 | 0.98 | 41963 | 0.1 | 0 | 56380 | 0.0 | 2289 | 1.91 | 8883 | 5063 | 179 | 0.18 | 14.5 |
| mmio-modern | 2/2 | 0.97 | 38948 | 0.1 | 0 | 53364 | 0.0 | 2746 | 2.18 | 8755 | 4727 | 168 | 0.16 | 14.1 |
| none-uring | 2/2 | 0.94 | 44332 | 0.0 | 0 | 57705 | 0.0 | 2939 | 2.58 | 5915 | 5122 | 130 | 0.13 | 15.7 |
| iothread | 2/2 | 0.92 | 64238 | 0.1 | 0 | 77146 | 0.0 | 2648 | 2.76 | 6740 | 4069 | 136 | 0.23 | 17.5 |
| guest-noatime-commit60 | 2/2 | 0.85 | 33386 | 0.1 | 0 | 47286 | 0.0 | 2173 | 2.40 | 7743 | 4738 | 152 | 0.19 | 13.2 |
| extl2-128k | 2/2 | 0.76 | 21518 | 0.1 | 0 | 45580 | 0.0 | 2375 | 2.66 | 7560 | 4222 | 148 | 0.25 | 10.4 |
| discard-unmap | 2/2 | 0.74 | 23942 | 0.1 | 0 | 36796 | 0.1 | 2434 | 3.29 | 6050 | 3495 | 122 | 0.13 | 11.9 |
| reflink-raw | 2/2 | 0.73 | 18116 | 0.1 | 0 | 36437 | 2.9 | 4280 | 2.60 | 7317 | 4149 | 116 | 0.31 | 9.4 |
| uring | 2/2 | 0.73 | 25796 | 0.1 | 0 | 33812 | 0.1 | 2223 | 3.37 | 7048 | 3529 | 149 | 0.18 | 11.7 |
| prod-today | 0/2 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| prealloc-meta | 0/2 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unsafe | 2/2 | 2.21 | 24628 | 2.4 | 316 | 42929 | 1.3 | 2862 | 2.08 | 8572 | 4986 | 143 | 0.14 | 9.8 |
| reflink-raw | 2/2 | 1.50 | 30167 | 0.1 | 0 | 33026 | 1.3 | 2550 | 2.45 | 7934 | 5360 | 106 | 1.59 | 9.2 |
| uring | 2/2 | 1.42 | 35798 | 5.4 | 126 | 55268 | 1.8 | 313 | 3.34 | 11112 | 5314 | 221 | 1.29 | 14.0 |
| cluster-2m | 2/2 | 1.31 | 9620 | 4.5 | 384 | 23907 | 0.9 | 1819 | 1.74 | 8340 | 5282 | 178 | 1.91 | 9.4 |
| iothread | 2/2 | 1.30 | 43891 | 5.5 | 190 | 66292 | 0.2 | 314 | 4.28 | 7688 | 5522 | 160 | 1.54 | 14.8 |
| extl2-128k | 2/2 | 1.14 | 23196 | 8.7 | 128 | 50300 | 0.4 | 153 | 1.80 | 8316 | 5065 | 177 | 2.20 | 10.3 |
| discard-unmap | 2/2 | 1.09 | 20935 | 5.1 | 128 | 38492 | 0.1 | 320 | 4.41 | 6692 | 4033 | 144 | 1.00 | 11.6 |
| lazy-refcounts | 2/2 | 1.03 | 15484 | 7.4 | 256 | 48810 | 0.5 | 195 | 4.15 | 8265 | 5413 | 179 | 1.95 | 11.6 |
| guest-noatime-commit60 | 2/2 | 1.03 | 15203 | 5.8 | 192 | 42262 | 0.1 | 304 | 4.37 | 7156 | 4326 | 149 | 1.46 | 11.5 |
| mmio-modern | 2/2 | 1.02 | 18647 | 7.4 | 192 | 50002 | 0.2 | 200 | 4.75 | 8250 | 4910 | 174 | 2.02 | 12.0 |
| eidx-off | 2/2 | 1.00 | 20039 | 5.2 | 128 | 35458 | 1.0 | 318 | 4.42 | 5514 | 4158 | 136 | 1.39 | 11.2 |
| none-uring | 2/2 | 0.89 | 13006 | 0.2 | 0 | 18966 | 0.2 | 269 | 4.02 | 2652 | 2437 | 49 | 0.12 | 10.2 |
| prod-today | 0/2 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| prealloc-meta | 0/2 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

Failures:

- `prealloc-meta` local rep 1: harness_error result.json empty
- `prealloc-meta` local rep 2: harness_error result.json empty
- `prealloc-meta` network rep 1: harness_error result.json empty
- `prealloc-meta` network rep 2: harness_error result.json empty
- `prod-today` local rep 1: timeout 
- `prod-today` local rep 2: timeout D fresh_rand rc=137 inflight= 0 167
- `prod-today` network rep 1: timeout D fresh_rand rc=137 inflight= 0 151
- `prod-today` network rep 2: timeout D fresh_rand rc=137 inflight= 0 143

## Iteration 0

Harness shakedown on GitHub-hosted runners (nested KVM). Today's prod config hung on 4K random writes into new files: the guest held ~130 writes in flight while QEMU sat idle (lost virtio notification). Turning off the virtio-blk event index (`event_idx=off`) is the only setting that fixed it. `ioeventfd=off`, modern virtio-mmio and an iothread did not.

Baseline: `base`

Runs: [43675251616](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43675251616), [43676726147](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43676726147)

Configs:

- `base`: `{}`
- `base-smp1`: `{"smp": 1}`
- `event-idx-off`: `{"dev_extra": "event_idx=off"}`
- `iothread`: `{"iothread": 1}`
- `mmio-ioeventfd-off`: `{"globals": "virtio-mmio.ioeventfd=off"}`
- `mmio-modern`: `{"globals": "virtio-mmio.force-legacy=false"}`

### local

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 0/2 | 1.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| mmio-modern | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| mmio-ioeventfd-off | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| iothread | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| event-idx-off | 1/1 | 0.00 | 48521 | 0.1 | 0 | 62817 | 0.0 | 3430 | 1.85 | 11140 | 7274 | 217 | 0.13 | 15.8 |
| base-smp1 | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

### network

| config | ok | score | fresh 4K IOPS | fresh worst s | fresh I/Os >1s | rewrite 4K IOPS | rewrite worst s | seq write MiB/s | 50k files s | fsync IOPS | pgbench TPS | base read MiB/s | VM stop s | host GiB written |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| event-idx-off | 1/1 | 1.06 | 19354 | 3.1 | 128 | 28524 | 0.1 | 436 | 4.15 | 5689 | 3420 | 123 | 0.74 | 10.8 |
| base | 1/2 | 1.00 | 13570 | 8.4 | 256 | 68400 | 0.4 | 172 | 4.63 | 8197 | 5205 | 180 | 2.26 | 12.4 |
| mmio-modern | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| mmio-ioeventfd-off | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| iothread | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| base-smp1 | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

Failures:

- `base` local rep 1: timeout D fresh_rand rc=137 inflight= 0 131
- `base` network rep 1: timeout D fresh_rand rc=137 inflight= 0 142
- `base-smp1` local rep 1: timeout D fresh_rand rc=137 inflight= 0 131
- `base-smp1` network rep 1: timeout D written_rand rc=137 inflight= 0 135
- `base` local rep 1: timeout D fresh_rand rc=137 inflight= 0 132
- `iothread` local rep 1: timeout D fresh_rand rc=137 inflight= 0 130
- `iothread` network rep 1: timeout D fresh_rand rc=137 inflight= 0 155
- `mmio-ioeventfd-off` local rep 1: timeout D fresh_rand rc=137 inflight= 0 130
- `mmio-ioeventfd-off` network rep 1: timeout D fresh_rand rc=137 inflight= 0 130
- `mmio-modern` local rep 1: timeout D fresh_rand rc=137 inflight= 0 132
- `mmio-modern` network rep 1: timeout D fresh_rand rc=137 inflight= 0 142
