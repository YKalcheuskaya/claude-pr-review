import json
import os
import unittest
from unittest.mock import patch

from pr_review.config import effective_config, review_budget, review_controls, selected_model, cache_only_mode
from pr_review.runtime import TIMERS
from pr_review.core import DEFAULT_MODEL, ReviewError


class ReviewBudget(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_conservative_default_prices_and_existing_mode_ceiling(self):
        self.assertEqual(review_budget(DEFAULT_MODEL), {
            "input_rate": "0.5", "output_rate": "2.5", "max_cost": None})

    def test_long_input_limit_retains_conservative_haiku_price_envelope(self):
        self.assertEqual(selected_model(), 'claude-haiku-5-5')
        with patch.dict(os.environ, {'CLAUDE_MAX_INPUT_TOKENS': '128000'}):
            self.assertEqual(effective_config()['budget'], {
                'input_rate': '0.5', 'output_rate': '2.5', 'max_cost': None})

    def test_any_selected_model_accepts_explicit_prices_and_ceiling(self):
        with patch.dict(os.environ, {
            "CLAUDE_INPUT_USD_PER_MILLION": "3.000",
            "CLAUDE_OUTPUT_USD_PER_MILLION": "15e0",
            "CLAUDE_MAX_REVIEW_USD": "0.5000",
        }):
            budget = review_budget("user-selected-model")
        self.assertEqual(budget, {
            "input_rate": "3", "output_rate": "15", "max_cost": "0.5"})
        self.assertEqual(json.loads(json.dumps(budget)), budget)

    def test_nondefault_model_requires_both_prices(self):
        for env in ({}, {"CLAUDE_INPUT_USD_PER_MILLION": "3"},
                    {"CLAUDE_OUTPUT_USD_PER_MILLION": "15"}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                with self.assertRaisesRegex(ReviewError, "configuration:.*requires both") as caught:
                    review_budget("user-selected-model")
                self.assertEqual(caught.exception.stage, "configuration")
                self.assertEqual(caught.exception.code, "configuration.missing_prices")

    def test_all_overrides_reject_invalid_or_nonpositive_values(self):
        for name in ("CLAUDE_INPUT_USD_PER_MILLION", "CLAUDE_OUTPUT_USD_PER_MILLION",
                     "CLAUDE_MAX_REVIEW_USD"):
            for value in ("oops", "NaN", "sNaN", "Infinity", "-Infinity",
                          "0", "-0", "-0.1"):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    with self.assertRaisesRegex(ReviewError, f"configuration: {name}") as caught:
                        review_budget(DEFAULT_MODEL)
                    self.assertEqual(caught.exception.code, "configuration.invalid_budget")

    def test_extreme_decimal_representations_fail_without_materializing_them(self):
        for value in ('1e999999999', '1e-999999999', '1' * 129, '0.' + '0' * 128 + '1'):
            with self.subTest(value=value), patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': value}):
                with self.assertRaises(ReviewError):
                    review_budget(DEFAULT_MODEL)

    def test_blank_actions_variables_are_unset(self):
        with patch.dict(os.environ, {"CLAUDE_INPUT_USD_PER_MILLION": "",
                                    "CLAUDE_OUTPUT_USD_PER_MILLION": "  ",
                                    "CLAUDE_MAX_REVIEW_USD": "\t"}):
            self.assertEqual(review_budget(DEFAULT_MODEL), {
                "input_rate": "0.5", "output_rate": "2.5", "max_cost": None})
            with self.assertRaisesRegex(ReviewError, "configuration:.*requires both"):
                review_budget("user-selected-model")

    def test_environment_changes_are_resolved_at_runtime(self):
        original = review_budget(DEFAULT_MODEL)
        with patch.dict(os.environ, {"CLAUDE_INPUT_USD_PER_MILLION": "2",
                                    "CLAUDE_MAX_REVIEW_USD": "0.3"}):
            self.assertEqual(review_budget(DEFAULT_MODEL), {
                "input_rate": "2", "output_rate": "2.5", "max_cost": "0.3"})
        self.assertEqual(review_budget(DEFAULT_MODEL), original)

    def test_equivalent_prices_have_identical_identity(self):
        with patch.dict(os.environ, {"CLAUDE_INPUT_USD_PER_MILLION": "1e0",
                                    "CLAUDE_OUTPUT_USD_PER_MILLION": "5.000"}):
            self.assertEqual(review_budget(DEFAULT_MODEL), {
                "input_rate": "1", "output_rate": "5", "max_cost": None})

    def test_decimal_precision_is_preserved(self):
        rate = "1.123456789012345678901234567890123456789"
        with patch.dict(os.environ, {"CLAUDE_INPUT_USD_PER_MILLION": rate}):
            self.assertEqual(review_budget(DEFAULT_MODEL)["input_rate"], rate)


class ReviewControls(unittest.TestCase):
    integers = (
        ("CLAUDE_MAX_EXPLORATION_CALLS", "research_calls", 0, 8),
        ("CLAUDE_MAX_TOOL_OPERATIONS", "tool_operations", 1, 100),
        ("CLAUDE_MAX_INPUT_TOKENS", "input_tokens", 4096, 128000),
        ("CLAUDE_EXPLORATION_MAX_OUTPUT_TOKENS", "research_output", 1, 16000),
        ("CLAUDE_FINAL_MAX_OUTPUT_TOKENS", "final_output", 1, 16000),
    )

    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_defaults_are_json_compatible(self):
        controls = review_controls()
        self.assertEqual(controls, {
            "mode": "context", "fail_severity": "high", "research_calls": 4,
            "tool_operations": 12, "input_tokens": 24000,
            "research_output": 2000, "final_output": 4000})
        self.assertEqual(json.loads(json.dumps(controls)), controls)

    def test_integer_boundaries_and_zero_research(self):
        for name, key, minimum, maximum in self.integers:
            for value in (minimum, maximum):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: str(value)}):
                    self.assertEqual(review_controls()[key], value)

    def test_invalid_integer_controls_fail_before_execution(self):
        for name, _, minimum, maximum in self.integers:
            for value in (str(minimum - 1), str(maximum + 1), "1.0", "1e2", "+1",
                          "-1", "true", "NaN", " 1", "1 ", "١", "1\n", "9" * 5000):
                with self.subTest(name=name, value=value[:30]), patch.dict(os.environ, {name: value}):
                    with self.assertRaisesRegex(ReviewError, f"configuration: {name}") as caught:
                        review_controls()
                    self.assertEqual(caught.exception.stage, "configuration")
                    self.assertEqual(caught.exception.code, "config.invalid_controls")

    def test_enum_choices(self):
        for name, key, choices in (
            ("CLAUDE_REVIEW_MODE", "mode", ("context", "diff")),
            ("CLAUDE_FAIL_SEVERITY", "fail_severity", ("low", "medium", "high", "critical", "none")),
        ):
            for value in choices:
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    self.assertEqual(review_controls()[key], value)
            for value in ("HIGH", "false", "disabled", "context ", "high\n"):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    with self.assertRaises(ReviewError) as caught:
                        review_controls()
                    self.assertEqual(caught.exception.code, "config.invalid_controls")

    def test_blank_variables_and_runtime_changes(self):
        original = review_controls()
        names = [name for name, _, _, _ in self.integers] + ["CLAUDE_REVIEW_MODE", "CLAUDE_FAIL_SEVERITY"]
        for blank in ("", " \t\n"):
            with patch.dict(os.environ, dict.fromkeys(names, blank)):
                self.assertEqual(review_controls(), original)
        with patch.dict(os.environ, {"CLAUDE_REVIEW_MODE": "diff", "CLAUDE_MAX_EXPLORATION_CALLS": "0"}):
            self.assertEqual(review_controls()["mode"], "diff")
            self.assertEqual(review_controls()["research_calls"], 0)
        self.assertEqual(review_controls(), original)

    def test_model_is_selected_at_runtime_without_allowlist(self):
        self.assertEqual(selected_model(), DEFAULT_MODEL)
        for value in ("claude-sonnet-4-6", "claude-future-model-99"):
            with patch.dict(os.environ, {"CLAUDE_MODEL": value}):
                self.assertEqual(selected_model(), value)
        for value in ("", " \n"):
            with patch.dict(os.environ, {"CLAUDE_MODEL": value}):
                self.assertEqual(selected_model(), DEFAULT_MODEL)
        self.assertEqual(selected_model(), DEFAULT_MODEL)

    def test_invalid_model_ids(self):
        for value in ("small", "high", "claude-", "Claude-sonnet", "claude-sonnet ",
                      "claude-sonnet\n", "claude_/model", "claude-sonnet;cmd"):
            with self.subTest(value=value), patch.dict(os.environ, {"CLAUDE_MODEL": value}):
                with self.assertRaises(ReviewError) as caught:
                    selected_model()
                self.assertEqual(caught.exception.code, "configuration.invalid_model")
        with self.assertRaises(ReviewError):
            effective_config(model="other-provider")

    def test_effective_configuration_has_no_secrets(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "must-not-appear", "GITHUB_TOKEN": "also-secret"}):
            config = effective_config()
        self.assertEqual(config, {"model": DEFAULT_MODEL,
                                  "budget": review_budget(DEFAULT_MODEL), "controls": review_controls(),
                                  "timers": TIMERS})
        serialized = json.dumps(config)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("must-not-appear", serialized)

    def test_effective_configuration_uses_selected_model_prices(self):
        with patch.dict(os.environ, {"CLAUDE_MODEL": "claude-future-model", "CLAUDE_INPUT_USD_PER_MILLION": "3",
                                    "CLAUDE_OUTPUT_USD_PER_MILLION": "15", "CLAUDE_FAIL_SEVERITY": "none"}):
            config = effective_config()
            self.assertEqual(config["model"], "claude-future-model")
            self.assertEqual(config["budget"]["input_rate"], "3")
            self.assertEqual(config["controls"]["fail_severity"], "none")
            self.assertEqual(effective_config(model=DEFAULT_MODEL)["model"], DEFAULT_MODEL)
        with patch.dict(os.environ, {"CLAUDE_MODEL": "claude-future-model"}):
            with self.assertRaisesRegex(ReviewError, "requires both"):
                effective_config()


class CacheOnlyControl(unittest.TestCase):
    def test_switch_is_strict_without_changing_policy_identity(self):
        from pr_review.review import policies
        with patch.dict(os.environ, {}, clear=True):
            original = policies()
            self.assertFalse(cache_only_mode())
            with patch.dict(os.environ, {'CLAUDE_CACHE_ONLY': 'true'}):
                self.assertTrue(cache_only_mode())
                self.assertEqual(policies(), original)
            with patch.dict(os.environ, {'CLAUDE_CACHE_ONLY': 'TRUE'}):
                with self.assertRaises(ReviewError):
                    cache_only_mode()
