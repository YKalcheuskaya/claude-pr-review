# Runtime Configuration

Reference for operators who need to change model selection, review depth or gate policy. For installation and the standard workflow, start with the [quick start](../README.md#quick-start).

## Configure Repository Variables

Open this repository on GitHub → **Settings → Secrets and variables → Actions → Variables → New repository variable** (or edit an existing one). Use **repository** variables: only analysis attaches the protected `claude-review` Environment. Keep these settings as repository variables so both jobs resolve the same policy. The workflow forwards the same settings to analysis and publication. No source edit or commit is needed for the variables below.

| Repository variable | Default | Accepted value / effect |
| --- | --- | --- |
| `CLAUDE_MODEL` | `claude-haiku-5-5` | Concrete Claude model ID; no model allowlist or fallback substitution |
| `CLAUDE_INPUT_USD_PER_MILLION` | `0.50` for the default model | Positive decimal input-token price; required for any other model |
| `CLAUDE_OUTPUT_USD_PER_MILLION` | `2.50` for the default model | Positive decimal output-token price; required for any other model |
| `CLAUDE_MAX_REVIEW_USD` | `0.20` context / `0.05` diff | Positive decimal per-review token-cost reservation ceiling |
| `CLAUDE_REVIEW_MODE` | `context` | `context` explores related code; `diff` uses the narrower baseline described in the [architecture](architecture.md) |
| `CLAUDE_FAIL_SEVERITY` | `high` | `low`, `medium`, `high`, `critical`, or `none`; findings at or above the threshold fail the gate |
| `CLAUDE_MAX_EXPLORATION_CALLS` | `4` | Integer `0`–`8`; research operations before the final operation, context mode only; each generation operation permits up to four HTTP attempts for transient failures, subject to budget and deadline |
| `CLAUDE_MAX_TOOL_OPERATIONS` | `12` | Integer `1`–`100`; total tool operations per analysis |
| `CLAUDE_MAX_INPUT_TOKENS` | `24000` | Integer `4096`–`128000`; request admission/token-count limit, not a guarantee the provider supports that size |
| `CLAUDE_EXPLORATION_MAX_OUTPUT_TOKENS` | `2000` | Integer `1`–`16000`; output maximum per research call |
| `CLAUDE_FINAL_MAX_OUTPUT_TOKENS` | `4000` | Integer `1`–`16000`; output maximum for final structured review |
| `CLAUDE_CACHE_ONLY` | `false` | Exact `true` prohibits new model calls; cache miss fails. Use `false` for normal mode. |

Leave optional variables blank or delete them to restore defaults. Enum values are lowercase; numeric control values must be decimal integers without signs/spaces. Invalid settings fail configuration validation before provider use. Decimal amounts allow at most 128 characters and a base-10 exponent within ±100. `none` disables only severity-based failure: invalid evidence/output, provider failures, stale inputs and publication errors still fail. It does not disable validation or approve a PR. Zero research calls skips exploration and reports partial coverage.

## Change Model, Depth or Gate Policy

For a new model, set its concrete `CLAUDE_MODEL` ID and both current token prices. Use an ID available to your account supporting token counting, tool use and JSON-schema output. The ID goes unchanged to provider requests; unsupported models/features and returned-model mismatch fail rather than silently selecting Haiku. Compatibility with every ID is not established by offline tests. See [provider structured-output requirements](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Prices are operator-supplied estimates, not automatic price discovery. The default Haiku reservations use the upper pricing tier (`0.50` input / `2.50` output per million tokens), conservatively covering the configurable input range. At up to 100,000 input tokens, the published rates are `0.10` input / `0.50` output per million; operators can configure those rates when their request limit stays within that tier. See [official pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked October 18, 2026. Verify them before paid use, even for the default model. A higher-cost model or deeper review may need a higher explicitly chosen `CLAUDE_MAX_REVIEW_USD`. Larger limits permit more work but cannot override the fixed time controls or guarantee complete coverage. The application reserves a worst-case final request before exploration; if the budget does not fit, it fails before sending that generation request. This is not an account-wide invoice guarantee.

For less exploration, set `CLAUDE_MAX_EXPLORATION_CALLS=2` and `CLAUDE_MAX_TOOL_OPERATIONS=6`. To fail on medium as well as high/critical findings, set `CLAUDE_FAIL_SEVERITY=medium`. These changes affect application policy; enforced GitHub required checks are still necessary to prevent merging. Do not use a passing partial review as a complete-clean certificate.

## Validate Configuration Locally

From the project root, use the same environment variables as GitHub:

```sh
PYTHONPATH=src .venv/bin/python -m pr_review.cli show-config
CLAUDE_MAX_EXPLORATION_CALLS=2 CLAUDE_MAX_TOOL_OPERATIONS=6 CLAUDE_FAIL_SEVERITY=medium PYTHONPATH=src .venv/bin/python -m pr_review.cli show-config
```

`show-config` prints effective model, budget settings, controls, fixed timers, cache-only switch, prompt and policy hashes as JSON, requires no credentials and makes no network calls. Exit 0 means the local configuration/prompt is valid; exit 2 means invalid settings. A null budget `max_cost` means use the mode default in the table. This does not verify live model availability or current prices. The workflow also runs this validation before preparing a review.

`prepare --model` and `prepare --mode` override the corresponding environment defaults for that preparation. Keep the same effective settings for analysis/publication. The evaluation tool prepares both modes; set the same model/controls when preparing, freezing and executing a comparison. See [evaluation guide](evaluation.md).

## Edit Review Instructions

The prompt is [review-policy.md](../src/pr_review/review-policy.md), a plain Markdown file shipped with the Python package. Edit it through GitHub's file editor or locally, review the change in a PR, and merge it into the base branch. No Python edit is needed. It must be nonempty UTF-8 and at most 32 KiB. The workflow reads the file from its trusted base checkout; a PR changing the prompt is reviewed with the prior base version. The new prompt applies after merge.

Instructions guide the model; application code still enforces schemas, evidence validation, allowed tools, snapshot freshness and fixed resource guardrails. Changing prose does not bypass these checks.

## Apply and Inspect Changes

Variables apply to a new eligible workflow run and do not change existing reviews or an in-flight request. Keep them unchanged during a run: publication revalidates the configuration. Model, effective controls/prices, prompt and actual implementation participate in policy/cache identity. Changed review-policy settings require fresh preparation and prevent reuse of old results. The execution-only `CLAUDE_CACHE_ONLY` switch is deliberately excluded from identity so it can reuse the same review. Inspect `show-config` in the Actions console and the analysis diagnostic `configuration` event for effective settings (`mode` is the actual run mode; `controls.mode` is its preparation default); prompt/policy hashes appear in prepared input and manifests.

Store the provider key only as the `CLAUDE_REVIEW_PROVIDER_KEY` environment secret described below, never Variables or the prompt. The analysis step exposes it to the SDK as `ANTHROPIC_API_KEY`. `GITHUB_TOKEN` is supplied automatically by Actions. Editing variables does not activate a disabled workflow. Enable the review workflow separately when ready to run it.

Fixed controls also bound changed-file/diff size, tool types, file access, source validation and runtime. Analysis has a five-minute total deadline, with shorter token-count/generation timers. SDK retries are disabled; the application retries transient read and generation failures within its attempt, budget and time limits. Three retries mean at most four attempts, with backoff delays of 0.5, 1 and 2 seconds; a new cost reservation is retained for each submitted generation attempt, even when usage is unknown. These per-review settings do not control the separate evaluation aggregate ceiling. See [architecture](architecture.md) for execution details and [security and data handling](../README.md#security-and-data-handling) before sending repository content to the provider.

## Credential and Workflow Trust

1. Create the **claude-review** Environment under repository Settings → Environments. Restrict deployment branches to **main** (selected branch policy). If the GitHub plan does not support the required environment protections, keep paid review disabled until those protections are available.
2. Add **CLAUDE_REVIEW_PROVIDER_KEY** to that environment's secrets. Do not create a repository or organization secret with that name: such a fallback defeats environment isolation. Remove any previous repository-level provider secret after safely migrating or rotating it. GitHub never returns an existing secret's value, so this migration requires its owner or provider-side rotation.
3. Check that repository/organization Actions policy permits **pull_request_target**. GitHub documents a default public-repository event restriction; an explicit policy may be needed. See [GitHub's trusted-trigger guidance](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target), checked October 18, 2026.
4. Protect **main**, review workflow and policy changes, and require human approval plus the review gate if merge blocking is needed. Administrators who can change these settings/code are trusted operators.

The workflow definition comes from the trusted base, checks out only its fixed commit and fetches the PR commit as Git data. It never checks out or runs candidate code in either privileged job. The provider secret exists only in the analysis step; publication has PR-write permission without that key. The separate Verify workflow runs candidate tests without the provider environment.

A base checkout alone does not secure a `pull_request` workflow: its YAML can come from the candidate merge ref. Likewise, keeping a provider key as a repository secret makes every permitted same-repository workflow author part of the secret's trust boundary. Review [GitHub's security guidance](https://docs.github.com/en/actions/reference/security/secure-use) before enabling paid use.
