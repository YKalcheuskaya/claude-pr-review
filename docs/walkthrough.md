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

Independent explanation and live model quality are not yet demonstrated. Do not
claim production use, independent implementation, hostile-code containment or
general review accuracy from the local tests.
