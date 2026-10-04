import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowBoundaries(unittest.TestCase):
    def test_review_uses_base_and_separates_authority(self):
        text = (ROOT / ".github/workflows/claude-review.yml").read_text()
        analyze, publisher = text.split("  gate:")
        self.assertNotIn("pull-requests: write", analyze)
        self.assertIn("pull-requests: write", publisher)
        self.assertNotIn("ANTHROPIC_API_KEY", publisher)
        self.assertEqual(text.count("ref: ${{ github.event.pull_request.base.sha }}"), 2)
        self.assertNotIn("pull_request_target", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("if: always()", publisher)
        self.assertIn("types: [opened, synchronize, reopened, ready_for_review]", text)

    def test_candidate_ci_has_no_provider_secret_and_collects_tests(self):
        text = (ROOT / ".github/workflows/verify.yml").read_text()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("write", text)
        self.assertIn("python scripts/run-tests.py", text)

    def test_actions_are_immutable(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            refs = re.findall(r"uses:\s*([^\s]+)", path.read_text())
            self.assertTrue(refs)
            for ref in refs:
                self.assertRegex(ref, r"^[^@]+@[0-9a-f]{40}$")

    def test_direct_sdk_pin_and_dependency_lock_agree(self):
        self.assertIn("anthropic==1.11.0", (ROOT / "pyproject.toml").read_text())
        self.assertIn("anthropic==1.11.0", (ROOT / "requirements-lock.txt").read_text())
