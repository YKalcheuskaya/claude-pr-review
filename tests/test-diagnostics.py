import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pr_review.diagnostics import Diagnostics, MAX_BUNDLE_BYTES, sanitize


class DiagnosticsTests(unittest.TestCase):
    def test_secrets_redacted_before_all_sinks_and_reopening(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "GITHUB_TOKEN": "canary-github-credential", "ANTHROPIC_API_KEY": "canary-anthropic-credential",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}):
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                log = Diagnostics(directory, "analyze")
                for secret in ("canary-github-credential", "canary-anthropic-credential"):
                    log.event("tool.start", query=secret, operation_id="tool-01")
                    log.request("call-01", {"diff": secret, "password": "hidden-password"})
                    log.response("call-01", secret)
                    log.context([{"source_id": "source-01", "text": secret}])
                log.error(ValueError("canary-github-credential"))
                log.finalize("failed")
                reopened = Diagnostics(directory, "finalize")
                manifest = reopened.finalize("failed")
            combined = console.getvalue() + "".join(path.read_text() for path in Path(directory).iterdir())
            for secret in ("canary-github-credential", "canary-anthropic-credential", "hidden-password"):
                self.assertNotIn(secret, combined)
            self.assertTrue(manifest["redacted"])
            self.assertFalse(manifest["complete"])
            self.assertEqual(manifest["trace_id"], "github-123-2")
            self.assertEqual(len((Path(directory) / "requests.jsonl").read_text().splitlines()), 2)

    def test_hostile_strings_remain_json_data(self):
        hostile = "::error::fake\nforged log\n<script>evil()</script>\n```"
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as console:
            log = Diagnostics(directory, "analyze")
            log.event("tool.start", query=hostile)
            log.finalize("success", note=hostile)
            self.assertEqual(len(console.getvalue().splitlines()), 1)
            self.assertNotIn("::error::", console.getvalue())
            self.assertNotIn("<script>", console.getvalue())
            row = json.loads((Path(directory) / "events.jsonl").read_text())
            self.assertEqual(row["query"], hostile)

    def test_bundle_is_bounded_and_truncation_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "analyze")
            log.request("call-01", "x" * (MAX_BUNDLE_BYTES + 100))
            log.response("call-01", "y" * (MAX_BUNDLE_BYTES + 100))
            log.context(["z" * MAX_BUNDLE_BYTES])
            manifest = log.finalize("failed")
            self.assertLessEqual(sum(path.stat().st_size for path in Path(directory).iterdir()), MAX_BUNDLE_BYTES)
            self.assertTrue(manifest["truncated"])
            self.assertFalse(manifest["complete"])
            row = json.loads((Path(directory) / "responses.jsonl").read_text())
            self.assertTrue(row["truncated"])
            self.assertEqual(len(row["sanitized_sha256"]), 64)
            self.assertIn("prefix", row)

    def test_failure_without_result_records_safe_frames(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "analyze")
            log.event("sdk.start", operation_id="call-01")
            try:
                local_secret = "exception-only-plaintext"
                raise RuntimeError(local_secret)
            except RuntimeError as exc:
                log.finalize("failed", error=exc)
            combined = "".join(path.read_text() for path in Path(directory).iterdir())
            self.assertNotIn("exception-only-plaintext", combined)
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertEqual(manifest["error"]["exception_class"], "RuntimeError")
            self.assertEqual(set(manifest["error"]["stack"][0]), {"file", "line", "function"})
            self.assertTrue((Path(directory) / "summary.md").exists())
            self.assertFalse((Path(directory) / "result.json").exists())

    def test_patterns_and_sdk_objects_are_never_dumped(self):
        class Unsafe:
            def __repr__(self):
                raise AssertionError("must not repr SDK objects")
        value = sanitize({"authorization": "hidden", "nested": ["ghp_" + "a" * 30,
            "password=super-secret", "Bearer abc123", "-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----"], "sdk": Unsafe()})
        self.assertEqual(value["authorization"], "[REDACTED]")
        self.assertEqual(value["nested"], ["[REDACTED]"] * 4)
        self.assertEqual(value["sdk"], {"unserialized_type": "Unsafe"})

    def test_requests_flush_before_finalization_and_full_trace_success(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "prepare")
            log.request("api-01", {"route": "/repos/owner/repo/pulls/1"})
            self.assertEqual(json.loads((Path(directory) / "requests.jsonl").read_text())["operation_id"], "api-01")
            log.event("snapshot.end", head="a" * 40)
            manifest = log.finalize("success", snapshots={"head": "a" * 40})
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["last_successful_event"], "snapshot.end")

    def test_oversized_metadata_and_repeated_records_cannot_bypass_cap(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "analyze")
            with patch("pr_review.diagnostics.MAX_BUNDLE_BYTES", 280 * 1024):
                for index in range(100):
                    log.response(f"call-{index}", "x" * 6000)
                manifest = log.finalize("failed", provider_data="z" * MAX_BUNDLE_BYTES)
            self.assertLessEqual(sum(path.stat().st_size for path in Path(directory).iterdir()), 280 * 1024)
            self.assertTrue(manifest["truncated"])
            self.assertFalse(manifest["complete"])

    def test_provider_failure_preserves_safe_identifiers(self):
        class ProviderError(Exception):
            status_code = 429
            request_id = "req-test-01"
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "analyze")
            log.event("sdk.start", operation_id="call-01")
            log.response("call-01", {"error": "quota exhausted"}, status_code=429)
            log.finalize("failed", error=ProviderError("untrusted error body"))
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertEqual(manifest["error"]["status_code"], 429)
            self.assertEqual(manifest["error"]["request_id"], "req-test-01")
            self.assertNotIn("untrusted error body", (Path(directory) / "summary.md").read_text())

    def test_controlled_groups_summary_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as console:
            summary = Path(directory) / "step-summary"
            bundle = Path(directory) / "bundle"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                log = Diagnostics(bundle, "analyze")
                log.event("stage.start")
                manifest = log.finalize("success")
            self.assertIn("::group::Review analyze", console.getvalue())
            self.assertIn("::endgroup::", console.getvalue())
            self.assertIn("Review diagnostics", summary.read_text())
            self.assertIn("anthropic", manifest["runtime"])

    def test_open_operations_survive_reopen_and_block_complete(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            log = Diagnostics(directory, "analyze")
            log.event("sdk.start", operation_id="call-01")
            resumed = Diagnostics(directory, "finalize-diagnostics")
            manifest = resumed.finalize("failed")
            self.assertFalse(manifest["complete"])
            self.assertEqual(manifest["open_operations"], {"call-01": "sdk.start"})
            resumed.event("sdk.end", operation_id="call-01")
            self.assertTrue(resumed.finalize("success")["complete"])

    def test_typed_validation_and_sanitized_provider_body(self):
        from pr_review.core import ReviewError
        class ProviderError(Exception):
            status_code = 500
            request_id = "req-safe"
            body = {"error": "canary-provider-body"}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), patch.dict(os.environ, {"GITHUB_TOKEN": "canary-provider-body"}):
            log = Diagnostics(directory, "analyze")
            row = log.error(ReviewError("findings.2.reference: arbitrary body must be discarded"))
            self.assertEqual(row["validation_path"], "findings.2.reference")
            log.error(ProviderError("arbitrary secret"), operation_id="call-01")
            log.finalize("failed")
            response = json.loads((Path(directory) / "responses.jsonl").read_text())
            self.assertEqual(response["payload"], {"error": "[REDACTED]"})
            self.assertEqual(response["status_code"], 500)
            combined = "".join(path.read_text() for path in Path(directory).iterdir())
            self.assertNotIn("arbitrary body must be discarded", combined)
            self.assertNotIn("canary-provider-body", combined)
