# Private GitHub live verification

Verified October 5, 2026. Julia authorized paid calls on the cheapest compatible
model and complete flow testing, then added the key directly to GitHub Settings.
No credential entered source, artifacts or this report. Repository visibility
remained private. No demonstration PR was merged.

## Scope and observations

Base for all four workflow attempts:
`ed1c74574ebef290a7dcd44bc114656215aeff50`.
Model: `claude-haiku-4-5-20251001`; config:
`v1-files20-bytes61440-tokens4000-seconds60`.
Three model calls, zero paid retries, two PRs, one correction and one cached rerun.

| Snapshot | Evidence | Actual review | Gate / ordinary Verify |
| --- | --- | --- | --- |
| Clean `649a9d57bd36224ccfe0f5ebdefcde76247cd8bc` | [PR 1](https://github.com/YKalcheuskaya/claude-pr-review/pull/1), [review run](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37380870882/attempts/1), [Verify](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37380870838) | Complete, no findings; bot review `5421229938` | Passed / passed on Python 3.10 and 3.12 |
| Same clean snapshot, rerun | [Attempt 2](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37380870882/attempts/2) | Byte-identical result; still exactly one review; no new model call inferred from validated cache reuse | Passed / no new candidate test run |
| Defect `fca00118132608bc8ff8baf9225e732d50a0a6c0` | [PR 2](https://github.com/YKalcheuskaya/claude-pr-review/pull/2), [review run](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37381013348), [Verify](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37381013324) | Complete; one `critical` finding on RIGHT line 12, `src/pr_review/demo.py`; review `5421242148`, [inline comment](https://github.com/YKalcheuskaya/claude-pr-review/pull/2#discussion_r4189396960) | Failed for severity / boundary test failed on Python 3.10; Python 3.12 cancelled by matrix fail-fast |
| Fixed `693d152832b187e45121a1a4e71980cb8b1753f8` | [Same PR 2](https://github.com/YKalcheuskaya/claude-pr-review/pull/2), [review run](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37381197098), [Verify](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/37381197015) | Complete, no findings; new review `5421259357`; original review and inline comment remain | Passed / passed on Python 3.10 and 3.12 |

PR 2 initially changed `< maximum` to `<= maximum`. The existing boundary test
failed locally and remotely without modifying its expected answer. Correcting
the condition left only a docstring change against the original base, so the
third response correctly described the displayed diff as documentation-only.
This verifies new-commit processing, not semantic memory of the earlier review.

Both analysis and publication ran base-commit scripts. Analysis had read-only
GitHub permissions and the Anthropic key; publication had scoped PR-write and
no Anthropic key. COMMENT reviews worked while
`can_approve_pull_request_reviews` remained false and default permissions stayed
read-only. No automatic approval setting was needed.

## Usage and cost

| Paid call | Input tokens | Output tokens | Model duration | Estimated USD |
| --- | ---: | ---: | ---: | ---: |
| Clean | 912 | 64 | 5.829 s | 0.001232 |
| Defect | 973 | 273 | 4.831 s | 0.002338 |
| Fixed | 912 | 58 | 2.682 s | 0.001202 |
| Total | 2797 | 395 | 13.342 s | 0.004772 |

Estimate uses the documented $1/million input and $5/million output token rates,
checked October 4–5, 2026: [Haiku pricing and active model ID](https://platform.claude.com/docs/en/models/haiku-4-5/overview).
This is model-token cost from response usage, not a verified billing invoice or
GitHub Actions charge; taxes and other account activity are excluded. The rerun
retains the original usage and duration, not newly billed usage. No account-wide
spend/balance verification was performed.

## Claim boundaries and remaining blocker

- The concrete seeded boundary defect was detected at the correct diff location.
  The two documentation-only snapshots had no findings. This tiny sample does
  not establish general accuracy, prompt-injection robustness or production readiness.
- Severity `critical` is the model's output, not an endorsed assessment. For this
  pure boolean demo, one excess retry is real, but catastrophic impact is not
  demonstrated. Treat the severity as over-calibrated; do not train the expected
  outcome to match it. No prompt or severity policy changed during the experiment.
- The severity gate really failed and publication really succeeded. Actual merge
  prevention was **not** verified or enabled. The protection API returned HTTP 403:
  "Upgrade to GitHub Pro or make this repository public to enable this feature."
  The defective snapshot had merge state `UNSTABLE`, which is not proof of a
  prohibited merge. No purchase, visibility change or experimental merge occurred.
- Timeout, malformed output, stale snapshots and ambiguous writes remain covered
  by deterministic tests, not intentionally induced paid GitHub calls here.
- Julia's independent explanation, Sonnet comparison and private branch-rule
  enforcement remain separate work. The original full completion criterion has
  not been met while protection is unavailable.

## Retained evidence and operational state

Validated input/result artifacts are retained under `evaluation/live-clean/`,
`evaluation/live-clean-rerun/`, `evaluation/live-defect/` and
`evaluation/live-fixed/`. They contain only the demonstration diff and model output.
The original clean artifact was saved before rerunning; GitHub no longer exposed
that first-attempt artifact through the later download lookup. The rerun artifact
was downloaded separately and compared byte-for-byte with the retained original.

After the third call and successful cached rerun, the Claude PR review workflow
was disabled (`disabled_manually`) to prevent unintended future charges, as the
bounded delivery plan required. Ordinary Verify remains enabled; the secret and
model variable remain configured. Re-enable the workflow in Actions when another
bounded demonstration or ongoing paid operation is authorized. The two PRs remain
open as private evidence, not pending merge requests for production use.
