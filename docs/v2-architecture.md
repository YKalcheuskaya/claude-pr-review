# Version 2 architecture and acceptance contract

Implemented October 10, 2026 from Julia's approved local implementation plan. Supported context is repository-local Python, Java/Spring and JS/TS/React with SQL/configuration. No code execution, fork support, cross-repository access, GitHub Pro purchase or automatic paid retry is included.

## Identity and preparation

`service.prepare` gets current PR eligibility and title/body, fixes base/head/merge base, reads a bounded ordinary Git diff, validates it and checks freshness again. `v2.validate_input` requires exact v2 fields, actual policy hashes, mode, metadata and changed-file list. Context/tool policy and implementation hashes are computed from actual trusted module contents; the system prompt/schema/limits have their own hashes. Changing implementation is deliberately conservative cache invalidation.

The workflow checks out trusted base scripts, fetches PR head only as data and persists no checkout credential. Repository instructions are supplied as untrusted text. Tool permissions are enforced by application code; model resistance to prompt injection is not established. Filename exclusions, selected content patterns and runtime-secret checks are bounded. The raw diff does not receive the context reader's path exclusions; credential URLs and quoted serialized password fields can bypass checks, including before provider token counting. Some serialized secrets can also survive diagnostic sanitization. Do not submit sensitive repositories assuming automatic exclusion (open M-01). Diagnostic redaction is a separate control, not proof that raw data never reaches the provider.

## Context and model interaction

`ContextReader` reads Git tree/blob objects for before/after/target, with no replacement objects and no global/system Git configuration. Only permitted regular textual tracked blobs are readable. Initial context includes small changed files (8 KiB/file, 32 KiB total) and bounded root README/manifests. It records omissions rather than implying full analysis.

`list_files` returns up to 100 paths; `search_text` returns up to 50 literal matches; both paginate. `read_file` returns up to 200 lines/16 KiB and a continuation line. Individual blobs cap at 256 KiB; each snapshot caps at 10,000 paths and 32 MiB scanned text. Repeated reads use local cache and still count against the configured tool-operation limit (default twelve). Stable evidence IDs bind snapshot, path, complete-line range and text; each source also names its Git blob. Denials and limits are explicit.

The SDK loop permits the configured exploration-call count (default four), pairing native `tool_use` IDs with immediate `tool_result` responses. Final review uses a new request without tools and receives the diff, metadata, retained source fragments and application limitations. It cannot cite sources removed by input trimming. This validation does not ensure all diff hunks have citable sources; the separate diff-mode extraction gap is described below. Known omissions force partial status even when the model declares complete. No hidden reasoning is requested or persisted.

A conservative UTF-8 byte admission check and provider token counting bound each request at the configured input-token limit (default 24,000). Exploration/final output caps are configurable (defaults 2,000/4,000). Generation uses a Unix signal timer of at most 60 seconds and zero SDK retries, with elapsed-time checks targeting five minutes and a final-call reserve. This is not an end-to-end deadline guarantee: token-count preflight runs outside the generation timer, and a blocking Git reader can outlast its deadline check (open MD-02). Preparation and publication have separate timeouts; Actions supplies a ten-minute job timeout. Worst-case call spending reserves final input/output before exploration. The requested Claude model ID is configurable; token counting and generation receive it unchanged. Effective prices and review ceiling are validated and hashed with policies. Only the exact historical default has fallback price assumptions; other models require explicit rates. Provider feature/availability errors fail without substitution. The evaluation adapter reserves the whole per-review envelope in the shared aggregate ledger before invoking the analyzer; failed/unknown requests keep that reservation.

## Result, publication and cache

V2 result fields: version, trusted input identity, model, duration, content, usage, live provenance, cited source metadata, call count, coverage and gate outcome. Content has summary/status/limitations/findings. Each finding has severity, explanation/evidence/recommendation, optional hunk anchor and one or more source references. Citations must match a source actually retained for the final request, including snapshot/path/blob and line containment.

Only cited source metadata/hashes enter the compact durable result. Full model-visible text remains in diagnostic context/request records. Publisher validates the exact trusted input again, reconstructs cited source text from immutable Git objects, checks stable evidence IDs and text hashes, and checks current PR eligibility/snapshots/metadata. Transcript files are not accepted as results. A source citation proves the referenced text exists and was included by the trusted analyzer; it does not prove the model's interpretation is correct.

The body stores a compact base64 result of at most 32 KiB. It names the head and gate, renders text escaped, links evidence to fixed commits, and puts unanchored findings in the review body. Only COMMENT reviews are posted. Bot identity, submitted state, input digest, model and full contract must match for reuse. Cache hits retain original result/usage and emit zero current calls/cost. Deleted reviews remove cache evidence.

There is no atomic compare-head-and-post GitHub operation: before/after freshness checks fail the gate when a concurrent push/edit occurs. An uncertain POST receives read-only reconciliation, with exactly one write attempt per invocation. Conflicting/pending/invalid cached records require inspection.

## Diagnostics and failure policy

The CLI, Git reader, tools, SDK/token preflight, validation, cache, publisher and GitHub transport emit structured operation records. Trace IDs correlate workflow run/attempt; each job has an independently uploaded diagnostic bundle. Provider/native tool/source IDs connect operation records. Requests flush before external calls. Responses include available safe payloads even when parsing/validation fails. Errors record safe codes, class, field path, status/request ID and stack frames without locals or uncontrolled exception text.

Manifest completeness covers only available application interactions. Open operations, redaction, truncation and upload failure invalidate exact traceability. The ten-MiB cap reserves metadata and preserves safe hashes/prefixes when possible. Finalize/upload always run independently of `result.json`; platform logs remain the fallback when Python never starts or the runner disappears.

Gate policy fails at the configured severity threshold (default high/critical), and independently for invalid result/evidence, provider error, stale snapshot or publication failure. Valid complete/partial reviews below the threshold succeed. `none` disables only severity-based failure. Partial success emits INCOMPLETE REVIEW plus limitations and annotation. Excluded PRs explicitly receive no coverage. A required branch protection rule remains necessary for actual merge enforcement.

## Open implementation boundaries (October 11, 2026)

Diff mode reads the continuous first-to-last displayed line span on each side, capped at 200 lines. It can include unchanged gaps and omit citable late hunks while the raw diff still contains them. Coverage can incorrectly remain complete. Do not use it as an exact hunk-only quality baseline before MD-01 is repaired. Context-mode live observations are separate evidence.

Selected call/tool/token limits now come from the same validated runtime configuration used for hashing/enforcement; fixed timer literals remain a separate consolidation follow-up to L-01. The prompt is loaded from packaged `review-policy.md` in the trusted base checkout. See the [User Guide](../README.md#user-guide). Pinned setuptools 80.9.0 has the dated build-time advisory GHSA-h35f-9h28-mq5c, affecting sdist filename exclusion on macOS; no reviewer-runtime exploit was established. No dependency update is included here. See [known limitations](../README.md#limitations).
