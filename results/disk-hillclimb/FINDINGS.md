# CI VM disk hill-climb: findings

What the iterations in `README.md` established, with the reasoning. Numbers are paired same-runner ratios
against each iteration's baseline (above 1 is better) unless stated. The test rig is described in `README.md`.

## Current best config for CI VMs (`pci-iothread`)

virtio-blk-pci (microvm `pcie=on`), `num-queues` = vCPUs, one iothread, `cache=unsafe`, `aio=io_uring`,
event_idx on (default), qcow2 overlay with 64K clusters on the sparse raw base, QEMU 8.2.2 (Ubuntu 24.04).
`cache=unsafe` is for disposable CI disks only, never sandboxes.

Medians over 9 runs, iterations 4-6:

| class | fsync IOPS (QD1) | fsync p50 | fresh 4K IOPS | rewrite 4K IOPS |
|---|---|---|---|---|
| local | 55,970 | 11 us | 161,902 | 173,320 |
| network | 58,084 | 11 us | 133,033 | 90,723 |

## Why each part

- **virtio-mmio hangs (prod today).** With event_idx on, the guest holds about 130 writes in flight while
  QEMU sits idle: a lost notification. It reproduces on QEMU 8.2.2 and 11.1.3 (6/6). virtio-blk-pci with
  event_idx on never hung. PCI also gave 2-5x fsync and random IOPS on both classes (iteration 3), with no
  boot-time cost.
- **iothread:** about 1.8-1.9x fsync on top of PCI (iteration 4).
- **Multiqueue:** one queue cost 26% fsync and about 18% fresh writes against two at 2 vCPUs; at 4 vCPUs,
  4 queues gave 1.4x fsync over 1. `iothread-vq-mapping` with 2 iothreads (QEMU 11.1.3) gave nothing.
- **io_uring over threads:** threads scored 0.6x. With `cache=writeback,aio=threads` (prod) on the network
  class, host page-cache writeback stalled writes up to 7.5 s even on PCI.
- **qcow2 over raw:** our raw disk is a sparse reflink copy, so each first guest write allocates in XFS at a
  random offset; qcow2 appends new clusters. Raw lost on fresh writes (local 0.12x, network 0.46x), and an
  XFS extent size hint did not fix it. qcow2 L2 cache tuning does not apply: the default covers the 40G disk.
- **dm-thin (LVM thin snapshot per VM, 64K chunks, zeroing on):** slower than qcow2 on every class.
  Network: fresh 0.08-0.11x, fsync 0.07-0.25x. Local (2 of 3 repeats): fresh 0.53-0.79x, fsync 0.19-0.59x,
  sequential 0.26-0.51x. Rejected.
- **Smaller knobs:** `event_idx=off` changed results by about 5%; guest `noatime` gave no gain.

## QEMU version: stay on 8.2.2 (or 9.2)

Fresh (allocating) writes regress from QEMU 10.1 on; rewrites and pgbench are unchanged.

| QEMU | local fresh | worst local stall | network sequential |
|---|---|---|---|
| 8.2.2 source build | 0.93 | 13 ms | 1.55 |
| 9.2.4 | 0.93 | 22 ms | 1.41 |
| 10.0.6 | 0.94 | 11 ms | 1.37 |
| 10.1.5 | 0.20 | 17.3 s | 0.49 |
| 10.2.4 | 0.16 | 16.0 s | 0.59 |
| Ubuntu 26.04 (10.2.1) | 0.15 | 4.8 s | 0.50 |
| Ubuntu 26.10 (11.0.3) | 0.17 | 4.8 s | 0.39 |
| 11.1.3 (iteration 5) | 0.15-0.2 | 9.8 s | |

Our 8.2.2 source build matches Ubuntu's 8.2.2, so the build is not the cause. Network sequential writes are
noisy (8.2.2 against Ubuntu's 8.2.2 reads 1.55), so judge versions by the local columns.

**Likely cause (not yet confirmed by trace):** QEMU commit
[a6a0a7fb0e](https://github.com/qemu/qemu/commit/a6a0a7fb0e) "file-posix, gluster: Handle zero block
status hint better" (with [c33159dec7](https://github.com/qemu/qemu/commit/c33159dec7) and
[31bf15d97d](https://github.com/qemu/qemu/commit/31bf15d97d), all in 10.1). In 10.0,
`bdrv_co_is_zero_fast()` asked for block status without zero detection, and file-posix answered "all data"
without `lseek`. So qcow2's `handle_alloc_space()` never saw the backing file as zero and did normal
copy-on-write. From 10.1 it asks with `BDRV_WANT_ZERO`, file-posix runs `lseek(SEEK_DATA/SEEK_HOLE)` and
finds holes in our sparse raw base. qcow2 then zeroes every newly allocated cluster with
`bdrv_co_pwrite_zeroes(..., BDRV_REQ_NO_FALLBACK)` before writing guest data. On XFS that is an
`fallocate` per new cluster. `fallocate` takes the inode's exclusive I/O lock, waits for in-flight direct
I/O, and can flush the range, which would serialize concurrent writes and explain the multi-second stalls.
Only first writes into new clusters take this path, which matches rewrites and pgbench being unaffected.

To confirm: count `fallocate` calls (`strace -c -f -e trace=fallocate`) or the `qcow2_skip_cow` trace
event on 10.0.6 against 10.1.5. No upstream report of this was found (QEMU GitLab issues, web search) as
of 2026-11-14.

## Test-rig notes

- GitHub runners come in several CPU models with about 2x speed spread; only paired ratios
  (iteration 3 on) are reliable.
- Iteration 6: the 4 dm-thin local jobs where the thin VM ran first lost their runners (no logs). Likely
  RAM: the local class is a 22 GiB RAM-backed `null_blk` on a 16 GiB runner, and deleted thin volumes do not
  return their chunks to `null_blk` the way XFS deletes do.
- Single VM per runner: no neighbor load. Finalists still need a check on real hosts.
