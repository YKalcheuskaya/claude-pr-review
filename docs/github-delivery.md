# Operator delivery and recovery

## Historical delivery

Private publication occurred October 4, 2026; v1 live verification followed October 5. Contextual v2 release and the live-discovered anchor repair merged after credential-free Verify before the October 11 smoke. All six completed release/repair/demo branches were later removed; demo PRs were closed unmerged and main history preserved. See [development history](development-history.md), [v1 results](live-verification-2026-10-05.md), and [v2 results](v2-live-verification-2026-10-11.md). These dated operations grant no current permission.

## Before a future delivery

Review the exact source diff, run offline verification, reconcile remote drift, and obtain explicit operator authorization for remote writes, paid calls, workflow activation and visibility changes. Keep secrets in the hosting secret store, never in source or artifacts. Candidate Verify executes without provider credentials; privileged review jobs execute trusted base scripts and treat PR code as data. Do not activate the disabled paid workflow merely to test documentation.

A severity check only blocks merging if an enforced required rule exists. Private protection returned 403 in the recorded experiment; enforcement remains unverified. No automatic merge or PR approval is provided.

## Recovery

- Missing secret or unsupported model: analysis fails; diagnose before any authorized retry.
- Stale head/base/metadata: preserve the old trace and prepare the new snapshot. Base updates alone do not trigger the selected PR events.
- Uncertain POST: inspect submitted/pending reviews and the hidden marker read-only. The publisher does not send a second POST in the same invocation.
- False positive: verify cited source and semantic dependency; a failed severity check is not evidence that the finding is correct.
- Timeout or unknown billing: retain the reservation and inspect diagnostics; no automatic paid retry.

Use the [evaluation guide](v2-evaluation.md) for the separately authorized paid adapter and dated budget assumptions. Security/deadline gaps in [architecture](v2-architecture.md) remain unresolved.
