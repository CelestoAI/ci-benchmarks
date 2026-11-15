#!/usr/bin/env bash
# Round 3: does ext4 lazy inode-table init (running on every fresh CI VM after
# the rootfs is grown) cause the host-side write stalls? VARIANT=on|off.
set -u
OUT=${OUT:-/tmp/disk-probe3}; mkdir -p "$OUT"; W=${GITHUB_WORKSPACE:-$PWD}/.probe
EXT=$(ls -d /sys/fs/ext4/*/ | grep -v features | head -1)
lw() { cat "$EXT/lifetime_write_kbytes"; }
li() { ps -eo stat=,comm= | awk '$2=="ext4lazyinit"{print "ext4lazyinit:"$1; f=1} END{if(!f)print "ext4lazyinit:none"}'; }
echo "variant=$VARIANT uptime=$(cut -d' ' -f1 /proc/uptime)s ext4 sysfs=$EXT $(li)"
if [ "$VARIANT" = off ]; then sudo mount -o remount,noinit_itable / && echo "remounted noinit_itable"; sleep 1; echo "$(li)"; fi
findmnt -no OPTIONS /

idle() { local a b; a=$(lw); sleep 20; b=$(lw); echo "idle 20s: ext4 wrote $(( (b-a)/1024 )) MiB ($(( (b-a)/20 )) KiB/s), $(li)"; }
canary() { # single 4K synced writes: worst-case pause without other load
  rm -rf "$W"; mkdir -p "$W"
  fio --name=c --directory="$W" --ioengine=psync --direct=1 --size=256M --bs=4k --rw=randwrite --fallocate=none \
    --time_based --runtime=20 --output-format=json > "$OUT/canary.json" 2>&1
  jq -r '.jobs[0].write as $w | "canary qd1: \($w.iops|floor) IOPS, p99.9 \($w.clat_ns.percentile["99.900000"]/1000|floor) us, max \($w.clat_ns.max/1000|floor) us"' "$OUT/canary.json"
}
randA() {
  rm -rf "$W"; mkdir -p "$W"
  fio --name=A --directory="$W" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' \
    --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --ramp_time=2s --group_reporting=1 \
    --output-format=json > "$OUT/A.json" 2>&1
  jq -r '.jobs[0].write as $w | "randwrite fresh qd32x4: \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, max \($w.clat_ns.max/1000|floor) us"' "$OUT/A.json"
  rm -rf "$W"
}
pg() {
  sudo service postgresql start >/dev/null; sleep 2
  sudo -u postgres createdb bench && sudo -u postgres pgbench -i -s 50 -q bench > "$OUT/pg-init.txt" 2>&1
  sudo -u postgres psql -qtAc CHECKPOINT >/dev/null
  sudo -u postgres pgbench -c 10 -j "$(nproc)" -T 30 bench > "$OUT/pg.txt" 2>&1
  echo "pgbench read-write local: $(grep -oE 'tps = [0-9.]+' "$OUT/pg.txt") | $(grep 'latency average' "$OUT/pg.txt")"
  sudo service postgresql stop >/dev/null
}
idle; canary; randA; pg; idle
echo "end uptime=$(cut -d' ' -f1 /proc/uptime)s $(li)"
