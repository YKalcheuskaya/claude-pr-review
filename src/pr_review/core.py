"""Diff, result and publication contracts. No network or model dependency."""
import base64
import hashlib
import html
import json
import re

from .security import restricted_path, sensitive

DEFAULT_MODEL = "claude-haiku-5-5"
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
    if sensitive(diff):
        raise ReviewError("credential-like content in diff; review withheld")
    lines = diff.splitlines()
    result = {}
    i = 0
    while i < len(lines):
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", lines[i])
        if not match or not all(path_ok(p) for p in match.groups()):
            raise ReviewError("unsupported diff path/header")
        old, new = match.groups()
        if restricted_path(old) or restricted_path(new):
            raise ReviewError("restricted changed path; review withheld")
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
            elif not re.fullmatch(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100(?:644|755))?|(?:new file|deleted file) mode 100(?:644|755)|similarity index [0-9]+%|rename (?:from|to) .+", line):
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


def validate_snapshot_fields(data):
    """Validate shared snapshot identity before Git or network operations."""
    required = {"repository", "pr", "base", "head", "merge_base", "diff", "model"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise ReviewError("invalid snapshot fields")
    if not isinstance(data["repository"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", data["repository"]):
        raise ReviewError("invalid repository")
    if type(data["pr"]) is not int or data["pr"] < 1:
        raise ReviewError("invalid PR")
    if any(not isinstance(data[k], str) or not SHA.fullmatch(data[k]) for k in ("base", "head", "merge_base")):
        raise ReviewError("invalid snapshot")
    if not isinstance(data["model"], str) or not re.fullmatch(r"claude-[a-z0-9-]+", data["model"]):
        raise ReviewError("invalid model")
    return locations(data["diff"])


def validate_input(data):
    from .review import validate_input as validate
    return validate(data)


def validate_result(result, data):
    from .review import validate_result as validate
    return validate(result, data)


def gate(result):
    from .review import gate as evaluate
    return evaluate(result)


def safe_text(text):
    return "<pre>" + html.escape(text).replace("@", "&#64;") + "</pre>"


def payload(data, result):
    from .review import payload as build
    return build(data, result)


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
