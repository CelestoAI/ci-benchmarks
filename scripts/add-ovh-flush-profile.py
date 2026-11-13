"""Add an explicitly reported diagnostic fsync after normal upload/finalize."""

import hashlib
import json
import os
from pathlib import Path

out = Path("/dev/shm/cache-native-profile")
p = (
    Path(os.environ["RUNNER_WORKSPACE"]).parent
    / "_actions/actions/cache/55cc8345863c7cc4c66a329aec7e433d2d1c52a9/dist/save-only/index.js"
)
manifest = json.loads((out / "patch.json").read_text())
original = p.read_bytes()
assert hashlib.sha256(original).hexdigest() == manifest["profiled_sha256"]
before = 'yield profileCachePhase("cleanup", () => unlinkFile(archivePath))'
after = (
    'yield profileCachePhase("diagnostic_archive_flush", () => profileFlushFile(archivePath)); '
    + before
)
text = original.decode()
assert text.count(before) == 1
text = text.replace(before, after)
function = '\nfunction profileFlushFile(path) { const fd = profileFs.openSync(path, "r"); try { profileFs.fsyncSync(fd); } finally { profileFs.closeSync(fd); } }\n'
assert text.replace(after, before).encode() == original
patched = (text + function).encode()
p.write_bytes(patched)
manifest.update(
    pre_diagnostic_profile_sha256=manifest["profiled_sha256"],
    profiled_sha256=hashlib.sha256(patched).hexdigest(),
    diagnostic_fsync_after_finalize=True,
    reversible_timing_patch=False,
    reversible_profile_patch=True,
)
(out / "patch.json").write_text(json.dumps(manifest, indent=2) + "\n")
