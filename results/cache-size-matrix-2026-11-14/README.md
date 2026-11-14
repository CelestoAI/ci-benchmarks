# Cache size matrix: 20 MiB to 4 GiB

[Benchmark run](https://github.com/CelestoAI/ci-benchmarks/actions/runs/43530675306) · [Workflow](../../.github/workflows/cache-size-matrix.yml) · [Methodology](../../docs/cache-size-matrix.md)

**30/30 save/restore roundtrips passed.** Each of ten payload sizes ran three times sequentially on Celesto Large (4 vCPU, at least 14 GiB usable RAM). Every restore was an exact-key hit and matched the original file size and SHA-256.

## Results

All times are seconds. Medians use three successful repetitions. Ranges show the fastest and slowest repetition. Roundtrip is the median of each repetition’s save plus restore; generation, hashing, verification, queueing and artifact upload are excluded.

| Payload | Save median (range) | Restore median (range) | Roundtrip median |
| --- | ---: | ---: | ---: |
| 20 MiB | 3 (3–3) | 1 (1–2) | 4 |
| 24 MiB | 3 (2–4) | 1 (1–2) | 4 |
| 32 MiB | 3 (3–4) | 1 (1–1) | 4 |
| 64 MiB | 5 (4–6) | 1 (1–2) | 6 |
| 96 MiB | 6 (5–7) | 2 (1–2) | 8 |
| 400 MiB | 6 (6–9) | 4 (3–4) | 10 |
| 1 GiB | 8 (8–8) | 7 (6–8) | 15 |
| 2 GiB | 13 (12–17) | 17 (14–25) | 34 |
| 3 GiB | 15 (12–21) | 21 (15–28) | 42 |
| 4 GiB | 22 (22–26) | 41 (29–42) | 64 |

## Scope and evidence

- Measurements use the deployed runner image and the same pinned `actions/cache` v6.1.0 as the original 4 GiB suite. This run does not install or qualify the adaptive upload patch in [backend PR #1284](https://github.com/CelestoAI/backend/pull/1284).
- Sizes are random payload bytes, not exact compressed archive bytes. Tar/zstd overhead can cross an archive cutoff, including the PR’s 24 MiB boundary.
- GitHub step timings have one-second resolution and include action startup, compression/extraction and transfer. They are not transfer-stage-only timings.
- Jobs were serialized within this workflow. Other workflows and host load can still influence timings. Three repetitions describe this batch, not fleet-wide latency.
- Queue timings in the raw results include intentional matrix serialization; they do not measure provider provisioning latency.
- [results.json](results.json) preserves the collector’s raw phase timings and job status. [jobs.json](jobs.json) preserves the source GitHub Jobs API response; its step timestamps were checked against the collector. [summary.json](summary.json) contains every repetition, original/restored SHA-256 hashes, cache keys, payload bytes and host fingerprints, plus the statistics above.
- Original integrity artifacts and the collector artifact are attached to the benchmark run with 14-day retention. The JSON files here preserve their measurements and integrity evidence beyond that retention period.
- This sweep is separate from the published 4 GiB comparison.

## Validation

- Workflow lint: `actionlint` v1.7.12 passed (custom `celesto-large` label allowed).
- Existing repository checks: `npm test`, 4 passed, 0 skipped.
- Evidence audit: all 30 expected size/repetition pairs, exact cache hits, payload byte counts, original/restored SHA-256 matches, successful timed phases, and four-CPU host fingerprints passed.
