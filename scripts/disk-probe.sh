#!/usr/bin/env bash
# Diagnostic: why 4K random writes and pgbench read-write are slow.
# Separates host-side first-write allocation, guest ext4 extent conversion and
# steady-state random writes, then varies PostgreSQL flush settings.
set -u
OUT=${OUT:-/tmp/disk-probe}; mkdir -p "$OUT"
W=${GITHUB_WORKSPACE:-$PWD}/.probe
log() { printf '\n== %s\n' "$*"; }

disk_of() {
  local src; src=$(findmnt -no SOURCE --target "$1" 2>/dev/null)
  local p; p=$(lsblk -no PKNAME "$(readlink -f "$src" 2>/dev/null)" 2>/dev/null | head -1)
  if [ -n "$p" ]; then echo "$p"; elif [ -e /sys/block/vda ]; then echo vda; else basename "$src"; fi
}

log "machine"
nproc; free -m | head -2; uname -r
WDEV=$(disk_of "${GITHUB_WORKSPACE:-$PWD}"); RDEV=$(disk_of /)
echo "workspace disk=$WDEV root disk=$RDEV"
findmnt -no SOURCE,FSTYPE,OPTIONS --target "${GITHUB_WORKSPACE:-$PWD}"
for f in scheduler nr_requests write_cache rotational max_sectors_kb discard_max_bytes; do
  printf '%s=%s\n' "$f" "$(cat /sys/block/$WDEV/queue/$f 2>/dev/null)"; done
echo "hw_queues=$(ls /sys/block/$WDEV/mq 2>/dev/null | wc -l)"
grep -E 'Dirty|Writeback:' /proc/meminfo
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.dirty_bytes vm.dirty_background_bytes 2>/dev/null

ios_start() { S_TIME_FORMAT=ISO iostat -dxy 1 "$1" > "$OUT/iostat-$2.txt" 2>&1 & IOS_PID=$!; }
ios_stop() {
  kill "$IOS_PID" 2>/dev/null; wait "$IOS_PID" 2>/dev/null
  awk -v d="$1" -v n0="$2" '$1=="Device"{for(i=1;i<=NF;i++)c[$i]=i;next}
    $1==d{n++; w=$c["w/s"]; ws+=w; wk+=$c["wkB/s"]; wa+=$c["w_await"]; q+=$c["aqu-sz"]; u+=$c["%util"];
      if(c["f/s"]){fs+=$c["f/s"]; fa+=$c["f_await"]}
      if(n==1||w>mx)mx=w; if(n==1||w<mn)mn=w; if(w<50)stall++}
    END{if(n)printf "   iostat %s (%s, %ds): w/s avg %.0f min %.0f max %.0f, wMB/s %.1f, w_await %.2f ms, aqu-sz %.1f, util %.0f%%, flush/s %.0f f_await %.2f ms, seconds under 50 w/s: %d\n",
      n0,d,n,ws/n,mn,mx,wk/n/1024,wa/n,q/n,u/n,fs/n,fa/n,stall}' "$OUT/iostat-$2.txt"
}

fio_run() { # name dir rw bs depth jobs [extra...]
  local name=$1 dir=$2 rw=$3 bs=$4 depth=$5 jobs=$6; shift 6
  ios_start "$(disk_of "$dir")" "$name"
  fio --name="$name" --directory="$dir" --ioengine=libaio --direct=1 --size=1G --numjobs="$jobs" \
    --filename_format='f.$jobnum' --bs="$bs" --iodepth="$depth" --rw="$rw" --time_based --runtime=20 \
    --ramp_time=2s --group_reporting=1 --output-format=json "$@" > "$OUT/$name.json" 2> "$OUT/$name.err"
  ios_stop "$(disk_of "$dir")" "$name"
  jq -r --arg n "$name" '.jobs[0].write as $w | "   \($n): \($w.iops|floor) IOPS, \($w.bw_bytes/1048576*10|floor/10) MiB/s, clat p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, p99.9 \($w.clat_ns.percentile["99.900000"]/1000|floor) us"' "$OUT/$name.json" || cat "$OUT/$name.err"
}
prefill() { # dir: write 4 x 1 GiB sequentially, allocating every block on every layer
  fio --name=prefill --directory="$1" --ioengine=libaio --direct=1 --size=1G --numjobs=4 \
    --filename_format='f.$jobnum' --bs=1M --iodepth=32 --rw=write --fallocate=none --end_fsync=1 \
    --output-format=json > "$OUT/prefill-$(basename "$1").json" 2>&1
}

log "A. random 4K writes to fresh preallocated files (what the benchmark measures)"
rm -rf "$W"; mkdir -p "$W/a"; fio_run A_fresh_qd32x4 "$W/a" randwrite 4k 32 4
log "B. the same files again (partly written by A)"
fio_run B_again_qd32x4 "$W/a" randwrite 4k 32 4
log "C. files fully written first (every layer allocated)"
mkdir -p "$W/c"; prefill "$W/c"; fio_run C_prefilled_qd32x4 "$W/c" randwrite 4k 32 4
log "D. one write at a time on written files (per-write latency)"
fio_run D_prefilled_qd1 "$W/c" randwrite 4k 1 1
log "E. fresh files on ext4 inside a fully written loop file (guest ext4 fresh, disk below already allocated)"
dd if=/dev/zero of="$W/loop.img" bs=1M count=6144 oflag=direct status=none && sync
LOOP=$(sudo losetup --direct-io=on -f --show "$W/loop.img") && sudo mkfs.ext4 -q -F "$LOOP" && \
  sudo mkdir -p /mnt/probe && sudo mount "$LOOP" /mnt/probe && sudo chown "$(id -u)" /mnt/probe && \
  { ios_start "$(basename "$LOOP")" E_loop; fio --name=E --directory=/mnt/probe --ioengine=libaio --direct=1 --size=1G --numjobs=4 \
      --filename_format='f.$jobnum' --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --ramp_time=2s \
      --group_reporting=1 --output-format=json > "$OUT/E_loop_fresh_qd32x4.json" 2>&1; ios_stop "$(basename "$LOOP")" E_loop;
    jq -r '.jobs[0].write as $w | "   E_loop_fresh_qd32x4: \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, p99.9 \($w.clat_ns.percentile["99.900000"]/1000|floor) us"' "$OUT/E_loop_fresh_qd32x4.json"; }
sudo umount /mnt/probe 2>/dev/null; [ -n "${LOOP:-}" ] && sudo losetup -d "$LOOP"
log "F. synced 4K writes (commit latency)"
fio_run F_sync_qd1 "$W/c" write 4k 1 1 --fdatasync=1
rm -rf "$W"

PGB() { sudo -u postgres pgbench "$@"; }
pg_tps() { # label, pgbench flags
  local label=$1; shift
  sudo -u postgres psql -qtAc 'CHECKPOINT' >/dev/null
  ios_start "$RDEV" "pg-$label"
  PGB -c 10 -j "$(nproc)" -T 30 "$@" bench > "$OUT/pg-$label.txt" 2>&1
  ios_stop "$RDEV" "pg-$label"
  printf '   %-28s %s | %s\n' "$label" "$(grep -oE 'tps = [0-9.]+' "$OUT/pg-$label.txt" | head -1)" "$(grep -E 'latency average' "$OUT/pg-$label.txt")"
}
pgset() { sudo -u postgres psql -qtAc "ALTER SYSTEM SET $1" && sudo -u postgres psql -qtAc 'SELECT pg_reload_conf()' >/dev/null; }

log "P. PostgreSQL 16 local cluster, pgbench scale 50, 10 clients, 30 s"
sudo service postgresql start >/dev/null || true
sleep 2
sudo -u postgres psql -qtAc 'SHOW server_version'; sudo -u postgres psql -qtAc 'SHOW shared_buffers'
sudo -u postgres createdb bench && PGB -i -s 50 -q bench > "$OUT/pg-init.txt" 2>&1; tail -1 "$OUT/pg-init.txt"
pg_tps read-only -S
pg_tps read-write-default
pgset "synchronous_commit = off"; pg_tps read-write-no-commit-wait; pgset "synchronous_commit = on"
sudo -u postgres psql -qtAc "ALTER SYSTEM SET shared_buffers = '4GB'" && sudo service postgresql restart >/dev/null && sleep 2
pg_tps read-write-big-buffers
sudo -u postgres psql -qtAc "ALTER SYSTEM RESET shared_buffers" && sudo service postgresql restart >/dev/null && sleep 2
pgset "fsync = off"; pgset "full_page_writes = off"; pg_tps read-write-no-flush; pgset "fsync = on"; pgset "full_page_writes = on"
sudo service postgresql stop >/dev/null || true

log "Q. benchmark method (postgres:16 in Docker, pgbench from the host)"
docker run -d --name probe-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=bench -p 5433:5432 postgres:16 >/dev/null 2>&1
for i in $(seq 1 60); do pg_isready -q -h localhost -p 5433 && break; sleep 1; done; sleep 2
export PGPASSWORD=postgres
pgbench -i -s 50 -q -h localhost -p 5433 -U postgres bench > "$OUT/docker-init.txt" 2>&1
ios_start "$RDEV" docker-rw
pgbench -h localhost -p 5433 -U postgres -c 10 -j "$(nproc)" -T 30 bench > "$OUT/docker-rw.txt" 2>&1
ios_stop "$RDEV" docker-rw
printf '   %-28s %s | %s\n' docker-read-write "$(grep -oE 'tps = [0-9.]+' "$OUT/docker-rw.txt" | head -1)" "$(grep -E 'latency average' "$OUT/docker-rw.txt")"
docker rm -f probe-pg >/dev/null 2>&1
echo "PROBE DONE"
