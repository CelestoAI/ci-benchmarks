#!/usr/bin/env bash
# Round 2: during the random-write stall, are writes queued in the guest
# (scheduler, wbt, ext4 journal) or dispatched to the virtual disk and not
# completing (host)? Then flip guest-side knobs one at a time.
set -u
OUT=${OUT:-/tmp/disk-probe2}; mkdir -p "$OUT"
W=${GITHUB_WORKSPACE:-$PWD}/.probe; DEV=vda
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null
DBG=/sys/kernel/debug/block/$DEV
echo "kernel $(uname -r)"; ls $DBG 2>/dev/null | tr '\n' ' '; echo
for f in scheduler rotational wbt_lat_usec nr_requests write_cache; do printf '%s=%s\n' $f "$(cat /sys/block/$DEV/queue/$f 2>/dev/null)"; done
cat /sys/block/$DEV/mq/0/nr_tags /sys/block/$DEV/mq/0/nr_reserved_tags 2>/dev/null | paste -sd' ' | sed 's/^/tags,reserved=/'
dumpe2fs -h "$(findmnt -no SOURCE /)" 2>/dev/null | grep -iE 'journal size|Journal features|features' ; sudo dumpe2fs -h /dev/vda 2>/dev/null | grep -iE 'journal size|Filesystem features|Default mount'

sampler() { # every 0.5 s: in-flight at driver vs scheduler, D-state wait channels
  local tag=$1
  while :; do
    local busy sched inflight
    busy=$(sudo cat $DBG/hctx0/busy 2>/dev/null | wc -l)
    sched=$(sudo sh -c "cat $DBG/sched/queued $DBG/sched/owned_by_driver 2>/dev/null" | paste -sd' ')
    inflight=$(cat /sys/block/$DEV/inflight | awk '{print $2}')
    wch=$(ps -eLo stat=,wchan:28=,comm= | awk '$1~/^D/{print $2"("$3")"}' | sort | uniq -c | sort -rn | head -4 | awk '{printf "%s x%s; ",$2,$1}')
    printf '%s t=%s inflight=%s driver_busy=%s sched[queued owned]=%s D: %s\n' "$tag" "$(date +%S.%N | cut -c1-5)" "$inflight" "$busy" "$sched" "$wch"
    sleep 0.5
  done
}

run_A() { # tag [setup command]
  local tag=$1
  rm -rf "$W"; mkdir -p "$W"
  sampler "$tag" > "$OUT/samples-$tag.txt" 2>&1 & local sp=$!
  fio --name=A --directory="$W" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' \
    --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --ramp_time=2s --group_reporting=1 \
    --output-format=json > "$OUT/A-$tag.json" 2>&1
  kill $sp; wait $sp 2>/dev/null
  jq -r --arg t "$tag" '.jobs[0].write as $w | "\($t): \($w.iops|floor) IOPS, p50 \($w.clat_ns.percentile["50.000000"]/1000|floor) us, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us, p99.9 \($w.clat_ns.percentile["99.900000"]/1000|floor) us"' "$OUT/A-$tag.json"
  # summarize stall samples: where are writes while nothing completes?
  awk '{for(i=1;i<=NF;i++){split($i,kv,"="); if(kv[1]=="inflight")inf=kv[2]; if(kv[1]=="driver_busy")drv=kv[2]}; n++; si+=inf; sd+=drv; if(inf>40){hi++; hd+=drv}}
       END{printf "   samples %d: avg in-flight %.0f, avg at driver %.0f; samples with >40 in flight: %d, at driver during those: %.0f\n", n, si/n, sd/n, hi, (hi?hd/hi:0)}' "$OUT/samples-$tag.txt"
  grep -oE 'D: .*' "$OUT/samples-$tag.txt" | tr ';' '\n' | sed 's/^D: //; s/^ *//' | grep -v '^$' | sed -E 's/ x[0-9]+$//' | sort | uniq -c | sort -rn | head -6 | sed 's/^/   D-state: /'
}

echo "== baseline (mq-deadline, rotational=1, default wbt)"
run_A baseline
sed -n '1,400p' "$OUT/samples-baseline.txt" | awk 'NR%4==1' | head -50
echo "== sysrq-w during a stall"
sudo sysctl -q kernel.sysrq=1; rm -rf "$W"; mkdir -p "$W"
fio --name=A --directory="$W" --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --output-format=json > /dev/null 2>&1 &
FP=$!; sleep 8; sudo dmesg -C; echo w | sudo tee /proc/sysrq-trigger >/dev/null; sleep 1; sudo dmesg | grep -vE '^\s*$' | head -150; wait $FP

echo "== scheduler none"
echo none | sudo tee /sys/block/$DEV/queue/scheduler >/dev/null; run_A sched-none
echo mq-deadline | sudo tee /sys/block/$DEV/queue/scheduler >/dev/null
echo "== wbt off"
echo 0 | sudo tee /sys/block/$DEV/queue/wbt_lat_usec >/dev/null; run_A wbt-off
echo -1 | sudo tee /sys/block/$DEV/queue/wbt_lat_usec >/dev/null
echo "== rotational=0"
echo 0 | sudo tee /sys/block/$DEV/queue/rotational >/dev/null; run_A rot0
echo 1 | sudo tee /sys/block/$DEV/queue/rotational >/dev/null
echo "== all three"
echo none | sudo tee /sys/block/$DEV/queue/scheduler >/dev/null; echo 0 | sudo tee /sys/block/$DEV/queue/wbt_lat_usec >/dev/null; echo 0 | sudo tee /sys/block/$DEV/queue/rotational >/dev/null
run_A all-three
echo mq-deadline | sudo tee /sys/block/$DEV/queue/scheduler >/dev/null; echo -1 | sudo tee /sys/block/$DEV/queue/wbt_lat_usec >/dev/null; echo 1 | sudo tee /sys/block/$DEV/queue/rotational >/dev/null

echo "== ext4 options on a loop filesystem (written loop file underneath)"
mkdir -p "$W"; dd if=/dev/zero of="$W/../loop.img" bs=1M count=6144 oflag=direct status=none; sync
for opts in "defaults" "data=writeback,nobarrier,commit=30" "noload-journal"; do
  LOOP=$(sudo losetup --direct-io=on -f --show "$W/../loop.img")
  if [ "$opts" = noload-journal ]; then sudo mkfs.ext4 -q -F -O ^has_journal "$LOOP"; mo=defaults; else sudo mkfs.ext4 -q -F "$LOOP"; mo=$opts; fi
  sudo mkdir -p /mnt/p && sudo mount -o "$mo" "$LOOP" /mnt/p && sudo chown "$(id -u)" /mnt/p
  fio --name=E --directory=/mnt/p --ioengine=libaio --direct=1 --size=1G --numjobs=4 --filename_format='f.$jobnum' --bs=4k --iodepth=32 --rw=randwrite --time_based --runtime=20 --ramp_time=2s --group_reporting=1 --output-format=json > "$OUT/E-$opts.json" 2>&1
  jq -r --arg t "$opts" '.jobs[0].write as $w | "   loop ext4 \($t): \($w.iops|floor) IOPS, p99 \($w.clat_ns.percentile["99.000000"]/1000|floor) us"' "$OUT/E-$opts.json"
  sudo umount /mnt/p; sudo losetup -d "$LOOP"
done
rm -rf "$W" "$W/../loop.img"
sudo dmesg | grep -iE 'virtio|blk|timeout|hung|I/O error' | tail -10
echo PROBE2 DONE
