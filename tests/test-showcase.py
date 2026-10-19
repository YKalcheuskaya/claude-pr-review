"""Real snapshot, SDK serialization, evidence, gate and cache showcase checks."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('showcase', ROOT / 'scripts/showcase.py')
showcase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(showcase)


class Showcase(unittest.TestCase):
    def test_all_scenarios_exercise_real_harness_without_network_or_credentials(self):
        credentials = {'ANTHROPIC_API_KEY': 'synthetic-provider-canary', 'GITHUB_TOKEN': 'synthetic-github-canary',
            'CLAUDE_MODEL': 'claude-operator-setting', 'CLAUDE_FAIL_SEVERITY': 'none'}
        with patch.dict(os.environ, credentials), patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), \
                patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            report = showcase.run_showcase()
            self.assertEqual(os.environ['CLAUDE_MODEL'], 'claude-operator-setting')
            self.assertEqual(os.environ['CLAUDE_FAIL_SEVERITY'], 'none')
        self.assertTrue(report['simulation'])
        self.assertEqual(report['paid_provider_calls'], 0)
        self.assertEqual(report['real_network_requests'], 0)
        self.assertNotIn(credentials['ANTHROPIC_API_KEY'], json.dumps(report))
        self.assertNotIn(credentials['GITHUB_TOKEN'], json.dumps(report))
        rows = {row['scenario']: row for row in report['scenarios']}
        self.assertEqual(set(rows), {'broken', 'fixed', 'js'})
        for name, expected in [('broken', 'failure'), ('fixed', 'success'), ('js', 'failure')]:
            row = rows[name]
            self.assertEqual(row['gate'], expected)
            self.assertEqual(row['coverage'], 'complete')
            self.assertTrue(row['diff_nonempty'])
            self.assertTrue(row['runtime_live_flag'])  # The SDK ran against a mock transport.
            self.assertEqual(row['response_origin'], 'authored-sdk-mock-transport')
            self.assertEqual(row['logical_calls'], 3)
            self.assertEqual(row['simulated_generation_requests'], 3)
            self.assertEqual(row['simulated_token_count_requests'], 3)
            self.assertEqual(row['simulated_http_requests'], 6)
            self.assertEqual(row['in_memory_review_posts'], 1)
            self.assertEqual(row['cache_rerun'], dict(byte_identical_result=True, gate=expected,
                new_generation_requests=0, new_token_count_requests=0, new_review_posts=0))
            generation = [r['body'] for r in row['sdk_requests'] if r['path'] == '/v1/messages']
            initial = json.loads(generation[0]['messages'][0]['content'])
            self.assertNotIn(row['unchanged_caller'], [s['path'] for s in initial['sources']])
            self.assertEqual(generation[1]['messages'][-1]['content'][1]['tool_use_id'], 'showcase_read')
            self.assertNotIn('tools', generation[-1])
            final = json.loads(generation[-1]['messages'][0]['content'])
            self.assertIn(row['unchanged_caller'], [s['path'] for s in final['sources']])
            if expected == 'failure':
                self.assertEqual(len(row['findings']), 1)
                finding = row['findings'][0]
                self.assertEqual(finding['severity'], 'high')
                self.assertEqual(finding['references'][0]['path'], row['unchanged_caller'])
                self.assertEqual(finding['references'][0]['snapshot'], 'after')
                self.assertEqual(row['review_payload']['comments'][0]['line'], 2)
                self.assertIn('/blob/' + row['snapshots']['head'] + '/' + row['unchanged_caller'], row['review_payload']['comments'][0]['body'])
            else:
                self.assertEqual(row['findings'], [])
                self.assertEqual(row['inline_comments'], 0)

    def test_repository_mode_validates_exact_snapshots_and_preserves_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / 'repository'
            base, head = showcase.materialize(repository, showcase.SCENARIOS['broken'])
            (repository / 'untracked.txt').write_text('preserve user work\n')
            status = showcase.git(repository, 'status', '--porcelain')
            report = showcase.run_showcase('broken', repository, base, head, 'fixture/repository')
            self.assertEqual(report['scenarios'][0]['snapshots']['head'], head)
            self.assertIn('https://github.com/fixture/repository/blob/' + head, report['scenarios'][0]['review_payload']['comments'][0]['body'])
            self.assertEqual(showcase.git(repository, 'status', '--porcelain'), status)
            self.assertEqual((repository / 'untracked.txt').read_text(), 'preserve user work\n')
            with self.assertRaisesRegex(showcase.ReviewError, 'showcase.fixture'):
                showcase.run_showcase('fixed', repository, base, head)
            with self.assertRaisesRegex(showcase.ReviewError, 'showcase.snapshot'):
                showcase.run_showcase('broken', repository, 'HEAD', head)

    def test_fabricated_blob_cannot_become_an_in_memory_review(self):
        import httpx2
        original = showcase.AuthoredTransport.respond
        def tamper(transport, request):
            response = original(transport, request)
            body = json.loads(request.content)
            if request.url.path == '/v1/messages' and 'tools' not in body:
                changed = response.json()
                content = json.loads(changed['content'][0]['text'])
                content['findings'][0]['references'][0]['blob'] = '0' * 40
                changed['content'][0]['text'] = json.dumps(content)
                return httpx2.Response(200, json=changed)
            return response
        with patch.object(showcase.AuthoredTransport, 'respond', tamper), \
                patch.object(showcase.InMemoryGithub, 'post') as post:
            with self.assertRaisesRegex(showcase.ReviewError, 'reference'):
                showcase.run_showcase('broken')
        post.assert_not_called()

    def test_cli_writes_reviewable_json_and_markdown_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            markdown = Path(directory) / 'summary.md'
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                self.assertEqual(showcase.main(['--scenario', 'fixed', '--output', str(output), '--summary', str(markdown)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report['scenarios'][0]['gate'], 'success')
            self.assertIn('Authored SDK transport simulation', markdown.read_text())
            self.assertIn('Real network requests: 0', console.getvalue())

    def test_incomplete_repository_arguments_fail_before_transport(self):
        with patch.object(showcase.AuthoredTransport, 'respond') as respond:
            for scenario, repository, base, head in [('all', '.', 'a' * 40, 'b' * 40),
                    ('broken', '.', None, 'b' * 40), ('broken', None, 'a' * 40, None)]:
                with self.subTest(scenario=scenario, repository=repository), self.assertRaises(showcase.ReviewError):
                    showcase.run_showcase(scenario, repository, base, head)
            respond.assert_not_called()


if __name__ == '__main__':
    unittest.main()
