# Version 2 troubleshooting without another model run

The trace records observable application interactions. It does not reveal hidden model reasoning or prove that a finding is correct. A successful gate with an `INCOMPLETE REVIEW` warning means known gaps remain. Resolve the original trace before considering another paid request.

## Locate the evidence

Start with the failing job's ordinary Actions console, its step status and `GITHUB_STEP_SUMMARY`. Find the snapshot identifiers, trace ID, last completed operation and exact error code. Each job has its own diagnostic artifact named with run ID, attempt and job, retained for seven days. Download both analysis and publication job artifacts when both jobs ran. Locally, the default is `outputs/diagnostics`, or the directory passed with `--diagnostics-dir`.

The expected bundle consists of:

| File | Purpose |
| --- | --- |
| `manifest.json` | Snapshot and policy identities, runtime/SDK versions, trace identifiers and completeness/redaction/truncation status |
| `events.jsonl` | Ordered operation starts, ends and errors with timestamps and durations |
| `requests.jsonl` | Sanitized application-level model and GitHub request payloads |
| `responses.jsonl` | Available sanitized responses, including malformed or truncated model content |
| `context.json` | Sources actually supplied to the model, with snapshot, blob, path, lines and source IDs |
| `summary.md` | Outcome, last successful step, error and next diagnostic action |

Match jobs by run/attempt, PR and immutable base/head/merge-base snapshots; correlate operation IDs, model-call IDs, native tool-use IDs and source/evidence IDs within each trace. A cache hit creates a fresh trace referencing the original review/result: current paid call count must be zero, while historical usage belongs to the original review. Execution IDs and timestamps are not cache keys.

## Diagnose the stopping point

| Symptom | Read first | Interpretation and next action |
| --- | --- | --- |
| Provider timeout or HTTP error | SDK start/error, sanitized response, request ID and usage | Distinguish transport/provider failure from a validated model response. A timeout can have unknown billable usage; preserve the reservation. Do not automatically retry. |
| SDK start without end/error | Last event, platform logs and runner status | Operation was interrupted or diagnostic capture failed. This does not prove the server rejected the request. |
| JSON/schema validation failure | Response record and validation error code/field path | Model output arrived but cannot be accepted. Inspect the exact available payload and schema identity. Never publish from a transcript. |
| Invalid evidence | Finding source IDs, `context.json`, immutable Git blobs | Check that cited lines/blobs match the correct snapshot and were actually supplied in final context. An invented citation is an invalid result, not a provider outage. |
| Incomplete review | Coverage, limitations and denied/truncated tool results | Find the exact budget, time, unsupported-file or policy boundary. Success with warning does not provide complete coverage. |
| Stale snapshot | Prepared snapshot and fresh PR metadata | Head, base or metadata changed. Preserve the historical trace; a new snapshot requires normal preparation and a new eligible run. |
| Cache miss after an edit | Snapshot, title/body, mode and actual policy hashes | The cache identity intentionally changes. A v1 result cannot satisfy v2. |
| Publication failure or unknown POST | Write operation, HTTP status, commit, review ID and reconciliation read | Check the PR's reviews read-only for the exact marker and snapshot. There must be one write attempt followed by read-only reconciliation, never a blind second POST. |
| Missing diagnostics | Finalize/upload step status and platform logs | Upload is independent of the required result artifact. Failure to upload must remain visible; a bundle before Python startup may not exist. |

A valid high/critical finding produces a failed gate by policy. A valid clean incomplete result produces success with a conspicuous warning. No valid final result, invalid evidence, stale snapshot or failed publication produces failure. An excluded PR has no review coverage. These are distinct outcomes; do not classify every failed gate as a model or network failure.

## Sanitized examples

The following console fragments are illustrative rather than evidence of a live run. Literal untrusted paths, queries and bodies are escaped/sanitized before logging. Full source/response content belongs in the bounded artifact rather than the console.

```text
[analyze][call-02] sdk.start model=claude-haiku-4-5-20251001 max_tokens=2000
[analyze][call-02] sdk.end stop_reason=tool_use duration_ms=420
[analyze][tool-05] read_file snapshot=after path=src/client.py lines=40:95
[analyze][tool-05] tool.end lines=56 bytes=1740 source_id=source-09
[analyze][call-03] sdk.end stop_reason=end_turn findings=0
[gate][publish-01] review.created review_id=123 comments=0
[gate] outcome=success coverage=complete
```

Reconstruct the model-visible context by following `source-09` to the after-snapshot blob and range in `context.json`, and checking its inclusion in the final request record. Check other tool operations, initial context and limitations too; a single successful read does not establish complete coverage.

```text
[analyze][call-02] sdk.start model=claude-haiku-4-5-20251001 max_tokens=2000
[analyze][call-02] sdk.error code=provider_timeout request_id=redacted-example
[gate] outcome=failure reason=no_valid_result
```

In the failure example, inspect the start/error sequence and any available response. Absence of `result.json` is expected; finalize and diagnostic upload should still run. Preserve the safe request parameters and reserved budget. Do not imply that the model returned a clean review or that a timeout cost zero.

If redaction, the 10 MiB bundle limit, hard cancellation or upload failure removed information, the manifest and summary must say so. Hashes and retained beginnings help identify content, but a truncated/redacted trace is not an exact copy of the request. Hard runner loss is best effort; platform logs may be the only available evidence.

## Manual reruns

A manual model rerun is appropriate only after identifying a concrete cause, ensuring the snapshot remains eligible, checking explicit paid authorization and reserving additional budget in the shared ledger. First use offline reproduction with the preserved response when feasible. Never repeat an ambiguous publication write: reconcile existing reviews read-only and require human inspection if identity remains uncertain. Do not activate a paused paid workflow or publish a change merely to investigate a trace. The local offline suite requires no provider credentials.

For a handoff, provide the run/attempt/job, immutable snapshot, trace/operation ID, safe error code, relevant artifact record, completeness limitations and proposed next action. Exclude credentials, headers, environment dumps and unsanitized provider objects. This information should let another developer explain the stop without rerunning the model.
