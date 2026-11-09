#!/usr/bin/env bash
# Reproduce the Celesto CI VM disk layout without a VM: a qcow2 overlay (64 KiB clusters,
# lazy_refcounts=off) on a raw base, as on the pool hosts (qemu-img info on 2026-11-09).
# Writes 4 KiB blocks at queue depth 64, like the guest's small-file copies (~80 in flight),
# through QEMU's own block layer (qemu-img bench, aio=threads, cache=writeback).
# Prints one line per case and repetition: case, rep, seconds, writes/s.
set -euo pipefail
dir=${1:-$PWD/qcow2-bench}; mkdir -p "$dir"; cd "$dir"
COUNT=${COUNT:-60000}; DEPTH=${DEPTH:-64}; REPS=${REPS:-3}
qemu-img --version | head -1
qemu-img create -q -f raw base.raw 8G
bench() {  # name, extra qemu-img create options; writes the same 4 KiB-step region twice
  local name=$1 opts=$2
  for rep in $(seq 1 "$REPS"); do
    rm -f ov.qcow2
    qemu-img create -q -f qcow2 -F raw -b base.raw -o "$opts" ov.qcow2 8G
    for pass in fresh allocated; do
      local t0=$(date +%s.%N)
      qemu-img bench -w -t writeback -i threads -c "$COUNT" -d "$DEPTH" -s 4096 -S 4096 -o 0 ov.qcow2 >/dev/null
      local t1=$(date +%s.%N)
      awk -v n="$name" -v p="$pass" -v r="$rep" -v a="$t0" -v b="$t1" -v c="$COUNT" 'BEGIN{printf "RESULT %s %s rep%d %.2f s %.0f writes/s\n", n, p, r, b-a, c/(b-a)}'
    done
  done
}
bench prod-64k "cluster_size=65536,lazy_refcounts=off"
bench lazy-refcounts "cluster_size=65536,lazy_refcounts=on"
bench extended-l2-128k "cluster_size=131072,extended_l2=on"
bench cluster-4k "cluster_size=4096"
rm -rf "$dir"
