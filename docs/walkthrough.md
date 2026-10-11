# Version 2 offline walkthrough

1. Run `python scripts/run-tests.py` without provider credentials. Distinguish deterministic mechanism verification from observed model quality.
2. Run `python scripts/evaluate-v2.py prepare --split development --output outputs/walkthrough`. Inspect a generated input and its fixture repository: mode, title/body, fixed snapshots, diff and actual policy hashes are part of identity. Oracle labels are outside the model input.
3. Inspect `ContextReader` and `tests/test-context.py`: explain Git object reads, before/after/target, a literal caller search, line limits, denied credentials and evidence IDs. Changing the worktree cannot change the fixed snapshot.
4. Inspect `tests/test-v2.py`: the real installed SDK receives mocked tool_use, the immediate tool_result and a final request with no tools. Reconstruct the cited unchanged caller and changed hunk anchor.
5. Explain why a clean partial review succeeds with INCOMPLETE REVIEW, and why malformed output, an invented citation or stale metadata fails. A citation does not prove the defect is real.
6. Inspect a local diagnostic bundle under `outputs/diagnostics`: trace ID, snapshots, operation starts/ends/errors, requests/responses and context source IDs. Find the exact available response without rerunning the model. Missing end events indicate interruption, not a proven server failure.
7. Explain cache reuse and ambiguous publication: identity includes PR metadata and actual policies; new execution data does not. One POST is followed by read-only reconciliation when uncertain.
8. Read the v2 delivery package and pilot budget. Publication, workflow activation and live calls are separately authorized. A red check requires a protection rule to block merge.

This checklist is preparation, not an observed independent assessment. Julia's uncoached explanation remains unverified.

---

## Historical v1 walkthrough

# Explain the project

Use these prompts to practice in English. Reading this guide is not an assessment.

## One-minute overview

“This project integrates Claude into GitHub Actions to review pull requests.
Opening a PR or pushing another commit triggers a read-only analysis job. It
collects the diff, calls Claude once, and validates the structured findings.
A separate publisher posts inline comments and fails a required check for high
or critical findings. The model cannot push code or merge. I test the integration
with recorded responses separately from measuring the model's review quality.”

## Trace one finding

1. Read `demo.py`: explain why `completed == maximum` must return false.
2. Read the evaluation diff: explain the `<` to `<=` regression and its boundary.
3. Trace `prepare`: PR API identity, merge base, pinned Git diff, current snapshot.
4. Trace `analyze`: cached review lookup, system prompt, schema, one API call.
5. Trace `validate_content`: severity, LEFT/RIGHT, actual hunk lines, completeness.
6. Trace `payload` and `publish`: commit-bound inline comment, marker, reconciliation.
7. Explain why a published high finding and a failed gate are compatible outcomes.
8. Explain why branch protection is needed to turn the failed check into a merge block.

## Questions Julia should be able to answer

- Why use two jobs? Which credential does each job receive?
- Which code comes from the PR and which code executes in the privileged jobs?
- What happens when Claude times out or produces an invalid line number?
- How do reruns avoid duplicate findings and additional model calls?
- What happens if another commit arrives before publication?
- Why does a complete response not prove the code is correct?
- How can a false positive block a PR? How would you investigate it?
- What did the live experiment actually establish, and what remains unverified?

Independent explanation is not yet demonstrated. The private live experiment
verified clean/defect/fix reviews and cached rerun behavior, but model quality
evidence is limited to those cases and severity was over-calibrated. The current
private GitHub plan does not enforce merge blocking. Do not
claim production use, independent implementation, hostile-code containment or
general review accuracy from the local tests.
