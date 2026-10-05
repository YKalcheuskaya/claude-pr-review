"""Validate retained live artifacts offline; never call providers or GitHub."""
import json
from pathlib import Path
import unittest

from pr_review.core import gate, validate_result


ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def read(case, name):
    return json.loads((ROOT / case / (name + ".json")).read_text())


class LiveEvidence(unittest.TestCase):
    def test_observed_snapshots_validate_and_gate(self):
        for case, expected in (("live-clean", True), ("live-defect", False),
                               ("live-fixed", True)):
            with self.subTest(case=case):
                data, result = read(case, "input"), read(case, "result")
                validate_result(result, data)
                self.assertTrue(result["live"])
                self.assertEqual(result["model"], "claude-haiku-4-5-20251001")
                self.assertEqual(gate(result), expected)
        self.assertNotEqual(read("live-defect", "input")["head"],
                            read("live-fixed", "input")["head"])

    def test_cached_rerun_preserves_result_and_usage(self):
        self.assertEqual(read("live-clean", "input"),
                         read("live-clean-rerun", "input"))
        self.assertEqual(read("live-clean", "result"),
                         read("live-clean-rerun", "result"))
