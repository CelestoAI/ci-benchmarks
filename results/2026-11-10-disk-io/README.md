# Disk I/O: Celesto CI VMs vs GitHub-hosted runners (2026-11-10)

Question: why do disk-heavy CI steps (warm `yarn install`, cache unpack) run slower on Celesto CI
VMs than on GitHub-hosted runners, and how much does the host type matter?

Workflow: [`.github/workflows/disk-io.yml`](../../.github/workflows/disk-io.yml) on branch
`investigate-disk-io`. Each run starts 9 jobs on `ubuntu-24.04` and 9 on
`["self-hosted","celesto-large"]` (4 vCPU, 16 GiB on both). Four runs on 2026-11-10: 36 GitHub jobs and 36 Celesto jobs (9 on the AWS host, 27 on OVH hosts).

## Short answer

1. **Disk is the cause of the slower installs, through stalls.** [verified]
   - On Celesto the guest's whole disk queue (30-85 requests) sometimes stops for 1 to 60 s, then
     all requests complete at once. The guest file system waits behind it.
   - Per `yarn install --offline` run, these stalls explain 90% (AWS host) and
     95% (OVH hosts) of the extra time on disk compared with the same install in RAM.
   - GitHub: 0 stalls in 108 runs. Its install is 1.2 s slower on disk than in RAM (median).
   - The guest file system is not the problem: ext4 on a RAM disk in the same VM is as fast as tmpfs.
2. **The host type matters a lot.**
   - AWS host (`m6i.metal`, Xeon 8375C, bare metal): fastest CPU and the fastest disk when it does
     not stall, but by far the most stall time. Warm install: 59.5 s on disk, 7.1 s in RAM.
   - OVH hosts (`b3-256-flex`, EPYC-Milan, themselves KVM guests): fewer stalls (18.5 s on
     disk), but the install is slower than GitHub even in RAM (14.4 s vs 10.9 s).
     That part is not disk.
3. **Where the stalls come from (QEMU on the host).** [verified on 6 hosts]
   - All VM disks of a host are qcow2 files on one XFS file system on one network volume that is
     capped at about 500 MB/s. During the runs the AWS host's volume was at its cap (busy ≥ 95%)
     44-69% of the time; the OVH hosts' volumes 22-44% of the time.
   - ~25% of stall time: QEMU itself calls `fdatasync` on the VM's qcow2 file (the guest sends no
     flushes). It waits in the host's write-back throttling on the full volume, and the VM's other
     writes queue behind it on the XFS inode lock. Pre-allocated qcow2 metadata removed all these
     `fdatasync` calls on the rig.
   - ~55% of stall time: QEMU has finished requests but its event loop sleeps. Nothing is blocked
     and no I/O happens until something unrelated wakes the loop. Root cause inside QEMU not found.
   - ~20%: mixed; QEMU writes some data but the guest gets no completion.

## What each job measures

Every test runs 3 times on the workspace disk and on `/dev/shm` (RAM) as a control:

- `fio --direct=1`: 4 KiB random read and write at iodepth 1 and 32, 1 MiB sequential read and
  write (iodepth 8), and 4 KiB buffered writes with `fdatasync` after each one.
- Small files: extract a tar of excalidraw's real `node_modules` (62,379 entries, 846 MB) and
  delete it; create and delete 100k 4 KiB files from one process; `sync` after each step.
- `yarn install --frozen-lockfile --offline` of excalidraw from a filled 3 GB yarn cache, into the
  workspace, into `/dev/shm`, and (round 2+) into ext4 on a RAM-backed loop device.
- A sampler reads `/proc/diskstats` every 50 ms. A **stall** is 0.5 s or more with requests in
  flight and none completing. Round 3+ also run CPU and memory micro-benchmarks with no disk.

On the pool hosts (read-only, `celesto-pool-host-access` skill): a `/proc` sampler every 1 s
(round 1) or 0.5 s (round 2+) for the data disk and each QEMU process (bytes, syscalls, threads in
D state with their kernel wait point), and `bpftrace` counters of guest kicks, injected interrupts,
QEMU disk syscalls and `ppoll` returns per QEMU process. Each job is matched to its QEMU process by
its 2 GiB `fio` write bursts, or by correlating the guest's written bytes with each QEMU's write
rate. Nothing on the hosts was changed; the tracers and their files were removed afterwards.

## Results

### Disk (fio on the workspace, median of job medians)

| fio on workspace disk (IOPS / MB/s / p99) | GitHub `ubuntu-24.04` (36 jobs) | Celesto, AWS host (8375C) (9 jobs) | Celesto, OVH hosts (Milan) (27 jobs) |
|---|---|---|---|
| 4k rand read QD1 | 7,120 / 29 / 260 µs | 23,140 / 95 / 50 µs | 6,351 / 26 / 202 µs |
| 4k rand read QD32 | 19,564 / 80 / 41 ms | 5,895 / 24 / 506 µs | 9,762 / 40 / 2146 µs |
| 4k rand write QD1 | 12,738 / 52 / 157 µs | 21,566 / 88 / 54 µs | 6,169 / 25 / 208 µs |
| 4k rand write QD32 | 19,572 / 80 / 41 ms | 8,524 / 35 / 481 µs | 10,299 / 42 / 1860 µs |
| 1M seq read QD8 | 394 / 414 / 62 ms | 2,079 / 2,181 / 586 µs | 4,666 / 4,894 / 1401 µs |
| 1M seq write QD8 | 416 / 436 / 62 ms | 379 / 398 / 468 ms | 344 / 361 / 835 ms |
| 4k write + fdatasync | 3,863 / 16 / 14 µs | 5,682 / 23 / 7 µs | 1,388 / 6 / 31 µs |

- QD1 latency: AWS host best, OVH worst. QD32 on Celesto is limited by stalls inside the 8 s test.
- 1 MiB writes: p99 of 0.4-0.8 s on Celesto (stalls) against GitHub's flat 62 ms (its throughput cap).
- `fdatasync` is cheap on Celesto because the guest disk is `write through` (PR #1116): no flush
  reaches QEMU.

### Small files and yarn

| step, seconds: median of job medians (range) | GitHub `ubuntu-24.04` | Celesto, AWS host (8375C) | Celesto, OVH hosts (Milan) |
|---|---|---|---|
| extract node_modules tar, disk | 2.3 (1.1-2.7) | 1.1 (1.0-1.2) | 1.7 (1.5-1.9) |
| extract node_modules tar, RAM | 1.2 (0.7-1.5) | 0.6 (0.6-0.7) | 0.9 (0.8-1.1) |
| create 100k files, disk | 2.6 (1.2-3.0) | 1.0 (0.9-1.1) | 1.6 (1.5-1.9) |
| delete 100k files, disk | 8.0 (4.8-15.2) | 0.8 (0.8-0.9) | 1.5 (1.4-2.1) |
| **yarn install --offline, disk** | 12.4 (9.3-14.3) | 59.5 (37.0-134.5) | 18.5 (13.5-51.8) |
| yarn install --offline, RAM (tmpfs) | 10.9 (5.7-12.9) | 7.1 (7.0-7.9) | 14.4 (13.8-15.8) |
| yarn install --offline, ext4 in RAM | 11.7 (6.0-13.6) | 7.4 (7.1-8.1) | 13.4 (12.7-14.6) |
| yarn install cold (network) | 46.3 (33.7-54.4) | 45.5 (33.7-115.0) | 61.4 (50.1-77.3) |

### Is disk the cause? Stall time vs extra time on disk

| | yarn runs on disk | extra time vs RAM (total) | extra per run (median) | guest stall time | stalls / extra | runs with a stall |
|---|--:|--:|--:|--:|--:|--:|
| GitHub `ubuntu-24.04` | 108 | 253 s | 1.2 s | 0 s | 0% | 0 |
| Celesto, AWS host (8375C) | 27 | 1,880 s | 57.2 s | 1,687 s | 90% | 27 |
| Celesto, OVH hosts (Milan) | 81 | 730 s | 4.4 s | 695 s | 95% | 49 |

### Per host

| host | jobs | 4k write QD1 IOPS | 4k read QD1 IOPS | 4k write QD32 IOPS | 1M write MB/s | fsync IOPS | extract s | yarn disk s | yarn RAM s | stall s per job |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| GitHub | 36 | 12,738 | 7,120 | 19,572 | 436 | 3,863 | 2.3 | 12.4 | 10.9 | 0 |
| 408bfda0 OVH | 6 | 6,172 | 6,484 | 3,967 | 297 | 1,237 | 1.6 | 21.8 | 14.2 | 46 |
| 5a61d920 OVH | 5 | 6,582 | 6,944 | 7,633 | 401 | 1,541 | 1.6 | 22.6 | 14.0 | 51 |
| 9358bdb2 OVH | 3 | 6,573 | 6,555 | 11,582 | 473 | 1,624 | 1.5 | 16.0 | 14.5 | 21 |
| 9b5db889 OVH | 8 | 5,973 | 6,156 | 10,852 | 302 | 1,374 | 1.8 | 20.0 | 15.3 | 34 |
| cf15ca5b OVH | 5 | 5,700 | 6,084 | 22,465 | 440 | 1,274 | 1.7 | 14.3 | 14.4 | 27 |
| f2eb72ca AWS m6i.metal | 9 | 21,566 | 23,140 | 8,524 | 398 | 5,682 | 1.1 | 59.5 | 7.1 | 205 |

### CPU and memory (no disk, round 3+)

| | jobs | Python loop s | spawn 2000 processes s | touch 2 GiB s | 30x `node -e 0` s | fio 4k QD1 on tmpfs IOPS |
|---|--:|--:|--:|--:|--:|--:|
| GitHub `ubuntu-24.04` | 18 | 2.2 | 1.4 | 1.9 | 0.7 | 345,646 |
| Celesto, AWS host (8375C) | 4 | 1.9 | 0.8 | 0.9 | 0.6 | 583,407 |
| Celesto, OVH hosts (Milan) | 14 | 1.7 | 1.8 | 1.4 | 0.7 | 239,687 |

- OVH guests are not slower at plain CPU, page faults or `node` start-up; process spawn is ~30%
  slower and syscall-heavy work on tmpfs (fio) is ~30% slower than GitHub. Why yarn takes 14 s in
  RAM there is not measured further. Nested virtualization is the likely cause. [inferred]

## Where the stall time goes (host side)

Each Celesto job was matched to its QEMU process on the pool host. For every guest stall of 1 s or
more in rounds 2-4 (615 stalls, 5,437 s), the 0.5 s host samples inside the stall decide its type:

| Stall type | What the host shows | Stalls (AWS / OVH) | Share of stall time | Host disk busy (median) |
|---|---|--:|--:|--:|
| QEMU blocked | a QEMU thread of that VM in D state for at least half of the stall | 203 (55 / 148) | 23% | 100% |
| QEMU idle | QEMU writes less than 1 MiB and has no blocked thread | 326 (164 / 162) | 56% | 15-97% by round |
| slow (mixed) | QEMU writes data, but the guest gets no completion | 86 (56 / 30) | 21% | 18-71% |

### QEMU blocked: QEMU's own `fdatasync` on a saturated shared volume [verified]

- The blocked QEMU threads wait in `fdatasync` → `rq_qos_wait`, the host's write-back throttling
  (WBT): 1,950 thread-samples. Other QEMU threads of the same VM wait in `xfs_ilock` inside
  `pwritev`/`pwrite64` (813 samples), so all of that VM's I/O stops. `fallocate` is rare (15).
- The guest sends **no** flushes: in all 36 Celesto jobs `write_cache` is `write through` and the
  guest flush counter stayed at 0. So the `fdatasync` comes from QEMU's qcow2 driver itself.
- The flush must write all of the VM's dirty data in the host page cache through the shared volume,
  which is full at those moments (median host disk busy 100%).
- Rig A/B (below): with the production overlay QEMU called `fdatasync` 27-31 times during one
  1.7 GB extract, about 0.55 s each; with the qcow2 metadata allocated up front it called it 0 times.
  So the calls come from qcow2 metadata allocation (new L2 tables or refcount blocks flush the whole
  file). [the exact QEMU function is inferred, not traced]

### QEMU idle: finished requests wait for QEMU's main loop to wake up [verified symptom; root cause in QEMU not found]

- In idle stalls of 17-24 s the whole QEMU process made 0-27 read/write syscalls, raised no disk
  interrupt and had no blocked thread. The guest held 30-80 requests and sent no new kick.
- They happen even when the host disk is mostly idle: in round 4 the AWS host's disk was a median
  15% busy during them. So they are not the volume limit.
- Disk-only tracing in rounds 3-4 (kicks to the disk's MMIO address `0xfeb02c50`, interrupts on
  GSI 22, QEMU disk syscalls, and the main loop's `ppoll` returns): of 157 stalls of 2 s or more with
  at least 1 s of QEMU disk silence, 133 ended right after QEMU's main loop returned from `ppoll`
  (40 times by a plain timeout after up to 24 s, 93 times by an unrelated fd event), 23 ended when a
  new guest kick woke the loop, and 1 otherwise. On the AWS host the first disk event after the
  wake-up was QEMU raising the disk interrupt in 93 of 121 cases, with no new disk I/O before it.
- So the requests were already finished inside QEMU, and QEMU's main loop slept until something
  unrelated woke it. This matches the earlier QMP reading (Nov 9): QEMU held 1-3 taken but not
  completed requests for the whole stall.
- Setup where it happens: QEMU 8.2.2, `microvm` with `virtio-mmio`, `aio=threads`, no IOThread, so
  disk completions go from QEMU's thread pool back to the main loop. Both providers show it.

## The VM disk path (code and hosts)

Code (read from `origin/main` of the backend and the pinned SDK `celesto==0.1.12`):

| Layer | Setting | Where |
|---|---|---|
| QEMU machine | `-machine microvm,accel=kvm,acpi=on,pcie=off,pic=off,pit=off,rtc=on`, disk as `-device virtio-blk-device` (virtio-mmio), no IOThread | SDK `src/celesto/runtime/qemu_args.py` |
| QEMU drive | `-drive file=<vm>.qcow2,if=none,format=qcow2,id=rootdisk0-drive,node-name=rootdisk0`: no `cache=`, no `aio=`, so QEMU defaults: `cache=writeback`, `aio=threads` | SDK `src/celesto/runtime/qemu_args.py` |
| VM disk | `qemu-img create -f qcow2 -b <base> -F raw`: 64 KiB clusters, `lazy_refcounts=off`, no `extended_l2`, no preallocation | SDK `src/celesto/vm.py` `_create_qemu_overlay_disk` |
| Base | reflink copy (FICLONE) of the template rootfs, grown with `truncate` and `resize2fs` | backend `dataplane/host/agent/template_artifacts.py` `prepare_template_disk` |
| Guest flushes | the runner start command writes `write through` to `/sys/block/vd*/queue/write_cache`, so the guest never sends a flush (PR #1116) | backend `src/celesto_cloud_core/services/github_actions_ci_service.py` `ci_disable_guest_flushes_command` |

Measured on the hosts and in the guests (read-only):

| | AWS host `f2eb72ca` | OVH hosts (6) | GitHub runner |
|---|---|---|---|
| Machine | `m6i.metal`, Xeon 8375C, bare metal, 503 GB RAM | `b3-256-flex` KVM guest, EPYC-Milan, 245 GB RAM | Azure VM (EPYC 7763 / 9V74 / Xeon 8573C) |
| VMs at the time | 24-46 | 0-23 per host | 1 |
| Where VM disks live | XFS (reflink) on one 4 TB EBS gp3 volume (`nvme1n1`) | XFS on one 1,000 GiB High Speed Gen2 network volume (`sdb`, "QEMU HARDDISK") | own disk (Hyper-V "Virtual Disk" or "MSFT NVMe Accelerator") |
| Volume limit | 500 MB/s; at the cap (busy ≥ 95%) 44-69% of the run time | ~500 MB/s (OVH: 0.5 MB/s per GB, max 512); at the cap 22-44% of the run time | ~435 MB/s, ~19.6k IOPS cap |
| Host queue | scheduler none, WBT 2 ms, max 128 KiB per request | rotational=1, WBT 75 ms | - |
| QEMU file open flags | `02100002` (no `O_DIRECT`), so writes go to the host page cache | same | - |
| cgroup limits on QEMU | none (all VMs in `celesto-pool-agent.service`) | none | - |
| Guest kernel / fs | 7.3.0, ext4 `rw,relatime` (data=ordered, commit=5), 64 MiB journal | same | 7.0 azure, ext4 `nobarrier,data=writeback,commit=30,journal_async_commit` |
| Guest disk queue | `vda`: mq-deadline, rotational=1, 1 hardware queue, `write_cache=write through`, IRQ `IO-APIC 22-fasteoi` | same | none scheduler, 4 queues (NVMe) |

## Rig experiments (local only)

Rig: Lima VM `celesto-hostpull` on the Mac (Ubuntu 24.04, QEMU 8.2.2, the same package as the
pool hosts, nested KVM, arm64). VM disks are qcow2 overlays like production, on XFS (reflink) on a
`null_blk` device capped at 125 MB/s with 1 ms per request, WBT 75 ms. One 4 vCPU "victim" VM
extracts the same `node_modules` tar; two neighbour VMs write 80 MB/s each, so the device stays
full. Guests use `write through`, as on Celesto. The rig is arm64 (`virt` machine, GIC), not x86
`microvm`, and has 18 GB RAM, so it is a model of the host side, not a copy.

**1. Where QEMU's flushes come from (victim alone, 2 runs each, alternating):**

| VM disk | extract x2 + sync | QEMU `fdatasync` calls | time spent in them |
|---|--:|--:|--:|
| production overlay: `qemu-img create -f qcow2 -b base -F raw` | 21.9 s, 20.9 s | 31, 27 (avg 0.54-0.58 s) | 16.6 s, 15.7 s |
| `-o cluster_size=128k,extended_l2=on,preallocation=metadata` | 7.7 s, 6.4 s | 0, 0 | 0 |

**2. Settings under neighbour load (extract of 846 MB, 3 rounds each, alternating with the baseline):**

| configuration | rounds | extract (median) | stall time per 3 rounds | longest stall | extract + sync (median) |
|---|--:|--:|--:|--:|--:|
| production overlay, victim alone (no neighbours) | 3 | 7.4 s | 19 s | 6.0 s | 14.0 s |
| **production overlay + neighbours (baseline)** | 12 | 23.7 s | 61 s | 12.3 s | 38.0 s |
| `cache=unsafe` on all VMs | 3 | 26.5 s | 57 s | 8.2 s | 42.0 s |
| `cache=none,aio=io_uring` on all VMs | 3 | 108.2 s | 7 s | 2.5 s | 135.7 s |
| IOThread for the victim's disk | 3 | 24.8 s | 53 s | 7.3 s | 35.2 s |
| host WBT off (`wbt_lat_usec=0`) | 3 | 20.6 s | 44 s | 9.8 s | 32.7 s |
| overlays with `extended_l2` + `preallocation=metadata` | 3 | 21.6 s | 48 s | 3.6 s | 32.7 s |
| **same load, device 1,000 MB/s and 0.1 ms (like local NVMe)** | 3 | 4.7 s | 3 s | 1.3 s | 6.1 s |
| baseline again, after the fast-device run | 3 | 23.7 s | 60 s | 17.1 s | 34.9 s |
| baseline, host dirty limit 4 GiB (like production) | 6 | 10.1 s | 26 s | 7.4 s | 10.6 s |
| pre-allocated metadata, host dirty limit 4 GiB | 6 | 2.4 s | 0 s | 0.1 s | 2.8 s |
| `cache=unsafe`, host dirty limit 4 GiB | 3 | 2.7 s | 0 s | 0.2 s | 3.1 s |

- With the rig's default host memory (18 GB RAM, 20% dirty ratio), the blocked QEMU thread waits
  in `balance_dirty_pages`: the host's small dirty-page limit throttles it, and the other QEMU threads
  wait on `xfs_ilock`. Production hosts have 130-190 GB free and never hit that limit. In this mode
  no QEMU setting helped much (`cache=unsafe`, IOThread, pre-allocated metadata, WBT off).
- `cache=none,aio=io_uring` removed the stalls, but every write then waited for the full device:
  the extract took 108 s instead of 23 s. Do not use it on a shared, saturated volume.
- **More device bandwidth removed the stalls.** Same VMs, same 160 MB/s of neighbour writes, same
  production disk settings, but a 1,000 MB/s / 0.1 ms device: extract 4.7 s instead of 23.7 s, stall
  time 3 s instead of ~60 s per 3 rounds. The control run right after, back at 125 MB/s, was 23.7 s.
- **With production-like host memory** (rows "host dirty limit 4 GiB"), the rig's stalls look
  exactly like production's blocked stalls: the QEMU thread waits in `fdatasync` → `rq_qos_wait`
  while the device is 100% busy (7 of 7 stalls). Then pre-allocated metadata and `cache=unsafe`
  both removed every stall and made the extract about 4x faster. Each was run twice, alternating
  with the baseline: baseline 10.1 s with 52 s of stalls over 6 rounds (12 of 12 stalls in
  `fdatasync`), pre-allocated metadata 2.4 s with 0 stalls over 6 rounds.
- The rig never showed the "QEMU idle" stalls, so it cannot test fixes for them.

## Recommendation

1. **Create CI overlays with their qcow2 metadata allocated up front.** In the SDK,
   `src/celesto/vm.py` `_create_qemu_overlay_disk`, add
   `-o cluster_size=131072,extended_l2=on,preallocation=metadata` to `qemu-img create -f qcow2 -b <base> -F raw`
   (QEMU needs `extended_l2=on` to combine a backing file with preallocation).
   - Gain on the rig: victim alone, QEMU `fdatasync` calls 27-31 → 0 and extract 21-22 s → 6-8 s;
     under neighbour load with production-like host memory, extract 10.5 s → 2.4 s and all stalls
     gone. Tested on the rig only.
   - Expected in production: removes the "QEMU blocked" stalls (~25% of Celesto stall time).
   - `cache=unsafe` on CI drives did the same on the rig (2.7 s, no stalls), because QEMU then skips
     the flushes. Pre-allocated metadata keeps flush semantics for any other caller, so it is the
     smaller change; either works for throwaway CI disks.
   - Cost on the rig for a 60 GiB disk: create 122 ms instead of 10 ms, 61 MB of real space, and a
     sparse apparent size of 60 GiB; `qemu-img check` passes and guests boot and run normally.
   - Check before rollout: `qemu-img` paths that read overlays (stopped-disk offload, snapshots)
     and disk-space accounting that uses the apparent size.
2. **Stop many VMs sharing one ~500 MB/s volume.** The AWS host's EBS gp3 volume was at its
   500 MB/s cap 44-69% of the run time, and blocked stalls happen when the volume is full (median
   100% busy). Options: raise gp3 throughput to its 1,000 MB/s maximum, spread VM disks over several
   volumes, or use hosts with local NVMe (for example `m6id.metal`). On the rig, 8x device bandwidth
   made the same loaded extract 5x faster and removed nearly all stalls; the production gain is
   inferred.
3. **Test an IOThread for the disk on one canary host** (`-object iothread,id=io0` and
   `virtio-blk-device,...,iothread=io0` in `src/celesto/runtime/qemu_args.py`), with the disk-only
   gap tracer from this study. The "QEMU idle" stalls (~55% of stall time) happen while QEMU's main
   loop sleeps with completed requests; an IOThread moves disk completion out of the main loop.
   Not tested: the rig does not reproduce these stalls, and production changes were out of scope.

**What it would gain:** if all disk stalls go, the warm install takes about its in-RAM time:
AWS host 59.5 s → about 8 s (GitHub: 12.4 s); OVH hosts 18.5 s → about 14.4 s. OVH stays ~30%
slower than GitHub for this install because of the non-disk part.

## Runs and timing

All runs: `CelestoAI/ci-benchmarks`, branch `investigate-disk-io`, at most 9 Celesto jobs at once
(one run at a time, `max-parallel: 18` over 9 + 9 jobs). Every job's start time is in its
`result.json` (`job_start_ms`); all 9 Celesto jobs of a run started within 20 s of each other.

| Round | Run ID | Start - end (UTC) | Celesto jobs: AWS host / OVH hosts | Upload-benchmark runs that overlapped (other agent) |
|---|---|---|---|---|
| 1 | [42872088223](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42872088223) | 18:08:15 - 18:25:51 | 3 / 6 | 42872499396 (18:10:38 - 18:25:55) |
| 2 | [42877780160](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42877780160) | 18:41:42 - 18:59:20 | 2 / 7 | 42875716811 (18:29:31 - 18:59:12) |
| 3 | [42881380542](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42881380542) | 19:03:19 - 19:21:40 | 1 / 8 | 42880658667 (18:59:04 - 19:07:52) |
| 4 | [42897852624](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42897852624) | 20:42:07 - 20:57:24 | 3 / 6 | none |

## Open questions

1. **Why does QEMU's event loop sleep with finished disk requests?** Next step: on one canary host,
   trace QEMU's thread-pool completion (`aio_notify`/bottom half) and `ppoll` timeouts for one VM,
   and A/B an IOThread for the disk. Needs a production canary; not done here.
2. **Exact qcow2 code path of the `fdatasync` calls** (L2 table or refcount block allocation) is
   inferred from the rig A/B, not traced inside QEMU.
3. **Why yarn is ~30% slower in RAM on OVH guests** (nested virtualization is the likely reason).
4. Job placement is not under the benchmark's control, so the AWS host got fewer jobs than the OVH
   hosts (see the job counts above). There is only one AWS host, so "8375C" and "AWS" are the same
   sample here, as are "Milan" and "OVH".

## Files

- Per job, each run's artifact `diskio-r<round>-<provider>-s<n>` holds `result.json` (environment,
  every fio result, every step with its guest disk stats), `env.txt` (lsblk, mount, queue settings,
  ext4, virtio), `disk.csv` (50 ms guest disk trace) and `cmd.log`.
- Host-side logs, rig scripts and analysis scripts stayed local; only this README and the workflow
  are committed.
