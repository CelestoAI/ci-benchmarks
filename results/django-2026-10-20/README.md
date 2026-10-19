# Exploratory: boxd-style Django runs, October 19, 2026 (superseded)

**Not a result.** This folder keeps the raw data of a first attempt to reproduce boxd's CI benchmark for Django. It has the flaws below and was replaced by [`../django-ci-2026-10-20/`](../django-ci-2026-10-20/README.md), which runs Django's own CI jobs on GitHub and Celesto runners.

What was tried: Django's lint and test work as one job, as one checks job plus 8 test shards, and on 9 long-lived Celesto computers that were set up once and reused ("warm"), with GitHub jobs held to 2 cores by `taskset`.

Why it is not a valid comparison:

- **The warm setup is not boxd's.** boxd creates new machines from a snapshot on every push. These 9 computers were created once and kept running; machine creation was never measured. Celesto Cloud has no API to start computers from a snapshot.
- **The warm runs were not timed from a push.** Each computer timed its own job with its own clock after a command was sent to it, so event handling and dispatch are missing and the start was not checked to be simultaneous.
- **Celesto runner runs failed.** In [`celesto-red/runs.jsonl`](celesto-red/runs.jsonl), 12 Django tests fail on Celesto's runner image (root user, no time-zone data); the later benchmark adds fix steps for these.
- **Few samples, high variance.** One to three runs per cell; the dependency-change variant added one small package and is a weak test.
- **Not Django's own jobs.** Lint ran as one job, regular Python 3.14 instead of 3.14t, and GitHub's 4 vCPU runner was pinned to 2 cores rather than matched.

Files: `runs.jsonl` (GitHub one-job and sharded runs), `celesto-red/runs.jsonl` (Celesto runner runs that failed), `warm.jsonl` (per-computer timings of the reused computers), `warmup.jsonl` (unmeasured warm-ups).
