"""Bounded application traces; all sinks receive sanitized JSON-compatible values.

This records observable requests and responses, never SDK objects, authorization
headers, environment dumps, exception reprs, traceback locals, or model reasoning.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata as package_metadata
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid

MAX_BUNDLE_BYTES = 10 * 1024 * 1024
_METADATA_RESERVE = 256 * 1024
_REDACTED = "[REDACTED]"
from .security import SENSITIVE_KEY as _SENSITIVE, redact


def sanitize(value):
    """Return sanitized data; unknown objects become type names, never reprs."""
    def clean(item):
        if isinstance(item, str):
            return redact(item)
        if isinstance(item, dict):
            return {clean(str(key)) if isinstance(key, (str, int)) else "unknown-key":
                    _REDACTED if _SENSITIVE.search(str(key)) else clean(val)
                    for key, val in item.items() if isinstance(key, (str, int))}
        if isinstance(item, (tuple, list)):
            return [clean(part) for part in item]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return {"unserialized_type": type(item).__name__}

    return clean(value)


def _json(value):
    # Escaping remains valid JSON and prevents commands, HTML, and fake lines.
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False).replace("::", "\\u003a\\u003a").replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("`", "\\u0060")


def _now():
    return datetime.now(timezone.utc).isoformat()


class Diagnostics:
    """One job's flush-on-write trace. Reopening preserves prior stage records."""

    def __init__(self, directory, stage):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stage = sanitize(stage)
        self.started = time.monotonic()
        self.manifest_path = self.directory / "manifest.json"
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        else:
            run = os.environ.get("GITHUB_RUN_ID")
            attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
            # Workflow jobs share run and attempt; local runs receive unique IDs.
            self.manifest = {"version": 2, "trace_id": f"github-{run}-{attempt}" if run else f"local-{uuid.uuid4().hex}",
                             "job": os.environ.get("GITHUB_JOB", "local"), "run_id": run,
                             "run_attempt": attempt, "created_at": _now(), "sequence": 0,
                             "redacted": False, "truncated": False, "dropped_records": 0,
                             "complete": False, "runtime": {"python": sys.version.split()[0]},
                             "last_successful_event": None, "outcome": "running"}
        for filename in ("events.jsonl", "requests.jsonl", "responses.jsonl"):
            (self.directory / filename).touch(exist_ok=True)
        if not (self.directory / "context.json").exists():
            (self.directory / "context.json").write_text("[]\n", encoding="utf-8")
        self.manifest.setdefault("open_operations", {})
        try:
            self.manifest.setdefault("runtime", {})["anthropic"] = package_metadata.version("anthropic")
        except package_metadata.PackageNotFoundError:
            self.manifest.setdefault("runtime", {})["anthropic"] = "not-installed"
        self._group_open = False
        self._manifest()

    @property
    def trace_id(self):
        return self.manifest["trace_id"]

    def _size(self):
        return sum(path.stat().st_size for path in self.directory.iterdir() if path.is_file())

    def _clean(self, value):
        safe = sanitize(value)
        if safe != value:
            self.manifest["redacted"] = True
        return safe

    def _manifest(self):
        self.manifest["complete"] = bool(self.manifest.get("finalized")) and not (self.manifest["redacted"] or self.manifest["truncated"] or self.manifest.get("open_operations") or self.manifest.get("summary_write_failed"))
        safe = sanitize(self.manifest)
        if len(_json(safe).encode("utf-8")) > _METADATA_RESERVE // 4:
            self.manifest["truncated"] = True
            self.manifest["complete"] = False
            # Preserve scalar identity/status and bounded metadata, not huge payloads.
            for key, value in list(self.manifest.items()):
                encoded = _json(sanitize(value)).encode("utf-8")
                if len(encoded) > 4096:
                    self.manifest[key] = {"truncated": True, "sanitized_bytes": len(encoded),
                                          "sanitized_sha256": hashlib.sha256(encoded).hexdigest()}
            if len(_json(sanitize(self.manifest)).encode("utf-8")) > _METADATA_RESERVE // 4:
                keep = ("version", "trace_id", "job", "run_id", "run_attempt", "created_at",
                        "sequence", "redacted", "truncated", "dropped_records", "complete",
                        "outcome", "finalized", "finished_at", "last_successful_event", "error")
                self.manifest = {key: self.manifest[key] for key in keep if key in self.manifest}
            safe = sanitize(self.manifest)
        self.manifest_path.write_text(_json(safe) + "\n", encoding="utf-8")

    def _record(self, filename, value):
        safe = self._clean(value)
        raw = (_json(safe) + "\n").encode("utf-8")
        available = MAX_BUNDLE_BYTES - _METADATA_RESERVE - self._size()
        if len(raw) > available:
            self.manifest["truncated"] = True
            # Hash only sanitized bytes; do not expose hashes of secrets.
            safe = {"trace_id": self.trace_id, "stage": self.stage,
                    "operation_id": safe.get("operation_id"), "truncated": True,
                    "sanitized_bytes": len(raw), "sanitized_sha256": hashlib.sha256(raw).hexdigest(),
                    "prefix": raw[:max(0, min(4096, available // 8))].decode("utf-8", errors="ignore")}
            raw = (_json(safe) + "\n").encode("utf-8")
        if len(raw) <= max(0, available):
            with (self.directory / filename).open("ab") as stream:
                stream.write(raw)
                stream.flush()
        else:
            self.manifest["dropped_records"] += 1
        self._manifest()
        return safe

    def event(self, name, **fields):
        if name == "stage.start" and not self._group_open:
            # Only a fixed allowlist controls command syntax; untrusted names
            # remain JSON data and can never become workflow commands.
            stage = self.stage if self.stage in ("prepare", "analyze", "publish", "finalize-diagnostics") else "review"
            print("::group::Review " + stage, flush=True)
            self._group_open = True
        operation = fields.get("operation_id")
        if operation and isinstance(operation, str):
            operation = self._clean(operation)
            if str(name).endswith(".start"):
                self.manifest["open_operations"][operation] = self._clean(name)
            elif str(name).endswith((".end", ".error", ".success")):
                self.manifest["open_operations"].pop(operation, None)
        self.manifest["sequence"] += 1
        record = {**fields, "name": name, "trace_id": self.trace_id, "stage": self.stage,
                  "timestamp": _now(), "sequence": self.manifest["sequence"],
                  "duration_ms": round((time.monotonic() - self.started) * 1000)}
        if str(name).endswith((".end", ".success")):
            self.manifest["last_successful_event"] = self._clean(name)
        safe = self._record("events.jsonl", record)
        # Payload and full source text belong in the artifact, not console.
        console = {key: value for key, value in safe.items() if key not in ("payload", "content", "text", "sources", "prefix")}
        print(_json(console), flush=True)
        return safe

    def request(self, operation_id, payload, **fields):
        return self._record("requests.jsonl", {**fields, "operation_id": operation_id,
                            "trace_id": self.trace_id, "stage": self.stage, "timestamp": _now(), "payload": payload})

    def response(self, operation_id, payload, **fields):
        return self._record("responses.jsonl", {**fields, "operation_id": operation_id,
                            "trace_id": self.trace_id, "stage": self.stage, "timestamp": _now(), "payload": payload})

    def context(self, sources):
        safe = self._clean(sources)
        raw = (_json(safe) + "\n").encode("utf-8")
        path = self.directory / "context.json"
        available = MAX_BUNDLE_BYTES - _METADATA_RESERVE - self._size() + path.stat().st_size
        if len(raw) > available:
            self.manifest["truncated"] = True
            safe = {"truncated": True, "sanitized_bytes": len(raw),
                    "sanitized_sha256": hashlib.sha256(raw).hexdigest(),
                    "prefix": raw[:max(0, min(4096, available // 8))].decode("utf-8", errors="ignore")}
            raw = (_json(safe) + "\n").encode("utf-8")
        if len(raw) <= max(0, available):
            path.write_bytes(raw)
        else:
            self.manifest["dropped_records"] += 1
        self._manifest()
        return safe

    def error(self, exception, **fields):
        frames = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                  for frame in traceback.extract_tb(exception.__traceback__)]
        # Exception messages can contain arbitrary provider bodies or credentials.
        details = {**fields, "exception_class": type(exception).__name__,
                   "message": "Operation failed; inspect sanitized request/response records.", "stack": frames}
        for attr in ("status_code", "request_id", "code"):
            value = getattr(exception, attr, None)
            if isinstance(value, (str, int)):
                details[attr] = value
        if type(exception).__name__ == "ReviewError":
            raw_prefix = exception.args[0] if exception.args and isinstance(exception.args[0], str) else ""
            match = re.match(r"^(input|result|content|sources|findings|evidence|cache|publication|provider|budget)(?:\.(?:[a-z]+|[0-9]+))+(?::|$)", raw_prefix)
            if match:
                details["code"] = match.group(0).rstrip(":")
                details["validation_path"] = details["code"]
        operation_id = fields.get("operation_id", "provider-error")
        body = getattr(exception, "body", None)
        if isinstance(body, (str, dict)):
            self.response(operation_id, body, status_code=details.get("status_code"), request_id=details.get("request_id"), error_response=True)
        self.manifest["error"] = self._clean(details)
        return self.event("operation.error", **details)

    def finalize(self, outcome="unknown", error=None, **metadata):
        if isinstance(error, BaseException):
            self.error(error)
        elif error is not None:
            self.manifest["error"] = self._clean(error)
        self.manifest.update(self._clean(metadata))
        self.manifest.update({"outcome": self._clean(outcome), "finalized": True, "finished_at": _now()})
        self._manifest()
        summary = {"outcome": self.manifest["outcome"], "trace_id": self.trace_id,
                   "last_successful_event": self.manifest["last_successful_event"],
                   "error": self.manifest.get("error"), "complete": self.manifest["complete"],
                   "open_operations": self.manifest.get("open_operations", {}),
                   "redacted": self.manifest["redacted"], "truncated": self.manifest["truncated"],
                   "next_step": "Inspect events and the matching operation in requests/responses. Missing end events mean an interrupted operation; do not infer a server failure or repeat a write automatically."}
        text = "# Review diagnostics\n\n```json\n" + _json(sanitize(summary)) + "\n```\n"
        (self.directory / "summary.md").write_text(text, encoding="utf-8")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            try:
                with Path(summary_path).open("a", encoding="utf-8") as stream:
                    stream.write(text)
            except OSError:
                self.manifest["summary_write_failed"] = True
                self.manifest["complete"] = False
                self._manifest()
        if self._group_open:
            print("::endgroup::", flush=True)
            self._group_open = False
        return sanitize(self.manifest)
