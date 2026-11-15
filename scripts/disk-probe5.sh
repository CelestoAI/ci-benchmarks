#!/usr/bin/env bash
# Round 5: A/B of the guest disk write-cache setting inside one VM.
# "wt" = write through (what the runner start command sets since backend #1116:
#        guest flushes never reach QEMU). "wb" = write back (guest flushes reach
#        QEMU, which fdatasyncs the qcow2 on the host). Only this VM changes.
set -u
OUT=${OUT:-/tmp/disk-probe5}; mkdir -p "$OUT"; W=${GITHUB_WORKSPACE:-$PWD}/.probe
ITER=${ITER:-1}
IP=$(curl -s --max-time 5 https://checkip.amazonaws.com || echo unknown)
case "$IP" in 100.59.248.9) H="aws-m6id-nvme";; 35.168.91.32) H="aws-m6i-ebs";; *) H="ovh";; esac
echo "HOST ip=$IP type=$H uptime=$(cut -d' ' -f1 /proc/uptime)s start_write_cache=$(cat /sys/block/vda/queue/write_cache)"
fj() { jq -r --arg n "$1" '.jobs[0].write as $w | "   \($n): \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99.9 \($w.clat_ns.percentile["99.900000"]/1000|floor) us, max \($w.clat_ns.max/1000|floor) us"' "$OUT/$1.json"; }
fr() { local n=$1; shift; fio --name="$n" --ioengine=libaio --direct=1 --time_based --runtime=15 --ramp_time=2s --group_reporting=1 --percentile_list=50:99:99.9 --output-format=json "$@" > "$OUT/$n.json" 2>&1; fj "$n"; }
setmode() {
  local v; [ "$1" = wb ] && v="write back" || v="write through"
  for f in /sys/block/vd*/queue/write_cache; do echo "$v" | sudo tee "$f" >/dev/null; done
  local t0=$(date +%s.%N); sync; local t1=$(date +%s.%N)
  echo "== mode $1: write_cache=$(cat /sys/block/vda/queue/write_cache) (switch sync $(echo "$t1 - $t0" | bc | cut -c1-5)s)"
  sleep 3
}
run_mode() {
  local m=$1; setmode "$m"
  rm -rf "$W"; mkdir -p "$W/c" "$W/a" "$W/s"
  fio --name=prefill --directory="$W/c" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' --bs=1M --iodepth=32 --rw=write --fallocate=none --end_fsync=1 > /dev/null 2>&1
  fr "${m}_qd1_write"      --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=1 --bs=4k --iodepth=1 --rw=randwrite
  fr "${m}_qd1_fdatasync"  --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=1 --bs=4k --iodepth=1 --rw=randwrite --fdatasync=1
  fr "${m}_written_qd32x4" --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite
  fr "${m}_fresh_qd32x4"   --directory="$W/a" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite
  # Small files: 20,000 x 4 KiB files through the page cache, then sync (like the end of npm ci).
  local t0=$(date +%s.%N)
  python3 -c "
import os,sys
d=sys.argv[1]; b=os.urandom(4096)
for i in range(20000):
    p=os.path.join(d,str(i//1000)); os.makedirs(p,exist_ok=True)
    with open(os.path.join(p,str(i)),'wb') as f: f.write(b)
" "$W/s"
  local t1=$(date +%s.%N); sync; local t2=$(date +%s.%N)
  echo "   ${m}_smallfiles: write $(echo "$t1 - $t0" | bc | cut -c1-5)s, sync $(echo "$t2 - $t1" | bc | cut -c1-5)s"
  rm -rf "$W"; sync
  sudo -u postgres psql -qtAc CHECKPOINT >/dev/null
  sudo -u postgres pgbench -c 10 -j "$(nproc)" -T 20 bench > "$OUT/${m}_pg.txt" 2>&1
  echo "   ${m}_pgbench_rw: $(grep -oE 'tps = [0-9.]+' "$OUT/${m}_pg.txt") | $(grep -oE 'latency average = [0-9.]+ ms' "$OUT/${m}_pg.txt")"
}
sudo service postgresql start >/dev/null; sleep 2
sudo -u postgres createdb bench && sudo -u postgres pgbench -i -s 50 -q bench > "$OUT/pg-init.txt" 2>&1
# Alternate order across jobs so neither mode always runs first.
if [ $((ITER % 2)) -eq 1 ]; then run_mode wt; run_mode wb; else run_mode wb; run_mode wt; fi
setmode wt >/dev/null
