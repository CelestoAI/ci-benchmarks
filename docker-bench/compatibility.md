# Docker compatibility findings

Docker builds and Compose integration tests can pass while particular flags or
cache protocols still fail. These findings apply to the pinned October 17
environment; they are not claims about every Docker workload or future version.

## Direct BuildKit GHA cache export: failed on Celesto

Docker 29.1.3, Buildx 0.30.1, BuildKit 0.26.2; `type=gha,version=2`.

- [Initial pilot](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39072808126): Celesto failed; GitHub passed.
- [Independent reproduction](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39073026017): same outcome.
- BuildKit container state: `ExitCode: 2`, `OOMKilled: false`.
- Stack: `panic: runtime error: invalid memory address or nil pointer dereference`,
  in `go-actions-cache.(*Cache).uploadV2`, `cache_v2.go:74`.

The [pinned upstream code](https://github.com/moby/buildkit/blob/v0.26.2/vendor/github.com/tonistiigi/go-actions-cache/cache_v2.go#L74)
dereferences the response request-ID pointer. Source inspection found that the
baked Celesto cache proxy's successful upload response omitted `x-ms-request-id`.
This is consistent with the panic; no production fix or verified fix rollout is
part of this benchmark. Shared-registry and portable-local-cache results test
different paths and do not establish that native GHA caching works.

## Explicit container CPU limit: failed on Celesto

[Resource-limit preflight](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39073489613):
the same `docker run --cpus=4` command passed on GitHub and failed on Celesto:

```text
error setting cgroup config ... openat2 /sys/fs/cgroup/docker/.../cpu.max:
no such file or directory
```

The repeated benchmark removes explicit CPU/memory flags on **both** providers,
uses each VM's four-CPU / 16-GiB allocation, asserts four visible CPUs in the
compiler container, and runs offline compilation with four Cargo workers.
It does not certify support for Docker CPU/memory-limit flags.

## What this means for the prospect

The repeated Python/Postgres/Azurite tests exercise real SQL and blob roundtrips
through a Compose stack, not only `docker version`. They are representative,
not the customer's actual application. Native GitHub `services:` support has a
separate [functional smoke run](https://github.com/CelestoAI/ci-benchmarks/actions/runs/39071944026);
its success is not a measured five-repeat performance comparison.

Share these boundaries alongside the numbers. Do not promise drop-in support
for workflows relying on the failing cache path or resource-limit flags.
