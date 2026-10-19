#!/usr/bin/env bash
# Times each piece of an actions/cache round trip in isolation, on the same
# random payload the cache benchmark uses, so a slow restore or save can be
# blamed on disk, CPU, or network instead of guessed.
#
# Runs after the cache steps so it cannot disturb their timings. Every probe
# writes one `probe` event (seconds, exit code, notes) through record-event.mjs;
# a failed probe is recorded, never turned into a fast timing.
#
# Env: BENCHMARK_CACHE_DIR (payload source), PROBE_URL (optional object for the
# network probes), PROBE_RANGES (parallel range requests, default 8).
set -uo pipefail

CACHE_DIR="${BENCHMARK_CACHE_DIR:-.benchmark-cache}"
PAYLOAD="$CACHE_DIR/payload.bin"
WORK="$RUNNER_TEMP/step-probes"
RANGES="${PROBE_RANGES:-8}"
rm -rf "$WORK" && mkdir -p "$WORK"

record() { node scripts/record-event.mjs "$1" "$2"; }

# Drops the page cache so a read measures the disk, not memory. Recorded per
# probe because a runner without passwordless sudo cannot do it.
drop_caches() {
  sync
  if sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; then echo true; else echo false; fi
}

# timed <name> <cache_dropped> <command...>: run once, record wall seconds.
timed() {
  local name="$1" dropped="$2"; shift 2
  local start end code
  start=$(date +%s%N)
  "$@" >"$WORK/$name.log" 2>&1
  code=$?
  end=$(date +%s%N)
  local seconds
  seconds=$(awk -v s="$start" -v e="$end" 'BEGIN { printf "%.4f", (e - s) / 1e9 }')
  record probe "{\"probe\":\"$name\",\"seconds\":$seconds,\"exit_code\":$code,\"page_cache_dropped\":$dropped}"
  if [ "$code" -ne 0 ]; then tail -5 "$WORK/$name.log"; fi
}

if [ ! -f "$PAYLOAD" ]; then
  record probe_skipped '{"reason":"payload missing"}'
  exit 0
fi
BYTES=$(stat -c %s "$PAYLOAD")

# --- Where the job ran -------------------------------------------------------
# Celesto starts its cache proxy with --host-provider (aws, ovh, ...); GitHub
# runners have no proxy, so the field stays empty there.
host_provider=$(pgrep -af celesto-ci-cache-proxy | grep -o -- '--host-provider [a-z0-9-]*' | awk '{print $2}' | head -1)
workspace_fs=$(df -T "$GITHUB_WORKSPACE" | awk 'NR==2 {print $1" "$2}')
temp_fs=$(df -T "$RUNNER_TEMP" | awk 'NR==2 {print $1" "$2}')
disk_model=$(lsblk -dno NAME,MODEL,ROTA 2>/dev/null | tr '\n' ';' | tr -s ' ')
azure_location=$(curl -s -m 2 -H Metadata:true 'http://169.254.169.254/metadata/instance/compute/location?api-version=2021-02-01&format=text' 2>/dev/null || true)
record probe_host "{\"host_provider\":\"${host_provider}\",\"workspace_fs\":\"${workspace_fs}\",\"temp_fs\":\"${temp_fs}\",\"disks\":\"${disk_model}\",\"azure_location\":\"${azure_location}\",\"payload_bytes\":${BYTES},\"zstd\":\"$(zstd --version 2>&1 | head -1)\",\"tar\":\"$(tar --version | head -1)\"}"

# --- Disk alone ----------------------------------------------------------------
# Copy the payload through the page cache, then force it to disk: the same
# write path tar uses when it extracts a restored archive.
cat "$PAYLOAD" >/dev/null
timed disk_write_fsync false dd if="$PAYLOAD" of="$WORK/disk.bin" bs=4M conv=fsync status=none
timed disk_read_cold "$(drop_caches)" dd if="$WORK/disk.bin" of=/dev/null bs=4M status=none
rm -f "$WORK/disk.bin"

# --- CPU alone (zstd in memory, no disk) ---------------------------------------
# Payload warmed into memory and output to /dev/null, so only compression runs.
cat "$PAYLOAD" >/dev/null
timed zstd_compress_mem false sh -c "zstdmt -c '$PAYLOAD' > /dev/null"
zstdmt -q -c "$PAYLOAD" > "$WORK/payload.zst"
cat "$WORK/payload.zst" >/dev/null
timed zstd_decompress_mem false sh -c "unzstd -c '$WORK/payload.zst' > /dev/null"
rm -f "$WORK/payload.zst"

# --- actions/cache's own tar commands, against local disk ----------------------
# Exactly the command lines actions/cache@v4 logs, so these match the
# "compress" and "extract" phases of the real steps minus any network.
mkdir -p "$WORK/archive" "$WORK/extract"
printf '%s\n' "$(realpath "$CACHE_DIR")" > "$WORK/archive/manifest.txt"
cat "$PAYLOAD" >/dev/null
timed tar_create_warm false tar --posix -cf "$WORK/archive/cache.tzst" --exclude cache.tzst -P -C "$GITHUB_WORKSPACE" --files-from "$WORK/archive/manifest.txt" --use-compress-program zstdmt
sync
timed tar_extract_cold "$(drop_caches)" tar -xf "$WORK/archive/cache.tzst" -P -C "$WORK/extract" --use-compress-program unzstd
timed tar_extract_sync false sync
rm -rf "$WORK/archive" "$WORK/extract"

# --- Network to the Celesto cache bucket ---------------------------------------
# Both providers download one fixed object from the same store, once as a
# single stream and once as parallel ranges, discarding the bytes.
if [ -n "${PROBE_URL:-}" ]; then
  # A one-byte GET, not HEAD: a presigned GET link refuses other methods.
  size=$(curl -sfL -m 20 -r 0-0 -D - -o /dev/null "$PROBE_URL" | awk 'tolower($1)=="content-range:" {split($3, a, "/"); print a[2]}' | tr -d '\r' | tail -1)
  if [ -n "$size" ]; then
    timed net_single_stream false curl -sf -m 120 -o /dev/null "$PROBE_URL"
    chunk=$(( (size + RANGES - 1) / RANGES ))
    ranged() {
      local i pids=() code=0
      for ((i = 0; i < RANGES; i++)); do
        local from=$(( i * chunk )) to=$(( (i + 1) * chunk - 1 ))
        [ "$to" -ge "$size" ] && to=$(( size - 1 ))
        curl -sf -m 120 -r "$from-$to" -o /dev/null "$PROBE_URL" & pids+=($!)
      done
      for pid in "${pids[@]}"; do wait "$pid" || code=1; done
      return $code
    }
    timed net_ranged false ranged
    record probe_net "{\"bytes\":$size,\"ranges\":$RANGES,\"host\":\"$(echo "$PROBE_URL" | awk -F/ '{print $3}')\"}"
  else
    record probe_skipped '{"reason":"probe url not reachable"}'
  fi
fi

# --- Celesto cache proxy log ---------------------------------------------------
# Kept for per-request detail; signed-link query strings are stripped.
if [ -f /tmp/celesto-ci-cache-proxy.log ]; then
  sed -E 's/\?[^ "]*//g' /tmp/celesto-ci-cache-proxy.log > celesto-ci-cache-proxy.log
fi
exit 0
