#!/usr/bin/env bash
# Read-only guest probe: CPU, clock, kernel, memory, disk queue and network
# settings, plus short micro-benchmarks that separate clock cost from memory speed.
set +e
sec() { echo; echo "===== $*"; }

sec identity
echo "runner=$RUNNER_NAME"; uname -a; cat /proc/cmdline; nproc; systemd-detect-virt 2>/dev/null
lscpu
sec cpu flags
grep -m1 '^flags' /proc/cpuinfo | cut -d: -f2 | tr ' ' '\n' | sed '/^$/d' | sort | tr '\n' ' '; echo
grep -m1 'model name' /proc/cpuinfo; grep -m1 'cpu MHz' /proc/cpuinfo
sec clock
cat /sys/devices/system/clocksource/clocksource0/current_clocksource /sys/devices/system/clocksource/clocksource0/available_clocksource
sec cpuidle
cat /sys/devices/system/cpu/cpuidle/current_driver /sys/devices/system/cpu/cpuidle/current_governor 2>&1
sec smt and vulnerabilities
cat /sys/devices/system/cpu/smt/control 2>&1; grep -H . /sys/devices/system/cpu/vulnerabilities/* | sed 's#.*/##'
sec dmesg
sudo dmesg | grep -iE 'clocksource|tsc|kvm-clock|pvclock|hypervisor|paravirt|spinlock|steal|kvm-guest|x86/fpu|hpet|haltpoll|virtio|EXT4-fs|Memory:|DMI|smpboot|APIC|ACPI: ' | head -100
sec kernel config
if [ -r /proc/config.gz ]; then zcat /proc/config.gz; elif [ -r /boot/config-$(uname -r) ]; then cat /boot/config-$(uname -r); else echo "no config available"; fi | grep -E '^(CONFIG_(KVM_GUEST|PARAVIRT[A-Z_]*|HYPERVISOR_GUEST|HZ|HZ_[0-9]+|PREEMPT[A-Z_]*|NO_HZ[A-Z_]*|TRANSPARENT_HUGEPAGE[A-Z_]*|HALTPOLL_CPUIDLE|CPU_IDLE[A-Z_]*|X86_X2APIC|SCHED_MC|NUMA|MQ_IOSCHED[A-Z_]*|IOSCHED_BFQ|BLK_WBT[A-Z_]*|ZSWAP|ZRAM|MITIGATION[A-Z_]*|RETPOLINE|CPU_MITIGATIONS|VIRTIO_BLK|VIRTIO_NET|VHOST[A-Z_]*|IKCONFIG[A-Z_]*))=' 
sec memory
free -m; swapon --show; cat /sys/kernel/mm/transparent_hugepage/enabled /sys/kernel/mm/transparent_hugepage/defrag; grep -E 'AnonHugePages|HugePages_Total|MemTotal' /proc/meminfo
sysctl vm.swappiness vm.dirty_ratio vm.dirty_background_ratio vm.dirty_expire_centisecs vm.dirty_writeback_centisecs vm.overcommit_memory kernel.sched_autogroup_enabled 2>/dev/null
sec mounts
findmnt -no SOURCE,FSTYPE,OPTIONS -T "${GITHUB_WORKSPACE:-$PWD}"; findmnt -no SOURCE,FSTYPE,OPTIONS -T /tmp; findmnt -no SOURCE,FSTYPE,OPTIONS -T /var/lib/docker 2>/dev/null
lsblk -o NAME,SIZE,ROTA,TYPE,MOUNTPOINT,FSTYPE 2>/dev/null
sec block queues
for d in /sys/block/vd* /sys/block/nvme* /sys/block/sd*; do [ -d "$d" ] || continue; q=$d/queue; echo "$(basename $d) sched=$(cat $q/scheduler) nr_requests=$(cat $q/nr_requests) read_ahead_kb=$(cat $q/read_ahead_kb) write_cache=$(cat $q/write_cache) rotational=$(cat $q/rotational) hw_queues=$(ls $d/mq 2>/dev/null | wc -l) max_sectors_kb=$(cat $q/max_sectors_kb) wbt_lat_usec=$(cat $q/wbt_lat_usec 2>/dev/null) nomerges=$(cat $q/nomerges)"; done
sec interrupts
head -1 /proc/interrupts; grep -iE 'virtio|vd|eth|blk|net|LOC|RES|CAL|TLB' /proc/interrupts | head -20
sec network
ip -br link; ethtool -l eth0 2>/dev/null | tail -6; ethtool -k eth0 2>/dev/null | grep -E '^(tcp-segmentation|generic-segmentation|generic-receive|scatter-gather|tx-checksumming|rx-checksumming):'
sysctl net.core.default_qdisc net.ipv4.tcp_congestion_control net.ipv4.tcp_wmem net.ipv4.tcp_rmem 2>/dev/null
sec docker
docker info --format 'driver={{.Driver}} root={{.DockerRootDir}} cgroup={{.CgroupDriver}} v{{.ServerVersion}}' 2>&1 | head -2
sec tools
command -v gcc sysbench strace perf 2>&1
