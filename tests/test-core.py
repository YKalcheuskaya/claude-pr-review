"""Current input, findings, patch, cache and publication contracts."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import ReviewFixture
from pr_review.core import (MAX_BYTES, ReviewError, cached_result, gate,
                           locations, payload, validate_input)
from pr_review.service import analyze


class Contracts(unittest.TestCase):
    def setUp(self):
        self.fixture = ReviewFixture()
        self.addCleanup(self.fixture.close)
        self.data, self.content = self.fixture.data, self.fixture.content

    def review(self, content=None):
        return analyze(self.data, recorded=content if content is not None else self.content,
                       repository_path=self.fixture.repository)

    def test_schema_version_must_be_an_integer(self):
        with self.assertRaises(ReviewError):
            validate_input({**self.data, "version": 2.0})
        result = self.review()
        from pr_review.core import validate_result
        with self.assertRaises(ReviewError):
            validate_result({**result, "version": 2.0}, self.data)

    def test_vertical_inline_and_gate(self):
        result = self.review()
        body = payload(self.data, result)
        self.assertEqual(body["commit_id"], self.data["head"])
        self.assertEqual(body["comments"][0]["line"], 2)
        self.assertEqual(body["comments"][0]["side"], "RIGHT")
        self.assertEqual(body["event"], "COMMENT")
        self.assertFalse(gate(result))
        self.assertFalse(result["live"])

    def test_all_severities(self):
        for severity, passed in (("low", True), ("medium", True), ("high", False), ("critical", False)):
            with self.subTest(severity=severity):
                self.content["findings"][0]["severity"] = severity
                self.assertEqual(gate(self.review()), passed)

    def test_clean_passes(self):
        self.assertTrue(gate(self.review(self.fixture.clean())))

    def test_partial_coverage_and_severity_are_independent(self):
        self.content.update(status="partial", limitations=["Insufficient surrounding context."])
        self.assertFalse(gate(self.review()))
        self.content["findings"][0]["severity"] = "low"
        result = self.review()
        self.assertTrue(gate(result))
        self.assertIn("INCOMPLETE REVIEW", payload(self.data, result)["body"])

    def test_invalid_output_and_position_rejected(self):
        variants = []
        c = copy.deepcopy(self.content)
        c["findings"][0]["anchor"]["end"] = 0
        variants.append(c)
        c = copy.deepcopy(self.content)
        c["findings"][0]["severity"] = "approve"
        variants.append(c)
        variants.extend([{}, {**self.content, "extra": "bad"}])
        for content in variants:
            with self.subTest(content=content), self.assertRaises(ReviewError):
                self.review(content)

    def test_deleted_side(self):
        self.content["findings"][0]["anchor"]["side"] = "LEFT"
        self.assertEqual(payload(self.data, self.review())["comments"][0]["side"], "LEFT")
        diff = "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex 1111111..0000000\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        self.assertEqual(set(locations(diff)["gone.py"]["LEFT"]), {1})

    def test_new_file_rename_and_executable_text(self):
        new = "diff --git a/new.py b/new.py\nnew file mode 100644\nindex 0000000..2222222\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+new\n"
        self.assertEqual(set(locations(new)["new.py"]["RIGHT"]), {1})
        self.assertEqual(locations(new), locations(new.replace("100644", "100755")))
        rename = "diff --git a/old.py b/new.py\nsimilarity index 50%\nrename from old.py\nrename to new.py\nindex 1111111..2222222 100644\n--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new\n"
        self.assertEqual(set(locations(rename)["new.py"]["LEFT"]), {1})
        self.assertEqual(locations(rename), locations(rename.replace("100644", "100755")))

    def test_multi_line_range_and_cross_hunk_body_fallback(self):
        anchor = self.content["findings"][0]["anchor"]
        anchor["start"] = 1
        comment = payload(self.data, self.review())["comments"][0]
        self.assertEqual(comment["start_line"], 1)
        self.data["diff"] += "@@ -10 +10 @@\n-x\n+y\n"
        anchor["end"] = 10
        body = payload(self.data, self.review())
        self.assertEqual(body["comments"], [])
        self.assertIn("The caller requires", body["body"])

    def test_limits_and_unsupported_inputs(self):
        diff = self.data["diff"]
        variants = ["x" * (MAX_BYTES + 1), "\x00", diff.replace("100644", "120000"),
                    diff.replace('+    return', 'GIT binary patch\n+    return'),
                    diff.replace("@@ -1,2 +1,2 @@", "@@ -1,4 +1 @@"),
                    diff.replace("contract.py", "../escape.py")]
        variants.append("".join(diff.replace("contract.py", f"file-{n}.py") for n in range(21)))
        for patch in variants:
            with self.subTest(diff=patch[:60]), self.assertRaises(ReviewError):
                locations(patch)

    def test_duplicate_and_invalid_identity(self):
        with self.assertRaises(ReviewError):
            locations(self.data["diff"] * 2)
        self.data["head"] = "--exec=bad"
        with self.assertRaises(ReviewError):
            validate_input(self.data)

    def test_only_current_contract_is_accepted(self):
        for version in (1, 3, True):
            with self.subTest(version=version), self.assertRaises(ReviewError):
                validate_input({**self.data, "version": version})

    def test_untrusted_output_escaped(self):
        self.content["summary"] = "<script>bad</script> @everyone <!-- result:spoof -->"
        body = payload(self.data, self.review())["body"]
        self.assertNotIn("<script>", body)
        self.assertNotIn("@everyone", body)
        self.assertIn("&lt;script&gt;", body)

    def test_cache_requires_bot_snapshot_and_valid_result(self):
        result = self.review()
        review = {"user": {"login": "github-actions[bot]", "type": "Bot"}, "state": "COMMENTED",
                  "commit_id": self.data["head"], "body": payload(self.data, result)["body"]}
        self.assertEqual(cached_result([review], self.data), result)
        spoof = copy.deepcopy(review)
        spoof["user"]["login"] = "human"
        self.assertIsNone(cached_result([spoof], self.data))
        self.assertIsNone(cached_result([review], {**self.data, "head": "c" * 40}))
