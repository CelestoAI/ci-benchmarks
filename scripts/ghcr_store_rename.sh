#!/usr/bin/env bash
# Does a repeat pull stay fast after image names are removed from Docker's store?
#
# Celesto's design docs/designs/ci-image-pull-cache.md (D-07) replaces each image
# name with an internal name before it saves a store. A workflow name then cannot
# resolve locally, so GHCR must approve each use. The speed gain needs containerd
# to reuse the layers and unpacked snapshots after the rename.
#
# Each phase prints one line: exit code, seconds, MB received, MB written to disk,
# whether igzip ran (an unpack), and the images, snapshots and blobs in the store.
# A negative control at the end proves that these numbers detect a real miss.
#
# Not tested here: a second disk, a saved or cloned store, or a new VM.
set -u

IMAGE="${1:?usage: ghcr_store_rename.sh IMAGE}"
RESULTS="${RESULTS_FILE:-results.txt}"

# dockerd's own containerd, as in scripts/ghcr_pull_split.py.
SOCK=/var/run/docker/containerd/containerd.sock
sudo test -S "$SOCK" || SOCK=/run/containerd/containerd.sock
ctr_moby() { sudo ctr -a "$SOCK" -n moby "$@"; }

rx_bytes() { awk 'NR > 2 && $1 != "lo:" { sum += $2 } END { printf "%d", sum }' /proc/net/dev; }
# Sectors written to whole virtio disks, in 512-byte units.
written_sectors() { awk '$3 ~ /^vd[a-z]+$/ { sum += $10 } END { printf "%d", sum }' /proc/diskstats; }
count_store() {
  images=$(ctr_moby images ls -q | wc -l)
  snapshots=$(ctr_moby snapshots --snapshotter overlayfs ls | tail -n +2 | wc -l)
  blobs=$(ctr_moby content ls -q | wc -l)
  echo "images=$images snapshots=$snapshots blobs=$blobs"
}

# measure NAME COMMAND...: run a command and record what it did.
measure() {
  local name="$1"; shift
  local marker; marker=$(mktemp)
  # igzip is the decompressor, so seeing it means layers were unpacked again.
  ( while :; do pgrep -x igzip >/dev/null && echo seen >"$marker"; sleep 0.1; done ) &
  local sampler=$!
  sync
  local rx0 wr0 t0 t1 rc
  rx0=$(rx_bytes); wr0=$(written_sectors); t0=$(date +%s.%N)
  "$@"; rc=$?
  t1=$(date +%s.%N)
  sync
  kill "$sampler" 2>/dev/null; wait "$sampler" 2>/dev/null
  local igzip=no; [ -s "$marker" ] && igzip=yes; rm -f "$marker"
  awk -v n="$name" -v rc="$rc" -v t0="$t0" -v t1="$t1" -v rx0="$rx0" -v rx1="$(rx_bytes)" \
      -v wr0="$wr0" -v wr1="$(written_sectors)" -v ig="$igzip" -v store="$(count_store)" \
    'BEGIN { printf "%-26s rc=%-3d %8.2fs rx=%9.1fMB written=%9.1fMB igzip=%-3s %s\n",
             n, rc, t1 - t0, (rx1 - rx0) / 1048576, (wr1 - wr0) * 512 / 1048576, ig, store }' \
    | tee -a "$RESULTS"
}

restart_dockerd() {
  sudo pkill -x dockerd
  sleep 2
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && return 0; sleep 1; done
  echo "::error::dockerd did not come back"; exit 1
}

# Pull leases hold content for hours, so a store can look safe only because of
# them. Delete them to force garbage collection to use the image records alone.
drop_leases() {
  local id
  for id in $(ctr_moby leases ls -q); do ctr_moby leases rm --sync "$id" || true; done
  sleep 3
}

login() { echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null; }

: >"$RESULTS"
docker info -f 'docker {{.ServerVersion}}, driver {{.Driver}}, {{.DriverStatus}}' | tee -a "$RESULTS"
echo "image: $IMAGE, socket: $SOCK" | tee -a "$RESULTS"
echo "--- control: the image is private" | tee -a "$RESULTS"
measure anonymous_pull_refused docker pull -q "$IMAGE"

echo "--- baseline" | tee -a "$RESULTS"
login
measure cold_pull docker pull "$IMAGE"
DIGEST=$(docker image inspect "$IMAGE" --format '{{.Id}}')
echo "digest: $DIGEST" | tee -a "$RESULTS"
measure warm_pull_name_kept docker pull "$IMAGE"

echo "--- rename as in D-07" | tee -a "$RESULTS"
INTERNAL="celesto-store/${DIGEST#sha256:}:keep"
docker tag "$IMAGE" "$INTERNAL"
docker rmi "$IMAGE"
docker image prune -f
restart_dockerd
drop_leases
docker logout ghcr.io
echo "store after rename, restart and lease removal: $(count_store)" | tee -a "$RESULTS"
docker images --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' | tee -a "$RESULTS"

echo "--- access with no login: rc must not be 0 for the three name forms" | tee -a "$RESULTS"
measure name_pull_no_login docker pull "$IMAGE"
measure name_run_no_login docker run --rm --entrypoint /bin/true "$IMAGE"
measure name_digest_run_no_login docker run --rm --entrypoint /bin/true "${IMAGE%:*}@$DIGEST"
echo "--- local forms with no login: these show what D-07 does not cover" | tee -a "$RESULTS"
measure bare_digest_run_no_login docker run --rm --entrypoint /bin/true "$DIGEST"
measure internal_run_no_login docker run --rm --entrypoint /bin/true "$INTERNAL"

echo "--- the real check: pull the original name with a login" | tee -a "$RESULTS"
login
measure warm_pull_after_rename docker pull "$IMAGE"
measure run_after_rename docker run --rm --entrypoint /bin/true "$IMAGE"

echo "--- negative control: remove every name, so the next pull must be cold" | tee -a "$RESULTS"
docker rmi "$IMAGE" "$INTERNAL"
docker image prune -af
restart_dockerd
drop_leases
echo "store after removing all names: $(count_store)" | tee -a "$RESULTS"
measure cold_pull_after_removal docker pull "$IMAGE"

echo "--- results"
cat "$RESULTS"
