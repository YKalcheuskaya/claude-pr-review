"""Offline corpus, isolation, scoring and aggregate budget regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evaluation_v2", ROOT / "scripts" / "evaluate-v2.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class EvaluationV2(unittest.TestCase):
    def test_corpus_shape_and_cross_file_oracles(self):
        self.assertEqual(len(ev.cases("development")), 3)
        held = ev.cases("held-out")
        self.assertEqual(len(held), 12)
        for stack in ("python", "java-spring", "js-ts-react"):
            group = [case for case in held if case["stack"] == stack]
            labels = [ev.read(ev.CORPUS / "labels" / (case["id"] + ".json")) for case in group]
            self.assertEqual(sum(bool(label["expected"]) for label in labels), 2)
            self.assertEqual(len(group), 4)
            for case, label in zip(group, labels):
                for defect in label["expected"]:
                    self.assertNotEqual(case["before"][defect["changed_path"]], case["after"][defect["changed_path"]])
                    for related in defect["related_paths"]:
                        self.assertEqual(case["before"][related], case["after"][related])

    def test_prepare_excludes_labels_and_preserves_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = ev.prepare_case(ev.cases("held-out")[0], tmp)
            left, right = ev.read(directory / "diff-input.json"), ev.read(directory / "context-input.json")
            self.assertEqual(left["head"], right["head"])
            self.assertEqual(left["base"], right["base"])
            self.assertNotIn("case_id", left)
            self.assertEqual(left["diff"], right["diff"])
            self.assertNotIn("expected", json.dumps(left))
            self.assertNotIn("regression-1", json.dumps(right))
            repo_files = ev.git(directory / "repository", "ls-files")
            self.assertNotIn("labels", repo_files)
            self.assertFalse((directory / "repository" / ".git" / "config").read_text().find("[remote") >= 0)
            with self.assertRaises(ValueError):
                ev.prepare_case(ev.cases("held-out")[0], tmp)

    def test_fixture_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ev.materialize(Path(tmp), {"../escape.py": "bad"})

    def test_freeze_cli_normalizes_blank_model_and_rejects_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'CLAUDE_MODEL': '   '}):
            seal = Path(tmp)/'freeze.json'
            policy = Path(tmp)/'policy.txt'
            policy.write_text('test-only policy')
            self.assertEqual(ev.main(['freeze', '--policy', str(policy), '--output', str(seal)]), 0)
            self.assertEqual(ev.verify_freeze(seal)['model'], ev.MODEL)
            with patch.dict('os.environ', {'CLAUDE_MODEL': 'small'}):
                with self.assertRaises(ValueError):
                    ev.main(['freeze', '--policy', str(policy), '--output', str(Path(tmp)/'invalid.json')])
                self.assertFalse((Path(tmp)/'invalid.json').exists())

    def test_freeze_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy, seal = Path(tmp) / "policy.txt", Path(tmp) / "freeze.json"
            policy.write_text("frozen")
            ev.freeze(seal, [policy])
            self.assertEqual(ev.verify_freeze(seal)["model"], ev.MODEL)
            policy.write_text("changed")
            with self.assertRaises(ValueError):
                ev.verify_freeze(seal)

    def test_budget_failed_and_unknown_remain_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            for number in range(20):
                ev.reserve(ledger, str(number), "context", 100, 100, 1, 5, "explicit-pilot-approval", "verified-current-pricing")
            with self.assertRaises(ValueError):
                ev.reserve(ledger, "overflow", "diff", 1, 1, 1, 5, "approval", "pricing")
            self.assertEqual(sum(ev.money(row["reserved_usd"]) for row in ev.read(ledger)["entries"]), ev.PILOT_CAP)

    def test_budget_requires_approval_preflight_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            for input_tokens, output_tokens, approval in ((1, 1, ""), (1, 0, "approved"), (1_000_000, 100, "approved")):
                with self.assertRaises(ValueError):
                    ev.reserve(ledger, "a", "context", input_tokens, output_tokens, 1, 5, approval, "pricing")
            ev.reserve(ledger, "a", "diff", 100, 100, 1, 5, "approved", "pricing")
            with self.assertRaises(ValueError):
                ev.reserve(ledger, "a", "diff", 100, 100, 1, 5, "approved", "pricing")

    def report_fixture(self, tmp):
        policy, seal = Path(tmp) / "policy.txt", Path(tmp) / "freeze.json"
        policy.write_text("frozen")
        frozen = ev.freeze(seal, [policy])
        records = {"freeze_id": frozen["freeze_id"], "model": ev.MODEL, "runs": []}
        for case in ev.cases("held-out"):
            oracle = ev.read(ev.CORPUS / "labels" / (case["id"] + ".json"))["expected"]
            for mode in ("diff", "context"):
                findings = []
                if oracle and mode == "context":
                    findings = [{"expected_id": oracle[0]["id"], "severity": "high", "evidence_correct": True,
                                 "adjudicator": "offline-test", "rationale": "Synthetic scoring assertion only"}]
                records["runs"].append({"case_id": case["id"], "mode": mode, "status": "complete",
                                        "latency_ms": 10, "cost_usd": "0.001", "findings": findings})
        path = Path(tmp) / "records.json"
        ev.write(path, records)
        return path, seal, records

    def test_scoring_paired_runs_and_claim_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, seal, _ = self.report_fixture(tmp)
            result = ev.report(path, seal)
            self.assertTrue(result["all_pairs_present"])
            self.assertEqual(result["additional_detected_defects"], 6)
            self.assertEqual(result["metrics"]["context"]["recall"], 1)
            self.assertEqual(result["metrics"]["diff"]["recall"], 0)
            self.assertIn("Provisional", result["claim_boundary"])

    def test_clean_high_false_positive_blocks_improvement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, seal, records = self.report_fixture(tmp)
            row = next(row for row in records["runs"] if row["case_id"] == "heldout-03" and row["mode"] == "context")
            row["findings"] = [{"expected_id": None, "severity": "high", "evidence_correct": False,
                                "adjudicator": "offline-test", "rationale": "Unsupported claim"}]
            ev.write(path, records)
            self.assertFalse(ev.report(path, seal)["observed_improvement_criterion"])

    def test_missing_pairs_and_duplicate_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, seal, records = self.report_fixture(tmp)
            records["runs"].pop()
            ev.write(path, records)
            self.assertIsNone(ev.report(path, seal)["observed_improvement_criterion"])
            records["runs"].append(records["runs"][0])
            ev.write(path, records)
            with self.assertRaises(ValueError):
                ev.report(path, seal)

    def test_failed_run_cannot_claim_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, seal, records = self.report_fixture(tmp)
            row = next(row for row in records["runs"] if row["findings"])
            row["status"] = "failure"
            ev.write(path, records)
            with self.assertRaises(ValueError):
                ev.report(path, seal)

    def test_report_requires_human_adjudication(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, seal, records = self.report_fixture(tmp)
            row = next(row for row in records["runs"] if row["findings"])
            row["findings"][0].pop("adjudicator")
            ev.write(path, records)
            with self.assertRaises(ValueError):
                ev.report(path, seal)

    def test_nonfinite_budget_rejected(self):
        for value in ("NaN", "Infinity", "-1"):
            with self.assertRaises(ValueError):
                ev.money(value)


class PaidExecutionAdapter(unittest.TestCase):
    def setup_case(self, tmp):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from pr_review import v2, context, config
        directory = ev.prepare_case(ev.cases("held-out")[0], tmp)
        seal = Path(tmp) / "freeze.json"
        ev.freeze(seal, [v2.__file__, context.__file__, config.__file__, Path(v2.__file__).with_name("review-policy.md")])
        return dict(input_path=directory / "context-input.json", repository_path=directory / "repository",
                    output=Path(tmp) / "result.json", diagnostics_dir=Path(tmp) / "diagnostics",
                    ledger_path=Path(tmp) / "ledger.json", seal_path=seal, run_id="test-run",
                    authorize_paid=True, authorization_reference="separately-recorded-human-approval",
                    pricing_reference="dated-provider-price-reference", input_rate="1", output_rate="5")

    def test_selected_model_and_prices_are_preserved_by_adapter(self):
        from pr_review import v2, context, config
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {
                'CLAUDE_INPUT_USD_PER_MILLION': '3', 'CLAUDE_OUTPUT_USD_PER_MILLION': '15',
                'CLAUDE_MAX_REVIEW_USD': '1'}):
            model = 'claude-selected-test-model'
            directory = ev.prepare_case(ev.cases('development')[0], tmp, model=model)
            seal = Path(tmp) / 'freeze.json'
            ev.freeze(seal, [v2.__file__, context.__file__, config.__file__, Path(v2.__file__).with_name("review-policy.md")], model=model)
            data = ev.read(directory / 'context-input.json')
            result = v2.analyze(data, recorded={'status': 'complete', 'summary': 'Authored replay',
                                'findings': [], 'limitations': []}, repository_path=directory/'repository')
            with patch('pr_review.v2.analyze', return_value=result) as analyze:
                ev.run_paid(input_path=directory/'context-input.json', repository_path=directory/'repository',
                            output=Path(tmp)/'result.json', diagnostics_dir=Path(tmp)/'trace',
                            ledger_path=Path(tmp)/'ledger.json', seal_path=seal, run_id='selected',
                            authorize_paid=True, authorization_reference='test-only', pricing_reference='test-only',
                            input_rate='3', output_rate='15')
                self.assertEqual(analyze.call_args.args[0]['model'], model)
            row = ev.read(Path(tmp)/'ledger.json')['entries'][0]
            self.assertEqual(ev.money(row['reserved_usd']), 1)
            self.assertEqual(row['input_usd_per_million'], '3')

    def test_no_authorization_means_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = self.setup_case(tmp)
            options["authorize_paid"] = False
            with patch("pr_review.v2.analyze") as analyze:
                with self.assertRaises(ValueError):
                    ev.run_paid(**options)
                analyze.assert_not_called()
            self.assertFalse(options["ledger_path"].exists())

    def test_reservation_precedes_call_and_failure_retains_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = self.setup_case(tmp)
            def fail(*args, **kwargs):
                self.assertIsNone(kwargs["github"])
                row = ev.read(options["ledger_path"])["entries"][0]
                self.assertEqual(row["reserved_usd"], "0.20")
                self.assertEqual(row["input_tokens"], 120000)
                self.assertEqual(row["output_tokens"], 12000)
                raise RuntimeError("untrusted-secret-exception")
            with patch("pr_review.v2.analyze", side_effect=fail):
                with self.assertRaisesRegex(ValueError, "reservation retained"):
                    ev.run_paid(**options)
            self.assertEqual(len(ev.read(options["ledger_path"])["entries"]), 1)
            self.assertFalse(options["output"].exists())
            self.assertTrue((options["diagnostics_dir"] / "summary.md").exists())
            self.assertNotIn("untrusted-secret-exception", (options["diagnostics_dir"] / "summary.md").read_text())

    def test_success_writes_valid_result_without_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = self.setup_case(tmp)
            from pr_review import v2
            data = ev.read(options["input_path"])
            result = v2.analyze(data, recorded={"status": "complete", "summary": "Offline fixture",
                                "findings": [], "limitations": []}, repository_path=options["repository_path"])
            with patch("pr_review.v2.analyze", return_value=result) as analyze:
                ev.run_paid(**options)
                analyze.assert_called_once()
            self.assertEqual(ev.read(options["output"]), result)
            self.assertEqual(ev.read(options["ledger_path"])["entries"][0]["status"], "reserved-or-unknown")

    def test_unsealed_policy_and_excess_rates_prevent_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = self.setup_case(tmp)
            options["input_rate"] = "2"
            with patch("pr_review.v2.analyze") as analyze:
                with self.assertRaises(ValueError):
                    ev.run_paid(**options)
                analyze.assert_not_called()
            self.assertFalse(options["ledger_path"].exists())
            options["input_rate"] = "1"
            other = Path(tmp) / "other-policy.txt"
            other.write_text("not the actual policies")
            options["seal_path"] = Path(tmp) / "other-freeze.json"
            ev.freeze(options["seal_path"], [other])
            with patch("pr_review.v2.analyze") as analyze:
                with self.assertRaises(ValueError):
                    ev.run_paid(**options)
                analyze.assert_not_called()
