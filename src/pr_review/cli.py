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


def api(data):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ReviewError("GITHUB_TOKEN is missing")
    return Github(data["repository"], data["pr"], token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--event", required=True)
    p.add_argument("--repository-path", default=".")
    p.add_argument("--model", default=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL))
    p.add_argument("--output", required=True)
    a = commands.add_parser("analyze")
    a.add_argument("--input", required=True)
    a.add_argument("--recorded")
    a.add_argument("--output", required=True)
    p = commands.add_parser("publish")
    p.add_argument("--input", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--event")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            event = read(args.event)
            identity = {"repository": event["repository"]["full_name"], "pr": event["number"]}
            # Event values are validated before forming a URL.
            import re
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity["repository"]) or type(identity["pr"]) is not int or identity["pr"] < 1:
                raise ReviewError("invalid event identity")
            data = prepare(api(identity), **{"repository": identity["repository"], "pr_number": identity["pr"], "repository_path": args.repository_path, "model": args.model})
            event_pr = event["pull_request"]
            if data["base"] != event_pr["base"]["sha"] or data["head"] != event_pr["head"]["sha"]:
                raise ReviewError("event snapshot is stale; no model call")
            write(args.output, data)
        else:
            data = read(args.input)
            validate_input(data)
            if args.command == "analyze":
                result = analyze(data, recorded=read(args.recorded) if args.recorded else None,
                                 github=None if args.recorded else api(data))
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
                    github = api(data)
                    fresh = prepare(github, data["repository"], data["pr"], ".", args_model(data))
                    if fresh != data:
                        raise ReviewError("artifact input differs from trusted Git snapshot")
                    passed = publish(fresh, result, github)
                print("Claude review gate: " + ("passed" if passed else "blocked"))
                return 0 if passed else 1
        return 0
    except ReviewError as error:
        print("Claude review failed: " + str(error) + ". No clean verdict.", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, OSError, ImportError):
        # Keep logs free of model text, source and credentials; retained operational
        # errors are deliberately generic at the CLI boundary.
        print("Claude review failed: input, provider, snapshot or publication error. No clean verdict. See setup and retry guidance.", file=sys.stderr)
        return 2


def args_model(data):
    configured = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)
    if data["model"] != configured:
        raise ReviewError("artifact model differs from trusted configuration")
    return configured


if __name__ == "__main__":
    raise SystemExit(main())
