"""Exercise the context reader against real immutable Git objects."""
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from pr_review.context import ContextReader, POLICY
from pr_review.core import ReviewError, digest


class GitContext(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Context Test")
        self.git("config", "user.email", "test@example.invalid")
        self.write("app.py", "old = 1\n")
        self.write("caller.py", "from app import old\nprint(old)\n")
        self.write("README.md", "# Test repository\n")
        self.write(".env", "PASSWORD=private\n")
        self.write("vendor/hidden.py", "never exposed\n")
        self.write("secret.pem", "private\n")
        self.write("binary.dat", b"text\0binary")
        self.write("credential.py", "token = 'ghp_" + "a" * 25 + "'\n")
        self.write("many.py", "".join(f"needle {n}\n" for n in range(130)))
        self.git("add", ".")
        self.git("commit", "-qm", "before")
        before = self.git("rev-parse", "HEAD")
        self.write("app.py", "new = 2\n")
        (self.repo / "link.py").symlink_to("app.py")
        self.git("add", ".")
        self.git("commit", "-qm", "after")
        head = self.git("rev-parse", "HEAD")
        diff = self.git("diff", before, head, "--", "app.py") + "\n"
        self.data = {"merge_base": before, "head": head, "base": before, "diff": diff}
        self.reader = ContextReader(self.repo, self.data)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def write(self, path, text):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text if isinstance(text, bytes) else text.encode())

    def test_fixed_snapshots_ignore_worktree_and_preserve_evidence(self):
        self.write("app.py", "malicious worktree\n")
        self.write("untracked.py", "outside snapshot\n")
        after = self.reader.execute("read_file", {"path": "app.py"})["source"]
        before = self.reader.execute("read_file", {"snapshot": "before", "path": "app.py"})["source"]
        target = self.reader.execute("read_file", {"snapshot": "target", "path": "app.py"})["source"]
        self.assertEqual(after["text"], "new = 2\n")
        self.assertEqual(before["text"], "old = 1\n")
        self.assertEqual(target["blob"], before["blob"])
        self.assertNotEqual(after["blob"], before["blob"])
        self.assertTrue(self.reader.verify_source(after))
        forged = {**after, "text": "invented\n"}
        with self.assertRaises(ReviewError):
            self.reader.verify_source(forged)
        self.assertFalse(self.reader.execute("read_file", {"path": "untracked.py"})["ok"])

    def test_denies_paths_nonregular_objects_binary_and_credentials(self):
        for path in ("../app.py", "/app.py", ".env", "vendor/hidden.py", "secret.pem", "link.py", "binary.dat", "credential.py"):
            with self.subTest(path=path):
                result = self.reader.execute("read_file", {"path": path})
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
        self.assertFalse(any(s["path"] == "credential.py" for s in self.reader.sources))

    def test_literal_search_paginated_exact_line_sources(self):
        first = self.reader.execute("search_text", {"query": "needle", "path_prefix": "many.py"})
        self.assertEqual(len(first["matches"]), 50)
        self.assertEqual(first["next_cursor"], 50)
        self.assertEqual(first["matches"][0]["start_line"], 1)
        second = self.reader.execute("search_text", {"query": "needle", "path_prefix": "many.py", "cursor": first["next_cursor"]})
        self.assertEqual(second["matches"][0]["start_line"], 51)
        third = self.reader.execute("search_text", {"query": "needle", "path_prefix": "many.py", "cursor": second["next_cursor"]})
        self.assertEqual(len(third["matches"]), 30)
        self.assertIsNone(third["next_cursor"])
        self.assertEqual(self.reader.execute("search_text", {"query": "needle.*"})["matches"], [])
        for source in self.reader.sources:
            self.assertTrue(self.reader.verify_source(source))

    def test_read_bounds_cache_and_operation_budget(self):
        result = self.reader.execute("read_file", {"path": "many.py", "end_line": 1000})
        self.assertEqual(result["source"]["end_line"], 130)
        self.assertFalse(result["truncated"])
        with patch.dict(POLICY, {"max_read_lines": 10}):
            result = self.reader.execute("read_file", {"path": "many.py", "start_line": 2, "end_line": 1000})
            self.assertEqual(result["source"]["end_line"], 11)
            self.assertTrue(result["truncated"])
        repeated = self.reader.execute("read_file", {"path": "many.py", "start_line": 2, "end_line": 1000})
        self.assertTrue(repeated["cached"])
        with patch.object(self.reader, "_git", side_effect=AssertionError("cache must not read Git")):
            for _ in range(9):
                self.assertTrue(self.reader.execute("read_file", {"path": "many.py", "start_line": 2, "end_line": 1000})["ok"])
        self.assertFalse(self.reader.execute("list_files", {})["ok"])
        self.assertIn("tool operation limit reached", self.reader.limitations)

    def test_initial_small_files_and_root_manifest(self):
        sources = self.reader.initial_context()
        self.assertEqual({s["path"] for s in sources}, {"app.py", "README.md"})
        self.assertEqual(self.reader.operations, 0)
        self.assertEqual(self.reader.initial_context(), sources)
        for source in sources:
            self.assertTrue(self.reader.verify_source(source))

    def test_scan_and_blob_budgets_and_tree_pagination(self):
        with patch.dict(POLICY, {"list_page": 2}):
            listed = self.reader.execute("list_files", {})
        self.assertEqual(len(listed["files"]), 2)
        self.assertEqual(listed["next_cursor"], 2)
        with patch.dict(POLICY, {"max_blob_bytes": 1}):
            result = self.reader.execute("read_file", {"path": "caller.py"})
            self.assertIn("256 KiB", result["error"])
        fresh = ContextReader(self.repo, self.data)
        with patch.dict(POLICY, {"max_scan_bytes": 1}):
            result = fresh.execute("read_file", {"path": "caller.py"})
            self.assertIn("32 MiB", result["error"])
        fresh = ContextReader(self.repo, self.data)
        with patch.dict(POLICY, {"max_paths": 2}):
            result = fresh.execute("list_files", {})
            self.assertTrue(result["truncated"])
            self.assertTrue(fresh.limitations)

    def test_strict_arguments_and_invalid_snapshot(self):
        for name, args in (("shell", {}), ("read_file", {"path": "app.py", "extra": True}), ("read_file", {"path": "app.py", "start_line": True}), ("list_files", {"snapshot": "HEAD"}), ("search_text", {"query": ""}), ("search_text", {"query": "needle\n"}), ("list_files", {"prefix": "../"})):
            with self.subTest(name=name, args=args):
                self.assertFalse(self.reader.execute(name, args)["ok"])
        invalid = copy.deepcopy(self.data)
        invalid["head"] = "--help"
        with self.assertRaises(ReviewError):
            ContextReader(self.repo, invalid)

    def test_compact_metadata_verification_and_tampering(self):
        source = self.reader.execute("read_file", {"path": "many.py"})["source"]
        metadata = {k: v for k, v in source.items() if k != "text"}
        metadata["text_hash"] = digest(source["text"])
        self.reader.operations = 12
        self.assertTrue(self.reader.verify_metadata(metadata))
        self.assertEqual(self.reader.operations, 12)
        for key, value in (("text_hash", "f" * 64), ("blob", "a" * 40), ("source_id", "source-forged"), ("end_line", 131)):
            with self.subTest(key=key), self.assertRaises(ReviewError):
                self.reader.verify_metadata({**metadata, key: value})

    def test_runtime_secret_blob_and_query_are_withheld(self):
        canary = "runtime-canary-value-without-token-prefix"
        self.write("runtime.py", "value = '" + canary + "'\n")
        self.git("add", "runtime.py")
        self.git("commit", "-qm", "runtime fixture")
        self.data["head"] = self.git("rev-parse", "HEAD")
        with patch.dict(os.environ, {"GITHUB_TOKEN": canary}):
            reader = ContextReader(self.repo, self.data)
        blob = reader.execute("read_file", {"path": "runtime.py"})
        query = reader.execute("search_text", {"query": canary})
        self.assertFalse(blob["ok"])
        self.assertFalse(query["ok"])
        self.assertNotIn(canary, str(reader.sources) + str(reader.limitations) + str(blob) + str(query))

    def test_git_diagnostics_trace_and_missing_object_failure(self):
        logger = Mock()
        reader = ContextReader(self.repo, self.data, logger)
        source = reader.execute("read_file", {"path": "app.py"})["source"]
        events = [c.args[0] for c in logger.event.call_args_list]
        self.assertEqual(events.count("git.start"), events.count("git.end"))
        self.assertIn("git.source", events)
        self.assertNotIn(source["text"], str(logger.event.call_args_list))
        invalid = {**self.data, "head": "f" * 40}
        logger = Mock()
        reader = ContextReader(self.repo, invalid, logger)
        self.assertFalse(reader.execute("list_files", {})["ok"])
        self.assertIn("git.error", [c.args[0] for c in logger.event.call_args_list])

    def test_reader_deadline_prevents_context_operations(self):
        self.reader._deadline = 0
        result = self.reader.execute("read_file", {"path": "app.py"})
        self.assertFalse(result["ok"])
        self.assertIn("time limit", result["error"])
        self.assertFalse(self.reader.sources)

    def test_submodules_excluded_even_when_they_reference_existing_commit(self):
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.data["head"] + ",module")
        self.git("commit", "-qm", "gitlink")
        self.data["head"] = self.git("rev-parse", "HEAD")
        reader = ContextReader(self.repo, self.data)
        self.assertFalse(reader.execute("read_file", {"path": "module"})["ok"])
        self.assertNotIn("module", {f["path"] for f in reader.execute("list_files", {})["files"]})


if __name__ == "__main__":
    unittest.main()
