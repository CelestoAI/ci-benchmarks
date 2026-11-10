# Cache upload bandwidth, November 10, 2026

Why does a large `actions/cache` save upload about 3.5 times slower on Celesto CI than on GitHub-hosted runners? This report looks only at bytes per second during the upload. The reserve and finalize calls (the wait before the first byte and after the last) are out of scope.

Workflow: [`upload-bandwidth.yml`](../../.github/workflows/upload-bandwidth.yml) on branch `investigate-upload-bandwidth`.

| Run | Workflow commit | Jobs |
| --- | --- | --- |
| [42872499396](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42872499396) | `b634d13` | smoke test, 1 GitHub + 1 Celesto |
| [42875716811](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42875716811) | `3bef563` | round 1: 9 GitHub `ubuntu-24.04` + 9 Celesto `celesto-large` |
| [42880658667](https://github.com/CelestoAI/ci-benchmarks/actions/runs/42880658667) | `4b68fae` | round 2: 6 Celesto, adds 32 x 32 MiB and 64 x 16 MiB saves |

All 26 jobs passed. Celesto jobs ran on 3 AWS samples (`aws_m6i_metal`, Xeon Platinum 8375C) and 12 OVH samples on 6 hosts (AMD EPYC-Milan). Both are 4 vCPU / 16 GiB, like GitHub's runner.

## Answer

1. **[verified] The limit is the speed of one upload request into Cloudflare R2.** Each 64 MiB part moves at about 21-25 MB/s. It is the same on AWS hosts (median 25) and OVH hosts (median 21). The toolkit always uploads 8 blocks at a time, so a save tops out near 8 x 21 MB/s: **161-162 MB/s** median on both host types. GitHub's runner writes each block to Azure Blob at about 44 MB/s, so the same 8 blocks give **411 MB/s**.
2. **[verified] More parallel R2 requests remove the limit.** Through the same proxy and the same R2 bucket, with the same 1023 MiB: 16 x 64 MiB gives 257-303 MB/s, 32 x 16 MiB gives 514-527 MB/s, and 64 x 16 MiB gives 734-854 MB/s. That is 3.2 to 5.3 times the stock save, and above GitHub's 411 MB/s.
3. **[verified] The VM network, QEMU and the host uplink are not the limit.** The same VMs upload 0.9-1.3 GB/s to Netflix's servers with 8-16 streams (OVH) and 0.9-1.5 GB/s to an Ookla server in Ashburn (AWS and OVH). No ENA allowance, tap, NIC or qdisc drops on the hosts.
4. **[verified] The in-VM proxy is not the limit.** Built from backend `main` and run locally against a stand-in API and sink, it relays 490-640 MB/s on one stream and 1.3-1.9 GB/s on 8 (3 runs). In the CI VMs it uses 0.03 CPU cores at 1 stream and 0.2-0.3 at 8. Its R2 sockets hold 2-3 MB of unsent data most of the time, so it always has bytes ready; the other side is not taking them.
5. **[verified] The per-request cap is on Cloudflare's side.** Plain uploads to Cloudflare's edge (`speed.cloudflare.com/__up`) also run at 17-50 MB/s per request, from GitHub's Azure runners too. There, `ss` shows the sender waiting for Cloudflare's receive window for a median 89% of each upload (362 connections); uploads to Azure Blob and Netflix wait 0%. **[inferred]** Whether R2 storage or the edge in front of it sets the 21-25 MB/s, we cannot see from outside.
6. **[verified] Next ceiling, after a fix: QEMU's network thread.** QEMU attaches the VM to its tap without `vhost=on`, with one queue. When a VM sends 0.95-1.96 GB/s, QEMU's main thread runs at 87-98% of a core (6 of 6 round-2 jobs, host-side samples). The 64 x 16 MiB save also used 65-85% of the VM's 4 vCPUs.

## Results

1023 MiB of random data. MB/s is the payload rate on the NIC between 2% and 98% of the bytes, median over jobs (range in brackets). "Per request" is one HTTP request's own rate.

| Path | Streams | GitHub (Azure) | Celesto AWS | Celesto OVH |
| --- | --- | ---: | ---: | ---: |
| actions/cache save, per 64 MiB block | 1 | 44 (14-75) | 25 (23-26) | 21 (15-28) |
| actions/cache save | 1 x 64 MiB | 43 (9-70) | 24 (23-24) | 20 (16-26) |
| | 4 x 64 MiB | 206 (169-270) | 83 (81-84) | 86 (74-102) |
| | **8 x 64 MiB (stock)** | **411 (78-542)** | **161 (156-163)** | **162 (114-198)** |
| | 16 x 64 MiB | 571 (32-857) | 303 (286-367) | 257 (139-428) |
| | 32 x 16 MiB | 490 (466-857) | 514 (467-541) | 527 (395-570) |
| | 32 x 32 MiB | - | 570 (1 job) | 512 (321-642) |
| | 64 x 16 MiB | - | 734 (1 job) | 854 (685-856) |
| actions/cache restore (download) | stock | 151 (101-286) | 285 (198-311) | 221 (124-263) |
| Netflix upload | 1 / 4 / 8 / 16 | 10 / 43 / 85 / 165 | 27 / 107 / 214 / 359 | 134 / 529 / 914 / 1255 |
| Netflix upload, per request | 1 | 12 | 22 | 179 |
| Netflix download | 1 / 4 / 8 / 16 | 12 / 58 / 118 / 210 | 30 / 131 / 245 / 412 | 142 / 529 / 874 / 914 |
| Cloudflare edge upload, per request | 1 / 4 / 8 / 16 | 50 / 33 / 49 / 25 | 23 / 19 / 17 / 24 | 22 / 25 / 25 / 23 |
| Cloudflare edge download, per request | 1 / 4 | 132 / 181 | 173 / 161 | 118 / 130 |
| Ookla Ashburn upload / download | its own | 232 / 1402 | 1336 / 1459 | 1096 / 990 |
| Ookla upload range | | 177-1593 | 1264-1404 | 918-1516 |

Read the network rows with these limits in mind:

- GitHub placed its runners in five regions (Cloudflare colos IAD, ORD, SEA, SJC, LAX). Its cache storage is in the runner's region, so the save rows are fair; the Ookla and Netflix rows are not. The two Virginia runners (IAD) got 1067 and 1593 MB/s on Ookla.
- Netflix limits each flow from cloud networks: about 11-16 MB/s from Azure and 22-31 MB/s from AWS, at every stream count. From OVH it does not. So Netflix shows the VM's own capacity only on OVH; Ookla shows it on AWS.
- `speed.cloudflare.com` rate-limits bulk use (429, 502, 504; 78 of 1008 requests in round 1), so its aggregate MB/s is noise. The per-request numbers use only the 200 answers.
- Ookla numbers are Ookla's own (`speedtest -s 5132`, Shentel Ashburn).
- The toolkit's own "Sent ... MBs/sec" for the stock save counts from before the first byte. It reads 68-128 MB/s on Celesto (median 114) and 42-422 on GitHub (median 290) in round 1.

## How the limit was found

**The toolkit.** `actions/cache` v4.3.0 saves through `saveCacheV2`, which forces 64 MiB blocks and 8 parallel blocks (`dist/save-only/index.js` line 431). `saveCache` applies `CACHE_UPLOAD_CONCURRENCY` and `CACHE_UPLOAD_CHUNK_SIZE` to a copy of the options but passes the original options to the Azure SDK upload (lines 1389-1395). So these variables do nothing here, and a job cannot raise the 8. For the other stream counts the workflow downloads the same bundle and changes only those two numbers.

**The path.** On Celesto the toolkit uploads to the in-VM proxy (`dataplane/guest/src/ci_cache_proxy/upload.rs`). For each Put Block, the proxy asks the cache API for a presigned R2 part link (`/celesto/block-url`; direct multipart, D-36) and streams the body to R2 over its own HTTPS connection. One toolkit block is one R2 PUT. The VM does not upload to R2 on its own. HTTP/1.1 only (`reqwest` without `http2`), so 8 blocks are 8 TCP connections.

**Per request, not per VM.** With the same VM and the same proxy:

- 1 stream: 21-25 MB/s. 8 streams: 161-162. 64 streams: 734-854. The total grows with the number of R2 requests, so the VM and the path behind it have room.
- In `/proc/net/tcp` the proxy's R2 sockets hold a median 1.9-3.1 MB of queued data at 1 and 8 streams. In 71-81% of samples the queue is larger than the congestion window lets fly, with a window of 560-930 segments and about 0.1% retransmits. The sender is waiting for the receiver. (The Celesto guest kernel has no `inet_diag`, so `ss -i` shows almost nothing there; `/proc/net/tcp` still gives the queue and window.)
- On GitHub's runners, `ss -i` to Cloudflare's edge shows `rwnd_limited` for a median 89% of each upload (p90 98%). To Azure Blob the median is 0% (p90 5%), to Netflix 0%.

**Not the network.** The 16-stream Netflix upload reached 1114-1667 MB/s from OVH VMs; Ookla reached 918-1516 MB/s (OVH) and 1264-1404 MB/s (AWS). Inside the VM: `virtio_net`, 1 queue, MTU 1500, TSO and GSO on, `pfifo_fast`, `tcp_wmem` max 4 MiB, cubic. From the hosts (read-only): QEMU 8.2.2, `-netdev tap,...,script=no,downscript=no` without `vhost=on`, `virtio-net-device` on the `microvm` machine. No tc shaping (fq_codel on taps). AWS `m6i.metal` ENA: `bw_out_allowance_exceeded` and `pps_allowance_exceeded` are 0 after all runs (the counters are cumulative). OVH hosts are `b3-256-flex` instances, so the CI VMs are nested; `ens3`, qdisc and tap drop counters 0 on the hosts checked. Host-side samples of each round-2 VM's QEMU: at 0.95-1.96 GB/s from the VM, the main thread runs at 87-98% of a core, the vCPU threads lower.

**Not the proxy.** `proxytest`: the proxy built from backend `main` (release profile, Linux arm64 container, 4 CPUs), the stock toolkit bundle, a stand-in cache API and an HTTP sink on loopback. 1023 MiB, 3 runs: one stream 488-642 MB/s (parts 536-693 MB/s each), 8 streams 1311-1882 MB/s. No TLS in this test; in the CI VMs the proxy's CPU (TLS included) was 0.03-0.04 cores at 21-25 MB/s.

## Fix

Let the proxy send more, smaller parts to R2 at once than the toolkit's 8 blocks. The toolkit cannot be told to (see above), and each R2 request is slow, so the fan-out has to happen in `upload.rs`:

- Read the toolkit's block index from its block id (UUID + 12 digits, as `block_part` in `ci_cache_service.py` already does). Cut each 64 MiB block into four 16 MiB parts named `celesto-part-{4 x index + j}`. The control plane already maps that name to part `4 x index + j + 1` (D-36). Get one `block-url` link per part and PUT the four at once. At Put Block List, send `commit-blocks` the part names in order, as the BuildKit spool path does with `spool.parts`.
- That gives 32 R2 requests in flight for the toolkit's 8 blocks. For 64, either use 8 MiB parts or answer each Put Block once the block is spooled and upload parts from a pool of 64 (write-behind; Put Block List then waits for every part, and a failed part fails the save at commit).
- Each in-flight block needs its 64 MiB held in memory or in the spool directory (8 blocks: 512 MiB).
- Control plane: the per-entry link cap (D-29, `max_blocks_per_entry`, 1.25 x limit / 64 MiB) must allow 4 links per block. R2's rule that non-last parts are equal and at least 5 MiB holds: every part is 16 MiB except the last.

Gain, from the measured R2 rates: 1 GiB uploads at about 515-525 MB/s with 32 parts in flight, or 735-855 MB/s with 64, instead of about 160 MB/s (3.2-5.3x). For excalidraw's 1.35 GB yarn cache, the upload part of the save drops from about 8.4 s to about 2.6 s (32) or 1.7 s (64). GitHub's runner needs about 3.3 s at its 411 MB/s median. **[inferred]** These numbers come from the toolkit itself opening 32 or 64 connections to the proxy. The fix keeps the toolkit at 8 and fans out inside the proxy; this investigation did not build it.

Later, for headroom: `vhost=on` on the tap netdev would move packet work out of QEMU's main thread, which is busy at about 1-2 GB/s. Not needed for this fix.

## Open questions

- Is the 21-25 MB/s per request R2's storage or the Cloudflare edge? Both look the same from the client. The bucket is `celesto-ci-cache` with location hint ENAM; all R2 connections went to `172.64.190.1` and `172.64.66.1` through the IAD colo.
- Best part count per VM size. At 64 x 16 MiB a 4 vCPU VM was 65-85% busy (the proxy used 1.1-1.3 cores). Smaller VMs will hit CPU sooner.
- The presign call before every part (out of scope here) is paid 4 times as often with 16 MiB parts.

## Celesto jobs (for overlap checks)

Round 1 ran at most 6 jobs at once, GitHub and Celesto interleaved; round 2 ran at most 3. At most 4 Celesto jobs ran at the same time. Times are UTC, job start to end; MB/s columns as above.

| Run, sample | Host | CPU | Time | 1 stream, per block | 8 x 64 | 16 x 64 | 32 x 16 | 64 x 16 | Restore | Ookla up |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 42875716811 s1 | aws_m6i_metal | Xeon 8375C | 18:29-18:38 | 25 | 163 | 286 | 467 | - | 198 | 1336 |
| 42875716811 s2 | ovh_xfs_flex_6 | EPYC-Milan | 18:29-18:37 | 26 | 187 | 228 | 514 | - | 228 | 1054 |
| 42875716811 s3 | ovh_xfs_flex_7 | EPYC-Milan | 18:29-18:36 | 15 | 114 | 294 | 446 | - | 239 | 1093 |
| 42875716811 s4 | ovh_64_xfs | EPYC-Milan | 18:37-18:47 | 22 | 161 | 302 | 467 | - | 233 | 1046 |
| 42875716811 s5 | ovh_xfs_flex_2 | EPYC-Milan | 18:38-18:45 | 21 | 163 | 219 | 513 | - | 233 | 1406 |
| 42875716811 s6 | aws_m6i_metal | Xeon 8375C | 18:41-18:51 | 23 | 161 | 303 | 541 | - | 311 | 1404 |
| 42875716811 s7 | ovh_xfs_flex | EPYC-Milan | 18:46-18:54 | 26 | 171 | 428 | 541 | - | 201 | 1516 |
| 42875716811 s8 | ovh_xfs_flex_7 | EPYC-Milan | 18:46-18:57 | 20 | 133 | 145 | 541 | - | 153 | 1110 |
| 42875716811 s9 | ovh_xfs_flex_2 | EPYC-Milan | 18:51-18:59 | 28 | 151 | 139 | 570 | - | 124 | 961 |
| 42880658667 s10 | ovh_xfs_flex | EPYC-Milan | 18:59-19:02 | 20 | 156 | 302 | 395 | 855 | 193 | 1458 |
| 42880658667 s11 | ovh_xfs_flex_2 | EPYC-Milan | 18:59-19:02 | 18 | 132 | 202 | 540 | 856 | 187 | 1133 |
| 42880658667 s12 | aws_m6i_metal | Xeon 8375C | 18:59-19:04 | 26 | 156 | 367 | 514 | 734 | 285 | 1264 |
| 42880658667 s13 | ovh_64_xfs_2 | EPYC-Milan | 19:02-19:05 | 21 | 198 | 380 | 467 | 854 | 263 | 1010 |
| 42880658667 s14 | ovh_64_xfs | EPYC-Milan | 19:02-19:05 | 26 | 187 | 285 | 541 | 685 | 228 | 918 |
| 42880658667 s15 | ovh_xfs_flex_2 | EPYC-Milan | 19:04-19:07 | 19 | 190 | 228 | 568 | 733 | 214 | 1099 |

The smoke run's Celesto job ran on `ovh_xfs_flex_2` from 18:10 to 18:20.

## Reproduce

Push a change to `.github/workflows/upload-bandwidth.yml` on `investigate-upload-bandwidth`. `UBW_HTTP_LEVELS`, `UBW_CF` and `UBW_TOOLKIT` at the top choose the tests; the matrix chooses the jobs. Each job uploads a `ubw-<run>-<attempt>-<provider>-s<n>` artifact: `job.json` (all results), the raw 100 ms samples per test, curl timings per request, and the toolkit logs with per-block request and answer times. GitHub jobs delete their cache entries at the end. Celesto entries stay until the repository's LRU limit or the idle sweep removes them.
