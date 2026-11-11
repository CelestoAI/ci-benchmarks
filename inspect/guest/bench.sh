#!/usr/bin/env bash
# Short micro-benchmarks. Each prints "PROBE key=value" lines.
set +e
cd "$(dirname "$0")"
gcc -O2 -o /tmp/clockbench clockbench.c && /tmp/clockbench
command -v strace >/dev/null && strace -f -c -e trace=clock_gettime,clock_gettime64 /tmp/clockbench 2>&1 | tail -4
sb() { sysbench memory --memory-oper=read "$@" --time=10 run | grep -oE '\(([0-9.]+) MiB/sec\)' | tr -d '()' | awk '{print $1}'; }
echo "PROBE mem_read_1k_4t_MiBps=$(sb --threads=4)"
echo "PROBE mem_read_1k_1t_MiBps=$(sb --threads=1)"
echo "PROBE mem_read_1m_4t_MiBps=$(sb --threads=4 --memory-block-size=1M --memory-total-size=1000G)"
echo "PROBE mem_read_1m_1t_MiBps=$(sb --threads=1 --memory-block-size=1M --memory-total-size=1000G)"
echo "PROBE mem_write_1m_4t_MiBps=$(sysbench memory --memory-oper=write --threads=4 --memory-block-size=1M --memory-total-size=1000G --time=10 run | grep -oE '\(([0-9.]+) MiB/sec\)' | tr -d '()' | awk '{print $1}')"
echo "PROBE dd_zero_null_GBps=$(dd if=/dev/zero of=/dev/null bs=1M count=20000 2>&1 | grep -oE '[0-9.]+ GB/s' | awk '{print $1}')"
echo "PROBE cpu_1t_eps=$(sysbench cpu --threads=1 --time=10 run | awk '/events per second/ {print $4}')"
# Steal and guest-visible CPU time while all vCPUs are busy.
read -r _ u n s i w q sq st _ < /proc/stat
echo "PROBE cpu_4t_eps=$(sysbench cpu --threads=$(nproc) --time=15 run | awk '/events per second/ {print $4}')"
read -r _ u2 n2 s2 i2 w2 q2 sq2 st2 _ < /proc/stat
tot=$(( (u2-u)+(n2-n)+(s2-s)+(i2-i)+(w2-w)+(q2-q)+(sq2-sq)+(st2-st) ))
echo "PROBE steal_pct_under_load=$(awk -v a=$((st2-st)) -v t=$tot 'BEGIN{printf "%.1f", t?100*a/t:0}')"
echo "PROBE idle_pct_under_load=$(awk -v a=$((i2-i)) -v t=$tot 'BEGIN{printf "%.1f", t?100*a/t:0}')"
# Process spawn cost (fork+exec), a common CI pattern.
s0=$(date +%s%N); for k in $(seq 1 1000); do /bin/true; done; s1=$(date +%s%N)
echo "PROBE spawn_true_us=$(( (s1-s0)/1000000 ))"
