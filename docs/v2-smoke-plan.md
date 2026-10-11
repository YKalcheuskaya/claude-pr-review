# Historical v2 smoke design

**Planned October 10; executed October 11, 2026.** The actual [live report](v2-live-verification-2026-10-11.md) supersedes proposed outcomes and counts. Personal approval and budget administration are preserved privately in the parent workspace; this guide grants no new execution permission.

The design used independent Python and JavaScript producer/consumer fixtures outside the held-out corpus. Introduce a Python key-change regression, observe evidence-linked detection and severity gating, correct it, then verify cache-only reuse on the unchanged corrected snapshot. A separate clean JavaScript refactor checks for unsupported findings. Inspect actual imports rather than inferring cross-language dependency from matching names.

Observed execution included an initial failed validation and a separately reviewed repair. Three successful snapshots retained partial coverage; false positives occurred. An unchanged guarded rerun made zero new calls and created no duplicate review. The historical cost report distinguishes token estimates from conservative reservations and invoices.

For any future smoke, obtain explicit paid and external-action authorization, verify current exact model/rates, reserve the whole envelope serially before calling, preserve failures, and disable paid execution when the bounded experiment ends. Do not treat this old scenario as an account-wide spending guarantee or a reason to rerun the model. Use [offline verification](walkthrough.md) first.
