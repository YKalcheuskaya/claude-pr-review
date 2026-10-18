# Architecture

The workflow separates trusted execution, bounded model analysis and publication. Repository contents remain data: the model can inspect permitted source files but cannot execute code, change the repository or approve a pull request.

## Review Flow

1. **Prepare:** read PR eligibility and metadata, resolve immutable base/head/merge-base commits, validate a bounded Git diff and check freshness.
2. **Analyze:** assemble initial context, let Claude inspect related code through restricted tools, and request a structured final review.
3. **Validate:** enforce the result schema, source citations, configured severity policy and input identity.
4. **Publish:** recheck the current PR and reconstruct cited evidence from immutable Git objects before posting a COMMENT review.

The `pull_request_target` workflow uses trusted-base orchestration, a main-only provider environment and scripts from the trusted base commit, fetches the PR head as data and does not persist checkout credentials. Model and policy identities bind preparation, analysis, publication and cache reuse. The [configuration reference](runtime-configuration.md) explains the available controls.

## Context and Evidence

Context mode supports repository-local Python, Java/Spring and JS/TS/React code, with related SQL and configuration. Initial context includes bounded changed files and root documentation/manifests. Read-only tools provide paginated file listing, literal text search and line-range reads across before/after/target snapshots.

| Resource | Bound |
| --- | --- |
| Initial changed-file context | 8 KiB per file; 32 KiB total |
| File listing | 100 paths per page |
| Literal search | 50 matches per page |
| File read | 200 lines / 16 KiB per operation |
| Individual blob | 256 KiB |
| Snapshot scan | 10,000 paths / 32 MiB text |

Only permitted regular textual tracked blobs are readable. Git replacement objects and global/system configuration are disabled. Repeated reads may reuse local data but still count against the tool-operation limit. Omitted or denied context is reported explicitly.

Evidence IDs bind snapshot, path, Git blob, complete-line range and text. Findings must cite source fragments retained in the final model request. Publication reconstructs those fragments independently. These checks establish source integrity; a human still evaluates the finding's interpretation and recommendation.

Diff mode reads each displayed hunk in bounded complete-line chunks on both sides, without related-code exploration. Renamed files use the original path for before-snapshot evidence. Tool or byte limits mark omitted context as partial coverage.

## Execution Harness

Default context mode allows four exploration operations and one final generation operation, twelve tool operations, 24,000 input tokens per request and output caps of 2,000/4,000 tokens. The final request has no tools and receives only the retained sources, diff, metadata and recorded limitations.

A five-minute total analysis deadline covers context initialization, Git reads, token counting, generation, retry backoff and validation. Nested token-count and generation timers are 30 and 60 seconds; nested operations preserve the earlier enclosing deadline. Interrupted Git subprocesses are terminated. Preparation and publication have separate timeouts, and Actions limits each job to ten minutes.

Transient GitHub reads, token-count requests and generation failures allow three retries after the initial attempt: at most four attempts, with 0.5, 1 and 2 second backoffs. Permanent client errors and invalid model output are not retried. Deadline or budget exhaustion can stop earlier. SDK retries are disabled so application code owns attempt accounting.

Every submitted generation attempt receives a conservative cost reservation, including failures with unknown usage. The final request's budget is reserved before exploration. Logical generation counts and additional HTTP attempts are distinguished in diagnostics; unreported failed-attempt usage is not presented as zero cost. These ceilings use configured prices and do not represent an account-wide invoice guarantee.

## Publication and Cache

Only COMMENT reviews are posted. Findings on changed lines can use inline anchors; other findings remain in the review body with fixed-commit evidence links. The review stores a compact result, limited to 32 KiB, for validated reuse.

A reusable review must match bot identity, submitted state, immutable input digest, model and complete result contract. Model, metadata, snapshots, effective controls/prices, prompt and implementation policies participate in identity. A cache hit retains the original review's usage while making zero new model calls. Deleted reviews remove that cache evidence.

GitHub has no atomic compare-head-and-post operation. Freshness checks before and after publication detect concurrent changes and fail the gate. An uncertain POST receives read-only reconciliation; each invocation makes at most one publication write attempt.

## Gate and Human Oversight

The automatic gate fails on findings at or above the configured threshold, invalid results or evidence, provider failures, stale snapshots and publication errors. A valid partial review below the threshold succeeds with an **INCOMPLETE REVIEW** warning. Excluded PRs receive no coverage.

The workflow does not approve or merge code. Maintainers assess findings, decide whether coverage is sufficient and approve changes. Repository rules must separately require human approval and the relevant checks for merge enforcement. See [Human Oversight and AI Guardrails](../README.md#human-oversight-and-ai-guardrails).

## Security and Diagnostics

Tool permissions are enforced by code; repository instructions are untrusted input. Filename exclusions, selected secret patterns and runtime-secret checks reduce exposure, but are not comprehensive detection. Diff admission rejects restricted paths on both sides, and shares sensitive-content checks with metadata, context, output and trace redaction. The checks include quoted assignments, credential-bearing URLs and runtime credentials; they cannot recognize every secret or encoded representation. Review repository suitability before transmitting code or retaining traces.

Structured events, sanitized request/response records and source metadata connect each operation to a trace ID and immutable snapshots. Each job uploads an independent diagnostic bundle, including on application failure. A 10 MiB cap, redaction, truncation, cancellation or upload failure may prevent exact reconstruction. Platform logs remain the fallback when application capture cannot run. See [troubleshooting](troubleshooting.md).
