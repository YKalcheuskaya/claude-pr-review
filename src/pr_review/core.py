"""Diff, result and publication contracts. No network or model dependency."""
import base64
import hashlib
import html
import json
import re

CONFIG = "v1-files20-bytes61440-tokens4000-seconds60"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_BYTES = 60 * 1024
SHA = re.compile(r"[0-9a-f]{40}")


class ReviewError(ValueError):
    """Safe application failure with machine-readable contract/stage metadata."""
    def __init__(self, message, stage=None, code=None, validation_path=None, status_code=None, request_id=None):
        super().__init__(message)
        prefix = str(message).split(":", 1)[0]
        self.code = code or (prefix if re.fullmatch(r"[a-z][a-z0-9_.-]{1,80}", prefix) else "review.failure")
        self.stage = stage
        self.validation_path = validation_path
        self.status_code = status_code
        self.request_id = request_id


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def path_ok(path):
    return isinstance(path, str) and bool(path) and not path.startswith("/") and all(
        part not in ("", ".", "..") for part in path.split("/")) and not any(
        c in path for c in ('"', "\\", "\t", "\r", "\n", "\x00"))


def locations(diff):
    """Parse bounded ordinary UTF-8 patches, including deleted-side locations.

    Unsupported metadata-only, binary, mode/type and quoted-path changes fail.
    Locations include hunk identity to disallow ranges crossing separate hunks.
    """
    if not isinstance(diff, str) or len(diff.encode()) > MAX_BYTES or "\x00" in diff:
        raise ReviewError("diff exceeds limits or contains binary data")
    if re.search(r"sk-ant-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}", diff):
        raise ReviewError("credential-like content in diff; review withheld")
    lines = diff.splitlines()
    result = {}
    i = 0
    while i < len(lines):
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", lines[i])
        if not match or not all(path_ok(p) for p in match.groups()):
            raise ReviewError("unsupported diff path/header")
        old, new = match.groups()
        if new in result or len(result) >= 20:
            raise ReviewError("duplicate file or file limit exceeded")
        result[new] = {"LEFT": {}, "RIGHT": {}}
        i += 1
        before = after = None
        while i < len(lines) and not lines[i].startswith("@@"):
            line = lines[i]
            if line.startswith("--- "):
                before = line[4:]
            elif line.startswith("+++ "):
                after = line[4:]
            elif not re.fullmatch(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100644)?|(?:new file|deleted file) mode 100644|similarity index [0-9]+%|rename (?:from|to) .+", line):
                raise ReviewError("unsupported or non-textual change")
            i += 1
        if before not in ("a/" + old, "/dev/null") or after not in ("b/" + new, "/dev/null"):
            raise ReviewError("inconsistent patch headers")
        hunks = 0
        old_end = new_end = 0
        while i < len(lines) and not lines[i].startswith("diff --git "):
            m = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", lines[i])
            if not m:
                raise ReviewError("malformed hunk")
            a, ac, b, bc = m.groups()
            a, b, ac, bc = int(a), int(b), int(ac or 1), int(bc or 1)
            if a < old_end or b < new_end or (ac and a < 1) or (bc and b < 1):
                raise ReviewError("overlapping or invalid hunk")
            if (before == "/dev/null" and ac) or (after == "/dev/null" and bc):
                raise ReviewError("absent side has lines")
            hunks += 1
            i += 1
            while ac or bc:
                if i >= len(lines) or not lines[i] or lines[i][0] not in " +-":
                    raise ReviewError("hunk counts disagree")
                prefix = lines[i][0]
                if prefix in " -":
                    result[new]["LEFT"][a] = hunks
                    a += 1
                    ac -= 1
                if prefix in " +":
                    result[new]["RIGHT"][b] = hunks
                    b += 1
                    bc -= 1
                if min(ac, bc) < 0:
                    raise ReviewError("hunk counts disagree")
                i += 1
                if i < len(lines) and lines[i] == "\\ No newline at end of file":
                    i += 1
            old_end, new_end = a, b
        if not hunks:
            raise ReviewError("metadata-only change is unsupported")
    return result


def validate_input(data):
    if isinstance(data, dict) and data.get("version") == 2:
        from .v2 import validate_input as v2_input
        return v2_input(data)
    fields = {"version", "repository", "pr", "base", "head", "merge_base", "diff", "model", "config"}
    if not isinstance(data, dict) or set(data) != fields or data["version"] != 1:
        raise ReviewError("invalid input contract")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", data["repository"]):
        raise ReviewError("invalid repository")
    if type(data["pr"]) is not int or data["pr"] < 1:
        raise ReviewError("invalid PR")
    if any(not isinstance(data[k], str) or not SHA.fullmatch(data[k]) for k in ("base", "head", "merge_base")):
        raise ReviewError("invalid snapshot")
    if not isinstance(data["model"], str) or not re.fullmatch(r"claude-[a-z0-9-]+", data["model"]) or data["config"] != CONFIG:
        raise ReviewError("invalid model/config")
    return locations(data["diff"])


def validate_content(content, input_data):
    locs = validate_input(input_data)
    if not isinstance(content, dict) or set(content) != {"status", "summary", "findings", "limitations"}:
        raise ReviewError("invalid model contract")
    if content["status"] not in ("complete", "partial"):
        raise ReviewError("invalid status")
    texts = [content["summary"]]
    if not isinstance(content["limitations"], list) or len(content["limitations"]) > 10:
        raise ReviewError("invalid limitations")
    texts += content["limitations"]
    if content["status"] == "partial" and not content["limitations"]:
        raise ReviewError("partial review requires limitations")
    findings = content["findings"]
    if not isinstance(findings, list) or len(findings) > 10:
        raise ReviewError("invalid findings count")
    seen = set()
    for f in findings:
        if not isinstance(f, dict) or set(f) != {"severity", "file", "side", "start", "end", "description", "evidence", "recommendation"}:
            raise ReviewError("invalid finding")
        if f["severity"] not in ("low", "medium", "high", "critical") or f["side"] not in ("LEFT", "RIGHT"):
            raise ReviewError("invalid severity/side")
        if not path_ok(f["file"]) or any(type(f[k]) is not int for k in ("start", "end")) or not 1 <= f["start"] <= f["end"] or f["end"] - f["start"] > 20:
            raise ReviewError("invalid location")
        available = locs.get(f["file"], {}).get(f["side"], {})
        ids = {available.get(n) for n in range(f["start"], f["end"] + 1)}
        if None in ids or len(ids) != 1:
            raise ReviewError("finding outside reviewed hunk")
        key = (f["file"], f["side"], f["start"], f["end"], f["description"])
        if key in seen:
            raise ReviewError("duplicate finding")
        seen.add(key)
        texts += [f[k] for k in ("description", "evidence", "recommendation")]
    if any(not isinstance(t, str) or not t.strip() or len(t) > 1200 for t in texts):
        raise ReviewError("invalid or oversized text")
    if content["status"] == "complete" and content["limitations"]:
        raise ReviewError("limitations require partial status")
    return content


def validate_result(result, data):
    if data.get("version") == 2:
        from .v2 import validate_result as v2_result
        return v2_result(result, data)
    if not isinstance(result, dict) or set(result) != {"version", "identity", "model", "duration_ms", "content", "usage", "live"} or result["version"] != 1 or result["identity"] != digest(data) or result["model"] != data["model"]:
        raise ReviewError("result does not match trusted input")
    if type(result["duration_ms"]) is not int or result["duration_ms"] < 0:
        raise ReviewError("invalid latency")
    validate_content(result["content"], data)
    if type(result["live"]) is not bool or not isinstance(result["usage"], dict) or set(result["usage"]) != {"input_tokens", "output_tokens"}:
        raise ReviewError("invalid usage/provenance")
    if any(type(n) is not int or n < 0 for n in result["usage"].values()):
        raise ReviewError("invalid token count")
    return result


def gate(result):
    if result.get("version") == 2:
        from .v2 import gate as v2_gate
        return v2_gate(result)
    return result["content"]["status"] == "complete" and not any(
        f["severity"] in ("high", "critical") for f in result["content"]["findings"])


def safe_text(text):
    return "<pre>" + html.escape(text).replace("@", "&#64;") + "</pre>"


def payload(data, result):
    if data.get("version") == 2:
        from .v2 import payload as v2_payload
        return v2_payload(data, result)
    validate_result(result, data)
    marker = "<!-- claude-pr-review:" + digest(data) + " -->"
    saved = base64.b64encode(json.dumps(result, separators=(",", ":")).encode()).decode()
    body = "Claude PR review\n\n" + safe_text(result["content"]["summary"])
    body += "\n\nModel: " + data["model"] + "\nHead: " + data["head"]
    body += "\nGate: " + ("passed" if gate(result) else "blocked")
    for limitation in result["content"]["limitations"]:
        body += "\n" + safe_text(limitation)
    body += "\n" + marker + "\n<!-- result:" + saved + " -->"
    if len(body.encode()) > 60000:
        raise ReviewError("review body exceeds publication limit")
    comments = []
    for f in result["content"]["findings"]:
        c = {"path": f["file"], "side": f["side"], "line": f["end"],
             "body": f["severity"].upper() + "\n" + safe_text(f["description"]) + "\nEvidence:\n" + safe_text(f["evidence"]) + "\nRecommendation:\n" + safe_text(f["recommendation"])}
        if f["start"] != f["end"]:
            c.update(start_line=f["start"], start_side=f["side"])
        comments.append(c)
    return {"commit_id": data["head"], "event": "COMMENT", "body": body, "comments": comments}


def cached_result(reviews, data):
    marker = "<!-- claude-pr-review:" + digest(data) + " -->"
    for review in reviews:
        if review.get("user", {}).get("login") != "github-actions[bot]" or review.get("user", {}).get("type") != "Bot" or review.get("commit_id") != data["head"]:
            continue
        body = review.get("body") or ""
        if marker not in body:
            continue
        if review.get("state") != "COMMENTED":
            raise ReviewError("matching review is not submitted; reconcile before retry")
        match = re.search(r"<!-- result:([A-Za-z0-9+/=]+) -->", body)
        if not match:
            raise ReviewError("existing review lacks reusable result; inspect before retry")
        try:
            result = json.loads(base64.b64decode(match[1], validate=True))
            return validate_result(result, data)
        except (ValueError, TypeError) as error:
            raise ReviewError("existing result is invalid; inspect before retry") from error
    return None
