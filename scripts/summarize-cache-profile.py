import json
from pathlib import Path
import sys

out = Path(sys.argv[1])
events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
ends = [event for event in events if event["event"] == "end"]
phases = {event["phase"]: event for event in ends}
required = {"save_total", "detect_compression", "resolve_paths", "create_temp_dir",
            "archive", "reserve", "upload", "finalize", "cleanup", "process"}
assert set(phases) == required and len(ends) == len(required), "Missing/duplicate timing phases"
assert all(event.get("status", "success") == "success" for event in ends), "A phase failed"
assert phases["process"]["exit_code"] == 0
assert (out / "restore-verified").exists(), "Restored bytes were not verified"
assert "Cache saved with key:" in (out / "save.log").read_text(), "Cache action did not save"
command = json.loads((out / "command.json").read_text())
assert command["status"] == 0
size = int((out / "archive-bytes").read_text())
times = {name: phases[name]["duration_ms"] / 1000 for name in required}
main = ["archive", "reserve", "upload", "finalize", "cleanup"]
setup = times["save_total"] - sum(times[name] for name in main)
assert setup >= 0, "Timing intervals overlap"
result = {
    "provider": command["provider"], "sample": command["sample"],
    "run_url": command["run_url"], "command_seconds": command["seconds"],
    "save_seconds": times["save_total"], "setup_seconds": setup,
    **{name + "_seconds": times[name] for name in main},
    "archive_bytes": size, "upload_mib_per_second": size / 1048576 / times["upload"],
    "restore_verified": True, "phases": phases,
    "archive_resources": (out / "archive-resources.txt").read_text(),
    "action": json.loads((out / "patch.json").read_text()),
}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
rows = [("Node command (includes startup)", command["seconds"]),
        ("Save total", times["save_total"]), ("Setup / other", setup)]
rows += [(name, times[name]) for name in main]
summary = f'### {result["provider"]} sample {result["sample"]}: 4 GiB cache save\n\n'
summary += '| Phase | Seconds |\n|---|---:|\n'
summary += ''.join(f'| {name} | {value:.4f} |\n' for name, value in rows)
summary += f'\nUpload: **{result["upload_mib_per_second"]:.1f} MiB/s**. Restored SHA-256 matches.\n'
summary += '\nArchive is tar + zstd together; reservation is measured separately.\n'
(out / "summary.md").write_text(summary)
print(summary)
