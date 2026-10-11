# Historical release verification — updated 2026-10-04

This is the original dated v1 checkpoint, not current verification. Later observations: [October 5](live-verification-2026-10-05.md), [October 11](v2-live-verification-2026-10-11.md). The unknowns below describe the checkpoint date.

## Verified

- Python 3.10.1 on macOS: 37 tests passed, zero failures, zero skips in the locked
  environment (`.venv/bin/python scripts/run-tests.py`).
- The installed official `anthropic==1.11.0` SDK serialized the native JSON schema
  and parsed an authored response through an in-memory HTTP transport. A simulated
  transport timeout made exactly one attempt with zero retries.
- Real disposable Git repositories proved that preparation uses merge base and
  excludes unrelated commits added to the base branch.
- Offline CLI runs generated inline GitHub payloads and returned 0 for the authored
  clean response, 1 for a high finding, and 2 for invalid input.
- Tests cover old/new-side lines, additions/deletions/edited renames, invalid and
  cross-hunk ranges, partial responses, limits, credential-like text, prompt/input
  separation, repeated writes, uncertain publication, pending review reconciliation,
  stale workflow events and a push during publication.
- Both workflow files parsed as YAML. Workflow tests verify action SHA pins,
  base checkout, credential separation, always-run gate and candidate CI boundaries.
- Python compilation and `pip check` passed. Whitespace, staged-path, credential
  and documentation-link checks are part of the final local checkpoint review.

## Evidence limits

The SDK test uses a fake transport: it is not an Anthropic call. Replay responses
are authored fixtures. Their findings establish pipeline behavior only. The system
prompt's treatment of repository instructions is tested as request separation;
model resistance to prompt injection remains unverified.

Actual inline-comment acceptance, merge-blocking rule enforcement, Haiku
accuracy/cost, Sonnet comparison and Julia's independent explanation are **Unknown**.
The project stores no credential.

## Private publication — October 4

Julia authorized a private GitHub release. The repository
`YKalcheuskaya/claude-pr-review` was created with `isPrivate: true`, and the approved
`pr_review` rename was published in commit `db28be8fc7775997574f9b37f780f1b8faa37889`.
The [first Verify run](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37246943855)
passed both Python 3.10 and 3.12 jobs. Paid model calls, secrets, demo PRs and
branch-protection changes were not part of this publication.

Review [the delivery package](github-delivery.md) for the remaining experiment.
