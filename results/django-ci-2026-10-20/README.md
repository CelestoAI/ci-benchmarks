# Django's CI on GitHub and Celesto runners, October 19, 2026

**Django's own Linux lint, format and unit-test jobs, unchanged except for the runner.** Five measured runs per provider, each started by a real push. All 10 runs passed.

| Median of 5 runs | GitHub `ubuntu-latest` | Celesto `celesto-large` | Difference |
| --- | ---: | ---: | --- |
| **CI time** (first job starts → last job ends) | **5m 55s** | **4m 32s** | Celesto 23% less |
| Wait before jobs start (push → first job / last job starts) | 3s / 4s | 34s / 1m 09s | Celesto waits longer |
| Push → last job ends | 5m 58s | 5m 06s | Celesto 15% less |

**In this test:** once the jobs were running, Celesto finished Django's CI about 1m 20s sooner, almost all of it in the test suite (3m 51s against 5m 21s). Celesto's jobs then took 30 seconds to over a minute to start after the push, against 3–4 seconds on GitHub, which gives back about half of that lead. These are one project's jobs on one afternoon, not a prediction for every workload.

## What ran

The four Linux jobs from Django's CI at [`11af25c`](https://github.com/django/django/commit/11af25c0ae06c8275ebb8def8b8ca777a5660ed6) (django/django `main`, 19 October 2026), copied step for step from its `.github/workflows/linters.yml` and `tests.yml` into [`django-ci.yml`](../../.github/workflows/django-ci.yml):

| Job | What it runs |
| --- | --- |
| flake8 | Python 3.14, `pip install flake8`, `flake8` |
| isort | Python 3.14, `pip install isort`, `isort --check --diff django tests scripts` |
| black | `psf/black@stable` (`black --check --diff .`) |
| Ubuntu, SQLite, Python 3.14t | Free-threaded Python 3.14 with the pip cache, `pip install -r tests/requirements/py3-free-threading.txt -e .`, `python -Wall tests/runtests.py -v2`: 19,927 tests, 1,521 skipped, 7 expected failures |

This is the scope boxd used for its benchmark: the project's Linux lint, format, typecheck and unit-test jobs with one toolchain version. Django has no typecheck job. Left out: Windows, Playwright and screenshot (end-to-end), PostGIS (external service), docs, zizmor, biome and JavaScript tests.

The four jobs run in parallel, one machine each, as in Django's CI.

## Runners

| | GitHub | Celesto |
| --- | --- | --- |
| Label | `ubuntu-latest` | `[self-hosted, celesto-large]` |
| Size | 4 vCPU / 16 GB (GitHub's standard runner for public repositories) | 4 vCPU / 16 GiB |
| Workflow | [`django-ci-github.yml`](../../.github/workflows/django-ci-github.yml) | [`django-ci-celesto.yml`](../../.github/workflows/django-ci-celesto.yml) |

## How it was timed

Each run is a push to the `bench/django` branch that changes one trigger file, made by [`drive.py`](../../django-bench/drive.py). Runs went one at a time per provider, the two providers side by side, between 20:58 and 21:30 UTC on 19 October 2026, after one unmeasured warm-up run per provider that filled the pip cache.

All times are GitHub's own timestamps from the Actions API, not a local clock:

- **Push**: when GitHub created the workflow run.
- **Job start / end**: when a runner started and finished executing a job.
- **CI time** (the headline): first job start → last job end. It starts when the CI begins running the four jobs, so the wait for a runner before that is reported separately.

## Results

Median (min–max) over 5 runs.

| | GitHub `ubuntu-latest` | Celesto `celesto-large` |
| --- | ---: | ---: |
| Runs (green) | 5 (5) | 5 (5) |
| **CI time: first job start → last job end** | **5m 55s** (4m 18s–6m 05s) | **4m 32s** (4m 17s–4m 36s) |
| Wait: push → first job start | **3s** (3s–4s) | **34s** (30s–1m 10s) |
| Wait: push → last job start | **4s** (3s–4s) | **1m 09s** (56s–1m 24s) |
| Push → last job end | **5m 58s** (4m 21s–6m 08s) | **5m 06s** (4m 51s–5m 37s) |

Each job, start → end:

| | GitHub `ubuntu-latest` | Celesto `celesto-large` |
| --- | ---: | ---: |
| flake8 | **36s** (27s–38s) | **28s** (24s–30s) |
| isort | **14s** (11s–16s) | **19s** (19s–20s) |
| black | **45s** (38s–1m 02s) | **32s** (30s–35s) |
| Ubuntu, SQLite, Python 3.14t | **5m 55s** (4m 18s–6m 05s) | **4m 25s** (4m 04s–4m 36s) |

Test job, by step:

| | GitHub `ubuntu-latest` | Celesto `celesto-large` |
| --- | ---: | ---: |
| Checkout | **3s** (3s–4s) | **3s** (2s–4s) |
| Set up Python (with pip cache) | **10s** (9s–12s) | **11s** (8s–15s) |
| Upgrade pip and wheel | **1s** (1s–1s) | **0s** (0s–1s) |
| Install Django's requirements | **16s** (12s–16s) | **14s** (13s–15s) |
| Runner image fix steps (Celesto only) | **0s** (0s–0s) | **0s** (0s–1s) |
| Run the test suite | **5m 21s** (3m 45s–5m 29s) | **3m 51s** (3m 36s–4m 01s) |

## What the numbers say

1. **The test suite decides the result.** The three lint jobs take at most about a minute on both providers; the test job is the last to finish in every run. Setup (checkout, Python, install) takes about 30 seconds on both.
2. **Celesto ran the tests faster and more evenly.** 3m 51s median against 5m 21s, with a 25-second spread against GitHub's 1m 44s. This matches the [matched CPU benchmark](../2026-10-17-matched/README.md), where Celesto Large had about 17% more CPU throughput and a narrower range.
3. **Celesto jobs start late and one by one.** GitHub started all four jobs 3–4 seconds after every push. Celesto started the first job 30–70 seconds after the push and the last one 56–84 seconds after, in a different order each run. This wait is not in the CI time above but is in push → last job end, where Celesto's lead shrinks from 1m 23s to 52s.
4. **GitHub had one fast outlier.** Run 5's test suite took 3m 45s against 5m 18s–5m 29s in the other four, likely a faster host. The median is unaffected.

## Celesto runner image fixes

Django's workflow fails on Celesto's `github-ci` image as written. Two steps, added only on Celesto and timed separately (0–1 second in total), make it pass:

| Problem on the image | Effect on Django's workflow | Fix step |
| --- | --- | --- |
| No `lsb_release` | `actions/setup-python` with `cache: pip` fails | A shim that prints the OS name and version from `/etc/os-release` |
| Jobs run as root | Permission tests fail (a root process can write "read-only" files) | Run the test command as a normal user (`runuser`), with `/dev/shm` writable |
| No system time-zone data | Time-zone and date-formatting tests fail | Point glibc at the zoneinfo files of the `tzdata` wheel Django installs |

Together the last two failed 12 of Django's tests in an earlier run without the fixes.

The test step's command is `${{ env.RUN_AS }} python -Wall tests/runtests.py -v2`; `RUN_AS` is empty on GitHub. These belong in the runner image; until then, customers running Django's CI on Celesto would hit the same failures.

## Caveats

- **One project, one afternoon, five runs.** Runner hardware and load vary by host and time; see GitHub's outlier above.
- **Hardware is matched by size only.** Both had 4 vCPU and 16 GB; CPU models, disks and network were not recorded and differ.
- **GitHub's public-repository runner.** Private repositories get a 2 vCPU / 7 GB `ubuntu-latest`, which would be slower than the GitHub column here.
- **Warm caches on both.** One warm-up run filled the pip cache on each provider before measuring; a cold first run is not measured.
- **Not identical to Django's own run.** Django is checked out from `django/django` at a fixed commit instead of the triggering repository, and Celesto gets the fix steps above.
- **Cost was not compared.**
- **Not a boxd comparison.** boxd's 6× figure comes from starting jobs on machines restored from a snapshot of main's last green run. Celesto CI runners always start from the same image, so that approach was not tested here. An earlier exploratory attempt at it is kept in [`../django-2026-10-20/`](../django-2026-10-20/README.md) with its flaws stated.

## Reproduce

From a checkout of this repository on the `bench/django` branch, with push access and the [Celesto CI App](https://github.com/apps/celesto-ci) installed:

```sh
python3 django-bench/drive.py results/my-run/warmup.jsonl ci-github:none ci-celesto:none
python3 django-bench/drive.py results/my-run/runs.jsonl ci-github:none ci-github:none ci-github:none ci-github:none ci-github:none
python3 django-bench/drive.py results/my-run/runs.jsonl ci-celesto:none ci-celesto:none ci-celesto:none ci-celesto:none ci-celesto:none
python3 django-bench/summarize-ci.py results/my-run
```

## Raw data

- [`runs.jsonl`](runs.jsonl): the 10 measured runs, with run URLs and every job's and step's timestamps.
- [`warmup.jsonl`](warmup.jsonl): the two unmeasured warm-up runs.
