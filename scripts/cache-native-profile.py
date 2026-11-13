"""Observe the official cache action without changing its workload or upload tuning."""

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

out = Path("/dev/shm") / "cache-native-profile"
mode = sys.argv[1]


def snapshot():
    return {n: Path("/proc", n).read_text() for n in ["meminfo", "diskstats", "stat"]}


def write(name, data):
    (out / name).write_text(json.dumps(data, indent=2) + "\n")


def utc():
    return datetime.now(UTC).isoformat()


def command(*args):
    p = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
    return p.stdout.strip() if p.returncode == 0 else None


if mode == "prepare":
    out.mkdir()
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(
            f"PROFILE_OUT={out}\nCACHE_PROFILE_EVENTS={out}/events.jsonl\nCACHE_PROFILE_ARCHIVE_RESOURCES={out}/archive-resources.txt\n"
        )
    bundle = (
        Path(os.environ["RUNNER_WORKSPACE"]).parent
        / "_actions/actions/cache/55cc8345863c7cc4c66a329aec7e433d2d1c52a9/dist/save-only/index.js"
    )
    assert bundle.is_file(), f"Official action entrypoint missing: {bundle}"
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("prepare-cache-native.py")),
            str(bundle),
            str(bundle),
            str(out / "patch.json"),
        ],
        check=True,
    )
    subprocess.run(["node", "--check", str(bundle)], check=True)
    provider = "unknown"
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            args = (p / "cmdline").read_bytes().decode().split("\0")
        except (OSError, UnicodeError):
            continue
        if args and "celesto-ci-cache-proxy" in args[0] and "--host-provider" in args:
            value = args[args.index("--host-provider") + 1]
            if value in ["aws", "ovh"]:
                provider = value
    write(
        "host.json",
        {
            "runner": os.environ["RUNNER_NAME"],
            "provider": provider,
            "egress_ip": command(
                "curl", "-fsS", "--max-time", "10", "https://checkip.amazonaws.com"
            ),
            "kernel": os.uname().release,
            "metadata_device": out.stat().st_dev,
            "archive_device": Path(os.environ["RUNNER_TEMP"]).stat().st_dev,
            "metadata_filesystem": command("findmnt", "-J", "-T", str(out)),
            "cpu": command("lscpu"),
            "memory": command("free", "-b"),
            "payload_filesystem": command(
                "findmnt", "-J", "-T", os.environ["GITHUB_WORKSPACE"]
            ),
            "archive_temp_filesystem": command(
                "findmnt", "-J", "-T", os.environ["RUNNER_TEMP"]
            ),
            "tar": command("tar", "--version"),
            "zstd": command("zstd", "--version"),
            "run_url": f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            "sample": int(os.environ["PROFILE_SAMPLE"]),
            "snapshot": snapshot(),
        },
    )
elif mode == "generate":
    before = snapshot()
    started_utc = utc()
    started = time.monotonic()
    with open("cache-file", "wb") as f:
        subprocess.run(["head", "-c", "4G", "/dev/urandom"], stdout=f, check=True)
    ended_utc = utc()
    duration = time.monotonic() - started
    assert Path("cache-file").stat().st_size == 4 * 1024**3
    write(
        "generation.json",
        {
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "seconds": duration,
            "before": before,
            "after": snapshot(),
            "pre_save_hash": False,
            "pre_save_sync": False,
        },
    )
elif mode == "hash":
    h = hashlib.sha256()
    with open("cache-file", "rb") as f:
        while chunk := f.read(4 * 1024**2):
            h.update(chunk)
    (out / "payload.sha256").write_text(h.hexdigest() + "  cache-file\n")
elif mode == "verify":
    subprocess.run(["sha256sum", "-c", str(out / "payload.sha256")], check=True)
    assert Path("cache-file").stat().st_size == 4 * 1024**3
    (out / "restore-verified").touch()
else:
    raise ValueError(mode)
