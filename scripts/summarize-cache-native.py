"""Validate direct timers from the official runner-tuned action and its real restore."""

import json
import sys
from datetime import datetime
from pathlib import Path

out = Path(sys.argv[1])
events = [json.loads(l) for l in (out / "events.jsonl").read_text().splitlines()]
required = {
    "save_total",
    "detect_compression",
    "resolve_paths",
    "create_temp_dir",
    "archive",
    "reserve",
    "upload",
    "finalize",
    "cleanup",
    "process",
}
ends = [e for e in events if e["event"] == "end"]
assert len(ends) == len(required) and {e["phase"] for e in ends} == required, (
    "Missing or duplicate timing phases"
)
phases = {e["phase"]: e for e in ends}
starts = {e["phase"]: e for e in events if e["event"] == "start"}
assert set(starts) == required
assert all(e.get("status", "success") == "success" for e in ends)
assert phases["process"]["exit_code"] == 0
observations = {e["phase"]: e for e in events if e["event"] == "observed"}
assert observations["cache_result"]["saved"], "Cache action skipped the save"
config = observations["upload_config"]
assert config["concurrency"] == 64 and config["chunk_bytes"] == 64 * 1024**2, (
    "Runner upload tuning was bypassed or changed"
)
assert config["batch"] and config["size_metadata"], "Normal batch metadata missing"
assert config["script"].startswith(".celesto-upload-"), (
    "Official runner-prepared action was not invoked"
)
assert (out / "restore-verified").exists(), "Full restored SHA256 not verified"
size = observations["archive_bytes"]["bytes"]
assert 4 * 1024**3 < size < 4.01 * 1024**3
seconds = {k: e["duration_ms"] / 1000 for k, e in phases.items()}
main = ["archive", "reserve", "upload", "finalize", "cleanup"]
other = seconds["save_total"] - sum(seconds[k] for k in main)
assert other >= 0
host = json.loads((out / "host.json").read_text())
generation = json.loads((out / "generation.json").read_text())
assert host["metadata_device"] != host["archive_device"], (
    "Profiler metadata shares the cache archive disk"
)
assert observations["archive_directory"]["device"] == host["archive_device"], (
    "Archive was moved off the normal disk"
)
assert not generation["pre_save_hash"] and not generation["pre_save_sync"]
startup = (
    datetime.fromisoformat(starts["process"]["timestamp_utc"])
    - datetime.fromisoformat(generation["ended_utc"])
).total_seconds()
result = {
    "run_url": host["run_url"],
    "sample": host["sample"],
    "provider": host["provider"],
    "runner": host["runner"],
    "egress_ip": host["egress_ip"],
    "seconds": seconds,
    "setup_other_seconds": other,
    "metadata_device": host["metadata_device"],
    "archive_device": host["archive_device"],
    "archive_directory": observations["archive_directory"],
    "generation_seconds": generation["seconds"],
    "generation_end_to_action_process_start_seconds": startup,
    "archive_plus_reserve_seconds": seconds["archive"] + seconds["reserve"],
    "archive_bytes": size,
    "upload_mib_s": size / 1024**2 / seconds["upload"],
    "upload_config": config,
    "restore_verified": True,
    "archive_resources": (out / "archive-resources.txt").read_text(),
    "phase_starts": starts,
    "phase_ends": phases,
    "patch": json.loads((out / "patch.json").read_text()),
    "limits": [
        "Archive includes tar and zstd together.",
        "Generation-to-process interval includes runner/Node startup, module loading and step transition; it is separate from archive/reservation.",
        "Samples run on normal scheduler-selected hosts; no host disk settings changed.",
    ],
}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
summary = f"### Official cache action sample {host['sample']} ({host['provider']})\n\n| Phase | Seconds |\n|---|---:|\n"
summary += "".join(f"| {k} | {seconds[k]:.4f} |\n" for k in ["save_total", *main])
summary += f"| Startup / step transition | {startup:.4f} |\n\n64-stream upload tuning and batch metadata verified. Full restored SHA256 matches.\n"
(out / "summary.md").write_text(summary)
print(summary)
