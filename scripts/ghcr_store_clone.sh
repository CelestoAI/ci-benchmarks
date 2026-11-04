#!/usr/bin/env bash
# Does a saved Docker image store work in a new VM?
#
# Celesto's design docs/designs/ci-image-pull-cache.md (D-04, D-07, D-08) keeps
# Docker's data on a second disk, saves it after a trusted job, and gives the
# next VM a clone. This test copies that path with no host change: a file mounted
# at /var/lib/docker acts as the second disk, and a CI artifact moves it to a new VM.
#
#   save   IMAGE: empty disk file, cold pull, rename, clean stop, save
#   verify IMAGE: new VM, clone the file, mount it, check access, repeat pull
#
# Not tested: a real attached drive, host-side save or clone time, or real store
# sizes. The file's 20 GiB size is only for this test, not the D-04 size.
set -u

MODE="${1:?usage: ghcr_store_clone.sh save|verify IMAGE}"
IMAGE="${2:?usage: ghcr_store_clone.sh save|verify IMAGE}"
RESULTS="${RESULTS_FILE:-results.txt}"
STORE_FILE="$PWD/store.img"
ARCHIVE="$PWD/store.img.zst"
LABEL=celesto-docker
DOCKERD_PATHS="/usr/bin/dockerd /usr/local/bin/dockerd /usr/sbin/dockerd"

SOCK=/var/run/docker/containerd/containerd.sock
ctr_moby() { sudo ctr -a "$SOCK" -n moby "$@"; }
rx_bytes() { awk 'NR > 2 && $1 != "lo:" { sum += $2 } END { printf "%d", sum }' /proc/net/dev; }
count_store() {
  echo "images=$(ctr_moby images ls -q | wc -l) snapshots=$(ctr_moby snapshots --snapshotter overlayfs ls | tail -n +2 | wc -l) blobs=$(ctr_moby content ls -q | wc -l)"
}
log() { echo "$*" | tee -a "$RESULTS"; }

measure() {
  local name="$1"; shift
  local marker; marker=$(mktemp)
  # igzip is the decompressor, so seeing it means layers were unpacked again.
  ( while :; do pgrep -x igzip >/dev/null && echo seen >"$marker"; sleep 0.1; done ) &
  local sampler=$!
  local rx0 t0 t1 rc
  rx0=$(rx_bytes); t0=$(date +%s.%N)
  "$@"; rc=$?
  t1=$(date +%s.%N)
  kill "$sampler" 2>/dev/null; wait "$sampler" 2>/dev/null
  local igzip=no; [ -s "$marker" ] && igzip=yes; rm -f "$marker"
  awk -v n="$name" -v rc="$rc" -v t0="$t0" -v t1="$t1" -v rx0="$rx0" -v rx1="$(rx_bytes)" \
      -v ig="$igzip" -v store="$(count_store)" \
    'BEGIN { printf "%-26s rc=%-3d %8.2fs rx=%9.1fMB igzip=%-3s %s\n", n, rc, t1 - t0, (rx1 - rx0) / 1048576, ig, store }' \
    | tee -a "$RESULTS"
}

# The guest agent restarts dockerd when it exits, but it starts dockerd only if
# it finds the executable (dataplane/guest/src/docker.rs). Hiding the executable
# holds dockerd down while the disk changes.
stop_dockerd() {
  local path
  for path in $DOCKERD_PATHS; do
    if sudo test -x "$path"; then sudo mv "$path" "$path.held"; fi
  done
  sudo pkill -x dockerd || true
  for _ in $(seq 1 60); do
    pgrep -x dockerd >/dev/null || pgrep -f docker/containerd >/dev/null || return 0
    sleep 1
  done
  log "ERROR: dockerd or its containerd did not stop"; exit 1
}
start_dockerd() {
  local path t0
  t0=$(date +%s.%N)
  for path in $DOCKERD_PATHS; do
    if sudo test -e "$path.held"; then sudo mv "$path.held" "$path"; fi
  done
  for _ in $(seq 1 120); do
    if docker info >/dev/null 2>&1; then
      log "dockerd ready after $(awk -v a="$t0" -v b="$(date +%s.%N)" 'BEGIN { printf "%.2f", b - a }') s"
      return 0
    fi
    sleep 0.5
  done
  log "ERROR: dockerd did not come back"; sudo tail -n 30 /var/log/celesto-docker.log; exit 1
}
login() { echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null; }

save() {
  : >"$RESULTS"
  sudo test -e /dev/loop-control || { log "ERROR: no loop device in this VM"; exit 1; }
  stop_dockerd
  truncate -s 20G "$STORE_FILE"
  sudo mkfs.ext4 -q -F -L "$LABEL" "$STORE_FILE"
  sudo mount -o loop "$STORE_FILE" /var/lib/docker
  start_dockerd
  docker info -f 'docker root: {{.DockerRootDir}}, driver {{.Driver}}' | tee -a "$RESULTS"
  findmnt -no SOURCE,FSTYPE /var/lib/docker | tee -a "$RESULTS"

  login
  measure cold_pull docker pull "$IMAGE"
  local digest internal
  digest=$(docker image inspect "$IMAGE" --format '{{.Id}}')
  internal="celesto-store/${digest#sha256:}:keep"
  docker tag "$IMAGE" "$internal"
  docker rmi "$IMAGE"
  docker logout ghcr.io
  log "digest: $digest"
  # A pull lease can keep content alive for hours, so remove leases to prove that
  # the internal name alone keeps the layers in the saved store.
  local id
  for id in $(ctr_moby leases ls -q); do ctr_moby leases rm --sync "$id" || true; done
  log "store before save: $(count_store)"

  # The safe save steps: stop, sync, unmount, check.
  stop_dockerd
  sync
  df -BM --output=used /var/lib/docker | tail -n 1 | sed 's/^/store used: /' | tee -a "$RESULTS"
  sudo umount /var/lib/docker
  sudo e2fsck -fn "$STORE_FILE" >/dev/null; log "e2fsck rc=$?"
  sudo chown "$(id -u):$(id -g)" "$STORE_FILE"
  command -v zstd >/dev/null || { sudo apt-get update -qq; sudo apt-get install -y -qq zstd >/dev/null; }
  zstd -q -T0 -3 --sparse "$STORE_FILE" -o "$ARCHIVE"
  ls -la "$ARCHIVE" | tee -a "$RESULTS"
  echo "$digest" >digest.txt
  start_dockerd
}

verify() {
  : >"$RESULTS"
  sudo test -e /dev/loop-control || { log "ERROR: no loop device in this VM"; exit 1; }
  local digest; digest=$(cat digest.txt)
  command -v zstd >/dev/null || { sudo apt-get update -qq; sudo apt-get install -y -qq zstd >/dev/null; }
  zstd -q -d --sparse "$ARCHIVE" -o "$STORE_FILE"
  log "new VM: $(hostname), digest: $digest"
  # The real host would clone the saved store; this makes the same kind of copy.
  cp --reflink=auto --sparse=always "$STORE_FILE" "$STORE_FILE.clone"
  stop_dockerd
  sudo mount -o loop "$STORE_FILE.clone" /var/lib/docker
  findmnt -no SOURCE,FSTYPE /var/lib/docker | tee -a "$RESULTS"
  start_dockerd
  log "store at start: $(count_store)"
  docker images --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' | tee -a "$RESULTS"

  log "--- no login: rc must not be 0 for the name forms"
  measure name_pull_no_login docker pull "$IMAGE"
  measure name_run_no_login docker run --rm --entrypoint /bin/true "$IMAGE"
  log "--- no login: local forms that D-07 does not cover"
  measure bare_digest_run_no_login docker run --rm --entrypoint /bin/true "$digest"
  log "--- the real check: repeat pull in a new VM with a login"
  login
  measure warm_pull_new_vm docker pull "$IMAGE"
  measure run_new_vm docker run --rm --entrypoint /bin/true "$IMAGE"
  log "--- results"
  cat "$RESULTS"
}

case "$MODE" in
  save) save ;;
  verify) verify ;;
  *) echo "unknown mode: $MODE"; exit 2 ;;
esac
