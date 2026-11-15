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
