#!/bin/bash
# Guest disk tuning for Celesto CI VMs, chosen by a level name found in $1 (a branch name like
# cache-bench/dependency/tune-t2-run3 works). Prints the before/after settings.
set -u
lvl=$(echo "$1" | grep -oE 't[0-9]+' | head -1)
dev=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null); [ -n "$dev" ] || dev=$(basename "$(findmnt -no SOURCE /)")
q=/sys/block/$dev/queue
show() { echo "[$1] dev=$dev rotational=$(cat $q/rotational) scheduler=$(cat $q/scheduler) nr_requests=$(cat $q/nr_requests) read_ahead_kb=$(cat $q/read_ahead_kb) mount=$(findmnt -no OPTIONS /) dirty=$(sysctl -n vm.dirty_ratio)/$(sysctl -n vm.dirty_background_ratio) expire=$(sysctl -n vm.dirty_expire_centisecs) wb=$(sysctl -n vm.dirty_writeback_centisecs)"; }
show before
case "$lvl" in
  t1) echo 0 > $q/rotational; echo none > $q/scheduler ;;
  t2) echo 0 > $q/rotational; echo none > $q/scheduler
      mount -o remount,commit=60,noatime /
      sysctl -q -w vm.dirty_ratio=40 vm.dirty_background_ratio=20 vm.dirty_expire_centisecs=6000 vm.dirty_writeback_centisecs=1500 ;;
  t3) echo 0 > $q/rotational; echo none > $q/scheduler
      mount -o remount,commit=60,noatime /
      sysctl -q -w vm.dirty_ratio=60 vm.dirty_background_ratio=40 vm.dirty_expire_centisecs=30000 vm.dirty_writeback_centisecs=3000 ;;
  *) echo "no tuning level in '$1'" ;;
esac
show after
