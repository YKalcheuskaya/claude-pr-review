import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pr_review.cli import main
from pr_review.core import ReviewError, cached_result, payload
from pr_review.service import analyze

ROOT = Path(__file__).resolve().parents[1]


class CliScenarios(unittest.TestCase):
    def test_offline_commands_generate_payload_and_expected_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, expected in (("clean-response.json", 0), ("defect-response.json", 1)):
                result, body = str(Path(directory) / "result.json"), str(Path(directory) / "payload.json")
                input_path = str(ROOT / "evaluation/input.json")
                self.assertEqual(main(["analyze", "--input", input_path, "--recorded",
                    str(ROOT / "evaluation" / name), "--output", result]), 0)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["publish", "--input", input_path, "--result", result,
                                          "--dry-run", "--output", body]), expected)
                self.assertEqual(json.loads(Path(body).read_text())["event"], "COMMENT")

    def test_invalid_json_has_failure_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "invalid.json"
            file.write_text("not json")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["analyze", "--input", str(file), "--output", str(file)]), 2)

    def test_publisher_rejects_other_pr_before_network(self):
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        content = json.loads((ROOT / "evaluation/clean-response.json").read_text())
        result = analyze(data, recorded=content)
        with tempfile.TemporaryDirectory() as directory:
            event_path, result_path = Path(directory) / "event.json", Path(directory) / "result.json"
            event_path.write_text(json.dumps({"repository": {"full_name": data["repository"]},
                "number": 2, "pull_request": {"base": {"sha": data["base"]}, "head": {"sha": data["head"]}}}))
            result_path.write_text(json.dumps(result))
            with patch("pr_review.cli.api") as api, contextlib.redirect_stderr(io.StringIO()) as stderr:
                exit_code = main(["publish", "--input", str(ROOT / "evaluation/input.json"),
                    "--result", str(result_path), "--event", str(event_path)])
            self.assertEqual(exit_code, 2)
            api.assert_not_called()
            self.assertIn("workflow event", stderr.getvalue())

    def test_pending_matching_review_requires_reconciliation(self):
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        content = json.loads((ROOT / "evaluation/clean-response.json").read_text())
        result = analyze(data, recorded=content)
        review = {"user": {"login": "github-actions[bot]", "type": "Bot"}, "state": "PENDING",
                  "commit_id": data["head"], "body": payload(data, result)["body"]}
        with self.assertRaises(ReviewError):
            cached_result([review], data)

    def test_preflight_rejects_credential_like_diff(self):
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        data["diff"] = data["diff"].replace("+return", "+token='sk-ant-" + "x" * 30 + "'; return")
        with self.assertRaises(ReviewError):
            analyze(data, recorded=json.loads((ROOT / "evaluation/clean-response.json").read_text()))

    def test_prepare_rejects_stale_event_before_writing(self):
        data = json.loads((ROOT / "evaluation/input.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            event_path, output = Path(directory) / "event.json", Path(directory) / "input.json"
            event_path.write_text(json.dumps({"repository": {"full_name": data["repository"]},
                "number": 1, "pull_request": {"base": {"sha": data["base"]}, "head": {"sha": "c" * 40}}}))
            with patch("pr_review.cli.api"), patch("pr_review.cli.prepare", return_value=data), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["prepare", "--event", str(event_path), "--output", str(output)]), 2)
            self.assertFalse(output.exists())
