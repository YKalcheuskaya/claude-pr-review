# Evaluation

The evaluation tools compare context-aware and diff-mode reviews on a small synthetic corpus. Fixture preparation and reporting run offline; model execution is a separate paid operation. The corpus supports repeatable experiments, not a production-quality claim.

## Corpus and Separation

The corpus contains three development cases and twelve held-out cases across Python, Java/Spring and JS/TS/React, including SQL and configuration. Each held-out stack has two seeded cross-file regressions and two correct changes. The relevant contract can remain in an unchanged file.

Code and neutral PR metadata live in `evaluation/corpus/cases/`; expected defects, severities and rationales live separately in `evaluation/corpus/labels/`. Only fixture source and neutral metadata belong in model input. Labels, case IDs and split information must stay outside the request. The corpus and labels are maintainer-authored; independent label review is needed before making comparative quality claims.

## Prepare and Freeze

Run from the project root after installation:

```sh
.venv/bin/python scripts/evaluate.py prepare --split development --output outputs/development
.venv/bin/python scripts/evaluate.py prepare --split held-out --output outputs/held-out
.venv/bin/python scripts/evaluate.py freeze --policy src/pr_review --output outputs/freeze.json
```

Preparation creates one local Git repository per case, paired `context-input.json`/`diff-input.json` files and a local association record. Existing case directories are not overwritten. The freeze seals the model, cases, labels and all runtime Python modules, the review prompt, evaluation runner and any additional supplied policy files. Freeze after development and before held-out execution; keep all results associated with that seal. A changed policy or oracle requires a new experiment.

Use identical snapshots, model and sealed policies in both modes. Diff mode includes bounded displayed hunks but does not explore related files; see [context and evidence](architecture.md#context-and-evidence) when interpreting comparisons. Fixture code is inspected as data, never executed by model tools.

For a credential-free replay, follow the [walkthrough](walkthrough.md).

## Run a Paid Evaluation

Verify model availability and prices, select the model and token limits through [runtime configuration](runtime-configuration.md), and run `show-config` before preparation. Prepared inputs, freeze and execution must share the same configuration. The runner requires explicit paid authorization and pricing references; its command flags record an operator decision rather than grant one.

```sh
.venv/bin/python scripts/evaluate.py run --help
```

Supply the prepared input, fixture repository, freeze, output and diagnostics paths; a unique run ID; one shared ledger; and input/output rates matching configuration. Existing outputs are not overwritten. The runner performs no GitHub publication.

The ledger reserves the full configured review ceiling before analysis and retains the reservation on failed or unknown outcomes. Its aggregate ceiling is $4; each mode defaults to $0.20 for context and $0.05 for diff unless a review ceiling is configured. One serial owner must manage the ledger because concurrent writers are unsupported. Conservative worst-case token estimates must fit the review ceiling. The normal analyzer additionally enforces per-attempt cost reservations, transient retries and deadlines. A manual rerun needs a new run ID and reservation.

## Adjudicate and Report

A human reviewer checks each finding against the expected defect and immutable cited evidence, records severity and rationale, and marks unsupported findings explicitly. Duplicate reports of the same defect count as extra false positives. Failed reviews have no accepted findings; unavailable latency or cost remains null rather than zero.

Build an adjudication JSON file containing the seal's `freeze_id`, its `model` and a `runs` array. Each run records `case_id`, `mode`, `status` (`complete`, `incomplete` or `failure`), `latency_ms`, `cost_usd` and `findings`. Each finding records `expected_id` (or null), `severity`, `evidence_correct`, `adjudicator` and `rationale`.

```sh
.venv/bin/python scripts/evaluate.py report --records outputs/adjudication.json --freeze outputs/freeze.json --output outputs/report.json
```

The report measures precision, recall, false positives, false high/critical findings on clean cases, severity calibration, evidence correctness, incomplete/failure rates, latency and observed cost. The paired criterion requires all 24 case/mode results, at least two additional detected defects in context mode and no increase in false high/critical findings on clean cases. Partial results cannot satisfy it. Preserve negative outcomes and original labels; a synthetic comparison remains provisional pending independent oracle review.
