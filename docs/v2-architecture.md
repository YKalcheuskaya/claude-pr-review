# Version 2 architecture and acceptance contract

Implemented October 10, 2026 from Julia's approved local implementation plan. Supported context is repository-local Python, Java/Spring and JS/TS/React with SQL/configuration. No code execution, fork support, cross-repository access, GitHub Pro purchase or automatic paid retry is included.

## Identity and preparation

`service.prepare` gets current PR eligibility and title/body, fixes base/head/merge base, reads a bounded ordinary Git diff, validates it and checks freshness again. `v2.validate_input` requires exact v2 fields, actual policy hashes, mode, metadata and changed-file list. Context/tool policy and implementation hashes are computed from actual trusted module contents; the system prompt/schema/limits have their own hashes. Changing implementation is deliberately conservative cache invalidation.

The workflow checks out trusted base scripts, fetches PR head only as data and persists no checkout credential. Repository instructions remain text; they cannot alter system policy. Known secrets and credential-like input are rejected before model transmission or required input-artifact writing. Logs independently sanitize every sink.

## Context and model interaction

`ContextReader` reads Git tree/blob objects for before/after/target, with no replacement objects and no global/system Git configuration. Only permitted regular textual tracked blobs are readable. Initial context includes small changed files (8 KiB/file, 32 KiB total) and bounded root README/manifests. It records omissions rather than implying full analysis.

`list_files` returns up to 100 paths; `search_text` returns up to 50 literal matches; both paginate. `read_file` returns up to 200 lines/16 KiB and a continuation line. Individual blobs cap at 256 KiB; each snapshot caps at 10,000 paths and 32 MiB scanned text. Repeated reads use local cache and still count against twelve operations. Stable evidence IDs bind snapshot, path, complete-line range and text; each source also names its Git blob. Denials and limits are explicit.

The SDK loop permits four exploration calls, pairing native `tool_use` IDs with immediate `tool_result` responses. Final review uses a new request without tools and receives the diff, metadata, retained source fragments and application limitations. It cannot cite sources removed by input trimming. Known omissions force partial status even when the model declares complete. No hidden reasoning is requested or persisted.

A conservative UTF-8 byte admission check and provider token counting bound each request at 24,000 input tokens. Exploration outputs cap at 2,000 and final output at 4,000. Each model call has a 60-second wall timer and zero retries; the analysis deadline is five minutes with a final-call reserve. Worst-case call spending reserves final input/output before exploration. Only the explicitly priced Haiku snapshot may run live. The evaluation adapter reserves the whole per-review envelope in the shared aggregate ledger before invoking the analyzer; failed/unknown requests keep that reservation.

## Result, publication and cache

V2 result fields: version, trusted input identity, model, duration, content, usage, live provenance, cited source metadata, call count, coverage and gate outcome. Content has summary/status/limitations/findings. Each finding has severity, explanation/evidence/recommendation, optional hunk anchor and one or more source references. Citations must match a source actually retained for the final request, including snapshot/path/blob and line containment.

Only cited source metadata/hashes enter the compact durable result. Full model-visible text remains in diagnostic context/request records. Publisher validates the exact trusted input again, reconstructs cited source text from immutable Git objects, checks stable evidence IDs and text hashes, and checks current PR eligibility/snapshots/metadata. Transcript files are not accepted as results. A source citation proves the referenced text exists and was included by the trusted analyzer; it does not prove the model's interpretation is correct.

The body stores a compact base64 result of at most 32 KiB. It names the head and gate, renders text escaped, links evidence to fixed commits, and puts unanchored findings in the review body. Only COMMENT reviews are posted. Bot identity, submitted state, input digest, model and full contract must match for reuse. Cache hits retain original result/usage and emit zero current calls/cost. Deleted reviews remove cache evidence.

There is no atomic compare-head-and-post GitHub operation: before/after freshness checks fail the gate when a concurrent push/edit occurs. An uncertain POST receives read-only reconciliation, with exactly one write attempt per invocation. Conflicting/pending/invalid cached records require inspection.

## Diagnostics and failure policy

The CLI, Git reader, tools, SDK/token preflight, validation, cache, publisher and GitHub transport emit structured operation records. Trace IDs correlate workflow run/attempt; each job has an independently uploaded diagnostic bundle. Provider/native tool/source IDs connect operation records. Requests flush before external calls. Responses include available safe payloads even when parsing/validation fails. Errors record safe codes, class, field path, status/request ID and stack frames without locals or uncontrolled exception text.

Manifest completeness covers only available application interactions. Open operations, redaction, truncation and upload failure invalidate exact traceability. The ten-MiB cap reserves metadata and preserves safe hashes/prefixes when possible. Finalize/upload always run independently of `result.json`; platform logs remain the fallback when Python never starts or the runner disappears.

Gate policy is failure for high/critical, invalid result/evidence, provider error, stale snapshot or publication failure; success for valid complete/partial without high/critical. Partial success emits INCOMPLETE REVIEW plus limitations and annotation. Excluded PRs explicitly receive no coverage. A required branch protection rule remains necessary for actual merge enforcement.
