# GitHub delivery and bounded live demonstration

Updated October 5, 2026. Julia authorized private repository creation and source
publication, then paid cheapest-model calls and full GitHub flow verification.
She added the API secret directly in GitHub and confirmed readiness. The bounded
experiment is recorded in [live verification](live-verification-2026-10-05.md).
Public visibility, automatic merge and a Sonnet comparison are not authorized.

## Authorized initial publication

Create private `YKalcheuskaya/claude-pr-review`, configure its HTTPS remote, publish
the reviewed `main` source including the approved `pr_review` package rename, and
observe the credential-free Verify workflow. Do not overwrite an existing repository.
No Claude API secret is configured in this step; a push to `main` cannot trigger
the PR-only model workflow. Never configure a remote for the parent career repository.

## Authorized bounded live experiment

| Item | Proposed value |
| --- | --- |
| Repository | `YKalcheuskaya/claude-pr-review`, created privately October 4 |
| Visibility | Private; any public release needs separate approval |
| Remote | `https://github.com/YKalcheuskaya/claude-pr-review.git` |
| Source | Current published `main`; pin its exact SHA before the experiment |
| Authentication | Julia's existing GitHub session; runtime uses `GITHUB_TOKEN` |
| Secret | Julia supplies `ANTHROPIC_API_KEY` directly in GitHub Settings |
| Initial model | `claude-haiku-4-5-20251001`, subject to availability check |
| Model budget | Three new calls maximum, $2 ceiling, auto-reload off |
| Actions | Add secret/variable, use scoped COMMENT-review permission, protect `main` if available, create two demo PRs and push one correction |
| Merge | Manual; no merge authorized by this package |
| Sonnet | Separate later experiment after Haiku flow evidence is reviewed |

The repository stays private. The branch-protection API returned HTTP 403 requiring
GitHub Pro or public visibility. Do not make it public or purchase a subscription
without Julia's direction. Enforced merge blocking remains unverified and unavailable
on the current plan. The publisher submitted COMMENT reviews without enabling
automatic PR approval.

## Live steps after authorization

1. Review the exact local commit, publish it to `main`, and run Verify. Confirm model
   availability via official documentation or Julia's Console before enabling calls.
   Configure the secret and model variable; keep billing auto-reload off.
2. Create `codex/demo-clean`, adding a small explanatory docstring in the demo module.
   Open a PR. Expect one review and no actionable defect; retain actual findings,
   usage, latency, gate conclusion and run URL even if the expectation fails.
3. Create `codex/demo-defect` from `main`, changing `< maximum` to `<= maximum`.
   Open a PR. Record whether Haiku catches the known boundary defect and whether
   it labels it high/critical. Keep the failing deterministic test visible too.
4. Check that the maintainer cannot merge when the required gate fails. This must
   be a real rule enforcement check, not an inference from a red workflow.
5. Push the correction to the same defect PR. This consumes the third planned call.
   Confirm the new commit receives a new review, old discussions remain, and the
   required check reflects only the corrected snapshot.
6. Rerun a successful workflow once: verify reuse, no duplicate review and no new
   model call. Stop if the stored marker/result is missing or inconsistent.
7. Record PR/run URLs and expected versus observed findings in a new dated English
   report, including false positives, missed defects, usage and available cost data.

The $2 ceiling must be monitored in Console; the workflow has no durable total
spend ledger. Stop at three calls, unknown billing, unavailable model or ambiguous
publication. Disable the review workflow after the experiment to prevent unapproved
future paid calls. A failed call may already be billed and is not repeated automatically.

## If Haiku does not produce the desired blocking finding

Report the observation honestly. Local fixtures already establish severity gating;
they are not a substitute for observing model behavior. Ask for a bounded follow-up
before additional calls. After the flow works, choose an available exact Sonnet ID,
update `CLAUDE_MODEL`, and repeat the same scenarios without changing expected
answers post hoc. Compare semantic detection, unsupported findings, delay and cost.

## Operational recovery

- Missing secret/invalid model: analysis fails and the gate fails; fix configuration
  before an explicitly intended retry.
- Stale snapshot: run on the latest PR commit. Base-branch updates alone do not
  trigger the selected events; require an up-to-date branch and push its update.
- Ambiguous review POST: inspect submitted/pending reviews and the hidden marker.
  The tool reads state but never sends a blind second POST.
- High false positive: inspect code and finding; improve policy through a reviewed
  base-branch change and a bumped config version. Do not mark AI output correct
  merely because it blocked the merge.
- Fork/draft/bot: no AI coverage in v1; the successful skip is explicitly not a review.
