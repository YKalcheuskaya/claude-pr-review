# Troubleshooting

Start with the existing trace to identify why the review stopped. Diagnostics record observable application interactions. Thinking blocks, replay signatures and opaque thinking data are omitted from every retained request/response; they remain in memory only when needed for the SDK protocol. Omission marks the trace as redacted and incomplete. Diagnostics do not establish that a finding is correct.

## Find the Evidence

In Actions, inspect the failing job, console and step summary. Each job uploads its own diagnostic artifact, named with run ID, attempt and job, with seven-day retention. Download analysis and publication artifacts when both jobs ran. Local commands use `outputs/diagnostics` unless `--diagnostics-dir` overrides it.

| File | Contents |
| --- | --- |
| `manifest.json` | Snapshot/policy identities, runtime versions, trace ID and completeness status |
| `events.jsonl` | Operation starts, completions, errors and durations |
| `requests.jsonl` | Available sanitized model and GitHub requests |
| `responses.jsonl` | Available sanitized responses, including invalid model output |
| `context.json` | Model-visible sources with paths, blobs, lines and evidence IDs |
| `summary.md` | Outcome, last successful step and next diagnostic action |

Match run/attempt, PR, trace and immutable snapshots across jobs. Within a trace, follow operation, model-call, tool-use and source IDs. Cache reuse has zero current model calls; the reused review retains its original usage.

## Diagnose the Stopping Point

| Symptom | Inspect | Next Action |
| --- | --- | --- |
| Provider timeout or HTTP error | Retry events, safe status/request ID, elapsed time and reservations | Distinguish transient failure from permanent rejection, exhausted budget or deadline. Three retries are allowed within time and budget limits. Unknown failed-attempt usage retains its reservation. |
| Started operation with no completion | Last event, runner status and platform logs | Check interruption or missing capture; absence of a response does not prove provider rejection. |
| Invalid structured output | Response and schema error code/field path | Inspect the retained payload. Invalid output is not automatically retried or published. |
| Invalid evidence | Source IDs, context and cited immutable blobs | Confirm the source was retained in the final request and lines match the correct snapshot. |
| INCOMPLETE REVIEW | Coverage, limitations and denied/truncated tool results | Decide whether additional human review or a narrower change is needed. Passing partial coverage is not complete approval. |
| Stale snapshot | Prepared and current PR metadata | A changed head, base, title or body requires fresh preparation. |
| Cache miss | Snapshots, metadata, model and effective policy hashes | Identify the changed input or policy; cache identity deliberately includes these values. |
| Uncertain publication | POST status, review ID and reconciliation read | Inspect existing reviews for the exact marker and snapshot. Never blindly repeat a POST. |
| Missing bundle | Finalize/upload steps and platform logs | Use runner logs; capture may be unavailable before Python starts or after hard runner loss. |

A finding at or above the configured severity threshold fails the gate. Invalid output/evidence, provider failure, stale input or failed publication also fail it. A valid partial review below the threshold passes with a warning. Excluded PRs receive no review coverage.

## Inspect Context and Deadlines

Follow a finding's evidence IDs into `context.json`, then verify its snapshot, blob, path and lines against the final request. A valid citation confirms the source exists and was supplied; human judgment is still needed to assess the claim.

Analysis has a five-minute total deadline, including Git reads, token counting, generation and backoff. Token counting and generation have shorter nested timers, and Actions limits each job to ten minutes. Deadline expiry stops analysis. A missing `result.json` is expected when no valid final review was produced; diagnostic finalization/upload still run when the platform permits.

Redaction, truncation, the 10 MiB bundle cap or upload failure can prevent exact reconstruction. Inspect manifest completeness before relying on a trace. Pattern-based sanitization is not comprehensive secret detection; handle retained artifacts as potentially sensitive. See [security and diagnostics](architecture.md#security-and-diagnostics).

## Rerun Safely

Reproduce parsing or validation offline from a preserved response where possible. Before a new paid analysis, identify the cause, confirm the current eligible snapshot and reserve sufficient budget. An ambiguous publication requires read-only reconciliation and human inspection if identity remains uncertain.

For a handoff, provide the run/attempt/job, immutable snapshot, trace/operation ID, safe error code, relevant artifact record, completeness limitations and proposed next action. Exclude credentials, headers, environment dumps and unsanitized provider objects.
