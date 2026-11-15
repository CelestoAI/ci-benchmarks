#!/bin/bash
# Stand-in CI disk workload, run inside the guest. Prints one "R <json>" line per test.
set -u
wc=${1:-wt}; v="write through"; [ "$wc" = wb ] && v="write back"
for f in /sys/block/vd*/queue/write_cache; do echo "$v" > "$f"; done
echo "R {\"n\":\"guest\",\"write_cache\":\"$(cat /sys/block/vda/queue/write_cache)\",\"uptime_s\":$(cut -d' ' -f1 /proc/uptime),\"cpus\":$(nproc),\"mem_mib\":$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 )),\"mount\":\"$(awk '$2=="/"{print $4}' /proc/mounts)\"}"
W=/home/bench; rm -rf "$W"; mkdir -p "$W"
now() { date +%s.%N; }
el() { python3 -c "print(round($2-$1,3))"; }
fioj() {  # name, fio args...; json+ gives latency bins for freeze counts
  local n=$1; shift
  fio --name="$n" --ioengine=libaio --direct=1 --group_reporting=1 --percentile_list=50:99:99.9 \
    --output-format=json+ "$@" > /tmp/"$n".json 2>/tmp/"$n".err
  local j
  j=$(jq -c --arg n "$n" '.jobs[0].write as $w | {n:$n, iops:($w.iops|floor), mib_s:(($w.bw_bytes/1048576*10|floor)/10),
      p50_us:(($w.clat_ns.percentile["50.000000"]//0)/1000|floor), p999_us:(($w.clat_ns.percentile["99.900000"]//0)/1000|floor),
      max_us:(($w.clat_ns.max//0)/1000|floor),
      over100ms:([($w.clat_ns.bins//{}) | to_entries[] | select((.key|tonumber) > 100000000) | .value] | add // 0),
      over1s:([($w.clat_ns.bins//{}) | to_entries[] | select((.key|tonumber) > 1000000000) | .value] | add // 0)}' /tmp/"$n".json 2>/dev/null)
  if [ -n "$j" ]; then echo "R $j"
  else echo "R {\"n\":\"$n\",\"error\":\"$(head -c 200 /tmp/"$n".err | tr -d '"\\\n')\"}"; fi
}
# 1. Cold read of base-image files.
sync; echo 3 > /proc/sys/vm/drop_caches
t0=$(now); bytes=$(tar cf - /usr 2>/dev/null | wc -c); t1=$(now)
echo "R {\"n\":\"base_read\",\"mib\":$((bytes / 1048576)),\"s\":$(el "$t0" "$t1")}"
# 2. 50,000 small files (npm-install-like), sync, delete.
python3 - "$W/sf" <<'PY'
import json, os, random, shutil, sys, time
d = sys.argv[1]; random.seed(1); blob = os.urandom(1 << 20)
t0 = time.time(); total = 0
for i in range(50000):
    p = os.path.join(d, str(i // 500)); os.makedirs(p, exist_ok=True)
    n = min(int(random.lognormvariate(8.3, 1.2)), 1 << 20); total += n
    with open(os.path.join(p, f"{i}.js"), "wb") as f: f.write(blob[:n])
t1 = time.time(); os.sync(); t2 = time.time(); shutil.rmtree(d); os.sync(); t3 = time.time()
print("R " + json.dumps({"n": "smallfiles", "mib": total >> 20, "write_s": round(t1 - t0, 3), "sync_s": round(t2 - t1, 3), "rm_s": round(t3 - t2, 3)}))
PY
# 3. 4 GiB sequential write to a new file (image extract-like).
fioj seq_fresh --directory="$W" --filename=seq.dat --size=4G --bs=1M --iodepth=16 --rw=write --end_fsync=1
rm -f "$W/seq.dat"
# 4. 4K random writes into new files (fresh space), 4 jobs x QD32.
mkdir -p "$W/a"
fioj fresh_rand --directory="$W/a" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --ramp_time=2s
rm -rf "$W/a"
# 5. 4K random rewrites of written data, then QD1 fdatasync.
mkdir -p "$W/c"
fio --name=prefill --directory="$W/c" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' --bs=1M --iodepth=32 --rw=write --end_fsync=1 >/dev/null 2>&1
fioj written_rand --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=4 --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=15 --ramp_time=2s
fioj qd1_fdatasync --directory="$W/c" --filename_format='f.$jobnum' --size=1G --numjobs=1 --bs=4k --iodepth=1 --rw=randwrite --fdatasync=1 --time_based --runtime=10
rm -rf "$W/c"
# 6. PostgreSQL: init scale 20, then 20 s read-write.
mkdir -p /run/postgresql && chown postgres:postgres /run/postgresql
su postgres -c "pg_ctlcluster 16 main start" >/dev/null 2>&1; sleep 1
t0=$(now); su postgres -c "createdb bench && pgbench -i -s 20 -q bench" >/tmp/pginit.txt 2>&1; t1=$(now)
su postgres -c "pgbench -c 8 -j 2 -T 20 bench" >/tmp/pg.txt 2>&1
python3 - "$(el "$t0" "$t1")" <<'PGPY'
import json, re, sys
t = open("/tmp/pg.txt").read()
tps = re.search(r"tps = ([0-9.]+)", t); lat = re.search(r"latency average = ([0-9.]+)", t)
out = {"n": "pgbench", "init_s": float(sys.argv[1]), "tps": float(tps.group(1)) if tps else 0,
       "lat_ms": float(lat.group(1)) if lat else 0}
if not tps:
    out["error"] = (open("/tmp/pginit.txt").read() + t)[-300:]
print("R " + json.dumps(out))
PGPY
su postgres -c "pg_ctlcluster 16 main stop -m fast" >/dev/null 2>&1
