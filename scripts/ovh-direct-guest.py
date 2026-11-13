"""Own-job gates and integrity evidence for the one-VM OVH disk policy canary."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

out = Path("/dev/shm/cache-native-profile")
control = Path("/dev/shm/ovh-direct-control")
mode = sys.argv[1]
if mode == "identify":
    out.mkdir(exist_ok=True)
    control.mkdir(exist_ok=True)
    control.chmod(0o777)
    ip = subprocess.check_output(
        ["curl", "-fsS", "--max-time", "15", "https://checkip.amazonaws.com"], text=True
    ).strip()
    mac = subprocess.check_output(
        [
            "bash",
            "-c",
            "cat /sys/class/net/$(ip route show default | awk '{print $5;exit}')/address",
        ],
        text=True,
    ).strip()
    cid = 0
    if ip == "15.204.216.188":
        cid = int(
            subprocess.check_output(
                [
                    "sudo",
                    "-n",
                    "python3",
                    "-c",
                    "import fcntl,struct; f=open('/dev/vsock','rb'); print(struct.unpack('I',fcntl.ioctl(f.fileno(),0x7b9,bytes(4)))[0])",
                ],
                text=True,
            ).strip()
        )
    data = {
        "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "runner": os.environ["RUNNER_NAME"],
        "mac": mac,
        "ip": ip,
        "cid": cid,
    }
    (control / "identity.json").write_text(json.dumps(data))
    (out / "identity.json").write_text(json.dumps(data))
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(
            "selected="
            + str(ip == "15.204.216.188").lower()
            + "\ncid="
            + str(cid)
            + "\nmac="
            + mac
            + "\n"
        )
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write("PROFILE_OUT=" + str(out) + "\n")
    print(json.dumps(data))
elif mode == "gate":
    case = sys.argv[2]
    assert case in ["b1", "d1", "d2", "b2", "finish"]
    target = out / case
    target.mkdir(exist_ok=True)
    if case != "finish":
        t = time.monotonic()
        os.sync()
        (target / "initial-sync.json").write_text(
            json.dumps(
                {
                    "seconds": time.monotonic() - t,
                    "boundary": "Before input generation and before disk-mode switch",
                }
            )
        )
    (control / "waiting").write_text(case)
    until = time.monotonic() + 1200
    release = control / ("release-" + case + ".json")
    while not release.exists():
        if time.monotonic() > until:
            raise TimeoutError("Controller gate " + case)
        time.sleep(2)
    (target / "disk-mode.json").write_bytes(release.read_bytes())
    if case != "finish":
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(
                f"CACHE_PROFILE_EVENTS={target}/events.jsonl\nCACHE_PROFILE_ARCHIVE_RESOURCES={target}/archive-resources.txt\n"
            )
elif mode == "collect":
    case = sys.argv[2]
    target = out / case
    for name in [
        "host.json",
        "generation.json",
        "patch.json",
        "payload.sha256",
        "restore-verified",
    ]:
        shutil.copyfile(out / name, target / name)
    subprocess.run(
        [sys.executable, "scripts/summarize-ovh-direct.py", str(target)], check=True
    )
else:
    raise ValueError(mode)
