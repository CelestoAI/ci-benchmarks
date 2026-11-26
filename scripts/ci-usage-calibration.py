"""Independent VM measurements and a bounded workload for checking CI charts."""

import json
import mmap
import multiprocessing
import os
import time
from pathlib import Path


def burn_cpu():
    while True:
        sum(range(50_000))


def snapshot(phase):
    before = time.time_ns()
    uptime = float(Path("/proc/uptime").read_text().split()[0])
    cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, *values = line.split()
        if key in {"MemTotal:", "MemAvailable:"}:
            memory[key[:-1]] = int(values[0])
    after = time.time_ns()
    return {
        "phase": phase,
        "unix_ms": (before + after) // 2_000_000,
        "uptime_ms": round(uptime * 1000),
        "cpu_total": sum(cpu),
        "cpu_idle": cpu[3] + cpu[4],
        "memory_total_kib": memory["MemTotal"],
        "memory_available_kib": memory["MemAvailable"],
    }


def sample_phase(output, phase, duration):
    end = time.monotonic() + duration
    print(f"Phase {phase} ({duration}s)", flush=True)
    previous = None
    next_log = 0.0
    while time.monotonic() < end:
        point = snapshot(phase)
        output.write(json.dumps(point) + "\n")
        now = time.monotonic()
        if previous is None:
            previous = point
            next_log = now + 5
        elif now >= next_log:
            total = point["cpu_total"] - previous["cpu_total"]
            idle = point["cpu_idle"] - previous["cpu_idle"]
            memory_mib = (point["memory_total_kib"] - point["memory_available_kib"]) / 1024
            print(f'{point["unix_ms"]} {phase} CPU={(total - idle) * 100 / total:.1f}% memory={memory_mib:.1f} MiB', flush=True)
            previous = point
            next_log = now + 5
        time.sleep(0.25)


def sample_under_cpu(output, phase, workers):
    processes = [multiprocessing.Process(target=burn_cpu) for _ in range(workers)]
    for process in processes:
        process.start()
    try:
        sample_phase(output, phase, 26)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.join()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    cpus = len(os.sched_getaffinity(0))
    print(f"Available vCPUs: {cpus}", flush=True)
    assert 2 <= cpus <= 16, cpus
    with Path("ci-usage-reference.jsonl").open("w", buffering=1) as output:
        sample_phase(output, "idle_before", 20)
        with mmap.mmap(-1, 384 * 1024 * 1024, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS) as held_memory:
            for offset in range(0, len(held_memory), mmap.PAGESIZE):
                held_memory[offset] = 1
            sample_phase(output, "memory_only", 26)
            sample_under_cpu(output, "one_core_with_memory", 1)
        sample_under_cpu(output, "all_cores", cpus)
        sample_phase(output, "idle_after", 20)
