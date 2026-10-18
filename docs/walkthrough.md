# Offline Walkthrough

Run from the project root after the [quick start](../README.md#quick-start). This replay validates an authored response and creates a GitHub review payload locally. It needs no credentials, makes no provider calls and posts nothing to GitHub. It demonstrates application behavior, not model accuracy.

## Run the Replay

Prepare development fixtures, validate an **authored clean response**, and generate a GitHub payload without networking:

```sh
.venv/bin/python scripts/evaluate.py prepare --split development --output outputs/offline-demo
PYTHONPATH=src .venv/bin/python -m pr_review.cli analyze --input outputs/offline-demo/development-02/context-input.json --repository-path outputs/offline-demo/development-02/repository --recorded evaluation/corpus/authored-clean-response.json --output outputs/offline-demo/result.json --diagnostics-dir outputs/offline-demo/analyze-diagnostics
PYTHONPATH=src .venv/bin/python -m pr_review.cli publish --input outputs/offline-demo/development-02/context-input.json --result outputs/offline-demo/result.json --dry-run --output outputs/offline-demo/payload.json --diagnostics-dir outputs/offline-demo/publish-diagnostics
```

All three commands return **0**. Preparation creates three disposable Git repositories, paired `context-input.json`/`diff-input.json` and local-only `case-record.json` files. Development case 02 is a valid independent configuration change. Its snapshots and policy identities are generated locally, not hardcoded. Held-out labels are never model/example input.

Inspect `result.json` and `payload.json`. Selected expected fields (synthetic replay, not live model output):

```json
{
  "version": 2,
  "live": false,
  "calls": 0,
  "coverage": "complete",
  "gate_outcome": "success",
  "sources": [],
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

The payload has `event: "COMMENT"`, `commit_id` equal to the generated input's head, and `comments: []`. Empty sources are intentional: only cited metadata is retained, and this response has no findings. Diagnostic directories contain context, events, a manifest and empty request/response files for this replay; it does not create SDK calls.

For the supported evidence-linked finding path, [the review tests](../tests/test-review.py) construct a changed `contract.py` and unchanged `caller.py`. `finding()` derives a reference from the actual after-snapshot source, including its generated source ID/blob and lines 1–2. `test_body_only_finding_and_inline_anchor` verifies an immutable caller link and an inline RIGHT anchor at `contract.py:1`; `test_partial_success_high_still_fails` verifies the high gate. Neither authored examples nor mocks measure model accuracy.

`analyze` returns 0 after valid result creation even for a high finding. `publish --dry-run` returns 0 for a passing gate, 1 for findings at the configured failing threshold, or 2 for invalid input/result. It never posts a review. Recorded results cannot be published live. Fixture preparation refuses an existing case directory: for another run choose a fresh output path and use it consistently; do not delete real work. Generated outputs remain under ignored `outputs/`. Source edits can change policy hashes: regenerate inputs after such edits.

## Inspect the Result

1. Inspect the prepared `context-input.json`: mode, title/body, before/after/target commits and actual policy hashes bind identity. The fixture repository contains source, not held-out oracle labels.
2. Inspect `result.json`: zero calls, `live: false`, complete coverage and success for this authored clean response. Sources are empty because only cited metadata enters the result.
3. Inspect `payload.json`: COMMENT event, generated head commit, no inline comments, hidden cache marker. Dry-run creates a file without a POST.
4. For evidence-linked findings, inspect `finding()` and `test_body_only_finding_and_inline_anchor` in [review tests](../tests/test-review.py). References derive from real Git blobs; a changed hunk receives an inline anchor, while an unchanged caller can appear in the body. A high finding fails the default severity gate; the threshold is configurable in the [configuration reference](runtime-configuration.md).
5. Inspect [context tests](../tests/test-context.py) for immutable Git reads, literal searches, line limits and denied inputs. Restricted changed paths fail diff admission; shared pattern checks are not comprehensive secret detection.
6. Inspect diagnostic manifests/events/context. Missing end events indicate interruption, not proven server rejection. Redaction/truncation limits exact reconstruction.
7. Trace cache identity and uncertain publication in [service code](../src/pr_review/service.py). One POST is followed by read-only reconciliation when uncertain; no automatic write retry is safe.

A valid partial review below the configured failing severity passes with INCOMPLETE REVIEW. A citation validates source integrity, not the interpretation. See [architecture](architecture.md) and [troubleshooting](troubleshooting.md).
