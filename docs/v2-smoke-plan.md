# Bounded private v2 end-to-end smoke

## Authorization and prerequisites

October 10, 2026: Julia requested closing v1 demo PRs and running two or three real end-to-end examples for v2. This authorizes the bounded private smoke, new demo branches/PRs, workflow activation for that smoke and provider calls within the existing $5 planning ceiling. The selected package reserves $0.60 for three review envelopes plus $0.20 for the cache verification run; the maximum planned reservation is $0.80, with no automatic retries or full held-out evaluation.

Old PRs 1 and 2 were closed without merge. Their branches and reviews are preserved. GitHub remains private; no branch-protection, visibility or subscription change is included.

The workflow executes trusted base-commit scripts. Main currently holds v1 at `a89a22a39372f1cfc8f40448fa572be63fd7862e`. Release PR `codex/v2-release` contains the locally verified v2 implementation plus neutral standalone fixture producers/consumers. A separate explicit release merge approval is required before installing that trusted base. Keep the paid workflow disabled during release checks.

## Cases and independent oracles

| Snapshot | Change | Maintainer oracle | Review expectation |
| --- | --- | --- | --- |
| Python defect | Producer changes output key `total` to `amount`; consumer unchanged | Calling consumer raises KeyError | Cross-file finding supported by unchanged consumer and changed producer; high severity fails gate |
| Python corrected | Restore `total` with a harmless local calculation refactor, retaining a nonempty PR diff | Consumer returns `Invoice total: $108.00` for 100/8 | No remaining introduced defect; valid clean/partial review succeeds |
| JavaScript clean | Equivalent local-variable refactor preserving producer contract and consumer | Consumer still returns `Invoice total: $108.00` for 100/8 | No unsupported high/critical finding |

Fixtures live under `examples/context-smoke/`, separate from held-out evaluation cases. The maintainer executes their tiny deterministic oracles separately; Claude tools never execute PR code. Normal Verify remains unchanged. Baseline Python and JavaScript oracles and all 100 local tests pass before release.

## Execution and evidence

Root owns one serial shared ledger. Reserve an entire $0.20 envelope before each eligible PR event; retain failed/unknown usage. Avoid incidental title/body edits and unplanned pushes while paid workflow is active. Each review permits up to four research SDK calls plus one final call, so three examples do not mean three model calls. Provider rates checked October 10: first-party Haiku 4.5 $1/$5 per million input/output tokens. Recheck availability before execution; do not substitute a different model.

Run defect, then fix, then clean case sequentially. Inspect actual tool-use operations, context/source IDs, final request, citations/blob/range validation, COMMENT review, gate/annotations, per-job diagnostic uploads and Python 3.10/3.12 Verify. Tool choice is model-directed: record actual tools exercised without assuming all three tools will be used.

After corrected review, rerun identical SHA/title/body/policies. Expect zero new model calls and no duplicate review; the original result/usage must remain byte-equivalent. Reserve its conservative envelope beforehand despite expected zero spending. An unexpected cache miss stops further experimentation rather than triggering another retry.

Inspect failure artifacts without a paid rerun. Disable the workflow after the bounded experiment (also on failure), and verify disabled state and private visibility. Leave new demo PRs unmerged unless Julia separately authorizes their cleanup/merge. Keep exact run/review URLs, snapshots, sanitized application artifacts, actual outcomes and estimated model usage in a durable report. Do not classify three examples as a completed twelve-case held-out quality comparison or as independent interview evidence.

Sources checked October 10, 2026: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [model overview](https://platform.claude.com/docs/en/models/overview). Private merge enforcement remains unverified and outside this package.
