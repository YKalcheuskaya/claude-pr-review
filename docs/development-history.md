# Development history

The project evolved from a diff-only reviewer into a bounded contextual reviewer, then received a repair prompted by a real end-to-end failure. The implementation was AI-assisted. The commits record implementation batches and verification milestones; they do not establish independent authorship or a test-first development sequence.

| Milestone | Commit | What changed and why |
| --- | --- | --- |
| Initial v1 | `31c7d68` | Built the diff reviewer, structured result validation, severity gate, cache, separate analysis/publication jobs and offline tests. |
| Package and delivery setup | `db28be8` | Renamed the Python package from `prreview` to `pr_review` and prepared private GitHub delivery. |
| GitHub verification | `ed1c745` | Recorded private publication and remote verification. |
| Live v1 experiment | `a89a22a` | Recorded clean/defect/fix reviews and cached reuse. Also documented over-calibrated severity and unavailable private merge protection. |
| Contextual v2 | `06d0f7c` | Added bounded read-only repository exploration, validated source citations, partial-coverage reporting, diagnostic bundles and evaluation tooling. |
| Cross-file smoke fixtures | `a44fdc0` | Added separate Python and JavaScript producer/consumer examples for a live smoke, outside the held-out corpus. PR #3 integrated this and the v2 implementation. |
| Repair after live failure | `da80346` | A live result anchored a finding outside the changed hunk. Added review-body fallback for valid out-of-hunk anchors and a cache-only guard that prevents provider initialization on a cache miss. PR #5 integrated the repair. |
| Live v2 results | `181183d` | Recorded defect detection, corrected and clean snapshots, and a zero-call cache rerun. Retained partial coverage and false positives as explicit limitations. |

The two merge commits preserve the actual release and repair review boundaries. For a short overview, use `git log --first-parent --oneline`; for implementation commits and their merge relationships, use `git log --graph --oneline main`.

## Demonstration branches

The v1 demonstration PRs #1/#2 and v2 demonstration PRs #4/#6 were experiments, not missing product changes. Seeded defects were corrected on their demonstration branches. Their final differences were documentation or equivalent local-variable refactors.

On October 11, 2026, all six completed release/repair and demonstration branches were deleted locally and remotely; PRs #4/#6 were closed without merge. Only `main` remains. The closed PRs and their reviews remain historical evidence; deleting a branch does not erase those records. No main commit was rewritten, and no demonstration-only change was merged for cleanup.

See the [v1 live results](live-verification-2026-10-05.md) and [v2 live results](v2-live-verification-2026-10-11.md) for immutable snapshots, run links and limitations. Those reports describe conditions at the time of each experiment. General review-quality improvement and enforced merge blocking remain unverified.
