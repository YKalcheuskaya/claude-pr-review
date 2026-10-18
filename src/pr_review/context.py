"""Bounded, read-only Git-object context. Repository content is always data."""
import copy
import os
import re
import subprocess
import time

from .core import ReviewError, SHA, digest, locations, path_ok
from .runtime import bounded, deadline, TIMERS
from .config import review_controls
from .security import (DENIED_DIRECTORIES, DENIED_SUFFIXES, DENIED_NAMES, restricted_path, sensitive, runtime_secrets)

POLICY = {
    "version": 2, "max_paths": 10000, "max_reader_seconds": TIMERS["analysis"],
    "max_scan_bytes": 32 * 1024 * 1024, "max_blob_bytes": 256 * 1024,
    "max_read_bytes": 16 * 1024, "max_read_lines": 200,
    "list_page": 100, "search_page": 50,
    "initial_file_bytes": 8 * 1024, "initial_changed_bytes": 32 * 1024,
    "initial_root_bytes": 16 * 1024,
    "denied_directories": DENIED_DIRECTORIES,
    "denied_suffixes": DENIED_SUFFIXES,
    "denied_names": DENIED_NAMES,
}
POLICY_HASH = digest(POLICY)


def _schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_SNAPSHOT = {"type": "string", "enum": ["before", "after", "target"]}
TOOLS = [
    {"name": "list_files", "description": "List permitted tracked paths in a fixed snapshot. Paginate with next_cursor.", "input_schema": _schema({"snapshot": _SNAPSHOT, "prefix": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}}, [])},
    {"name": "search_text", "description": "Literal, case-sensitive search of bounded permitted UTF-8 Git blobs.", "input_schema": _schema({"snapshot": _SNAPSHOT, "query": {"type": "string", "minLength": 1, "maxLength": 1000}, "path_prefix": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}}, ["query"])},
    {"name": "read_file", "description": "Read a tracked UTF-8 blob range, up to 200 lines and 16 KiB. Lines start at 1.", "input_schema": _schema({"snapshot": _SNAPSHOT, "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, ["path"])},
]
_ROOTS = {"readme.md", "readme", "pyproject.toml", "requirements.txt", "setup.cfg", "setup.py", "package.json", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "tsconfig.json"}


class ContextReader:
    def __init__(self, repository_path, data, diagnostics=None):
        self.repository_path = str(repository_path)
        self.snapshots = {"before": data["merge_base"], "after": data["head"], "target": data["base"]}
        if any(not isinstance(s, str) or not SHA.fullmatch(s) for s in self.snapshots.values()):
            raise ReviewError("invalid context snapshot")
        self.data, self.diagnostics = data, diagnostics
        self.sources, self.limitations = [], []
        self.max_operations = review_controls()["tool_operations"]
        self.operations = 0
        self._git_operations = 0
        self._deadline = time.monotonic() + POLICY["max_reader_seconds"]
        self._runtime_secrets = runtime_secrets()
        self._trees, self._blobs, self._cache, self._source_keys = {}, {}, {}, {}
        self._scan_bytes = {s: 0 for s in self.snapshots}
        self._tree_truncated = set()

    def _limit(self, message):
        if message not in self.limitations:
            self.limitations.append(message)

    def _env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        return env

    def _git_event(self, name, **fields):
        if self.diagnostics is not None:
            self.diagnostics.event(name, **fields)

    def _check_time(self):
        if time.monotonic() >= self._deadline:
            raise ReviewError("context reader time limit reached")

    def _start_git(self, command):
        self._check_time()
        self._git_operations += 1
        operation_id = f"git-{self._git_operations}"
        self._git_event("git.start", operation_id=operation_id, command=list(command))
        return operation_id, time.monotonic()

    def _git(self, *args):
        operation_id, started = self._start_git(args)
        try:
            result = subprocess.run(["git", "--no-pager", "-C", self.repository_path, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self._env(), timeout=max(0.001, min(TIMERS["context_git"], self._deadline - time.monotonic())), check=True)
            self._git_event("git.end", operation_id=operation_id, bytes=len(result.stdout), duration_ms=int((time.monotonic() - started) * 1000))
            return result.stdout
        except (subprocess.SubprocessError, OSError) as exc:
            self._git_event("git.error", operation_id=operation_id, error_code="git_context_failed", exception_class=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
            raise ReviewError("Git context operation failed") from exc

    @staticmethod
    def _allowed(path):
        if not path_ok(path):
            return False
        return not restricted_path(path)

    @bounded(TIMERS["context_git"] + TIMERS["git_cleanup"])
    def _tree(self, snapshot):
        if snapshot in self._trees:
            return self._trees[snapshot]
        # Stream NUL records, stopping at the policy bound instead of loading a huge tree.
        command = ["git", "--no-pager", "-C", self.repository_path, "ls-tree", "-rz", "--full-tree", self.snapshots[snapshot]]
        entries = {}
        count = 0
        operation_id, started = self._start_git(("ls-tree", snapshot, self.snapshots[snapshot]))
        tree_deadline = min(started + TIMERS["context_git"], self._deadline)
        incomplete = True
        byte_count = 0
        try:
            with deadline(max(.001, tree_deadline - time.monotonic())), subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self._env()) as proc:
                try:
                    while True:
                        if time.monotonic() >= tree_deadline:
                            raise ReviewError("Git tree time limit exceeded")
                        record = bytearray()
                        while True:
                            char = proc.stdout.read(1)
                            if not char or char == b"\0":
                                break
                            record.extend(char)
                            if len(record) > 4096:
                                raise ReviewError("Git tree path exceeds bound")
                        if not record:
                            incomplete = False
                            break
                        byte_count += len(record) + 1
                        count += 1
                        if count > POLICY["max_paths"]:
                            self._tree_truncated.add(snapshot)
                            self._limit(f"{snapshot}: tree exceeds {POLICY['max_paths']} paths; remaining paths omitted")
                            break
                        metadata, raw_path = bytes(record).split(b"\t", 1)
                        mode, kind, blob = metadata.decode("ascii").split()
                        try:
                            path = raw_path.decode("utf-8")
                        except UnicodeError:
                            self._limit(f"{snapshot}: non-UTF-8 paths omitted")
                            continue
                        if kind == "blob" and mode in ("100644", "100755") and self._allowed(path):
                            entries[path] = blob
                        else:
                            self._limit(f"{snapshot}: restricted paths or non-regular objects omitted")
                finally:
                    if incomplete and proc.poll() is None:
                        proc.kill()
                    try:
                        proc.wait(timeout=max(.001, min(TIMERS["context_git"], tree_deadline - time.monotonic())))
                    finally:
                        # EOF does not imply process exit. Reap even when a
                        # deadline interrupts wait after stdout has closed.
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait(timeout=1)
                if not incomplete and proc.returncode != 0:
                    raise ReviewError("Git tree operation failed")
        except (OSError, subprocess.SubprocessError, ReviewError) as exc:
            self._git_event("git.error", operation_id=operation_id, error_code="git_tree_failed", exception_class=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
            raise ReviewError("Git tree operation failed") from exc
        self._git_event("git.end", operation_id=operation_id, bytes=byte_count, paths=count, truncated=snapshot in self._tree_truncated, duration_ms=int((time.monotonic() - started) * 1000))
        self._trees[snapshot] = entries
        return entries

    def _text(self, snapshot, path):
        tree = self._tree(snapshot)
        if path not in tree:
            raise ReviewError("path denied or absent from bounded snapshot")
        key = (snapshot, path)
        if key in self._blobs:
            value = self._blobs[key]
            if isinstance(value, ReviewError):
                raise value
            return value
        blob = tree[path]
        size = int(self._git("cat-file", "-s", blob))
        error = None
        if size > POLICY["max_blob_bytes"]:
            error = "blob exceeds 256 KiB limit"
        elif self._scan_bytes[snapshot] + size > POLICY["max_scan_bytes"]:
            error = "snapshot scan exceeds 32 MiB limit"
        if error:
            self._blobs[key] = ReviewError(error)
            raise self._blobs[key]
        raw = self._git("cat-file", "blob", blob)
        self._scan_bytes[snapshot] += size
        try:
            text = raw.decode("utf-8")
            if "\0" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise UnicodeError()
            if sensitive(text) or any(secret in text for secret in self._runtime_secrets):
                raise ReviewError("credential-like blob denied")
        except UnicodeError:
            self._blobs[key] = ReviewError("non-text blob denied")
            raise self._blobs[key]
        except ReviewError as exc:
            self._blobs[key] = exc
            raise
        self._blobs[key] = text
        return text

    def _source(self, snapshot, path, start, end, text):
        key = (snapshot, path, start, end, text)
        if key not in self._source_keys:
            source = {"source_id": "source-" + digest(list(key))[:24], "snapshot": snapshot, "path": path, "blob": self._tree(snapshot)[path], "start_line": start, "end_line": end, "text": text}
            self._source_keys[key] = source
            self.sources.append(source)
            self._git_event("git.source", source_id=source["source_id"], snapshot=snapshot, path=path, blob=source["blob"], start_line=start, end_line=end, bytes=len(text.encode()))
        return copy.deepcopy(self._source_keys[key])

    def execute(self, name, args):
        self.operations += 1
        if self.operations > self.max_operations:
            self._limit("tool operation limit reached")
            return {"ok": False, "error": "tool operation limit reached", "truncated": False, "next_cursor": None}
        try:
            self._check_time()
            if not isinstance(args, dict):
                raise ReviewError("tool arguments must be an object")
            schemas = {t["name"]: t["input_schema"] for t in TOOLS}
            if name not in schemas:
                raise ReviewError("unknown tool")
            schema = schemas[name]
            if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
                raise ReviewError("invalid tool argument fields")
            snapshot = args.get("snapshot", "after")
            if snapshot not in self.snapshots:
                raise ReviewError("invalid snapshot")
            for field in ("cursor", "start_line", "end_line"):
                if field in args and (type(args[field]) is not int or args[field] < (0 if field == "cursor" else 1)):
                    raise ReviewError("invalid numeric tool argument")
            for field in ("prefix", "path_prefix", "path", "query"):
                if field in args and (not isinstance(args[field], str) or len(args[field]) > 1000):
                    raise ReviewError("invalid text tool argument")
            prefix = args.get("prefix", args.get("path_prefix", ""))
            if prefix and not path_ok(prefix.rstrip("/")):
                raise ReviewError("invalid path prefix")
            key = digest([name, args])
            if key in self._cache:
                return {**copy.deepcopy(self._cache[key]), "cached": True}
            result = self._execute(name, args, snapshot, prefix)
            self._cache[key] = result
            return copy.deepcopy(result)
        except (ReviewError, TypeError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ReviewError) else "invalid tool arguments"
            self._limit(message)
            return {"ok": False, "error": message, "truncated": False, "next_cursor": None}

    def _execute(self, name, args, snapshot, prefix):
        tree = self._tree(snapshot)
        result = {"ok": True, "snapshot": snapshot, "truncated": snapshot in self._tree_truncated, "next_cursor": None}
        if name == "read_file":
            path = args["path"]
            if not self._allowed(path):
                raise ReviewError("path denied by context policy")
            text = self._text(snapshot, path)
            lines = text.splitlines(keepends=True)
            start = args.get("start_line", 1)
            requested = args.get("end_line", start + 199)
            if requested < start:
                raise ReviewError("invalid line range")
            if start > len(lines):
                raise ReviewError("start line outside file")
            end = min(requested, start + POLICY["max_read_lines"] - 1, len(lines))
            selected, size = [], 0
            for line in lines[start - 1:end]:
                if size + len(line.encode()) > POLICY["max_read_bytes"]:
                    break
                selected.append(line)
                size += len(line.encode())
            if not selected:
                raise ReviewError("single line exceeds read byte limit")
            end = start + len(selected) - 1
            truncated = end < min(requested, len(lines))
            if truncated:
                self._limit(f"{snapshot}:{path}: read range truncated")
            result.update(source=self._source(snapshot, path, start, end, "".join(selected)), truncated=result["truncated"] or truncated, next_line=end + 1 if end < len(lines) else None)
            return result
        cursor = args.get("cursor", 0)
        paths = sorted(p for p in tree if p.startswith(prefix))
        if name == "list_files":
            page = paths[cursor:cursor + POLICY["list_page"]]
            result["files"] = [{"path": p, "blob": tree[p]} for p in page]
            if cursor + len(page) < len(paths):
                result["next_cursor"] = cursor + len(page)
            return result
        query = args["query"]
        if sensitive(query) or any(secret in query for secret in self._runtime_secrets):
            raise ReviewError("credential-like search query denied")
        if not query or "\n" in query or "\r" in query or "\0" in query:
            raise ReviewError("query must be nonempty single-line literal text")
        matches, skipped, index = [], 0, 0
        # Scan bounded blobs; keep only one page plus a lookahead match in memory.
        for path in paths:
            self._check_time()
            try:
                text = self._text(snapshot, path)
            except ReviewError as exc:
                skipped += 1
                self._limit(f"{snapshot}: search omitted blobs ({exc})")
                continue
            for number, line in enumerate(text.splitlines(keepends=True), 1):
                if query not in line:
                    continue
                if len(line.encode()) > POLICY["max_read_bytes"]:
                    skipped += 1
                    self._limit(f"{snapshot}: search omitted oversized matching lines")
                    continue
                if index >= cursor:
                    if len(matches) == POLICY["search_page"]:
                        result.update(matches=matches, next_cursor=index, skipped=skipped, truncated=result["truncated"] or bool(skipped))
                        return result
                    matches.append(self._source(snapshot, path, number, number, line))
                index += 1
        result.update(matches=matches, skipped=skipped, truncated=result["truncated"] or bool(skipped))
        return result

    def initial_context(self):
        changed = locations(self.data["diff"])
        used = 0
        for path in changed:
            try:
                text = self._text("after", path)
                size = len(text.encode())
                if size > POLICY["initial_file_bytes"] or used + size > POLICY["initial_changed_bytes"]:
                    self._limit(f"after:{path}: omitted from initial changed-file budget")
                    continue
                if text:
                    self._source("after", path, 1, len(text.splitlines()), text)
                used += size
            except ReviewError as exc:
                self._limit(f"after:{path}: initial context omitted ({exc})")
        used = 0
        for path in sorted(self._tree("after")):
            if "/" in path or path.lower() not in _ROOTS or path in changed:
                continue
            try:
                text = self._text("after", path)
                size = len(text.encode())
                if size > POLICY["initial_file_bytes"] or used + size > POLICY["initial_root_bytes"]:
                    self._limit(f"after:{path}: omitted from initial root-file budget")
                    continue
                if text:
                    self._source("after", path, 1, len(text.splitlines()), text)
                used += size
            except ReviewError as exc:
                self._limit(f"after:{path}: initial context omitted ({exc})")
        return copy.deepcopy(self.sources)

    def verify_source(self, source):
        """Verify exact complete-line evidence against trusted Git objects."""
        required = {"source_id", "snapshot", "path", "blob", "start_line", "end_line", "text"}
        if not isinstance(source, dict) or set(source) != required:
            raise ReviewError("invalid evidence fields")
        snapshot, path = source["snapshot"], source["path"]
        if not isinstance(snapshot, str) or snapshot not in self.snapshots or not isinstance(path, str) or not self._allowed(path):
            raise ReviewError("invalid evidence snapshot/path")
        start, end = source["start_line"], source["end_line"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise ReviewError("invalid evidence range")
        lines = self._text(snapshot, path).splitlines(keepends=True)
        if end > len(lines) or source["blob"] != self._tree(snapshot)[path] or source["text"] != "".join(lines[start - 1:end]):
            raise ReviewError("evidence disagrees with Git snapshot")
        expected = "source-" + digest([snapshot, path, start, end, source["text"]])[:24]
        if source["source_id"] != expected:
            raise ReviewError("invalid evidence identifier")
        return True

    def verify_metadata(self, source):
        """Verify compact publication evidence without consuming model tool operations."""
        required = {"source_id", "snapshot", "path", "blob", "start_line", "end_line", "text_hash"}
        if not isinstance(source, dict) or set(source) != required:
            raise ReviewError("invalid evidence metadata fields")
        snapshot, path = source["snapshot"], source["path"]
        if not isinstance(snapshot, str) or snapshot not in self.snapshots or not isinstance(path, str) or not self._allowed(path):
            raise ReviewError("invalid evidence snapshot/path")
        start, end = source["start_line"], source["end_line"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise ReviewError("invalid evidence range")
        lines = self._text(snapshot, path).splitlines(keepends=True)
        if end > len(lines):
            raise ReviewError("evidence range outside blob")
        text = "".join(lines[start - 1:end])
        if source["text_hash"] != digest(text):
            raise ReviewError("evidence text hash disagrees with Git snapshot")
        full = {k: v for k, v in source.items() if k != "text_hash"}
        full["text"] = text
        return self.verify_source(full)
