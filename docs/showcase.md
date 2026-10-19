# Offline Capability Showcase

This showcase runs the actual review harness against real Git snapshots and the official Anthropic SDK, using **authored synthetic responses in an in-memory HTTP transport**. It demonstrates application behavior: related-code tools, grounded citations, inline placement, gates, in-memory publication and cached result reuse. It does not perform live model inference or measure detection accuracy.

No credentials are required. Every SDK HTTP request terminates inside `httpx2.MockTransport`; a local GitHub adapter stores reviews in memory. The script does not contact GitHub, call a provider, publish a review or execute the example code.

## Run All Scenarios

After installing the locked dependencies from the [Quick Start](../README.md#quick-start), run from the project root:

```sh
.venv/bin/python scripts/showcase.py --output outputs/showcase/report.json --summary outputs/showcase/summary.md
```

The script creates disposable Git repositories, generates nonempty changes, runs the harness, verifies publication through the local adapter, and performs an identical cache-only rerun. Temporary repositories are removed after the run. JSON and Markdown reports remain in the selected output paths. Existing `CLAUDE_*` variables are restored afterward; the demonstration uses the documented default model and a high-severity threshold for consistent results.

Expected standalone results:

| Scenario | Change | Gate | Coverage | Findings | Inline Comments |
| --- | --- | --- | --- | ---: | ---: |
| Broken Python Response Contract | Producer changes `total` to `amount`; unchanged caller still reads `total` | failure | complete | 1 high | 1 |
| Clean Nonempty Python Refactor | Producer introduces a local variable while preserving `total` | success | complete | 0 | 0 |
| Broken JavaScript Response Contract | Producer changes `total` to `amount`; unchanged caller invokes `toFixed` on `total` | failure | complete | 1 high | 1 |

Each initial scenario makes **3 simulated generation requests and 3 simulated token-count requests**, producing one in-memory review. The model-shaped first response requests a literal search and an unchanged-caller read. The real context reader executes these tools over immutable Git objects. The authored final response cites the resulting source identifier, blob and line range; the application validates that evidence before accepting the review.

For each scenario, the cache-only rerun returns the exact original result and makes **0 new generation requests, 0 new token-count requests and 0 new review writes**. The passing Python example contains a real code diff; it does not rely on the zero-diff fast path.

## Inspect the Evidence

The JSON report includes snapshots, input identity, actual coverage, findings and references, serialized SDK request bodies, the generated review payload and cache-rerun counters. Broken cases attach an inline comment to the producer's changed second line and cite the unchanged caller at its immutable head commit.

All rows carry `simulation: true` and `response_origin: authored-sdk-mock-transport`. The underlying runtime sets `live: true` when it executes an SDK call; the report exposes this as `runtime_live_flag`. Here that flag identifies the mocked SDK path, **not external inference**. Token usage is synthetic, and `paid_provider_calls` and `real_network_requests` are both zero. The review payload is stored locally and never sent to GitHub.

The [showcase tests](../tests/test-showcase.py) also alter a citation's blob to verify rejection before any local review write, check that source discovery actually brings an unchanged caller into final context, and ensure repository mode preserves existing working files.

## Use Existing Immutable Commits

To demonstrate a prepared example PR, pass a repository path and full immutable base/head commit SHAs:

```sh
.venv/bin/python scripts/showcase.py --scenario broken --repository-path . --repository-name OWNER/REPOSITORY --base FULL_BASE_COMMIT_SHA --head FULL_HEAD_COMMIT_SHA --output outputs/showcase/pr-report.json --summary outputs/showcase/pr-summary.md
```

Choose `broken`, `fixed` or `js`. Optional `--repository-name` supplies the owner/repository in generated source links; it does not create a remote connection. The script checks the exact example-file contents in both commits against its [authored scenarios](../scripts/showcase.py) before constructing an answer. The base must already contain the example producer and caller. The head changes the producer while leaving its caller unchanged; an unrelated PR cannot receive the prewritten finding. Extra repository content can introduce genuine reader limitations, so repository-mode coverage may be partial and is reported as observed.

The command reads Git objects and does not check out branches, alter commits or run candidate code. It uses the same local GitHub adapter and mocked provider transport as standalone mode. It neither activates the paid review workflow nor supplies evidence of live model quality. Broader synthetic-corpus comparisons remain separate in the [evaluation guide](evaluation.md).

## Guardrails Beyond the Three Examples

| Capability | Deterministic Evidence |
| --- | --- |
| Model, prices, depth and failing severity | [configuration integration tests](../tests/test-runtime-config.py) and `show-config` |
| Secret/path rejection before provider requests | [security regressions](../tests/test-security.py) |
| Invalid citations rejected before any review write | [showcase regressions](../tests/test-showcase.py) |
| Deadline, subprocess cleanup and three-retry bound | [runtime tests](../tests/test-runtime.py) and [review tests](../tests/test-review.py) |
| Stale snapshots and uncertain publication without duplicate POST | [service tests](../tests/test-service.py) |
| Partial coverage and independent severity outcome | [review contracts](../tests/test-review.py) |
| Trusted workflow and separated permissions | [workflow checks](../tests/test-workflow.py) plus operator-managed environment/branch policies |

Verify runs these checks on Python 3.10 and 3.12, then uploads a seven-day `offline-showcase-python-*` artifact and a summary. On the named showcase branches, it analyzes those actual immutable PR commits using the authored transport. A successful Verify job means the expected behavior was reproduced; it is separate from the paid **Claude review gate**.
