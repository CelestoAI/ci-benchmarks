# Cache benchmark: GitHub Actions vs Celesto CI

Times the three caches Celesto CI serves against GitHub's own cache, on real
open-source projects, on matched 4 vCPU / 16 GiB runners (`ubuntu-24.04` vs
`celesto-large`). Each job checks the project out at a pinned commit; nothing
from it is copied into this repository.

| Cache | Project (pinned commit) | Timed work | GitHub side | Celesto side |
| --- | --- | --- | --- | --- |
| Dependency | [excalidraw/excalidraw](https://github.com/excalidraw/excalidraw) `701b901` | `yarn install --frozen-lockfile` (yarn 1 workspace) | `actions/cache` on the yarn cache | same workflow, served by Celesto's cache |
| Docker layers | [plausible/analytics](https://github.com/plausible/analytics) `1264998` | its `Dockerfile` (Elixir deps, npm assets, release) | `build-push-action`, `type=gha,mode=max`, as in Plausible's own image workflow | same workflow, served by Celesto's cache |
| Turborepo | [formbricks/formbricks](https://github.com/formbricks/formbricks) `94ae970` | `pnpm build --filter=@formbricks/web^...`, the command and placeholder env from Formbricks' own CI | `actions/cache` on `.turbo/cache` (GitHub has no Turbo remote cache; this is Turborepo's documented pattern) | no cache step: Celesto's transparent Turbo remote cache |

Each workflow runs 3 samples per provider. **Cold** jobs start empty, do the
work and save. **Warm** jobs run later on fresh runners and restore what cold
saved. Every sample uses its own cache key. For Turbo, the job adds
`BENCH_NAMESPACE` to the project's `turbo.json` `globalEnv`, so each sample gets
its own hashes (Celesto's Turbo cache is shared per repository).

## Run

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

Reported per phase and provider: restore, work, save, and their total. Docker
restore and save happen inside the build, so only its total is meaningful. The
Formbricks install is not timed. To move to newer project commits, change the
`ref:` values in `.github/workflows/cache-bench-job.yml`.
