"""Three explicit commands; offline publish emits a payload without networking."""
import argparse
import json
import os
from pathlib import Path
import sys

from .core import DEFAULT_MODEL, ReviewError, gate, payload, validate_input
from .service import Github, analyze, prepare, publish


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def api(data, diagnostics=None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ReviewError("GITHUB_TOKEN is missing")
    return Github(data["repository"], data["pr"], token, diagnostics)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--event", required=True)
    p.add_argument("--repository-path", default=".")
    p.add_argument("--model", default=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL))
    p.add_argument("--output", required=True)
    p.add_argument("--mode", choices=("context", "diff"), default="context")
    a = commands.add_parser("analyze")
    a.add_argument("--input", required=True)
    a.add_argument("--recorded")
    a.add_argument("--cache-only", action="store_true")
    a.add_argument("--output", required=True)
    a.add_argument("--repository-path", default=".")
    a.add_argument("--mode", choices=("context", "diff"))
    p = commands.add_parser("publish")
    p.add_argument("--input", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--event")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output")
    f = commands.add_parser("finalize-diagnostics")
    f.add_argument("--outcome", default="unknown")
    for command in (p, a, commands.choices["prepare"], f):
        command.add_argument("--diagnostics-dir", default="outputs/diagnostics")
    args = parser.parse_args(argv)
    from .diagnostics import Diagnostics
    diagnostics = Diagnostics(args.diagnostics_dir, args.command)
    outcome = "failure"
    try:
        diagnostics.event("stage.start", stage=args.command)
        if args.command == "finalize-diagnostics":
            outcome = args.outcome
            return 0
        if args.command == "prepare":
            event = read(args.event)
            identity = {"repository": event["repository"]["full_name"], "pr": event["number"]}
            # Event values are validated before forming a URL.
            import re
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity["repository"]) or type(identity["pr"]) is not int or identity["pr"] < 1:
                raise ReviewError("invalid event identity")
            data = prepare(api(identity, diagnostics), **{"repository": identity["repository"], "pr_number": identity["pr"], "repository_path": args.repository_path, "model": args.model, "mode": args.mode})
            event_pr = event["pull_request"]
            if data["base"] != event_pr["base"]["sha"] or data["head"] != event_pr["head"]["sha"]:
                raise ReviewError("event snapshot is stale; no model call")
            diagnostics.event("snapshot.end", snapshots={k:data[k] for k in ("base","head","merge_base")}, pr=data["pr"], policy=data.get("policies"), files=len(data.get("changed_files", [])), diff_bytes=len(data["diff"].encode()))
            diagnostics.manifest.update(snapshots={k:data[k] for k in ("base","head","merge_base")}, policies=data.get("policies"))
            write(args.output, data)
        else:
            data = read(args.input)
            validate_input(data)
            diagnostics.manifest.update(snapshots={k:data[k] for k in ("base","head","merge_base")}, policies=data.get("policies"))
            if getattr(args, "mode", None) and data.get("mode") != args.mode:
                raise ReviewError("input.mode: mode differs from prepared identity")
            if args.command == "analyze":
                result = analyze(data, recorded=read(args.recorded) if args.recorded else None,
                                 github=None if args.recorded else api(data, diagnostics), repository_path=args.repository_path, diagnostics=diagnostics, cache_only=args.cache_only or os.environ.get("CLAUDE_CACHE_ONLY") == "true")
                write(args.output, result)
            else:
                result = read(args.result)
                if args.dry_run:
                    if not args.output:
                        raise ReviewError("dry-run requires --output")
                    write(args.output, payload(data, result))
                    passed = gate(result)
                else:
                    # Recollect the diff from trusted snapshots, not downloaded artifact text.
                    if not args.event:
                        raise ReviewError("live publication requires the trusted event")
                    event = read(args.event)
                    pr = event["pull_request"]
                    if (data["repository"] != event["repository"]["full_name"] or data["pr"] != event["number"]
                        or data["base"] != pr["base"]["sha"] or data["head"] != pr["head"]["sha"]):
                        raise ReviewError("artifact does not match this workflow event")
                    github = api(data, diagnostics)
                    fresh = prepare(github, data["repository"], data["pr"], ".", args_model(data), mode=data.get("mode"))
                    if fresh != data:
                        raise ReviewError("artifact input differs from trusted Git snapshot")
                    passed = publish(fresh, result, github, diagnostics=diagnostics)
                outcome = "success" if passed else "failure"
                diagnostics.event("gate", outcome=outcome, coverage=result.get("coverage", result["content"]["status"]))
                if result.get("version") == 2 and result["coverage"] == "partial":
                    print("::warning::INCOMPLETE REVIEW: inspect limitations in the review and diagnostic artifact.")
                print("Claude review gate: " + ("passed" if passed else "blocked"))
                return 0 if passed else 1
        outcome = "success"
        return 0
    except ReviewError as error:
        diagnostics.error(error, error_code="review.failure")
        from .diagnostics import sanitize
        print("Claude review failed: " + json.dumps(sanitize(str(error)), ensure_ascii=True).replace("::", "\\u003a\\u003a") + ". No clean verdict.", file=sys.stderr)
        return 2
    except Exception as error:
        diagnostics.error(error, error_code="unexpected.failure")
        # Keep logs free of model text, source and credentials; retained operational
        # errors are deliberately generic at the CLI boundary.
        print("Claude review failed: input, provider, snapshot or publication error. No clean verdict. See setup and retry guidance.", file=sys.stderr)
        return 2
    finally:
        diagnostics.finalize(outcome=outcome)


def args_model(data):
    configured = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
    if data["model"] != configured:
        raise ReviewError("artifact model differs from trusted configuration")
    return configured


if __name__ == "__main__":
    raise SystemExit(main())
