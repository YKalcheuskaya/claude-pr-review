"""Offline integration checks for user-controlled v2 runtime settings."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pr_review.cli import main
from pr_review.context import ContextReader
from pr_review.core import ReviewError, digest, gate, validate_result
from pr_review.service import analyze, prepare
from pr_review.v2 import policies, source_metadata, system_prompt


class FixtureGithub:
    def __init__(self, base, head):
        self.base, self.head = base, head

    def pr(self):
        return dict(state='open', draft=False, title='Rename contract', body='',
                    user={'type': 'User'}, base={'ref': 'main', 'sha': self.base},
                    head={'sha': self.head, 'repo': {'full_name': 'fixture/repo'}})


class RuntimeConfiguration(unittest.TestCase):
    def setUp(self):
        # Host configuration must not influence this isolated integration suite.
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args],
                                           text=True, stderr=subprocess.DEVNULL).strip()

        git('init', '-b', 'main')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'contract.py').write_text('FIELD = "name"\n')
        (self.root / 'caller.py').write_text('from contract import FIELD\nassert FIELD == "name"\n')
        git('add', '.')
        git('commit', '-m', 'base')
        base = git('rev-parse', 'HEAD')
        (self.root / 'contract.py').write_text('FIELD = "label"\n')
        git('commit', '-am', 'rename')
        self.github = FixtureGithub(base, git('rev-parse', 'HEAD'))
        self.clean = dict(status='complete', summary='No supported defect.',
                          findings=[], limitations=[])

    def prepared(self):
        return prepare(self.github, 'fixture/repo', 1, self.root, mode='context')

    def client(self, data, tool_count=1):
        calls = []

        def create(**kwargs):
            # Freeze requests because the analyzer extends its local transcript.
            calls.append(copy.deepcopy(kwargs))
            if 'tools' in kwargs:
                blocks = [NS(type='tool_use', id=f'tool_{len(calls)}_{n}',
                             name='read_file', input={'path': 'caller.py'})
                          for n in range(tool_count)]
                reason = 'tool_use'
            else:
                blocks = [NS(type='text', text=json.dumps(self.clean))]
                reason = 'end_turn'
            return NS(model=data['model'], stop_reason=reason, content=blocks,
                      usage=NS(input_tokens=100, output_tokens=20))

        return NS(messages=NS(create=create)), calls

    def test_exploration_and_output_limits_reach_provider(self):
        settings = {'CLAUDE_MAX_EXPLORATION_CALLS': '1',
                    'CLAUDE_EXPLORATION_MAX_OUTPUT_TOKENS': '321',
                    'CLAUDE_FINAL_MAX_OUTPUT_TOKENS': '654'}
        with patch.dict(os.environ, settings):
            data = self.prepared()
            client, calls = self.client(data)
            result = analyze(data, client=client, repository_path=self.root)
        self.assertEqual(result['calls'], 2)
        self.assertEqual([call['max_tokens'] for call in calls], [321, 654])
        self.assertIn('tools', calls[0])
        self.assertNotIn('tools', calls[-1])
        self.assertEqual(result['coverage'], 'partial')
        self.assertTrue(any('1 exploration calls' in line for line in result['content']['limitations']))

    def test_zero_exploration_calls_still_performs_final_review(self):
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0'}):
            data = self.prepared()
            client, calls = self.client(data)
            result = analyze(data, client=client, repository_path=self.root)
        self.assertEqual(result['calls'], 1)
        self.assertNotIn('tools', calls[0])
        self.assertEqual(result['coverage'], 'partial')
        self.assertIn('Exploration disabled by configuration.', result['content']['limitations'])

    def test_tool_operation_limit_returns_error_to_model_and_marks_coverage(self):
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '2',
                                    'CLAUDE_MAX_TOOL_OPERATIONS': '1'}):
            data = self.prepared()
            client, calls = self.client(data, tool_count=2)
            result = analyze(data, client=client, repository_path=self.root)
        replies = calls[1]['messages'][-1]['content']
        self.assertFalse(replies[0]['is_error'])
        self.assertTrue(replies[1]['is_error'])
        self.assertIn('operation limit', replies[1]['content'])
        self.assertTrue(any('operation limit' in line for line in result['content']['limitations']))
        self.assertEqual(result['coverage'], 'partial')

    def test_input_preflight_uses_configured_limit_before_generation(self):
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0',
                                    'CLAUDE_MAX_INPUT_TOKENS': '12000'}):
            data = self.prepared()
            client, calls = self.client(data)
            client.messages.count_tokens = lambda **kwargs: NS(input_tokens=12001)
            with self.assertRaisesRegex(ReviewError, 'budget.input'):
                analyze(data, client=client, repository_path=self.root)
        self.assertEqual(calls, [])

    def test_severity_threshold_and_disabled_gate_keep_validation(self):
        for threshold, severity, expected in [('high', 'medium', True),
                                               ('medium', 'medium', False),
                                               ('critical', 'high', True),
                                               ('low', 'low', False),
                                               ('none', 'critical', True)]:
            with self.subTest(threshold=threshold), patch.dict(os.environ, {'CLAUDE_FAIL_SEVERITY': threshold}):
                data = self.prepared()
                result = analyze(data, recorded=self.clean, repository_path=self.root)
                source = ContextReader(self.root, data).execute('read_file', {'path': 'caller.py'})['source']
                finding = dict(severity=severity, description='Caller expects the old contract.',
                               evidence='Caller asserts name.', recommendation='Update the caller.',
                               anchor=None, references=[{k: v for k, v in source.items() if k != 'text'}])
                result['sources'] = [source_metadata(source)]
                result['content']['findings'] = [finding]
                result['gate_outcome'] = 'success' if expected else 'failure'
                validate_result(result, data)
                self.assertEqual(gate(result), expected)
                # Turning finding gating off never accepts fabricated citations.
                if threshold == 'none':
                    finding['references'][0]['blob'] = '0' * 40
                    with self.assertRaisesRegex(ReviewError, 'reference'):
                        validate_result(result, data)
                    with self.assertRaisesRegex(ReviewError, 'content.contract'):
                        analyze(data, recorded={'bad': True}, repository_path=self.root)

    def test_prompt_and_controls_change_prepared_cache_identity(self):
        data = self.prepared()
        prompt = system_prompt()
        with patch('pr_review.v2.system_prompt', return_value=prompt + '\nAdditional review focus.'):
            changed = self.prepared()
            self.assertNotEqual(data['policies']['prompt'], changed['policies']['prompt'])
            self.assertNotEqual(digest(data), digest(changed))
            with self.assertRaisesRegex(ReviewError, 'input.policy'):
                analyze(data, recorded=self.clean, repository_path=self.root)
        for setting, value in [('CLAUDE_REVIEW_MODE', 'diff'), ('CLAUDE_FAIL_SEVERITY', 'none'),
                               ('CLAUDE_MAX_EXPLORATION_CALLS', '0'), ('CLAUDE_MAX_TOOL_OPERATIONS', '3'),
                               ('CLAUDE_MAX_INPUT_TOKENS', '12000'),
                               ('CLAUDE_EXPLORATION_MAX_OUTPUT_TOKENS', '1000'),
                               ('CLAUDE_FINAL_MAX_OUTPUT_TOKENS', '2000')]:
            with self.subTest(setting=setting), patch.dict(os.environ, {setting: value}):
                self.assertNotEqual(data['policies']['limits'], policies(data['model'])['limits'])

    def test_cli_prepare_uses_environment_mode_and_explicit_override(self):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'repository': {'full_name': 'fixture/repo'},
                                    'number': 1, 'pull_request': self.github.pr()}))
        for extra, expected in [([], 'diff'), (['--mode', 'context'], 'context')]:
            with self.subTest(extra=extra), patch.dict(os.environ, {'CLAUDE_REVIEW_MODE': 'diff'}), \
                    patch('pr_review.cli.api', return_value=self.github), contextlib.redirect_stdout(io.StringIO()):
                output = self.root / 'prepared.json'
                code = main(['prepare', '--event', str(event), '--repository-path', str(self.root),
                             '--output', str(output), '--diagnostics-dir', str(self.root / 'prepare-trace'), *extra])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.read_text())['mode'], expected)

    def test_show_config_is_offline_and_reports_effective_prompt_and_settings(self):
        capture = io.StringIO()
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '2'}), \
                patch('pr_review.cli.api') as api, patch('anthropic.Anthropic') as sdk, \
                contextlib.redirect_stdout(capture):
            code = main(['show-config', '--diagnostics-dir', str(self.root / 'config-trace')])
        self.assertEqual(code, 0)
        api.assert_not_called()
        sdk.assert_not_called()
        settings = json.loads(capture.getvalue())
        self.assertEqual(settings['controls']['research_calls'], 2)
        self.assertEqual(settings['prompt'], system_prompt())
        self.assertEqual(settings['policies']['prompt'], digest(system_prompt()))
        self.assertFalse((self.root / 'config-trace').exists())

    def test_show_config_invalid_setting_returns_configuration_failure(self):
        for variables in ({'CLAUDE_MAX_EXPLORATION_CALLS': '-1'},
                          {'CLAUDE_MODEL': 'small'},
                          {'CLAUDE_MODEL': 'claude-selected-test-model'}):
            capture = io.StringIO()
            error = io.StringIO()
            with self.subTest(variables=variables), patch.dict(os.environ, variables), \
                    patch('pr_review.cli.api') as api, patch('anthropic.Anthropic') as sdk, \
                    patch('urllib.request.urlopen') as network, \
                    contextlib.redirect_stdout(capture), contextlib.redirect_stderr(error):
                code = main(['show-config', '--diagnostics-dir', str(self.root / 'bad-config-trace')])
            self.assertEqual(code, 2)
            self.assertEqual(capture.getvalue(), '')
            self.assertIn('configuration:', error.getvalue())
            api.assert_not_called()
            sdk.assert_not_called()
            network.assert_not_called()
            self.assertFalse((self.root / 'bad-config-trace').exists())


if __name__ == '__main__':
    unittest.main()
