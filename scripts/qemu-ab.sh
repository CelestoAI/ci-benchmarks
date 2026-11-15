#!/bin/bash
# A/B of QEMU block settings on a qcow2 overlay over a raw base, the same
# layout Celesto pool VMs use. qemu-nbd runs the QEMU block layer; fio
# drives 4K random writes at queue depth 32 x 4 jobs, as in disk-probe4.
set -uo pipefail
work=${WORK:-/mnt/qab}
sudo mkdir -p "$work" && sudo chown "$(id -u)" "$work"
cd "$work"
sudo modprobe nbd max_part=0 nbds_max=4
# 8 GiB raw base with real data (overlay reads of unallocated clusters hit it).
[ -f base.raw ] || dd if=/dev/urandom of=base.raw bs=1M count=8192 status=none
echo "host: $(nproc) cpus, $(free -g | awk '/Mem:/{print $2}') GiB RAM, $(findmnt -no FSTYPE,SOURCE -T "$work")"
sysctl vm.dirty_ratio vm.dirty_background_ratio

run_fio() {  # $1 label, $2 device, $3 pattern (fresh|written)
  local out
  out=$(sudo fio --name=t --filename="$2" --direct=1 --ioengine=libaio \
    --rw=randwrite --bs=4k --iodepth=32 --numjobs=4 --size=6G \
    --time_based --runtime=40 --group_reporting --output-format=json 2>/dev/null)
  echo "$out" | jq -r --arg l "$1 $3" '.jobs[0].write as $w |
    "\($l): \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, max \($w.clat_ns.max/1000|floor) us"'
}

variant() {  # $1 label, rest = qemu-nbd options
  local label=$1; shift
  rm -f ov.qcow2
  qemu-img create -q -f qcow2 -F raw -b "$work/base.raw" ov.qcow2 8G
  sudo qemu-nbd --fork -f qcow2 "$@" -c /dev/nbd0 ov.qcow2 || { echo "$label: qemu-nbd failed"; return; }
  sleep 1
  sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
  run_fio "$label" /dev/nbd0 fresh
  run_fio "$label" /dev/nbd0 written
  echo "  qcow2 size $(du -h ov.qcow2 | cut -f1), host Dirty peak not tracked"
  sudo qemu-nbd -d /dev/nbd0 >/dev/null; sleep 1
}

low_dirty() { sudo sysctl -q vm.dirty_bytes=536870912 vm.dirty_background_bytes=134217728; }
default_dirty() { sudo sysctl -q vm.dirty_ratio=20 vm.dirty_background_ratio=10; }

# Celesto today: QEMU defaults (cache=writeback, aio=threads).
default_dirty; variant "A default(writeback,threads)" --cache=writeback --aio=threads
low_dirty;     variant "F default + dirty cap 512M/128M" --cache=writeback --aio=threads
default_dirty; variant "E unsafe,threads"             --cache=unsafe --aio=threads
low_dirty;     variant "G unsafe + dirty cap 512M/128M" --cache=unsafe --aio=threads
default_dirty; variant "B cache=none,aio=native"      --cache=none --aio=native
