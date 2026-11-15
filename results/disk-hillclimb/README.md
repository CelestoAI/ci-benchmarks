# CI VM disk hill-climb

Each run boots the prod CI microvm command line (QEMU 8.2.2, Celesto CI kernel `kernels-2026.10.28.0`,
virtio-mmio, 2 vCPU / 3 GiB guest) on a fresh GitHub-hosted runner (4 vCPU, 16 GiB, nested KVM) and runs `scripts/hillclimb/guest-bench.sh`.

- **local**: XFS (reflink) on a RAM-backed `null_blk` device with 20 us completions (stand-in for local NVMe;
  the runners have no local SSD).
- **network**: an XFS loop file (direct I/O) on the runner's only disk, a remote Azure disk attached over NVMe
  (stand-in for EBS / OVH volumes).
- Values are medians over repeats. **score** = geometric mean of each scored metric's ratio to the iteration's
  baseline config (named in each iteration) in the same disk class (above 1 is better).
- Worst-latency columns are not scored: a config that freezes is rejected. **ok** counts runs that finished;
  a run that hangs past its timeouts is not ok.
- Single VM per runner: no neighbor load. Finalists must still be checked on real hosts.
- Raw per-run records (config, QEMU drive string, every metric): `runs.jsonl`.

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
| mmio-modern | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| mmio-ioeventfd-off | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| iothread | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| event-idx-off | 1/1 | 0.00 | 48521 | 0.1 | 0 | 62817 | 0.0 | 3430 | 1.85 | 11140 | 7274 | 217 | 0.13 | 15.8 |
| base-smp1 | 0/1 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |
| base | 0/2 | 0.00 | – | – | – | – | – | – | – | – | – | – | – | – |

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
