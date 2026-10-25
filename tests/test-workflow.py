import copy
import json
import re
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / ".github/workflows/claude-review.yml"
BASE_REF = re.compile(r"\$\{\{\s*github\.event\.pull_request\.base\.sha\s*\}\}")
# GitHub expression strings use single quotes and escape them by doubling.
# A quoted `}}` is data, not the end of the expression.
EXPRESSION = re.compile(r"\$\{\{((?:'(?:[^']|'')*'|[^'])*?)\}\}", re.S)
SECRET_CONTEXT = re.compile(r"(?<![\w.])secrets\b", re.I)
PROVIDER_REF = re.compile(
    r"\$\{\{\s*secrets\s*(?:\.\s*CLAUDE_REVIEW_PROVIDER_KEY|\[\s*'CLAUDE_REVIEW_PROVIDER_KEY'\s*\])\s*\}\}", re.I)


def parse_workflow(text):
    # BaseLoader constructs only strings/lists/maps: preserve Actions' `on`
    # key and action-input strings without YAML 1.1 boolean coercion or tags.
    return yaml.load(text, Loader=yaml.BaseLoader)


def strings(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path + ("<key>",), key
            yield from strings(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, path + (index,))
    elif isinstance(value, str):
        yield path, value


def references_secrets(value):
    return any(SECRET_CONTEXT.search(expression) for expression in EXPRESSION.findall(value))


class WorkflowBoundaries(unittest.TestCase):
    def assert_review_boundaries(self, workflow):
        jobs = workflow["jobs"]
        analyze, publisher = jobs["analyze"], jobs["gate"]
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(analyze["permissions"], {"contents": "read", "pull-requests": "read"})
        self.assertEqual(publisher["permissions"], {"contents": "read", "pull-requests": "write"})
        environment = analyze["environment"]
        self.assertEqual(environment.get("name") if isinstance(environment, dict) else environment, "claude-review")
        self.assertNotIn("environment", publisher)
        needs = publisher["needs"]
        self.assertEqual(needs if isinstance(needs, list) else [needs], ["analyze"])
        self.assertIn(publisher["if"].strip(), ("always()", "${{ always() }}"))
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"].lower(), "false")
        self.assertEqual(set(workflow["on"]), {"pull_request_target"})
        trigger = workflow["on"]["pull_request_target"]
        self.assertEqual(trigger["branches"], ["main"])
        self.assertEqual(set(trigger["types"]), {"opened", "synchronize", "reopened", "ready_for_review", "edited"})

        for job_name, job in jobs.items():
            checkouts = [step for step in job.get("steps", [])
                         if step.get("uses", "").lower().startswith("actions/checkout@")]
            if job_name in ("analyze", "gate"):
                self.assertTrue(checkouts, f"{job_name}: trusted checkout required")
            for checkout in checkouts:
                options = checkout.get("with", {})
                self.assertIsNotNone(BASE_REF.fullmatch(options.get("ref", "").strip()), "checkout must use trusted base SHA")
                self.assertEqual(options.get("persist-credentials", "").lower(), "false",
                                 "checkout must explicitly disable credential persistence")

        # Inspect every parsed field, including job/step env, with, run and if.
        for path, value in strings(publisher):
            self.assertFalse(references_secrets(value), f"publisher secret reference at {path}")
            self.assertNotRegex(value, r"\b(?:ANTHROPIC_API_KEY|CLAUDE_REVIEW_PROVIDER_KEY)\b",
                                "publisher must not reference provider credential names")

        analysis_steps = [index for index, step in enumerate(analyze["steps"])
                          if re.search(r"(?m)^\s*python\s+-m\s+pr_review\.cli\s+analyze(?:\s|$)", step.get("run", ""))]
        self.assertEqual(len(analysis_steps), 1, "one provider analysis step required")
        provider_path = ("jobs", "analyze", "steps", analysis_steps[0], "env", "ANTHROPIC_API_KEY")
        provider_locations = []
        for path, value in strings(workflow):
            if path[-1:] in (("ANTHROPIC_API_KEY",), ("CLAUDE_REVIEW_PROVIDER_KEY",)) and "env" in path:
                self.assertEqual(path, provider_path, "provider env must be confined to analysis step")
            if references_secrets(value):
                # Unknown/dynamic secret lookups outside this slot fail closed.
                self.assertEqual(path, provider_path, "secret exposure outside provider analysis env")
                self.assertIsNotNone(PROVIDER_REF.fullmatch(value.strip()), "expected environment provider secret")
                provider_locations.append(path)
        self.assertEqual(provider_locations, [provider_path])

    def test_review_uses_base_and_separates_authority(self):
        self.assert_review_boundaries(parse_workflow(REVIEW.read_text()))

    def test_every_checkout_rejects_head_and_persistent_credentials(self):
        original = parse_workflow(REVIEW.read_text())
        for job_name in ("analyze", "gate"):
            checkout_index = next(index for index, step in enumerate(original["jobs"][job_name]["steps"])
                                  if step.get("uses", "").startswith("actions/checkout@"))
            for mutation in ("extra-head", "head", "persist-true", "persist-omitted"):
                workflow = copy.deepcopy(original)
                steps = workflow["jobs"][job_name]["steps"]
                checkout = steps[checkout_index]
                if mutation == "extra-head":
                    checkout = copy.deepcopy(checkout)
                    steps.append(checkout)
                if mutation in ("extra-head", "head"):
                    checkout["with"]["ref"] = "${{ github.event.pull_request.head.sha }}"
                elif mutation == "persist-true":
                    checkout["with"]["persist-credentials"] = "true"
                else:
                    del checkout["with"]["persist-credentials"]
                with self.subTest(job=job_name, mutation=mutation), self.assertRaises(AssertionError):
                    self.assert_review_boundaries(workflow)

    def test_publisher_rejects_secret_references_in_all_fields(self):
        original = parse_workflow(REVIEW.read_text())
        for expression in ("${{ secrets.OTHER_KEY }}", "${{ secrets [ 'OTHER_KEY' ] }}",
                           "${{ toJSON(secrets) }}", "${{ format('}}{0}', secrets.OTHER_KEY) }}",
                           "${{ format('It''s }}{0}', secrets['OTHER_KEY']) }}"):
            for field in ("env", "run", "with", "if", "job-env"):
                workflow = copy.deepcopy(original)
                publisher = workflow["jobs"]["gate"]
                if field == "job-env":
                    publisher["env"] = {"OTHER": expression}
                elif field in ("env", "with"):
                    publisher["steps"].append({field: {"OTHER": expression}})
                else:
                    publisher["steps"].append({field: expression})
                with self.subTest(expression=expression, field=field), self.assertRaisesRegex(AssertionError, "publisher secret reference"):
                    self.assert_review_boundaries(workflow)

    def test_provider_credential_cannot_escape_analysis_step(self):
        original = parse_workflow(REVIEW.read_text())
        expression = "${{ secrets.CLAUDE_REVIEW_PROVIDER_KEY }}"
        for location in ("workflow-env", "job-env", "setup-env", "checkout-token", "extra-job",
                         "publisher-env", "publisher-run", "analysis-run", "missing"):
            workflow = copy.deepcopy(original)
            analyze = workflow["jobs"]["analyze"]
            if location == "workflow-env":
                workflow["env"]["ANTHROPIC_API_KEY"] = expression
            elif location == "job-env":
                analyze["env"] = {"ANTHROPIC_API_KEY": expression}
            elif location == "setup-env":
                analyze["steps"][1]["env"] = {"RENAMED_PROVIDER_KEY": expression}
            elif location == "checkout-token":
                analyze["steps"][0]["with"]["token"] = expression
            elif location == "extra-job":
                workflow["jobs"]["extra"] = {"env": {"KEY": expression}, "steps": []}
            elif location == "publisher-env":
                workflow["jobs"]["gate"]["env"] = {"ANTHROPIC_API_KEY": "unexpected"}
            elif location == "publisher-run":
                workflow["jobs"]["gate"]["steps"].append({"run": 'echo "$ANTHROPIC_API_KEY"'})
            else:
                step = next(step for step in analyze["steps"] if "ANTHROPIC_API_KEY" in step.get("env", {}))
                if location == "missing":
                    del step["env"]["ANTHROPIC_API_KEY"]
                else:
                    step["run"] += "\necho " + expression
            with self.subTest(location=location), self.assertRaises(AssertionError):
                self.assert_review_boundaries(workflow)

    def test_equivalent_yaml_representations_pass(self):
        original = parse_workflow(REVIEW.read_text())
        alternate = copy.deepcopy(original)
        alternate["jobs"]["analyze"]["environment"] = {"name": "claude-review"}
        alternate["jobs"]["gate"]["needs"] = ["analyze"]
        alternate["jobs"]["gate"]["if"] = "${{ always() }}"
        for text in (yaml.safe_dump(original, sort_keys=True), json.dumps(original),
                     yaml.safe_dump(alternate, default_flow_style=True),
                     REVIEW.read_text().replace("${{ secrets.CLAUDE_REVIEW_PROVIDER_KEY }}", "${{ secrets [ 'CLAUDE_REVIEW_PROVIDER_KEY' ] }}")):
            with self.subTest(text=text[:60]):
                self.assert_review_boundaries(parse_workflow(text))

    def test_candidate_ci_has_no_provider_secret_and_collects_tests(self):
        text = (ROOT / ".github/workflows/verify.yml").read_text()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("write", text)
        self.assertIn("python scripts/run-tests.py", text)

    def test_actions_are_immutable(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            refs = [value for location, value in strings(parse_workflow(path.read_text())) if location[-1:] == ("uses",)]
            self.assertTrue(refs)
            for ref in refs:
                self.assertRegex(ref, r"^[^@]+@[0-9a-f]{40}$")

    def test_direct_sdk_pin_and_dependency_lock_agree(self):
        self.assertIn("anthropic==1.11.0", (ROOT / "pyproject.toml").read_text())
        self.assertIn("anthropic==1.11.0", (ROOT / "requirements-lock.txt").read_text())
