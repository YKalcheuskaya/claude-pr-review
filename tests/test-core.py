import copy
import json
from pathlib import Path
import unittest

from pr_review.core import (MAX_BYTES, ReviewError, cached_result, gate,
                           locations, payload, validate_content, validate_input)
from pr_review.service import analyze

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "evaluation" / name).read_text())


class Contracts(unittest.TestCase):
    def setUp(self):
        self.data = fixture("input.json")
        self.content = fixture("defect-response.json")

    def test_vertical_inline_and_gate(self):
        result = analyze(self.data, recorded=self.content)
        body = payload(self.data, result)
        self.assertEqual(body["commit_id"], self.data["head"])
        self.assertEqual(body["comments"][0]["line"], 1)
        self.assertEqual(body["comments"][0]["side"], "RIGHT")
        self.assertEqual(body["event"], "COMMENT")
        self.assertFalse(gate(result))
        self.assertFalse(result["live"])

    def test_all_severities(self):
        for severity, passed in (("low", True), ("medium", True), ("high", False), ("critical", False)):
            with self.subTest(severity=severity):
                self.content["findings"][0]["severity"] = severity
                self.assertEqual(gate(analyze(self.data, recorded=self.content)), passed)

    def test_clean_passes(self):
        self.assertTrue(gate(analyze(self.data, recorded=fixture("clean-response.json"))))

    def test_partial_blocks(self):
        self.content.update(status="partial", limitations=["Insufficient surrounding context."])
        self.assertFalse(gate(analyze(self.data, recorded=self.content)))

    def test_invalid_output_and_position_rejected(self):
        variants = []
        c = copy.deepcopy(self.content)
        c["findings"][0]["end"] = 2
        variants.append(c)
        c = copy.deepcopy(self.content)
        c["findings"][0]["severity"] = "approve"
        variants.append(c)
        variants.extend([{}, {**self.content, "extra": "bad"}, {**self.content, "limitations": ["missing context"]}])
        for content in variants:
            with self.subTest(content=content), self.assertRaises(ReviewError):
                validate_content(content, self.data)

    def test_deleted_side(self):
        self.content["findings"][0]["side"] = "LEFT"
        body = payload(self.data, analyze(self.data, recorded=self.content))
        self.assertEqual(body["comments"][0]["side"], "LEFT")
        self.data["diff"] = "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex 1111111..0000000\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        self.assertEqual(set(locations(self.data["diff"])["gone.py"]["LEFT"]), {1})

    def test_new_file_and_rename(self):
        new = "diff --git a/new.py b/new.py\nnew file mode 100644\nindex 0000000..2222222\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+new\n"
        self.assertEqual(set(locations(new)["new.py"]["RIGHT"]), {1})
        rename = "diff --git a/old.py b/new.py\nsimilarity index 50%\nrename from old.py\nrename to new.py\nindex 1111111..2222222 100644\n--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new\n"
        self.assertEqual(set(locations(rename)["new.py"]["LEFT"]), {1})

    def test_multi_line_range_and_cross_hunk_rejected(self):
        self.data["diff"] = self.data["diff"].replace("@@ -1 +1 @@\n-return completed < maximum\n+return completed <= maximum", "@@ -1,2 +1,2 @@\n-old\n+new\n context")
        self.content["findings"][0]["end"] = 2
        comment = payload(self.data, analyze(self.data, recorded=self.content))["comments"][0]
        self.assertEqual(comment["start_line"], 1)
        self.data["diff"] = fixture("input.json")["diff"] + "@@ -2 +2 @@\n-x\n+y\n"
        with self.assertRaises(ReviewError):
            analyze(self.data, recorded=self.content)

    def test_limits_and_unsupported_inputs(self):
        variants = ["x" * (MAX_BYTES + 1), "\x00", self.data["diff"].replace("100644", "100755"),
                    self.data["diff"].replace("+return", "GIT binary patch\n+return"),
                    self.data["diff"].replace("@@ -1 +1 @@", "@@ -1,4 +1 @@"),
                    self.data["diff"].replace("src/pr_review/demo.py", "../escape.py")]
        variants.append("".join(self.data["diff"].replace("demo.py", f"file-{n}.py") for n in range(21)))
        for diff in variants:
            with self.subTest(diff=diff[:60]), self.assertRaises(ReviewError):
                locations(diff)

    def test_duplicate_and_invalid_identity(self):
        with self.assertRaises(ReviewError):
            locations(self.data["diff"] * 2)
        self.data["head"] = "--exec=bad"
        with self.assertRaises(ReviewError):
            validate_input(self.data)

    def test_untrusted_output_escaped(self):
        self.content["summary"] = "<script>bad</script> @everyone <!-- result:spoof -->"
        body = payload(self.data, analyze(self.data, recorded=self.content))["body"]
        self.assertNotIn("<script>", body)
        self.assertNotIn("@everyone", body)
        self.assertIn("&lt;script&gt;", body)

    def test_cache_requires_bot_snapshot_and_valid_result(self):
        result = analyze(self.data, recorded=self.content)
        review = {"user": {"login": "github-actions[bot]", "type": "Bot"}, "state": "COMMENTED",
                  "commit_id": self.data["head"], "body": payload(self.data, result)["body"]}
        self.assertEqual(cached_result([review], self.data), result)
        spoof = copy.deepcopy(review)
        spoof["user"]["login"] = "human"
        self.assertIsNone(cached_result([spoof], self.data))
        changed = {**self.data, "head": "c" * 40}
        self.assertIsNone(cached_result([review], changed))


if __name__ == "__main__":
    unittest.main()
