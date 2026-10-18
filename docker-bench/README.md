# Docker CI benchmarks

Same workloads, fresh runners, **4 vCPU / 16 GiB RAM** on each provider.
This suite measures representative fixtures, not a customer's private application.

**Complete:** [120 successful authenticated jobs, numbers, and plot](../results/docker-2026-10-17/README.md).
Five repetitions per provider/scenario; all expected cache hits and saves passed
independent validation. Docker Hub authentication passed on both providers.
All final measurements come from this fresh matrix, not the pilots.
Earlier cache-quota, anonymous-pull-limit, and credential-setup failures are
retained as diagnostics; failed attempts are never counted as fast timings.

- [Original quota-limited run](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39073691950)
- [Continuation with registry-rate-limit failure](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39075713994)
- [Authentication attempt, before workload measurements](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39076674071)
- [Verified authentication on both providers](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39078014200)

## What runs

| Workload | What it checks |
| --- | --- |
| Node image | Locked npm install; TypeScript compilation and bundling of 800 generated modules; execute the resulting image |
| Python image | Hash-locked dependencies in a multi-stage image; import and execute the image |
| Layer caching | Cold seed, unchanged rebuild, source-only change, and dependency-lock change; warm builds run on new runners |
| CPU | Rust release build with pinned crates, four compiler workers, network disabled after a separately timed fetch; execute and assert output |
| Prospect-style stack | Python HTTP API + PostgreSQL + Azurite; migration, five rounds of 1,000 SQL inserts/aggregate checks and 1 MiB blob upload/download checks |
| Image caching | PostgreSQL and Azurite direct pulls versus Docker save + actions/cache + restore + Docker load; verify restored image IDs |

## Two cache comparisons, not one

- **Registry:** identical BuildKit `type=registry,mode=max` cache on GHCR for both providers. This is the shared-backend control.
- **Portable:** identical BuildKit `type=local,mode=max` layer export, transferred with `actions/cache`. GitHub jobs use GitHub's cache; Celesto jobs use Celesto's configured proxy. Restore/save boundaries include compression, transfer, and extraction overhead.

These are distinct from direct BuildKit **`type=gha,version=2`**. In the initial
pilot this direct path succeeded on GitHub but crashed BuildKit on Celesto in
two attempts. The daemon reported `OOMKilled=false`, exit code 2, and a
nil-pointer panic in `go-actions-cache` `uploadV2`, at a dereference of the
Azure response request ID. The image's cache proxy success response lacks that
header. This is a compatibility limitation, not a timing win or a cache miss.
No production fix or transparent cache substitution is part of this experiment.

The CPU preflight also found that Celesto rejects Docker's explicit `--cpus=4`
flag: runc could not open the nested cgroup's `cpu.max`. The benchmark therefore
uses the already-matched VM allocation on **both** providers, without per-container
CPU/memory flags, and asserts four CPUs inside the compiler container. This
does not certify Docker resource-limit support; workloads needing those flags
require separate compatibility work.

Evidence:

- [Initial protocol pilot](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39072808126)
- [Reproduction with daemon state and stack trace](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39073026017)
- [Upstream upload code at the pinned BuildKit version](https://github.com/moby/buildkit/blob/v0.26.2/vendor/github.com/tonistiigi/go-actions-cache/cache_v2.go#L74)

## Fairness controls

- GitHub `ubuntu-24.04` versus Celesto `celesto-large`; abort unless each exposes four CPUs and approximately 16 GiB nominal RAM.
- Docker Engine 29.1.3, Buildx 0.30.1, Compose 2.40.3, BuildKit 0.26.2, `docker-container` driver, host-networked builder, maximum four parallel BuildKit operations. Base/service/builder images are pinned in [images.json](images.json).
- GitHub's Docker Engine is normalized using `setup-docker-action`; Celesto's Engine is baked in. Setup and post-job cleanup are reported separately from workload numbers so normalization overhead does not become a provider advantage.
- Engine **semantic versions**, not distribution binaries, match: Celesto uses Ubuntu's 29.1.3 build (containerd 2.2.1 in preflight); GitHub uses the upstream 29.1.3 bundle (containerd v2.4.1 in preflight). Go builds/package patches, kernels, and supporting runtime packages can differ. Their full versions are in every job's raw logs; this is a matched-resource service comparison, not bit-identical host images.
- CPU model, kernel, OS, usable memory, free disk, image preexistence, runner identity, source revision, and cache endpoint hostname are recorded. Equal resource counts do not mean identical physical CPUs or storage.
- Provider-specific cache keys/refs. Each scenario consumes the unchanged seed on a fresh runner and exports to its own destination. No cross-provider cache reuse; no same-machine warm-cache shortcut.
- A warm source/unchanged build must prove the **dependency-install vertex** was cached. A dependency change must prove the install executes. A cache archive's presence alone is insufficient.
- Five repetitions in full mode; report every sample, median and observed range. Ranges are not confidence intervals. Pilot runs are not pooled into final results.
- At most two concrete jobs per paired experiment, with at most two paired experiments active (four concrete jobs total). Seed and warm scenarios stay together to reduce eviction risk. Provider ordering alternates for seed pairs; warm scenarios pair both providers in the same scheduling window. This is a controlled concurrent-runner comparison, not a claim of an otherwise idle physical host.
- Cache keys are cold, not the entire public registry/CDN: public registries may already hold shared blobs and have their own caches. Different network geography is part of the observed service performance, not pure CPU speed.
- No ARM/QEMU comparison, persistent runner disk advantage, production deployment, private customer code, or claimed universal speedup.

## Run it

The Celesto GitHub App must already be installed and linked to the repository.
The registry job needs `packages: write`; the workflow grants it only to this
benchmark. On `main`, `celesto.yml` is the Docker dispatcher. The matched CPU
comparison remains in `matched.yml`; the original individual Celesto CPU
workflow is preserved as `celesto-cpu.yml`. Nothing runs automatically on push.

Configure repository Actions secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
using a valid Docker Hub personal access token with **Repo Public Read-only**
permission. The same
login is required on both providers, including before the BuildKit image pull.
Never put a token in a workflow, command argument, commit, or benchmark log.
Celesto jobs consume Large-runner credit. Full mode needs roughly **4.5 GiB of
free cache headroom per provider**, in addition to any existing caches; check
your account's actual quota first. Use the smaller paired modes if headroom is
limited, and retain each seed until all its warm scenarios finish.
Also check Docker Hub's **live** pull allowance, not only whether login succeeds.
Both providers share the supplied account's quota. Full mode does not pace pulls
automatically; use it only with sufficient registry allowance. This experiment
dispatches paired cohorts only when a secret-safe HEAD probe reports enough
remaining allowance, and waits between cohorts when needed. Those waits are
outside workload timings and remain visible in the cohort manifest.

```sh
gh workflow run celesto.yml --repo CelestoAI/ci-benchmarks \
  --ref main \
  -f mode=pilot -f namespace=docker-pilot-yourname-001

# After the pilot passes, choose a NEW lowercase namespace:
gh workflow run celesto.yml --repo CelestoAI/ci-benchmarks \
  --ref main \
  -f mode=full -f namespace=docker-full-yourname-001

# To collect locally: Python 3.10+, Node 20+, and authenticated gh; no pip/npm install.
git clone --branch main \
  https://github.com/CelestoAI/ci-benchmarks.git
cd ci-benchmarks
# Once the full run completes:
python3 docker-bench/collect.py RUN_ID --output results/docker-DATE
node docker-bench/validate.mjs results/docker-DATE
node docker-bench/render.mjs results/docker-DATE
```

Full mode schedules 120 concrete jobs: 80 layer-cache builds, 10 uncached
baselines, 10 runtime/CPU jobs, and 20 image-cache seed/restore jobs. Each build
job builds both the Node and Python image. Use pilot mode first; don't mistake
these jobs for 120 independent CPU samples.

`runtime-pilot` runs one runtime pair; `image-pilot` runs one image-cache pair.
`continuation` runs five uncached/runtime repetitions without cache builds;
`image-full` runs five image-cache pairs. `native-probe` tests
the direct BuildKit GHA protocol and is expected to fail until compatibility
is repaired; it is not part of the repeated portable/registry comparison.
`auth-probe` verifies this repository's configured account directly and via
Docker CLI on both providers. `quota-probe` uses one GitHub job to inspect the
shared account's live allowance without pulling images. Its headers take
precedence over assumptions about the account's reset window. See Docker's
[HEAD-based quota-check documentation](https://docs.docker.com/docker-hub/usage/pulls/#view-pull-rate-and-limit).

### Storage headroom matters

The first full run filled Celesto's existing cache quota. Some saves emitted
warnings while their Actions jobs stayed green; later exact seed restores
failed. The collector audits cache-save warnings and excludes those jobs from
successful measurements. Missing/failed measurements are never zero.

After explicit approval, only task-owned Docker benchmark/pilot caches were
removed; quotas and unrelated caches were unchanged. The final report
uses **a complete new 120-job matrix with authenticated pulls on both
providers**, including all five registry and portable repetitions. No earlier
success or failure is pooled into those timings. The workload and fixtures are
byte-identical across these orchestration revisions (`combine.py` checks git).
The complete original quota-limited run is retained as diagnostic evidence.

For quota-controlled reproduction, use a fresh namespace and one pair at a time:

```sh
gh workflow run celesto.yml --repo CelestoAI/ci-benchmarks \
  --ref main \
  -f mode=portable-pair -f repetition=1 -f namespace=docker-clean-yourname-001
```

Repeat with repetitions 2–5. Ensure storage headroom before each pair; retain
the seed until its three warm cases finish. Only remove completed task-owned
caches with owner approval. Normal-operation results with this intervention
do **not** demonstrate retention or hit rates under storage pressure. Direct
BuildKit GHA compatibility and Docker CPU-limit flags remain separate caveats.

## How to read results

- `*-build`: build, image load, and in-BuildKit cache work, in wall seconds.
- BuildKit vertices: individual install/compile/cache-export observations.
  Vertices may overlap. Never add their reported durations to reconstruct a total.
- Portable workload total: measured suite wall time plus outer cache restore/save
  boundaries. Those phases are sequential; this total includes verification and context generation.
- Python CI total: image pulls, API image build/verification, stack startup,
  readiness, SQL/blob/API assertions, and cleanup. Excludes Rust/image-tar diagnostic work.
- Rust CPU: compilation only, with network disabled. Image pull and crate fetch
  are separate measurements; the fixture is a representative compile, not a production Rust service.
- Image-cache restore includes archive extraction; `docker load` is additional.
- Actions job duration includes tool setup and post-cleanup, but not time before
  GitHub assigns a runner. Provisioning/queue timestamps are not inferred from
  GitHub's job-start field.

Raw events/logs are uploaded even on failure, retained for 30 days, and collected
into the result directory for durable source evidence. Cache archives, built
images and dependency files remain disposable acceleration data, not customer
data. No automatic production deployments or customer messages are sent.

## Pilot corrections

The first service fixture failed on both providers because the Azure SDK could
not infer the account name from the Compose hostname `azurite`. This was
independently reproduced by constructing the client without a running service.
An explicit `AzureNamedKeyCredential` fixes that constructor; the integration
pilot must then pass real blob roundtrips before timings are accepted.
