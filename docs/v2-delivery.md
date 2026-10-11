# Version 2 local acceptance and private delivery package

**Date:** October 10, 2026. **Scope:** local implementation and offline verification only. **Historical v1 checkpoint:** `a89a22a39372f1cfc8f40448fa572be63fd7862e`, preserved with its recorded inputs/results unchanged.

## Verified locally

- 100 tests pass on installed Python 3.10 with zero skips. The 39 existing regressions remain, including retained v1 live-evidence contracts. New checks cover immutable snapshots, denied paths/credentials/nonregular blobs, scan/read/tool limits, metadata/policy/mode cache changes, exact evidence, incomplete gating, provider errors, races, budget reservation and diagnostics.
- Actual installed Anthropic SDK 1.11.0 passes in-memory HTTP tests: token-count preflight, tool_use/tool_result pairing, final schema and original no-retry timeout regression. These are SDK compatibility observations, not provider quality or availability evidence.
- Compilation, `pip check`, whitespace checks and Ruby YAML parsing of both workflows pass. A wheel builds and installs successfully as version 0.2.0 into the ignored `outputs/package-check` directory without dependencies or network. The old local pip cannot perform editable installation from pyproject; ordinary wheel installation succeeds.
- The offline corpus has three development and twelve held-out cases, each with diff/context inputs generated from the same fixed Git snapshots. Every stack has two seeded cross-file regressions and two correct changes. Oracle labels remain separate and require independent human review before quality conclusions.
- The evaluation runner prepares inputs, seals policy/corpus/oracle files, reserves a shared ledger, performs separately authorized execution and scores independently adjudicated recordings. Its execution adapter is tested with mocked analysis; no paid request was sent.
- Diagnostics preserve available application requests/responses and context, redact before every sink, keep source bodies out of console, bound bundles, and preserve failure traces without `result.json`. Ordinary GitHub malformed JSON is retained before parsing. Ambiguous writes reconcile without a second POST.

Python 3.12 is configured in Verify but unavailable locally; no new remote CI run was started. Live v2 tool behavior, GitHub artifacts/annotations, quality improvement and Julia's independent explanation remain unverified. Historical v1 evidence does not fill those gaps.

## Concrete external package awaiting separate approval

Target the existing private `YKalcheuskaya/claude-pr-review` repository. Publish the locally verified v2 checkpoint through a reviewed branch/PR and run credential-free Verify before enabling any paid reviewer. Keep visibility private. Do not merge or change branch protection as a side effect. Fetching/checking existing remote state and resolving any drift belong to that separately approved delivery execution.

The existing paid reviewer stays disabled until Julia authorizes activation and the bounded pilot. Check model availability and rates immediately before activation. The plan uses exactly `claude-haiku-4-5-20251001`, without Sonnet or fallback. The official pricing page checked October 10 lists $1/$5 per million input/output tokens; the runner rejects higher rates until the budget policy is revised. This is model-token budgeting, not an invoice guarantee.

One serial ledger owner reserves the whole review envelope before any provider request: three context development runs ($0.60), twelve context held-out ($2.40), twelve diff held-out ($0.60), two private context smoke reviews ($0.40), for at most $4. The remaining $1 is not automatically spendable. Failed, timed-out and unknown calls keep their entire reservation. No automatic retries; any manual rerun must fit the approved scope and have a new reservation. Use `scripts/evaluate-v2.py run` with the flags and actual prior approval described in the evaluation guide. Smoke reviews share the same ledger.

Freeze prompt/policies after development and before held-out execution. Review labels independently before interpreting quality. Preserve all outcomes, including a failed improvement criterion. Compare paired runs on the same model and cases; require at least two additional cross-file detections with no increase in false high/critical findings on clean cases. Report precision, recall, severity, evidence correctness, incomplete/failure rate, latency and estimated spending.

## Private smoke scenario

Use one bounded Python or Java/Spring fixture with an unchanged caller/SQL contract and a changed producer field/query. Open a private demo PR that introduces the cross-file defect, then push its correction. The two planned reviews are the defect and corrected snapshots. Inspect any finding against Git rather than assuming the model will detect the seeded issue. Confirm inline anchor or review-body fallback, immutable evidence links, failed-then-successful severity policy, diagnostics from both jobs and source reconstruction from the final request.

Rerun an unchanged successful snapshot to test cache reuse: exactly zero new model calls and no additional review. An unexpected cache miss stops the smoke rather than spending automatically. Read existing v1 PRs/reviews without altering them. Disable the paid workflow again after the experiment and preserve the observed result and final spending ledger.

Private protection remains the historical unavailable prerequisite; this package does not authorize purchasing Pro or making the repository public. A failed gate alone does not demonstrate merge enforcement.

## Evidence classification

| Result | State |
| --- | --- |
| Local v2 mechanism and offline acceptance | Verified |
| Installed SDK compatibility with mock HTTP | Verified |
| Live v2 provider/GitHub behavior | Unknown, not run |
| Better model quality on held-out cases | Unknown, not run |
| Independent oracle review | Pending |
| New Python 3.12 CI result | Unknown, not run |
| Enforced private merge blocking | Not demonstrated; historical HTTP 403 |
| Julia's independent explanation | Not demonstrated |

Sources: [Anthropic client tool protocol](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [model overview](https://platform.claude.com/docs/en/models/overview), [GitHub workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands), checked October 10, 2026. Recheck availability/pricing before a paid pilot.
