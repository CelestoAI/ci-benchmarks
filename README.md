# Celesto CI vs. GitHub Actions benchmark

A public, repeatable benchmark for comparing **CPU throughput** and **cache archive performance** across Celesto CI and GitHub-hosted Actions.

It follows the approach in [Celesto's dependency-cache benchmark](https://celesto.ai/blog/posts/celesto-ci-dependency-cache/): measure a cold save and a warm restore separately, capture the cache-hit outcome, and disclose the runner configuration alongside elapsed time.

## Workflows

| Workflow | Runner |
| --- | --- |
| **Benchmark on GitHub-hosted Actions** | `ubuntu-latest` |
| **Benchmark on Celesto CI** | `[self-hosted, celesto-micro]` |

Both workflows call the same shared harness in `.github/workflows/benchmark.yml`. Only the runner labels differ.

## What is measured

- **Single-core CPU throughput**: deterministic integer work in one worker, the best per-vCPU signal.
- **All-core CPU throughput**: the same workload across all processors reported by Node's `os.availableParallelism()`; this measures allocated capacity, not per-core performance alone.
- **Cache restore boundary**: wall time immediately before `actions/cache/restore@v4` through the following workflow step.
- **Cache save boundary**: wall time surrounding `actions/cache/save@v4` on a cache miss.
- **Cache payload generation**: a configurable high-entropy archive generated only on a miss, kept outside the cache-save boundary.

The payload contains random bytes so it does not create misleadingly high compression ratios. Supported workflow inputs are **256, 512, 1024, and 2304 MiB**. The 2304 MiB option mirrors the browser-tool cache shape in the referenced post.

## Run a paired comparison

1. Install the [Celesto CI GitHub App](https://github.com/apps/celesto-ci), enable this repository, and connect it to a Celesto workspace with credit.
2. Choose a fresh `cache_namespace` (for example `2026-10-17-a`), a payload size, and CPU iterations. Keep these identical for the pair.
3. Run the GitHub-hosted workflow once and the Celesto workflow once. Those are the two **cold** runs because the providers use separate cache stores.
4. Re-run both workflows without changing inputs. Those are the **warm** runs.
5. Download the `*-benchmark-*` artifact from each run. It contains `benchmark-events.jsonl` and `benchmark-summary.md`.

For more reliable results, use at least three fresh namespaces and alternate which provider runs first. Compare cold with cold and warm with warm. Cache transport, host generation, CPU allocation, image revision, and network location can all affect the result, so do not describe the outcome as a cache-service-only comparison.

## Local use

The harness uses Node 20+ and has no runtime dependencies:

```sh
BENCHMARK_CACHE_MIB=16 node scripts/seed-cache.mjs
BENCHMARK_CPU_ITERATIONS=1000000 node scripts/cpu-benchmark.mjs
```

