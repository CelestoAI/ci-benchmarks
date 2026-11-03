# GHCR private image cold pull split (2026-11-03)

Raw records from `.github/workflows/ghcr-pull-split.yml` on branch
`test/ghcr-pull-split`, one JSON object per line, as written by
`scripts/ghcr_pull_split.py`. Files are named `<run id>-<job>.jsonl`:

- run 41711370257: stock image, Small and Large;
- run 41712915379: stock image again, and `measure-igzip` jobs with `isal`
  (igzip) and `pigz` installed and dockerd restarted.

`*-mirror-proxy.jsonl` is the logging mirror's request log from the
`mirror-auth` step (method, path, whether `Authorization` was present, status).

Summary and conclusions: `docs/designs/ci-image-pull-cache.md` in
CelestoAI/backend.
