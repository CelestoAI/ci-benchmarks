#!/usr/bin/env bash
# Rerun 2026-11-15T02:38Z: after vm.dirty_bytes=512M/128M on host 77cd5eb2 (m6i EBS).
# Round 4: same disk tests, tagged with the host each job ran on.
set -u
OUT=${OUT:-/tmp/disk-probe4}; mkdir -p "$OUT"; W=${GITHUB_WORKSPACE:-$PWD}/.probe
IP=$(curl -s --max-time 5 https://checkip.amazonaws.com || echo unknown)
case "$IP" in 100.59.248.9) H="aws-m6id-nvme";; 35.168.91.32) H="aws-m6i-ebs";; *) H="other(ovh?)";; esac
F=$(cat /sys/block/vda/device/features 2>/dev/null)
echo "HOST ip=$IP type=$H cpu=\"$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)\" uptime=$(cut -d' ' -f1 /proc/uptime)s"
echo "virtio features: FLUSH(bit9)=${F:9:1} CONFIG_WCE(bit11)=${F:11:1} VERSION_1(bit32)=${F:32:1} write_cache=$(cat /sys/block/vda/queue/write_cache)"
fj() { jq -r --arg n "$1" '.jobs[0].write as $w | "   \($n): \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, max \($w.clat_ns.max/1000|floor) us"' "$OUT/$1.json"; }
fr() { local n=$1; shift; fio --name="$n" --ioengine=libaio --direct=1 --time_based --runtime=15 --ramp_time=2s --group_reporting=1 --output-format=json "$@" > "$OUT/$n.json" 2>&1; fj "$n"; }
rm -rf "$W"; mkdir -p "$W/c" "$W/a"
fio --name=prefill --directory="$W/c" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' --bs=1M --iodepth=32 --rw=write --fallocate=none --end_fsync=1 > /dev/null 2>&1
fr qd1_write    --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=1 --bs=4k --iodepth=1 --rw=randwrite
fr qd1_fdatasync --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=1 --bs=4k --iodepth=1 --rw=randwrite --fdatasync=1
fr written_qd32x4 --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite
fr fresh_qd32x4 --directory="$W/a" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite
rm -rf "$W"
sudo service postgresql start >/dev/null; sleep 2
sudo -u postgres createdb bench && sudo -u postgres pgbench -i -s 50 -q bench > "$OUT/pg-init.txt" 2>&1
sudo -u postgres psql -qtAc CHECKPOINT >/dev/null
sudo -u postgres pgbench -c 10 -j "$(nproc)" -T 30 bench > "$OUT/pg.txt" 2>&1
echo "   pgbench_rw: $(grep -oE 'tps = [0-9.]+' "$OUT/pg.txt")"
