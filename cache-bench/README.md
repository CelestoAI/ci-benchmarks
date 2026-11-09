# Cache benchmark: GitHub Actions vs Celesto CI

Times the three caches Celesto CI serves, against GitHub's own cache, on matched
4 vCPU / 16 GiB runners (`ubuntu-24.04` vs `celesto-large`).

| Cache | Workload | GitHub side | Celesto side |
| --- | --- | --- | --- |
| Dependency | `npm ci` of a web-app tree (Next, AWS SDK, Jest, ESLint, webpack; [`deps/`](deps)) | `actions/cache` on `~/.npm` | same workflow, served by Celesto's cache |
| Docker layers | [`docker/Dockerfile`](docker/Dockerfile): `npm ci` layer + `tsc` compile layer | `build-push-action`, `type=gha,mode=max` | same workflow, served by Celesto's cache |
| Turborepo | 8-package TypeScript monorepo, 3,200 files ([`turbo/gen.mjs`](turbo/gen.mjs)) | `actions/cache` on `.turbo/cache` (GitHub has no Turbo remote cache; this is Turborepo's documented pattern) | no cache step: Celesto's transparent Turbo remote cache |

Each cache runs 3 samples per provider. **Cold** jobs start empty, do the work and
save. **Warm** jobs run later on fresh runners and restore what cold saved. Every
sample uses its own key, and the Turbo hash includes it (`BENCH_NAMESPACE`), so no
sample reads another's cache.

## Run

Each cache has its own workflow, run separately:

| Workflow | File | Push to run with defaults |
| --- | --- | --- |
| Cache benchmark - Dependency cache | `cache-bench-dependency.yml` | `cache-bench/dependency/<name>` |
| Cache benchmark - Docker layer cache | `cache-bench-docker.yml` | `cache-bench/docker/<name>` |
| Cache benchmark - Turborepo cache | `cache-bench-turbo.yml` | `cache-bench/turbo/<name>` |

Actions → pick one → Run workflow with a new `namespace` (or push a branch
from the table). Each run is 12 jobs: 3 samples × 2 providers × cold/warm. Then:

```sh
node cache-bench/collect.mjs <run-id> [more run ids]   # Markdown table of medians
```

Reported per cache × phase × provider: restore, work (`npm ci` / build + cache
export / `turbo run build`), save, and their total. Docker restore and save happen
inside the build, so only its total is meaningful.
