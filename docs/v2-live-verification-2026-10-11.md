# V2 private end-to-end verification

**Verified October 11, 2026.** This bounded smoke exercises three review snapshots in two private demo PRs, plus an unchanged cache rerun. It verifies the live mechanism, not general review quality or the twelve-case held-out improvement criterion. Julia approved private release/repair delivery and the paid smoke, including additional calls needed after the first failure.

## Delivery and snapshots

Old v1 PRs [1](https://github.com/YKalcheuskaya/claude-pr-review/pull/1) and [2](https://github.com/YKalcheuskaya/claude-pr-review/pull/2) were closed without merge; their branches and reviews remain. Release [PR 3](https://github.com/YKalcheuskaya/claude-pr-review/pull/3) and repair [PR 5](https://github.com/YKalcheuskaya/claude-pr-review/pull/5) merged only after successful Verify on Python 3.10 and 3.12. Trusted main for all successful smoke snapshots was `fded6a76870623f070a663188600a4f0c8230da2`. The repair milestone passed 102 local tests.

The standalone Python and JavaScript fixtures are outside the held-out corpus. Each consumer imports its own language's producer. Independent deterministic checks establish the Python key-change defect (`KeyError`) and correct Python/JavaScript output (`Invoice total: $108.00` for 100/8). Claude's context tools read Git blobs; they do not execute PR code.

| Case | Head | Live run | Observed outcome |
| --- | --- | --- | --- |
| First Python defect attempt | `c512acd2f352801266bc27884ba2ccaa67076cbe` | [38101780126](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/38101780126) | Analysis validation failed; no review published |
| Python defect after repair | `e5857be0e771fd8c1d5c870a4ae1bcf29cc7f0a8` | [38159263748](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/38159263748) | Analysis succeeded; high finding failed severity gate |
| Corrected Python | `7e18fe1ea087284fa4a7790ea13bfcb45a08a69f` | [38159397996, attempt 1](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/38159397996/attempts/1) | Analysis and gate succeeded with partial coverage |
| Corrected Python cache | Same immutable snapshot and identity | [38159397996, attempt 2](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/38159397996/attempts/2) | Cache hit; zero new model calls and no duplicate review |
| JavaScript clean | `be4a4cdf0d4b0415db2fa339ed49fafff60cb556` | [38159680923](https://github.com/YKalcheuskaya/claude-pr-review/actions/runs/38159680923) | Analysis and gate succeeded, no findings, partial coverage |

## What the live experiment proved

The first attempt retained diagnostic artifacts despite having no mandatory result artifact. It exposed a well-formed anchor on an unchanged consumer that the validator rejected. The repair routes such out-of-hunk anchors to the review body while retaining strict anchor shape and source validation. It also clarifies the prompt about dependency proof and duplicate root causes. These prompt changes are mitigation, not proof of better quality.

The repaired defect review [5484213731](https://github.com/YKalcheuskaya/claude-pr-review/pull/4#pullrequestreview-5484213731) published the real Python regression [inline at producer line 6](https://github.com/YKalcheuskaya/claude-pr-review/pull/4#discussion_r4242486864). The gate failed because of that high finding, rather than an infrastructure failure. The unsupported medium cross-language finding appeared in the review body.

The corrected review [5484219699](https://github.com/YKalcheuskaya/claude-pr-review/pull/4#pullrequestreview-5484219699) preserved the contract and passed the gate with one low finding. Both snapshots explicitly retained partial coverage. Exploration reached its conservative input budget, and broad searches omitted credential-like test blobs. A successful partial gate is not a complete-clean certification.

All retained source metadata for the repaired defect and corrected snapshots matched immutable Git snapshots, blobs, ranges and text hashes and appeared in the final model request. Actual tools exercised all three APIs: defect `list_files` once, `search_text` twice, `read_file` three times; corrected three, two and three respectively. Both jobs' diagnostic manifests for each successful snapshot were complete, with no truncation, dropped events or unfinished operations.

The cache rerun used `CLAUDE_CACHE_ONLY=true`, which fails before provider initialization on a miss. Both jobs logged `cache.hit` with `current_calls=0` and `current_cost=0`; no `sdk.start` event appeared. The result file was byte-identical to attempt 1. PR 4 still had exactly the original defect and corrected reviews, with one review at the corrected SHA. Original usage retained in the cached result is historical usage, not new spending.

The clean JavaScript review [5484232179](https://github.com/YKalcheuskaya/claude-pr-review/pull/6#pullrequestreview-5484232179) published no findings and passed with partial coverage after four exploration calls plus a final call. Its limitations explicitly include tool-call exhaustion and denied/omitted paths. Its actual tools were two `list_files`, two `search_text` and five `read_file` operations (one denied directory read, four successful reads). All thirteen sources retained in the final request matched Git; the no-findings result has an empty `sources` list by design. Both jobs' manifests were complete without truncation, dropped events or unfinished operations. Python 3.10/3.12 Verify passed on all three successful snapshots.

## Quality limitations

- The first failed attempt found the real defect, duplicated it, and invented an independent JavaScript dependency. It remains a failed mechanism observation with mixed model quality.
- The repaired defect review had one true high finding and one unsupported medium cross-language finding. The JavaScript consumer imports its own producer; matching names do not prove a Python dependency.
- The clean Python refactor had one unsupported low documentation finding. No documentation mentioned the renamed local variable; a hypothetical introspection concern did not establish a defect. Its evidence description also attributed dictionary access to consumer line 6, although access occurs on line 7. Mechanical citation validation cannot establish semantic correctness.
- Three snapshots do not establish precision/recall or an improvement over v1. The paired held-out evaluation and independent interview explanation remain unperformed.

## Usage and retained evidence

| Paid attempt | Model calls | Input tokens | Output tokens | Estimated USD |
| --- | ---: | ---: | ---: | ---: |
| Original defect failure | 3 | 14,856 | 1,891 | 0.024311 |
| Repaired defect | 3 | 15,099 | 1,444 | 0.022319 |
| Corrected Python | 4 | 19,620 | 1,220 | 0.025720 |
| JavaScript clean | 5 | 24,226 | 820 | 0.028326 |
| Cache rerun | 0 new | 0 new | 0 new | 0.000000 |

Model: `claude-haiku-4-5-20251001`. Estimates use $1 input/$5 output per million tokens, checked against [first-party pricing](https://platform.claude.com/docs/en/about-claude/pricing) October 10. Total estimated model-token cost: **$0.100676 across 15 calls**, including the failed first attempt. They are calculated token costs, not an invoice. Four conservative $0.20 paid envelopes remain reserved ($0.80 total), including the failed first attempt. Cache had a zero-paid-call guard. No automatic retries, Sonnet substitution or full held-out run occurred.

Sanitized downloaded inputs, results, final requests, tool traces, manifests, authorization, shared budget and run index are retained privately in the parent workspace's ignored `resources/claude-pr-review-v2-smoke-2026-10-10/`. The tracked report retains durable conclusions; GitHub's short-lived artifact retention is not the only evidence copy. No credentials are included.

Final repository/workflow state verified: private; paid Claude review workflow `disabled_manually`; Verify `active`; demo PRs [4](https://github.com/YKalcheuskaya/claude-pr-review/pull/4) and [6](https://github.com/YKalcheuskaya/claude-pr-review/pull/6) open and unmerged. The cache-only variable was restored to false after its guarded test. No ongoing paid execution is enabled. Private merge enforcement remains unverified; a red severity check is not proof that GitHub blocks merging.

## Subsequent branch cleanup — October 11, 2026

After the experiment, Julia authorized removing the unused branches. PRs 4 and 6 were closed without merge, and all six release/repair and demonstration branches were deleted locally and on GitHub. Only main remains; its existing commits and the review evidence were preserved. The repository remains private, Claude PR review remains disabled, and Verify remains active. See the [development history](development-history.md) for the milestone map and rationale.
