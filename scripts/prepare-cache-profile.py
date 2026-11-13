"""Add timing only to a checksum-pinned actions/cache save bundle."""
import hashlib
import json
from pathlib import Path
import sys

source, destination, manifest = map(Path, sys.argv[1:])
original = source.read_bytes()
expected = "0d3cf341a79cdc0a8ce5a71103f46174e12cf4f98db46f15b8e604932eefd487"
assert hashlib.sha256(original).hexdigest() == expected, "Unexpected stock bundle"
text = original.decode()
changes = []


def replace_once(before, after):
    global text
    assert text.count(before) == 1, f"Patch anchor is not unique: {before}"
    text = text.replace(before, after)
    changes.append((before, after))


# Limit the phase wrappers to saveCacheV2. Leave restore and v1 untouched.
prefix, body = text.split("function saveCacheV2(", 1)
body, suffix = body.split("//# sourceMappingURL=cache.js.map", 1)
for phase, expression in [
    ("detect_compression", "getCompressionMethod()"),
    ("resolve_paths", "resolvePaths(paths)"),
    ("create_temp_dir", "createTempDirectory()"),
    ("archive", "createTar(archiveFolder, cachePaths, compressionMethod)"),
    ("reserve", "twirpClient.CreateCacheEntry(request)"),
    ("upload", "saveCache(cacheId, archivePath, signedUploadUrl, options)"),
    ("finalize", "twirpClient.FinalizeCacheEntryUpload(finalizeRequest)"),
    ("cleanup", "unlinkFile(archivePath)"),
]:
    before = "yield " + expression
    after = f'yield profileCachePhase("{phase}", () => {expression})'
    assert body.count(before) == 1, f"Missing or repeated phase: {phase}"
    body = body.replace(before, after)
    changes.append((before, after))
text = prefix + "function saveCacheV2(" + body + "//# sourceMappingURL=cache.js.map" + suffix

# GNU time observes CPU and disk I/O for tar and its zstd child together.
replace_once(
    "yield execCommands(commands, archiveFolder);",
    'yield execCommands(commands.map(command => "/usr/bin/time -v -o " + '
    'JSON.stringify(process.env.CACHE_PROFILE_ARCHIVE_RESOURCES) + " " + command), archiveFolder);',
)
replace_once(
    "const cacheId = await saveImpl(new NullStateProvider());",
    'const cacheId = await profileCachePhase("save_total", () => saveImpl(new NullStateProvider()));',
)

# Prove that undoing the instrumentation restores every byte of the stock bundle.
restored = text
for before, after in reversed(changes):
    assert restored.count(after) == 1
    restored = restored.replace(after, before)
assert restored.encode() == original, "Instrumentation changed non-timing code"
runtime = Path(__file__).with_name("cache-profile-runtime.mjs").read_text()
patched = (runtime + "\n" + text).encode()
destination.write_bytes(patched)
manifest.write_text(json.dumps({
    "action_commit": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "stock_sha256": expected,
    "profiled_sha256": hashlib.sha256(patched).hexdigest(),
    "reversible_timing_patch": True,
    "upload_chunk_mib": 64,
    "upload_concurrency": 8,
    "patches": len(changes),
}, indent=2) + "\n")
