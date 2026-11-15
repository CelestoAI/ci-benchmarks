#!/bin/bash
# Boots one stand-in CI VM with the disk config in $CFG (JSON), runs the suite,
# stops QEMU the way the pool agent does (SIGTERM, then SIGKILL), deletes the
# disk, and writes $OUT/result.json. Run as root from this directory.
set -uo pipefail
: "${CFG:?}" "${CLASS:?}" "${ROOT:?}" "${DEV:?}" "${KERNEL:?}" "${OUT:?}"
REP=${REP:-1}
get() { jq -r --arg k "$1" --arg d "$2" 'if has($k) then .[$k]|tostring else $d end' <<<"$CFG"; }
id=$(get id x); layout=$(get layout qcow2); qopts=$(get qcow2_opts ""); cache=$(get cache writeback)
aio=$(get aio threads); iothread=$(get iothread 0); discard=$(get discard ""); wc=$(get guest_wc wt)
fsopt=$(get guest_fsopt ""); smp=$(get smp 2); mem=$(get mem 3072); devtype=$(get dev mmio)
queues=$(get queues 1); extra=$(get drive_extra ""); devextra=$(get dev_extra ""); globals=$(get globals "")
xext=$(get xfs_extsize "")
iothreads=$(get iothreads 0); qver=$(get qemu system)
trace=$(get trace "")  # comma-separated QEMU trace events (log backend, to qemu.err); counts go in result.json
# "qemu": "<version>" (or "latest") uses that release's source build from the workflow's qemu job;
# default is the distro QEMU (8.2.2, as on prod hosts).
# "ubuntu-<release>" uses that Ubuntu release's prebuilt package, run in a chroot.
QEMU=(qemu-system-x86_64); QIMG=(qemu-img)
[ "$qver" = latest ] && qver=${QEMU_LATEST:?}
case "$qver" in
  system) ;;
  ubuntu-*) rfs=$QEMU_ROOT/qemu-$qver
    if ! mountpoint -q "$rfs/proc"; then  # same paths inside and out, so disk and kernel paths work unchanged
      mkdir -p "$rfs/dev" "$rfs/proc" "$rfs/sys" "$rfs$ROOT" "$rfs/tmp"
      mount --rbind /dev "$rfs/dev" && mount --make-rslave "$rfs/dev"; mount -t proc proc "$rfs/proc"; mount -t sysfs sys "$rfs/sys"
      mount --bind "$ROOT" "$rfs$ROOT"; mount --bind /tmp "$rfs/tmp"
    fi
    QEMU=(chroot "$rfs" /usr/bin/qemu-system-x86_64); QIMG=(chroot "$rfs" /usr/bin/qemu-img) ;;
  *) QEMU=("$QEMU_ROOT/qemu-$qver/bin/qemu-system-x86_64"); QIMG=("$QEMU_ROOT/qemu-$qver/bin/qemu-img") ;;
esac
qemu_version=$("${QEMU[@]}" --version | head -1)
mkdir -p "$OUT"; vm=$ROOT/vm; rm -rf "$vm"; mkdir -p "$vm"; base=$ROOT/base.raw
status=ok; note=""
# XFS extent size hint on the VM dir: new disk files inherit it (it cannot be set on a file that has data).
[ -n "$xext" ] && { xfs_io -c "extsize $xext" "$vm" || status=prep_failed; }
sectors() { awk -v d="$DEV" '$3==d{print $10}' /proc/diskstats; }

# Current init and suite go into the shared base (read-only to the VM's overlay).
mnt=$(mktemp -d); mount -o loop "$base" "$mnt" && install -m0755 init "$mnt/init" && install -m0755 guest-bench.sh "$mnt/guest-bench.sh"; umount "$mnt"; rmdir "$mnt"
# Prod hosts serve the shared base from a warm page cache; warm it here too.
python3 - "$base" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY); end = os.fstat(fd).st_size; off = 0
while off < end:
    try: off = os.lseek(fd, off, os.SEEK_DATA)
    except OSError: break
    hole = os.lseek(fd, off, os.SEEK_HOLE)
    while off < hole: off += len(os.pread(fd, min(8 << 20, hole - off), off))
PY
sync
if [ "$layout" = thin ]; then  # base volume in the thin pool, refreshed each run (the suite was just injected)
  lvremove -qqfy hc/base 2>/dev/null; lvcreate -qq -V 40G -T hc/pool -n base && python3 - "$base" /dev/hc/base <<'COPY'
import os, sys
src = os.open(sys.argv[1], os.O_RDONLY); dst = os.open(sys.argv[2], os.O_WRONLY)
end = os.fstat(src).st_size; off = 0
while off < end:  # copy data extents only, so holes stay unprovisioned in the pool
    try: off = os.lseek(src, off, os.SEEK_DATA)
    except OSError: break
    hole = os.lseek(src, off, os.SEEK_HOLE)
    while off < hole:
        b = os.pread(src, min(8 << 20, hole - off), off); os.pwrite(dst, b, off); off += len(b)
os.fsync(dst)
COPY
  [ $? = 0 ] || status=prep_failed
fi

t0=$(date +%s.%N)
case "$layout" in
  qcow2)   disk=$vm/disk.qcow2; fmt=qcow2
           "${QIMG[@]}" create -q -f qcow2 -F raw -b "$base" ${qopts:+-o "$qopts"} "$disk" 40G 2>"$vm/prep.err" || status=prep_failed ;;
  thin)    disk=/dev/hc/vm; fmt=raw  # dm-thin snapshot of the base volume, used as a raw block device
           lvcreate -qq -s -kn -n vm hc/base 2>"$vm/prep.err" || status=prep_failed ;;
  reflink) disk=$vm/disk.raw; fmt=raw
           cp --reflink=always "$base" "$disk" 2>"$vm/prep.err" || status=prep_failed ;;
  *)       status=bad_layout ;;
esac
prep_s=$(python3 -c "import time;print(round(time.time()-$t0,3))")

drive="file=$disk,if=none,format=$fmt,id=rootdisk0-drive,node-name=rootdisk0,cache=$cache,aio=$aio"
[ -n "$discard" ] && drive+=",discard=$discard,detect-zeroes=$([ "$discard" = unmap ] && echo unmap || echo on)"
[ -n "$extra" ] && drive+=",$extra"
iot=(); devprop=""
[ "$iothread" = 1 ] && iot=(-object iothread,id=io0) && devprop=",iothread=io0"
# iothreads=N (QEMU >= 9.0, PCI only): spread the disk's queues over N iothreads with iothread-vq-mapping.
if [ "$iothreads" -gt 1 ]; then
  iot=(); maps=""
  for i in $(seq 0 $((iothreads - 1))); do iot+=(-object "iothread,id=io$i"); maps+="${maps:+,}{\"iothread\":\"io$i\"}"; done
fi
rootdev=/dev/vda; ctl=()
case "$devtype" in
  pci)      pcie=on;  blk="virtio-blk-pci,drive=rootdisk0-drive,num-queues=$queues$devprop"
            if [ "$iothreads" -gt 1 ]; then  # list properties need the JSON form of -device
              ex=""; for kv in ${devextra//,/ }; do k=${kv%%=*}; v=${kv#*=}
                case $v in on) v=true;; off) v=false;; *[!0-9]*) v="\"$v\"";; esac; ex+=",\"$k\":$v"; done
              blk="{\"driver\":\"virtio-blk-pci\",\"drive\":\"rootdisk0-drive\",\"num-queues\":$queues,\"iothread-vq-mapping\":[$maps]$ex}"; devextra=""
            fi ;;
  scsi)     pcie=off; ctl=(-device "virtio-scsi-device,id=scsi0$devprop"); rootdev=/dev/sda
            blk="scsi-hd,drive=rootdisk0-drive,bus=scsi0.0" ;;
  scsi-pci) pcie=on;  ctl=(-device "virtio-scsi-pci,id=scsi0,num_queues=$queues$devprop"); rootdev=/dev/sda
            blk="scsi-hd,drive=rootdisk0-drive,bus=scsi0.0" ;;
  *)        pcie=off; blk="virtio-blk-device,drive=rootdisk0-drive$devprop" ;;
esac
# dev_extra is a virtio property: it goes on the virtio-scsi controller, not on scsi-hd.
if [ -n "$devextra" ]; then if [ ${#ctl[@]} -gt 0 ]; then ctl[1]+=",$devextra"; else blk+=",$devextra"; fi; fi
glob=(); for gl in ${globals//;/ }; do glob+=(-global "$gl"); done
tr=(); for ev in ${trace//,/ }; do tr+=(-trace "$ev"); done
sched=$(get guest_sched "")
append="console=ttyS0 reboot=k panic=1 root=$rootdev rw init=/init bench_wc=$wc${fsopt:+ bench_fsopt=$fsopt}${sched:+ bench_sched=$sched}"

declare -A R=(); exit_s=null; rm_s=null; killed=false; boot_s=null
s0=$(sectors)
if [ "$status" = ok ]; then
  # Same shape as the prod pool command line (minus network and vsock).
  "${QEMU[@]}" -smp "$smp" -m "$mem" -nodefaults -serial stdio -kernel "$KERNEL" -append "$append" \
    "${glob[@]}" "${tr[@]}" "${iot[@]}" -drive "$drive" -nographic -no-reboot -monitor none -rtc base=utc,clock=host \
    -qmp "unix:$vm/qmp.sock,server=on,wait=off" \
    -machine "microvm,accel=kvm,acpi=on,pcie=$pcie,pic=off,pit=off,rtc=on" -cpu host "${ctl[@]}" -device "$blk" \
    </dev/null >"$vm/serial.log" 2>"$vm/qemu.err" &
  qpid=$!
  ( peak=0; while kill -0 "$qpid" 2>/dev/null; do
      d=$(awk '/^Dirty:/{print int($2/1024)}' /proc/meminfo); [ "$d" -gt "$peak" ] && peak=$d && echo "$peak" > "$vm/dirty.peak"; sleep 1; done ) &
  deadline=$((SECONDS + 900))
  while kill -0 "$qpid" 2>/dev/null && ! grep -q '^GUEST_DONE' "$vm/serial.log" && [ $SECONDS -lt $deadline ]; do sleep 2; done
  if grep -q '^GUEST_DONE' "$vm/serial.log"; then
    t1=$(date +%s.%N); kill -TERM "$qpid"
    for _ in $(seq 300); do kill -0 "$qpid" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$qpid" 2>/dev/null; then kill -KILL "$qpid"; killed=true; fi
    wait "$qpid" 2>/dev/null
    exit_s=$(python3 -c "import time;print(round(time.time()-$t1,3))")
  else
    status=$(kill -0 "$qpid" 2>/dev/null && echo timeout || echo qemu_exited)
    {  # What QEMU and the host are blocked on.
      echo "== qemu thread states"; for t in /proc/"$qpid"/task/*; do echo "$(awk '/^State:/{print $2}' "$t/status") $(cat "$t/wchan" 2>/dev/null)"; done | sort | uniq -c
      echo "== D-state threads host-wide"; ps -eLo stat,comm,wchan:32 | awk '$1 ~ /^D/' | sort | uniq -c | head -20
      echo "== meminfo"; grep -E '^(MemAvailable|Dirty|Writeback|Cached):' /proc/meminfo
      echo "== diskstats"; grep -E " ($DEV|loop[0-9]+|nullb[0-9]+) " /proc/diskstats
      echo "== dmesg"; dmesg | grep -v -e fstab-generator -e mlx5 | tail -8
    } > "$vm/diag.txt" 2>&1; kill -KILL "$qpid" 2>/dev/null; wait "$qpid" 2>/dev/null
  fi
  boot_s=$(sed -n 's/^GUEST_UP \([0-9.]*\).*/\1/p' "$vm/serial.log" | head -1); boot_s=${boot_s:-null}
fi
t2=$(date +%s.%N); if [ "$layout" = thin ]; then lvremove -qqfy hc/vm; else rm -f "$disk"; fi; rm_s=$(python3 -c "import time;print(round(time.time()-$t2,3))")
sync; s1=$(sectors)

guest_diag=$(grep '^D ' "$vm/serial.log" 2>/dev/null | tr -d '\r' | tail -c 2500)
suite=$( (grep '^R ' "$vm/serial.log" 2>/dev/null || true) | sed 's/^R //' | jq -s 'map({(.n): (del(.n))}) | add // {}' 2>/dev/null)
jq -e . >/dev/null 2>&1 <<<"$suite" || suite='{}'
tcounts='{}'; for ev in ${trace//,/ }; do
  n=$(grep -c "$ev" "$vm/qemu.err" 2>/dev/null; true); tcounts=$(jq -c --arg e "$ev" --argjson n "${n:-0}" '. + {($e): $n}' <<<"$tcounts")
done
jq -n --argjson cfg "$CFG" --arg class "$CLASS" --arg rep "$REP" --arg status "$status" --argjson suite "$suite" \
  --arg prep_s "$prep_s" --arg exit_s "$exit_s" --arg rm_s "$rm_s" --arg boot_s "$boot_s" --argjson killed "$killed" \
  --arg host_gib "$(python3 -c "print(round((${s1:-0}-${s0:-0})*512/2**30,2))")" \
  --arg dirty "$(cat "$vm/dirty.peak" 2>/dev/null || echo 0)" \
  --arg qemu_err "$(tail -c 600 "$vm/qemu.err" "$vm/prep.err" 2>/dev/null; cat "$vm/diag.txt" 2>/dev/null | tail -c 3000)" \
  --arg guest_diag "$guest_diag" --argjson trace_counts "$tcounts" --arg serial_tail "$( [ "$status" = ok ] || tail -c 1500 "$vm/serial.log" 2>/dev/null)" \
  --arg runner "$(nproc) cpu $(sed -n 's/^model name[^:]*: //p' /proc/cpuinfo | head -1), $(free -g | awk '/Mem:/{print $2}') GiB, dev $DEV $(cat /sys/class/block/"$DEV"/device/model 2>/dev/null || true)" \
  --arg qemu_version "$qemu_version" --arg run_id "${GITHUB_RUN_ID:-local}" --arg drive "$drive" --arg blk "${ctl[1]:+${ctl[1]} }$blk${globals:+ globals=$globals}" \
  '{config:$cfg, id:$cfg.id, class:$class, qemu_version:$qemu_version, rep:($rep|tonumber), status:$status, run_id:$run_id, runner:$runner,
    drive:$drive, device:$blk, prep_s:($prep_s|tonumber), boot_s:($boot_s|fromjson? // null),
    exit_s:($exit_s|fromjson? // null), killed:$killed, rm_s:($rm_s|tonumber), host_gib_written:($host_gib|tonumber),
    host_dirty_peak_mib:($dirty|tonumber), trace_counts:$trace_counts, suite:$suite, guest_diag:$guest_diag, qemu_err:$qemu_err, serial_tail:$serial_tail}' > "$OUT/result.json"
jq -c '{id, class, rep, status, exit_s, host_gib_written, fresh: .suite.fresh_rand, pg: .suite.pgbench.tps}' "$OUT/result.json"
