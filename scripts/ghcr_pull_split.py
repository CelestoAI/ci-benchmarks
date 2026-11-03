#!/usr/bin/env python3
"""Split a cold pull of a private ghcr.io image into download and unpack.

Runs on a Celesto CI runner (dockerd with the containerd image store). For each
image and repetition it measures, from a clean store:

  cold      `docker pull`, download and unpack pipelined as in a real job
  network   every layer blob fetched with curl to /dev/null, 3 at a time
            (dockerd's default max-concurrent-downloads): network only
  fetch     `ctr content fetch` into dockerd's containerd: network + blob writes
  unpack    `docker pull` right after the fetch: blobs are local, so this is
            decompress + extract only (the rx byte count proves no download)
  gunzip    `gzip -dc` of every layer blob to /dev/null: decompression CPU only

Each phase records wall time, received bytes (/proc/net/dev), bytes written to
disk (/proc/diskstats) and CPU busy/iowait share (/proc/stat).

`mirror-auth` answers a separate question: when ghcr.io has a hosts.toml
mirror, does dockerd (or BuildKit) send the job's ghcr.io login to the mirror?
A small logging proxy stands in for the mirror and forwards to ghcr.io; it
rewrites the token realm to itself so the token request is visible too.
"""

import argparse
import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCEPT = ",".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
CONTAINERD_SOCKETS = ("/var/run/docker/containerd/containerd.sock", "/run/containerd/containerd.sock")
CONTENT_DIRS = (
    "/var/lib/docker/containerd/daemon/io.containerd.content.v1.content/blobs/sha256",
    "/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256",
)
RESULTS = os.environ.get("RESULTS_DIR", "pull-results")


def sh(cmd, check=True, quiet=False):
    if not quiet:
        print("+", cmd if isinstance(cmd, str) else " ".join(cmd), flush=True)
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check, text=True, capture_output=quiet)


def out(cmd):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True).stdout.strip()


def record(kind, **fields):
    os.makedirs(RESULTS, exist_ok=True)
    fields = {"kind": kind, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    with open(os.path.join(RESULTS, "results.jsonl"), "a") as f:
        f.write(json.dumps(fields) + "\n")
    print(json.dumps(fields), flush=True)


# --- counters ---------------------------------------------------------------


def _rx_bytes():
    total = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip() != "lo":
                total += int(data.split()[0])
    return total


def _disk_write_bytes():
    disks = set(os.listdir("/sys/block"))
    total = 0
    with open("/proc/diskstats") as f:
        for line in f:
            parts = line.split()
            if parts[2] in disks and not parts[2].startswith(("loop", "ram", "zram", "dm-")):
                total += int(parts[9]) * 512
    return total


def _cpu():
    with open("/proc/stat") as f:
        vals = [int(v) for v in f.readline().split()[1:]]
    idle, iowait = vals[3], vals[4]
    return sum(vals), idle, iowait


LABEL = os.environ.get("SPLIT_LABEL", "stock")


def _decompressors_seen(stop, seen):
    while not stop.is_set():
        for name in ("igzip", "unpigz"):
            if subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0:
                seen.add(name)
        stop.wait(0.5)


def measure(phase, image, rep, fn):
    rx0, wr0, (t0, idle0, io0) = _rx_bytes(), _disk_write_bytes(), _cpu()
    stop, seen = threading.Event(), set()
    sampler = threading.Thread(target=_decompressors_seen, args=(stop, seen), daemon=True)
    sampler.start()
    start = time.monotonic()
    try:
        extra = fn() or {}
    except subprocess.CalledProcessError as exc:
        # Keep measuring the other phases; the record says this one failed.
        extra = {"error": f"exit {exc.returncode}"}
    wall = time.monotonic() - start
    stop.set()
    sampler.join()
    rx1, wr1, (t1, idle1, io1) = _rx_bytes(), _disk_write_bytes(), _cpu()
    dt = max(t1 - t0, 1)
    record(
        "phase",
        label=LABEL,
        decompressor=",".join(sorted(seen)) or "go-gzip",
        phase=phase,
        image=image,
        rep=rep,
        wall_s=round(wall, 2),
        rx_mb=round((rx1 - rx0) / 1e6, 1),
        disk_write_mb=round((wr1 - wr0) / 1e6, 1),
        cpu_busy_pct=round(100 * (dt - (idle1 - idle0) - (io1 - io0)) / dt, 1),
        cpu_iowait_pct=round(100 * (io1 - io0) / dt, 1),
        **extra,
    )


# --- registry helpers --------------------------------------------------------


def registry_token(repo, user, password):
    q = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{repo}:pull"})
    req = urllib.request.Request(f"https://ghcr.io/token?{q}")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    return json.load(urllib.request.urlopen(req, timeout=30))["token"]


def manifest(ref, token):
    repo, tag = ref.removeprefix("ghcr.io/").rsplit(":", 1)
    req = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{tag}", headers={"Accept": ACCEPT})
    req.add_header("Authorization", f"Bearer {token}")
    m = json.load(urllib.request.urlopen(req, timeout=30))
    if "manifests" in m:
        digest = next(d["digest"] for d in m["manifests"] if d.get("platform", {}).get("architecture") == "amd64")
        req = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{digest}", headers={"Accept": ACCEPT})
        req.add_header("Authorization", f"Bearer {token}")
        m = json.load(urllib.request.urlopen(req, timeout=30))
    return repo, m


def containerd_socket():
    # dockerd's own containerd lives under root-only /var/run/docker.
    for sock in CONTAINERD_SOCKETS:
        if subprocess.run(["sudo", "test", "-S", sock]).returncode == 0:
            return sock
    raise SystemExit("no containerd socket found: " + out("sudo ls -la /var/run/docker /run/containerd 2>&1"))


def clean(image):
    sh(f"docker rmi -f {image}", check=False, quiet=True)
    sh("docker image prune -af", check=False, quiet=True)
    sh("docker builder prune -af", check=False, quiet=True)
    sh(f"sudo ctr -a {containerd_socket()} -n moby images rm {image}", check=False, quiet=True)
    # Let containerd's garbage collector drop unreferenced blobs and snapshots.
    time.sleep(3)
    sh("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null", check=False, quiet=True)
    blobs = out(f"sudo ctr -a {containerd_socket()} -n moby content ls -q | wc -l")
    return int(blobs or 0)


# --- commands ----------------------------------------------------------------


def cmd_env(_args):
    info = {
        "nproc": out("nproc"),
        "cpu_model": out("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2"),
        "mem_total_mb": out("awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo"),
        "kernel": out("uname -r"),
        "docker": out("docker version --format '{{.Server.Version}}'"),
        "storage": out("docker info -f '{{.Driver}} {{json .DriverStatus}}'"),
        "docker_root": out("docker info -f '{{.DockerRootDir}}'"),
        "unpigz": shutil.which("unpigz") or "absent",
        "ctr": out("ctr --version") or "absent",
        "containerd_socket": next((s for s in CONTAINERD_SOCKETS if subprocess.run(["sudo", "test", "-S", s]).returncode == 0), "absent"),
        "df": out("df -h / /var/lib/docker 2>/dev/null"),
        "lsblk": out("lsblk -o NAME,SIZE,ROTA,TYPE,MOUNTPOINT 2>/dev/null"),
        "ghcr_cdn_ip": out("getent hosts pkg-containers.githubusercontent.com | head -1"),
    }
    # Sequential write speed of the disk that holds Docker's data.
    root = info["docker_root"] or "/var/lib/docker"
    dd = out(f"sudo dd if=/dev/zero of={root}/dd-probe bs=1M count=2048 conv=fdatasync 2>&1 | tail -1")
    sh(f"sudo rm -f {root}/dd-probe", check=False, quiet=True)
    info["dd_write_2g"] = dd
    record("env", **info)


def cmd_split(args):
    user, password = os.environ["GHCR_USER"], os.environ["GHCR_TOKEN"]
    sock = containerd_socket()
    fetch_help = out(f"sudo ctr -a {sock} content fetch --help")
    conc = "--max-concurrent-downloads 3" if "max-concurrent-downloads" in fetch_help else ""
    phases = set(args.phases.split(","))
    for image in args.images:
        repo = image.removeprefix("ghcr.io/").rsplit(":", 1)[0]
        token = registry_token(repo, user, password)
        _, m = manifest(image, token)
        layers = [(layer["digest"], layer["size"]) for layer in m["layers"]]
        record(
            "image",
            image=image,
            layers=len(layers),
            compressed_mb=round(sum(s for _, s in layers) / 1e6, 1),
            largest_layer_mb=round(max(s for _, s in layers) / 1e6, 1),
        )
        for rep in range(1, args.reps + 1):
            left = clean(image)
            measure("cold", image, rep, lambda: (sh(f"docker pull -q {image}"), {"blobs_before": left})[1])
            size = out(f"docker image inspect -f '{{{{.Size}}}}' {image}")
            record("unpacked", image=image, rep=rep, unpacked_mb=round(int(size or 0) / 1e6, 1))

            clean(image)
            token = registry_token(repo, user, password)

            def network():
                def get(layer):
                    digest, _ = layer
                    r = subprocess.run(
                        [
                            "curl", "-fsSL", "-o", "/dev/null", "-w", "%{size_download} %{time_total}",
                            "-H", f"Authorization: Bearer {token}",
                            f"https://ghcr.io/v2/{repo}/blobs/{digest}",
                        ],
                        text=True, capture_output=True, check=True,
                    )
                    size, secs = r.stdout.split()
                    return float(size) / 1e6 / max(float(secs), 1e-3)

                with ThreadPoolExecutor(3) as pool:
                    rates = list(pool.map(get, layers))
                return {"max_layer_mb_s": round(max(rates), 1)}

            if "network" in phases:
                measure("network", image, rep, network)
            measure(
                "fetch",
                image,
                rep,
                lambda: sh(f"sudo ctr -a {sock} -n moby content fetch {conc} --platform linux/amd64 "
                           f"-u {user}:{password} {image} >/dev/null", quiet=True) and None,
            )
            measure("unpack", image, rep, lambda: sh(f"docker pull -q {image}") and None)

            def gunzip():
                blob_dir = next(d for d in CONTENT_DIRS if sh(f"sudo test -d {d}", check=False, quiet=True).returncode == 0)
                for digest, _ in layers:
                    sh(f"sudo cat {blob_dir}/{digest.split(':')[1]} | gzip -dc >/dev/null", quiet=True)

            if "gunzip" in phases:
                measure("gunzip", image, rep, gunzip)
            for tool in ("igzip", "unpigz"):
                if tool in phases and shutil.which(tool):
                    def run_tool(tool=tool):
                        blob_dir = next(d for d in CONTENT_DIRS if sh(f"sudo test -d {d}", check=False, quiet=True).returncode == 0)
                        for digest, _ in layers:
                            sh(f"sudo cat {blob_dir}/{digest.split(':')[1]} | {tool} -dc >/dev/null", quiet=True)
                    measure(tool, image, rep, run_tool)


# --- mirror credential probe ---------------------------------------------------


class _Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    listen = ""
    log_path = ""

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self._forward()

    def do_GET(self):
        self._forward()

    def _forward(self):
        auth = self.headers.get("Authorization")
        headers = {k: self.headers[k] for k in ("Authorization", "Accept", "User-Agent") if self.headers.get(k)}
        conn = http.client.HTTPSConnection("ghcr.io", timeout=60)
        conn.request(self.command, self.path, headers=headers)
        resp = conn.getresponse()
        body = resp.read() if self.command == "GET" else b""
        with open(self.log_path, "a") as f:
            f.write(json.dumps({
                "method": self.command,
                "path": self.path.split("?")[0],
                "auth": auth.split()[0].lower() if auth else "none",
                "status": resp.status,
                "ua": (self.headers.get("User-Agent") or "")[:24],
            }) + "\n")
        self.send_response(resp.status)
        for key, value in resp.getheaders():
            low = key.lower()
            if low in ("transfer-encoding", "connection", "content-length"):
                continue
            if low == "www-authenticate":
                value = value.replace("https://ghcr.io/token", f"http://{self.listen}/token")
            self.send_header(key, value)
        length = len(body) if self.command == "GET" else int(resp.getheader("Content-Length") or 0)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(body)


def cmd_mirror_auth(args):
    os.makedirs(RESULTS, exist_ok=True)
    listen = "127.0.0.1:5001"
    log_path = os.path.abspath(os.path.join(RESULTS, "mirror-proxy.jsonl"))
    _Proxy.listen, _Proxy.log_path = listen, log_path
    server = ThreadingHTTPServer(("127.0.0.1", 5001), _Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    sh("sudo mkdir -p /etc/docker/certs.d/ghcr.io")
    hosts = f'server = "https://ghcr.io"\n\n[host."http://{listen}"]\n  capabilities = ["pull", "resolve"]\n'
    sh(f"printf '%s' '{hosts}' | sudo tee /etc/docker/certs.d/ghcr.io/hosts.toml")

    def case(name, cmd):
        open(log_path, "a").write(json.dumps({"case": name}) + "\n")
        before = sum(1 for _ in open(log_path))
        ok = sh(cmd, check=False).returncode == 0
        lines = [json.loads(line) for line in open(log_path).readlines()[before:]]
        record(
            "mirror_case",
            case=name,
            pull_ok=ok,
            requests=len(lines),
            token_auth=sorted({entry["auth"] for entry in lines if entry["path"] == "/token"}),
            manifest_status=sorted({entry["status"] for entry in lines if "/manifests/" in entry["path"]}),
            blob_status=sorted({entry["status"] for entry in lines if "/blobs/" in entry["path"]}),
        )

    image = args.image
    sh(f"docker rmi -f {image}", check=False, quiet=True)
    case("docker-pull", f"docker pull -q {image}")
    sh(f"docker rmi -f {image}", check=False, quiet=True)
    sh("docker builder prune -af", check=False, quiet=True)
    case("docker-build-from", f"printf 'FROM {image}\\nRUN true\\n' | docker build --no-cache -q -")

    buildkitd = f'[registry."ghcr.io"]\n  mirrors = ["{listen}"]\n[registry."{listen}"]\n  http = true\n'
    with open(os.path.join(RESULTS, "buildkitd.toml"), "w") as f:
        f.write(buildkitd)
    sh(f"docker buildx create --name mirrorprobe --driver docker-container --driver-opt network=host "
       f"--buildkitd-config {RESULTS}/buildkitd.toml --bootstrap", check=False)
    case("buildx-container-from",
         f"printf 'FROM {image}\\nRUN true\\n' | docker buildx build --builder mirrorprobe --no-cache -")
    sh("docker buildx rm mirrorprobe", check=False, quiet=True)

    record("dockerd_log", host_mismatch=out("sudo grep -c \"Host doesn't match\" /var/log/celesto-docker.log") or "0",
           tail=out("sudo grep -iE 'mirror|host doesn|127.0.0.1:5001|trying next host' /var/log/celesto-docker.log | tail -n 20"))
    sh("sudo rm -f /etc/docker/certs.d/ghcr.io/hosts.toml", check=False)
    server.shutdown()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("env")
    split = sub.add_parser("split")
    split.add_argument("--reps", type=int, default=2)
    split.add_argument("--phases", default="network,gunzip")
    split.add_argument("images", nargs="+")
    mirror = sub.add_parser("mirror-auth")
    mirror.add_argument("image")
    args = parser.parse_args()
    {"env": cmd_env, "split": cmd_split, "mirror-auth": cmd_mirror_auth}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
