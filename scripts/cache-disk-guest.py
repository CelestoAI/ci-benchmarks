import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

root = Path(
    "/tmp/cache-disk-e2e-"
    + os.environ["GITHUB_RUN_ID"]
    + "-"
    + os.environ["GITHUB_RUN_ATTEMPT"]
)
root.mkdir(exist_ok=True)
mode = sys.argv[1]
if mode == "identify":
    mac = subprocess.check_output(
        [
            "bash",
            "-c",
            "cat /sys/class/net/$(ip route show default | awk '{print $5;exit}')/address",
        ],
        text=True,
    ).strip()
    ip = subprocess.check_output(
        ["curl", "-fsS", "--max-time", "15", "https://checkip.amazonaws.com"], text=True
    ).strip()
    d = {
        "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner": os.environ["RUNNER_NAME"],
        "mac": mac,
        "egress": ip,
    }
    (root / "ready.json").write_text(json.dumps(d))
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write("mac=" + mac + "\nselected=" + str(ip == "100.59.248.9").lower() + "\n")
    print(json.dumps(d))
    (Path(os.environ["RUNNER_TEMP"]) / "cache-disk-evidence").mkdir(exist_ok=True)
    (
        Path(os.environ["RUNNER_TEMP"]) / "cache-disk-evidence" / "identity.json"
    ).write_text(json.dumps(d))
elif mode == "gate":
    case = sys.argv[2]
    deadline = time.monotonic() + 1200
    (root / "waiting").write_text(case)
    while not (root / ("release-" + case + ".json")).exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Host controller gate " + case)
        time.sleep(2)
    evidence = Path(os.environ["RUNNER_TEMP"]) / "cache-disk-evidence" / case
    evidence.mkdir(exist_ok=True)
    (evidence / "disk-mode.json").write_bytes(
        (root / ("release-" + case + ".json")).read_bytes()
    )
    if case != "finish":
        # Clean before input mutation, never flush between the mutation and save.
        os.sync()
        start = time.monotonic()
        payload = Path(os.environ["GITHUB_WORKSPACE"]) / "cache-file"
        subprocess.run(
            [
                "dd",
                "if=/dev/urandom",
                "of=" + str(payload),
                "bs=4M",
                "count=1024",
                "status=none",
            ],
            check=True,
        )
        # Count input generation and hashing separately from cache save.
        h = hashlib.sha256()
        with payload.open("rb") as f:
            while b := f.read(4 * 1024**2):
                h.update(b)
        (evidence / "payload.sha256").write_text(h.hexdigest() + "  cache-file\n")
        (evidence / "prepare.json").write_text(
            json.dumps({"write_hash_seconds": time.monotonic() - start})
        )
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(
                "CACHE_PROFILE_EVENTS="
                + str(evidence / "events.jsonl")
                + "\nCACHE_PROFILE_ARCHIVE_RESOURCES="
                + str(evidence / "archive-resources.txt")
                + "\n"
            )
elif mode == "verify":
    case = sys.argv[2]
    evidence = Path(os.environ["RUNNER_TEMP"]) / "cache-disk-evidence" / case
    subprocess.run(["sha256sum", "-c", str(evidence / "payload.sha256")], check=True)
    (evidence / "restore-verified").touch()
