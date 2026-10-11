# Version 2 offline evaluation and separately authorized pilot

As of October 10, 2026, this is an offline synthetic corpus and reporting mechanism. It does not establish better model quality. No paid call is necessary to prepare cases or verify the runner. Historical version 1 evaluation artifacts remain unchanged.

## Corpus and separation

`evaluation/v2/manifest.json` lists three development cases and twelve held-out cases. Each held-out stack has two seeded cross-file regressions and two correct changes: Python, Java/Spring, and JavaScript/TypeScript/React. Related SQL and configuration files are present. Each seeded defect changes one file while the relevant contract remains in an unchanged file. Correct cases include equivalent refactors and a Spring variable rename with explicit binding, where a superficial warning would be a false positive.

Only `evaluation/v2/cases/` provides code and neutral PR metadata. Separate `evaluation/v2/labels/` files hold maintainer-defined expected defects, severities and rationales. Do not send the labels, this guide, the manifest split information, or evaluation IDs as a prompt's instructions. The prepared repository contains only fixture source files. The separate `case-record.json` carries the case ID and local repository path solely for result association; it is never a model input. The corpus is small and synthetic; independent label review remains pending. No fixture is represented as a real production incident.

Development case 01 deliberately changes the representation of an existing missing-user failure without creating a new regression; reporting that old problem as new would be incorrect. Development case 02 is a valid independent configuration change. Development case 03 has an endpoint mismatch. These may guide prompt development. Held-out outcomes must not be used to revise prompts or labels during the same comparison. An agent implementing the corpus has seen the labels; future evaluation must preserve separation at the model request boundary rather than claiming that the corpus author was blind.

## Prepare and freeze without credentials

Run from the project directory:

```sh
python scripts/evaluate-v2.py prepare --split development --output outputs/v2-development
python scripts/evaluate-v2.py prepare --split held-out --output outputs/v2-held-out
python scripts/evaluate-v2.py freeze --policy src/pr_review/v2.py --policy src/pr_review/context.py --output outputs/v2-freeze.json
```

Use the actual paths containing the final prompts, schemas and tool policies in `--policy`; repeat the option for every policy source. The example names are illustrative if module organization differs. Freeze after development and before any held-out request. The seal hashes actual policy content, every case and every label. Reports reject changes to sealed sources and do not overwrite an existing seal. Keep the seal with recorded results. Changing a policy or oracle starts a new experiment and must not silently replace the old comparison.

Preparation creates a local Git repository per case, with before/after commits and no remote. It writes validated `diff-input.json` and `context-input.json` application inputs with the same snapshots, diff, title, body and model, using the normal prepare path with an offline PR metadata stub. It also writes `case-record.json` for local association only. Normal validation must still run when analyzing those inputs. Context mode uses the fixture Git repository to access unchanged files; diff mode receives no additional context. Both modes must use the same model, remove the old retry-demo hint, and refer to the same sealed policy set. The normal v2 budgets and evidence validators apply in both modes. Do not execute fixture code through model tools.

The `run` adapter executes one review through the normal v2 analysis loop only after separately recorded explicit human pilot approval. It has no GitHub client, publication action or retry. Preparation, a flag, a reference string, or possession of an API key does not grant approval. The current implementation has not been used for a paid v2 call.

## Pilot budget and preflight

The planned model is `claude-haiku-4-5-20251001`. Verify current availability and input/output prices against official provider sources immediately before the pilot; the offline runner does not pretend to verify them. Record the dated references. Separate explicit authorization must identify the pilot, private smoke reviews and total ceiling.

The planned reservation is three context development reviews ($0.60), twelve context held-out reviews ($2.40), twelve diff held-out reviews ($0.60), and two private context smoke reviews ($0.40): $4.00. The remaining $1 of the stated $5 ceiling is not automatically spendable. A conservative reservation may reject a theoretically allowed request whose maximum token usage exceeds its per-review envelope; reduce scope or obtain a revised explicit budget before sending it. The architectural maximum of five calls is not itself a promise that five full-sized calls fit $0.20.

Before any external request, one serial ledger owner must use `reserve`, with token estimates covering all planned input calls and all output maxima, including final review. Rates are dollars per million tokens. The estimate must fit $0.20 for context or $0.05 for diff. The ledger holds the entire per-review cap and never refunds failure, timeout, unknown outcome, or lower observed usage. Each retry needs a new reservation and authorization within the approved scope. Smoke reviews share this same ledger; do not maintain separate smoke and evaluation totals. The ledger is not safe for concurrent writers.

```sh
python scripts/evaluate-v2.py reserve --ledger outputs/v2-budget.json --run-id development-01-context --mode context --input-tokens 1000 --output-tokens 4000 --input-rate 1 --output-rate 5 --authorization-reference approved-pilot-record --pricing-reference dated-official-pricing-record
```

The rates and token counts above are arithmetic examples, not verified current pricing or a real preflight. A reference string is a record of approval, not proof that approval exists. The authorized runner preserves the reservation before entering analysis; the normal SDK loop counts calls, preflights input tokens and reserves final output before each request. The operator must check the actual approval before invoking it. Use the normal bounded review loop rather than bypassing its per-call time/token checks. Provider preflight token counting and failure/unknown outcomes must be recorded even when no valid review is returned. Observability adds no model calls. Estimates are not an account-wide invoice guarantee.

## Separately authorized execution

After obtaining explicit human pilot approval, verifying model availability and recording current official pricing, use the prepared repository and its mode input. Pass the same shared ledger to development, held-out and smoke operations. The following is a command template, not permission to execute it:

```sh
python scripts/evaluate-v2.py run --authorize-paid --authorization-reference approved-pilot-record --pricing-reference dated-official-pricing-record --input-rate 1 --output-rate 5 --input outputs/v2-held-out/heldout-01/context-input.json --repository-path outputs/v2-held-out/heldout-01/repository --freeze outputs/v2-freeze.json --ledger outputs/v2-budget.json --run-id heldout-01-context --output outputs/v2-heldout-01-context-result.json --diagnostics-dir outputs/v2-heldout-01-context-diagnostics
```

The runner validates input, fixed model, frozen actual prompt/schema/tool policy modules, immutable snapshot existence and exact Git diff before paid execution. It reserves the full mode cap atomically before calling analysis, with a worst-case token envelope: five 24,000-token inputs plus 12,000 maximum output tokens for context; one 24,000-token input plus 4,000 output tokens for diff. Higher supplied rates than the implemented $1 input/$5 output per million are rejected pending revised budget policy; these values are implementation assumptions and still require live pricing verification. The normal SDK loop imposes additional per-request and final-call budget checks. No GitHub credentials or API client are used. Only the explicitly authorized provider is contacted. Failures preserve the full unknown reservation, produce sanitized diagnostics and never trigger a retry. Existing result files are never overwritten; manual retries need new run IDs and fresh reservations. The record's `reserved-or-unknown` status remains deliberately conservative even after successful completion; observed cost belongs in adjudication records.

## Record and adjudicate

Keep raw sanitized model results and diagnostic bundles separately. Build an adjudication JSON file, referencing its sealed `freeze_id` and `model`, with one row for each held-out case/mode pair. Never treat a model's self-rating as the oracle. A reviewer assigns each accepted finding to a known expected defect or `null` for an unsupported finding, verifies cited Git evidence and severity, and records their identity and rationale. A second report of the same expected defect counts as an extra false positive rather than extra recall. A failed review has no accepted findings.

```json
{
  "freeze_id": "sha256-from-freeze-file",
  "model": "claude-haiku-4-5-20251001",
  "runs": [{
    "case_id": "heldout-01",
    "mode": "context",
    "status": "complete",
    "latency_ms": 1200,
    "cost_usd": "0.003",
    "findings": [{
      "expected_id": "regression-1",
      "severity": "high",
      "evidence_correct": true,
      "adjudicator": "independent-reviewer",
      "rationale": "The cited after-snapshot column is absent from the unchanged schema."
    }]
  }]
}
```

Status is `complete`, `incomplete`, or `failure`. Latency and estimated model cost can be `null` when unavailable; unknown does not mean zero. Preserve failed runs and record their reservations in the ledger. The reporting cost fields describe available observations; ledger totals remain the conservative budget authority. Keep the linkage to original run/result/trace files in a sidecar experiment record.

```sh
python scripts/evaluate-v2.py report --records outputs/v2-adjudication.json --freeze outputs/v2-freeze.json --output outputs/v2-report.json
```

The report measures finding precision, defect recall, false positives, false high/critical findings on clean cases, severity calibration for matched defects, evidence correctness, incomplete/failure rate, observed latency and cost. Null precision means there were no accepted findings. A partial set cannot satisfy the paired comparison criterion. The observed criterion requires all 24 pairs, at least two additional true defects in context mode and no increase in false high/critical findings on clean cases. Even an observed pass remains provisional until independent oracle review; a failed comparison must be retained without relabeling examples. This sample does not establish production quality, GitHub behavior, or Julia's independent understanding.
