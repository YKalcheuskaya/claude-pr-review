"""Paired-corpus evaluation: offline preparation/reporting and an authorized paid runner.

Preparation and reporting work without provider calls. The paid runner requires
explicit authorization and can contact the provider; it is not an offline command.
"""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evaluation" / "corpus"
MODEL = "claude-haiku-5-5"
CAPS = {"context": Decimal("0.20"), "diff": Decimal("0.05")}
PILOT_CAP = Decimal("4.00")  # Default pilot reserve; increasing it requires separate operator authorization.


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Amounts must be finite and nonnegative")
    return result


def cases(split=None):
    data = [read(path) for path in sorted((CORPUS / "cases").glob("*.json"))]
    return [case for case in data if split is None or case["split"] == split]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def materialize(repo, files):
    for name, content in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts or not path.parts:
            raise ValueError("Unsafe fixture path")
        destination = repo.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def prepare_case(case, output, model=MODEL):
    """Create one local Git repo and two validated inputs, without oracle labels."""
    directory = Path(output) / case["id"]
    if directory.exists():
        raise ValueError("Case output already exists; choose a new directory")
    repo = directory / "repository"
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Offline Evaluation")
    git(repo, "config", "user.email", "offline@example.invalid")
    materialize(repo, case["before"])
    git(repo, "add", ".")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "Before snapshot")
    before = git(repo, "rev-parse", "HEAD")
    for path in case["before"]:
        if path not in case["after"]:
            (repo / path).unlink()
    materialize(repo, case["after"])
    git(repo, "add", "--all")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "After snapshot")
    after = git(repo, "rev-parse", "HEAD")
    sys.path.insert(0, str(ROOT / "src"))
    from pr_review.service import prepare
    repository = "offline/fixture"
    metadata = {"state": "open", "draft": False, "title": case["title"], "body": case["body"],
                "base": {"ref": "main", "sha": before},
                "head": {"sha": after, "repo": {"full_name": repository}},
                "user": {"type": "User"}}

    class OfflineGithub:
        def pr(self):
            return metadata

    for mode in ("diff", "context"):
        data = prepare(OfflineGithub(), repository, 1, repo, model=model, mode=mode)
        write(directory / f"{mode}-input.json", data)
    write(directory / "case-record.json", {"case_id": case["id"], "repository_path": str(repo.resolve())})
    return directory


def runtime_policy_paths():
    package = ROOT / "src" / "pr_review"
    return sorted(package.glob("*.py")) + [package / "review-policy.md", Path(__file__).resolve()]


def freeze(output, policies, model=MODEL):
    """Seal corpus, oracle and actual prompt/policy files before held-out evaluation."""
    if Path(output).exists():
        raise ValueError("Freeze output already exists; do not overwrite existing seals")
    sources = sorted((CORPUS / "cases").glob("*.json"))
    labels = sorted((CORPUS / "labels").glob("*.json"))
    if not policies:
        raise ValueError("Supply every actual prompt/schema/tool policy with --policy")
    selected = []
    for supplied in policies:
        path = Path(supplied)
        if path.is_dir():
            selected.extend(sorted(path.glob("*.py")))
            selected.append(path / "review-policy.md")
        else:
            selected.append(path)
    selected.append(Path(__file__).resolve())
    files = {str(path.resolve()): sha(path) for path in sources + labels + selected}
    value = {"version": 2, "model": model, "files": files}
    value["freeze_id"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    write(output, value)
    return value


def verify_freeze(path):
    seal = read(path)
    identity = {key: value for key, value in seal.items() if key != "freeze_id"}
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if seal["freeze_id"] != expected:
        raise ValueError("Invalid freeze identity")
    for source, digest in seal["files"].items():
        if sha(source) != digest:
            raise ValueError("Frozen source changed: " + source)
    required = {str(p.resolve()) for folder in ("cases", "labels") for p in (CORPUS / folder).glob("*.json")}
    if not required.issubset(seal["files"]):
        raise ValueError("Freeze does not include current corpus and labels")
    return seal


def reserve(ledger_path, run_id, mode, input_tokens, output_tokens, input_rate,
            output_rate, authorization_reference, pricing_reference, review_cap=None):
    """Reserve full review envelope before any external request; this function never calls an API.

    Rate units are USD per million tokens. Tokens include all planned calls and final output.
    An external authorized adapter must persist this reservation before transmitting a request.
    """
    if not authorization_reference.strip() or not pricing_reference.strip():
        raise ValueError("Separate explicit pilot authorization and current pricing references are required")
    if mode not in CAPS or not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ValueError("Invalid preflight")
    if input_tokens <= 0 or output_tokens <= 0:
        raise ValueError("Preflight must include positive input and output token reservations")
    input_price, output_price = money(input_rate), money(output_rate)
    if input_price == 0 or output_price == 0:
        raise ValueError("Paid preflight requires positive verified rates")
    cap = money(review_cap) if review_cap is not None else CAPS[mode]
    if cap <= 0:
        raise ValueError("Review ceiling must be positive")
    estimated = (input_tokens * input_price + output_tokens * output_price) / Decimal(1_000_000)
    if estimated > cap:
        raise ValueError("Conservative token estimate exceeds per-review ceiling; reduce review scope")
    ledger = read(ledger_path) if Path(ledger_path).exists() else {"version": 2, "entries": []}
    if any(row["run_id"] == run_id for row in ledger["entries"]):
        raise ValueError("Run already reserved; unknown calls must not be retried under the same reservation")
    # Hold the full per-review cap even after failures/unknown outcomes. No optimistic refunds.
    total = sum((money(row["reserved_usd"]) for row in ledger["entries"]), Decimal(0))
    if total + cap > PILOT_CAP:
        raise ValueError("Aggregate pilot cap exhausted; choose a separately authorized experiment budget")
    ledger["entries"].append({
        "run_id": run_id, "mode": mode, "status": "reserved-or-unknown",
        "reserved_usd": str(cap), "preflight_estimate_usd": str(estimated),
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "input_usd_per_million": str(input_price), "output_usd_per_million": str(output_price),
        "authorization_reference": authorization_reference, "pricing_reference": pricing_reference,
    })
    # Crash-safe replacement; one serial owner is still required for read-modify-write.
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ledger_path.parent,
                                     prefix="budget-", suffix=".json", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(ledger, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, ledger_path)
    finally:
        temporary.unlink(missing_ok=True)
    return ledger


def run_paid(input_path, repository_path, output, diagnostics_dir, ledger_path, seal_path,
             run_id, authorize_paid, authorization_reference, pricing_reference, input_rate, output_rate):
    """Execute one explicitly authorized review; never publish or retry.

    The flag/reference records prior human approval. It does not grant approval itself.
    """
    if not authorize_paid or not authorization_reference.strip() or not pricing_reference.strip():
        raise ValueError("Separate explicit human approval is required before paid execution")
    if Path(output).exists():
        raise ValueError("Result output already exists; preserve existing runs")
    seal = verify_freeze(seal_path)
    sys.path.insert(0, str(ROOT / "src"))
    from pr_review import review
    from pr_review.diagnostics import Diagnostics
    data = read(input_path)
    review.validate_input(data)
    if data["model"] != seal["model"]:
        raise ValueError("Prepared input model must match the frozen experiment model")
    from pr_review.config import review_budget, review_controls
    budget = review_budget(data["model"])
    if money(input_rate) != money(budget["input_rate"]) or money(output_rate) != money(budget["output_rate"]):
        raise ValueError("Verified rates must match configured input/output rates; reprepare inputs after changes")
    from pr_review import context, config
    required_policies = {str(path.resolve()) for path in runtime_policy_paths()}
    if not required_policies.issubset(seal["files"]):
        raise ValueError("Freeze must include every runtime module, review policy and evaluation runner")
    repo = Path(repository_path).resolve()
    for snapshot in ("base", "head", "merge_base"):
        if git(repo, "rev-parse", data[snapshot] + "^{commit}") != data[snapshot]:
            raise ValueError("Fixture repository does not match input snapshots")
    actual_diff = subprocess.check_output([
        "git", "-C", str(repo), "-c", "core.quotePath=false", "diff", "--no-ext-diff",
        "--no-textconv", "--no-color", "--unified=3", "--find-renames", data["merge_base"], data["head"], "--"], text=True)
    if actual_diff != data["diff"]:
        raise ValueError("Input diff does not match fixture snapshots")
    # Reserve the actual configured maximum, including the final request.
    controls = review_controls()
    research_calls = controls["research_calls"] if data["mode"] == "context" else 0
    input_tokens = controls["input_tokens"] * (research_calls + 1)
    output_tokens = controls["research_output"] * research_calls + controls["final_output"]
    diagnostics = Diagnostics(diagnostics_dir, "evaluation")
    try:
        reserve(ledger_path, run_id, data["mode"], input_tokens, output_tokens,
                input_rate, output_rate, authorization_reference, pricing_reference, review_cap=budget["max_cost"])
        diagnostics.event("evaluation.reserved", run_id=run_id, freeze_id=seal["freeze_id"],
                          reserved_usd=budget["max_cost"] or str(CAPS[data["mode"]]), snapshots={key: data[key] for key in ("base", "head", "merge_base")})
        result = review.analyze(data, github=None, repository_path=repo, diagnostics=diagnostics)
        review.validate_result(result, data)
        write(output, result)
        diagnostics.finalize("success", run_id=run_id, freeze_id=seal["freeze_id"])
        return result
    except Exception as error:
        diagnostics.finalize("failure-or-unknown", error=error, run_id=run_id, freeze_id=seal["freeze_id"])
        # Preserve full reservation even for failed preflight or unknown usage.
        raise ValueError("Evaluation failed; inspect sanitized diagnostics; reservation retained") from None


def report(record_path, seal_path):
    """Score human-adjudicated recorded outputs; never infer matching from model wording."""
    seal = verify_freeze(seal_path)
    recorded = read(record_path)
    if recorded.get("freeze_id") != seal["freeze_id"] or recorded.get("model") != seal["model"]:
        raise ValueError("Results must reference the same frozen policy set and planned model")
    expected = {case["id"]: read(CORPUS / "labels" / (case["id"] + ".json"))["expected"]
                for case in cases("held-out")}
    stats = {mode: Counter() for mode in CAPS}
    seen = set()
    for row in recorded["runs"]:
        key = (row["case_id"], row["mode"])
        if key in seen or key[0] not in expected or key[1] not in stats:
            raise ValueError("Duplicate or unknown case/mode")
        seen.add(key)
        stat = stats[key[1]]
        oracle = {item["id"]: item for item in expected[key[0]]}
        stat["runs"] += 1
        stat["expected_defects"] += len(oracle)
        status = row["status"]
        if status not in ("complete", "incomplete", "failure"):
            raise ValueError("Invalid run status")
        stat[status] += 1
        latency = row.get("latency_ms")
        if latency is not None:
            if not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
                raise ValueError("Invalid latency")
            stat["latency_ms"] += latency
            stat["latency_observed"] += 1
        cost = row.get("cost_usd")
        if cost is not None:
            stat["cost_usd"] += money(cost)
            stat["cost_observed"] += 1
        findings = row["findings"]
        if status == "failure" and findings:
            raise ValueError("Failed runs cannot have accepted findings")
        matched = set()
        for finding in findings:
            if not finding.get("adjudicator") or not finding.get("rationale"):
                raise ValueError("Every finding needs independent human adjudication and rationale")
            severity = finding["severity"]
            if severity not in ("low", "medium", "high", "critical"):
                raise ValueError("Invalid severity")
            if not isinstance(finding["evidence_correct"], bool):
                raise ValueError("Evidence correctness needs explicit human adjudication")
            match = finding.get("expected_id")
            if match is not None and match not in oracle:
                raise ValueError("Unknown expected label")
            stat["findings"] += 1
            stat["evidence_correct"] += finding["evidence_correct"]
            if match is not None and match not in matched:
                matched.add(match)
                stat["true_positives"] += 1
                stat["severity_correct"] += severity == oracle[match]["severity"]
            else:
                stat["false_positives"] += 1
            if not oracle and severity in ("high", "critical"):
                stat["clean_high_critical"] += 1
        stat["false_negatives"] += len(oracle) - len(matched)
    metrics = {}
    for mode, counts in stats.items():
        value = {key: str(number) if isinstance(number, Decimal) else number for key, number in counts.items()}
        for name, numerator, denominator in (
            ("precision", "true_positives", "findings"),
            ("recall", "true_positives", "expected_defects"),
            ("evidence_correctness", "evidence_correct", "findings"),
            ("severity_calibration", "severity_correct", "true_positives"),
            ("incomplete_rate", "incomplete", "runs"),
            ("failure_rate", "failure", "runs"),
            ("mean_latency_ms", "latency_ms", "latency_observed"),
        ):
            value[name] = counts[numerator] / counts[denominator] if counts[denominator] else None
        metrics[mode] = value
    paired = len(seen) == 24
    detected_delta = stats["context"]["true_positives"] - stats["diff"]["true_positives"]
    observed = paired and detected_delta >= 2 and stats["context"]["clean_high_critical"] <= stats["diff"]["clean_high_critical"]
    return {"version": 2, "freeze_id": seal["freeze_id"], "metrics": metrics,
            "all_pairs_present": paired, "additional_detected_defects": detected_delta,
            "observed_improvement_criterion": observed if paired else None,
            "claim_boundary": "Provisional synthetic-corpus result; requires independent label review. "
                              "No production-quality or hiring-skill claim follows from this report."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--model", default=None)
    prepare.add_argument("--split", choices=["development", "held-out"], default="development")
    freeze_cmd = commands.add_parser("freeze")
    freeze_cmd.add_argument("--output", required=True)
    freeze_cmd.add_argument("--model", default=None)
    freeze_cmd.add_argument("--policy", action="append", required=True)
    score = commands.add_parser("report")
    score.add_argument("--records", required=True)
    score.add_argument("--freeze", required=True)
    score.add_argument("--output", required=True)
    budget = commands.add_parser("reserve")
    budget.add_argument("--ledger", required=True)
    budget.add_argument("--run-id", required=True)
    budget.add_argument("--mode", choices=list(CAPS), required=True)
    budget.add_argument("--input-tokens", type=int, required=True)
    budget.add_argument("--output-tokens", type=int, required=True)
    budget.add_argument("--input-rate", required=True)
    budget.add_argument("--output-rate", required=True)
    budget.add_argument("--authorization-reference", required=True)
    budget.add_argument("--pricing-reference", required=True)
    live = commands.add_parser("run", help="Requires prior separate explicit human pilot approval")
    for option in ("input", "repository-path", "output", "diagnostics-dir", "ledger", "freeze", "run-id",
                   "authorization-reference", "pricing-reference", "input-rate", "output-rate"):
        live.add_argument("--" + option, required=True)
    live.add_argument("--authorize-paid", action="store_true",
                      help="Record existing explicit human authorization; this flag is not authorization itself")
    args = parser.parse_args(argv)
    if args.command in ("prepare", "freeze"):
        sys.path.insert(0, str(ROOT / "src"))
        from pr_review.config import effective_config
        args.model = effective_config(args.model)["model"]
    if args.command == "prepare":
        for case in cases(args.split):
            prepare_case(case, args.output, args.model)
    elif args.command == "freeze":
        freeze(args.output, args.policy, args.model)
    elif args.command == "report":
        write(args.output, report(args.records, args.freeze))
    elif args.command == "reserve":
        reserve(args.ledger, args.run_id, args.mode, args.input_tokens, args.output_tokens,
                args.input_rate, args.output_rate, args.authorization_reference, args.pricing_reference)
    elif args.command == "run":
        run_paid(args.input, args.repository_path, args.output, args.diagnostics_dir,
                 args.ledger, args.freeze, args.run_id, args.authorize_paid,
                 args.authorization_reference, args.pricing_reference, args.input_rate, args.output_rate)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print("Offline evaluation failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
