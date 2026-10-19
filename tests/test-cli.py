"""Offline CLI replay, trusted event identity and failure exit codes."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import ReviewFixture
from pr_review.cli import main
from pr_review.core import ReviewError, cached_result, payload
from pr_review.service import analyze


class CliScenarios(unittest.TestCase):
    def setUp(self):
        self.fixture = ReviewFixture()
        self.addCleanup(self.fixture.close)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.fixture.data
        self.input_path = self.root / "input.json"
        self.input_path.write_text(json.dumps(self.data))
        self.trace = str(self.root / "trace")

    def command(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()):
            return main([*arguments, "--diagnostics-dir", self.trace])

    def clean_result(self):
        return analyze(self.data, recorded=self.fixture.clean(), repository_path=self.fixture.repository)

    def test_offline_commands_generate_payload_and_expected_exit_codes(self):
        for name, response, expected in (("clean", self.fixture.clean(), 0), ("defect", self.fixture.content, 1)):
            with self.subTest(response=name):
                recorded = self.root / (name + "-response.json")
                recorded.write_text(json.dumps(response))
                result, body = str(self.root / "result.json"), str(self.root / "payload.json")
                self.assertEqual(self.command(["analyze", "--input", str(self.input_path), "--recorded", str(recorded),
                    "--repository-path", str(self.fixture.repository), "--output", result]), 0)
                self.assertEqual(self.command(["publish", "--input", str(self.input_path), "--result", result,
                    "--dry-run", "--output", body]), expected)
                self.assertEqual(json.loads(Path(body).read_text())["event"], "COMMENT")

    def test_blank_model_uses_default_for_preparation_and_publication(self):
        from pr_review.cli import args_model
        from pr_review.core import DEFAULT_MODEL
        with patch.dict("os.environ", {"CLAUDE_MODEL": ""}):
            event = self.root / "event.json"
            event.write_text(json.dumps({"repository": {"full_name": self.data["repository"]},
                "number": self.data["pr"], "pull_request": {
                "base": {"sha": self.data["base"]}, "head": {"sha": self.data["head"]}}}))
            with patch("pr_review.cli.api"), patch("pr_review.cli.prepare", return_value=self.data) as prepare:
                self.assertEqual(self.command(["prepare", "--event", str(event), "--output", str(self.root / "prepared.json")]), 0)
            self.assertEqual(prepare.call_args.kwargs["model"], DEFAULT_MODEL)
            self.assertEqual(args_model(self.data), DEFAULT_MODEL)

    def test_invalid_json_has_failure_exit(self):
        file = self.root / "invalid.json"
        file.write_text("not json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.command(["analyze", "--input", str(file), "--output", str(file)]), 2)

    def test_publisher_rejects_other_pr_before_network(self):
        event_path, result_path = self.root / "event.json", self.root / "result.json"
        event_path.write_text(json.dumps({"repository": {"full_name": self.data["repository"]},
            "number": 2, "pull_request": {"base": {"sha": self.data["base"]}, "head": {"sha": self.data["head"]}}}))
        result_path.write_text(json.dumps(self.clean_result()))
        with patch("pr_review.cli.api") as api, contextlib.redirect_stderr(io.StringIO()) as stderr:
            exit_code = self.command(["publish", "--input", str(self.input_path),
                "--result", str(result_path), "--event", str(event_path)])
        self.assertEqual(exit_code, 2)
        api.assert_not_called()
        self.assertIn("workflow event", stderr.getvalue())

    def test_pending_matching_review_requires_reconciliation(self):
        review = {"user": {"login": "github-actions[bot]", "type": "Bot"}, "state": "PENDING",
                  "commit_id": self.data["head"], "body": payload(self.data, self.clean_result())["body"]}
        with self.assertRaises(ReviewError):
            cached_result([review], self.data)

    def test_preflight_rejects_credential_like_diff(self):
        self.data["diff"] = self.data["diff"].replace('+    return', '+    token="sk-ant-' + "x" * 30 + '"; return')
        with self.assertRaises(ReviewError):
            analyze(self.data, recorded=self.fixture.clean(), repository_path=self.fixture.repository)

    def test_prepare_rejects_stale_event_before_writing(self):
        event_path, output = self.root / "event.json", self.root / "prepared.json"
        event_path.write_text(json.dumps({"repository": {"full_name": self.data["repository"]},
            "number": 1, "pull_request": {"base": {"sha": self.data["base"]}, "head": {"sha": "c" * 40}}}))
        with patch("pr_review.cli.api"), patch("pr_review.cli.prepare", return_value=self.data), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.command(["prepare", "--event", str(event_path), "--output", str(output)]), 2)
        self.assertFalse(output.exists())
