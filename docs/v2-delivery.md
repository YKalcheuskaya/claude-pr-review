# Version 2 local acceptance and private delivery package

**Historical local checkpoint:** October 10, 2026. Subsequent authorized delivery and live results: [October 11 verification](v2-live-verification-2026-10-11.md). The pending states below describe the pre-delivery checkpoint.

**Date:** October 10, 2026. **Scope:** local implementation and offline verification only. **Historical v1 checkpoint:** `a89a22a39372f1cfc8f40448fa572be63fd7862e`, preserved with its recorded inputs/results unchanged.

## Verified locally

- 100 tests pass on installed Python 3.10 with zero skips. The 39 existing regressions remain, including retained v1 live-evidence contracts. New checks cover immutable snapshots, denied paths/credentials/nonregular blobs, scan/read/tool limits, metadata/policy/mode cache changes, exact evidence, incomplete gating, provider errors, races, budget reservation and diagnostics.
- Actual installed Anthropic SDK 1.11.0 passes in-memory HTTP tests: token-count preflight, tool_use/tool_result pairing, final schema and original no-retry timeout regression. These are SDK compatibility observations, not provider quality or availability evidence.
- Compilation, `pip check`, whitespace checks and Ruby YAML parsing of both workflows pass. A wheel builds and installs successfully as version 0.2.0 into the ignored `outputs/package-check` directory without dependencies or network. The old local pip cannot perform editable installation from pyproject; ordinary wheel installation succeeds.
- The offline corpus has three development and twelve held-out cases, each with diff/context inputs generated from the same fixed Git snapshots. Every stack has two seeded cross-file regressions and two correct changes. Oracle labels remain separate and require independent human review before quality conclusions.
- The evaluation runner prepares inputs, seals policy/corpus/oracle files, reserves a shared ledger, performs separately authorized execution and scores independently adjudicated recordings. Its execution adapter is tested with mocked analysis; no paid request was sent.
- Diagnostics preserve available application requests/responses and context, apply bounded redaction before every sink (not complete secret detection; see current architecture caveats), keep source bodies out of console, bound bundles, and preserve failure traces without `result.json`. Ordinary GitHub malformed JSON is retained before parsing. Ambiguous writes reconcile without a second POST.

At this October 10 checkpoint, Python 3.12 was configured in Verify but unavailable locally; no new remote CI run had started. Live behavior was still unverified then. The October 11 report supplies later mechanism observations, not a held-out quality comparison or independent explanation.

## Subsequent delivery

The private v2 release and repair were delivered October 11 after Verify. The [live report](v2-live-verification-2026-10-11.md) records three snapshots, the initial failed attempt, false positives and zero-call cache reuse. Paid workflow activation was temporary and ended disabled. The full paired held-out evaluation was not performed. Historical personal authorization/budget administration is retained in the private parent workspace; it is not reusable operator permission.

## Historical smoke scenario

The following instructions describe the original proposed scenario, not a new execution request. The linked live report records what actually ran.

The original scenario proposed one bounded Python or Java/Spring fixture with an unchanged caller/SQL contract and a changed producer field/query. Open a private demo PR that introduces the cross-file defect, then push its correction. The two planned reviews are the defect and corrected snapshots. Inspect any finding against Git rather than assuming the model will detect the seeded issue. Confirm inline anchor or review-body fallback, immutable evidence links, failed-then-successful severity policy, diagnostics from both jobs and source reconstruction from the final request.

Rerun an unchanged successful snapshot to test cache reuse: exactly zero new model calls and no additional review. An unexpected cache miss stops the smoke rather than spending automatically. Read existing v1 PRs/reviews without altering them. Disable the paid workflow again after the experiment and preserve the observed result and final spending ledger.

Private protection remains the historical unavailable prerequisite; this package does not authorize purchasing Pro or making the repository public. A failed gate alone does not demonstrate merge enforcement.

## Evidence classification at October 10 checkpoint

| Result | State |
| --- | --- |
| Local v2 mechanism and offline acceptance | Verified |
| Installed SDK compatibility with mock HTTP | Verified |
| Live v2 provider/GitHub behavior | Unknown, not run |
| Better model quality on held-out cases | Unknown, not run |
| Independent oracle review | Pending |
| New Python 3.12 CI result | Unknown, not run |
| Enforced private merge blocking | Not demonstrated; historical HTTP 403 |
| Independent explanation | Not demonstrated |

Sources: [Anthropic client tool protocol](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [model overview](https://platform.claude.com/docs/en/models/overview), [GitHub workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands), checked October 10, 2026. Recheck availability/pricing before a paid pilot.
