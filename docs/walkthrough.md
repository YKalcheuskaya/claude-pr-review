# Offline walkthrough

Start with the [complete README commands](../README.md#complete-offline-v2-example). Use a fresh output directory and the project virtual environment. No provider credential or GitHub access is required. The authored replay proves result and payload contracts, not model quality.

1. Inspect the prepared `context-input.json`: mode, title/body, before/after/target commits and actual policy hashes bind identity. The fixture repository contains source, not held-out oracle labels.
2. Inspect `result.json`: zero calls, `live: false`, complete coverage and success for this authored clean response. Sources are empty because only cited metadata enters the result.
3. Inspect `payload.json`: COMMENT event, generated head commit, no inline comments, hidden cache marker. Dry-run creates a file without a POST.
4. For evidence-linked findings, inspect `finding()` and `test_body_only_finding_and_inline_anchor` in [v2 tests](../tests/test-v2.py). References derive from real Git blobs; a changed hunk receives an inline anchor, while an unchanged caller can appear in the body. A high finding fails the default severity gate; the threshold is configurable in the [User Guide](../README.md#user-guide).
5. Inspect [context tests](../tests/test-context.py) for immutable Git reads, literal searches, line limits and denied inputs. The known raw-diff/serialized-secret gaps remain open; bounded exclusions are not a secret-disclosure guarantee.
6. Inspect diagnostic manifests/events/context. Missing end events indicate interruption, not proven server rejection. Redaction/truncation limits exact reconstruction.
7. Trace cache identity and uncertain publication in [service code](../src/pr_review/service.py). One POST is followed by read-only reconciliation when uncertain; no automatic write retry is safe.

A valid partial review below the configured failing severity passes with INCOMPLETE REVIEW. A citation validates source integrity, not the interpretation. See [architecture limitations](v2-architecture.md), [troubleshooting](v2-troubleshooting.md) and the separate [live observations](v2-live-verification-2026-10-11.md).

## Historical v1 replay

```sh
PYTHONPATH=src .venv/bin/python -m pr_review.cli analyze --input evaluation/input.json --recorded evaluation/clean-response.json --output outputs/v1-result.json
PYTHONPATH=src .venv/bin/python -m pr_review.cli publish --input evaluation/input.json --result outputs/v1-result.json --dry-run --output outputs/v1-payload.json
```

Both commands return 0. This older diff-only path does not exercise v2 context tools. For actual v1 observations use the [dated report](live-verification-2026-10-05.md).
