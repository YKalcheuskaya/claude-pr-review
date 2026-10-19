"""Exercise the official SDK against an in-memory HTTP transport."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pr_review.core import ReviewError
from pr_review.service import analyze, prepare


@unittest.skipUnless(importlib.util.find_spec('anthropic'), 'Install requirements-lock.txt for SDK tests')
class SdkCompatibility(unittest.TestCase):
    def setUp(self):
        environment = patch.dict('os.environ', {'CLAUDE_MAX_REVIEW_USD': '.5'}, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.DEVNULL).strip()
        git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'app.py').write_text('value = 1\n')
        git('add', '.'); git('commit', '-m', 'base'); base = git('rev-parse', 'HEAD')
        (self.root / 'app.py').write_text('value = 2\n')
        git('commit', '-am', 'change'); head = git('rev-parse', 'HEAD')
        github = SimpleNamespace(pr=lambda: dict(state='open', draft=False, title='Change value', body='',
            user={'type': 'User'}, base={'ref': 'main', 'sha': base},
            head={'sha': head, 'repo': {'full_name': 'fixture/repo'}}))
        self.data = prepare(github, 'fixture/repo', 1, self.root, mode='diff')
        self.content = dict(status='complete', summary='No supported defect.', findings=[], limitations=[])

    def test_real_sdk_serializes_schema_and_parses_response(self):
        import anthropic
        import httpx2
        calls = []
        def respond(request):
            calls.append((request.url.path, json.loads(request.content)))
            if request.url.path.endswith('count_tokens'):
                return httpx2.Response(200, json={'input_tokens': 100})
            return httpx2.Response(200, json={'id': 'msg_fixture', 'type': 'message',
                'role': 'assistant', 'model': self.data['model'], 'stop_reason': 'end_turn',
                'stop_sequence': None, 'content': [{'type': 'text', 'text': json.dumps(self.content)}],
                'usage': {'input_tokens': 100, 'output_tokens': 60}})
        with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
            client = anthropic.Anthropic(api_key='fixture-not-a-real-key', http_client=http,
                                         timeout=60, max_retries=0)
            result = analyze(self.data, client=client, repository_path=self.root)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].endswith('count_tokens'))
        self.assertEqual(calls[-1][1]['output_config']['format']['type'], 'json_schema')
        self.assertEqual(result['usage']['output_tokens'], 60)
        self.assertEqual(result['calls'], 1)

    def test_sdk_timeout_retries_at_application_layer_without_nested_sdk_retries(self):
        import anthropic
        import httpx2
        calls = []
        def respond(request):
            if request.url.path.endswith('count_tokens'):
                return httpx2.Response(200, json={'input_tokens': 100})
            calls.append(request)
            raise httpx2.ReadTimeout('fixture timeout')
        with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
            client = anthropic.Anthropic(api_key='fixture-not-a-real-key', http_client=http,
                                         timeout=60, max_retries=0)
            with patch('pr_review.review.backoff'), self.assertRaisesRegex(ReviewError, 'provider.call'):
                analyze(self.data, client=client, repository_path=self.root)
        self.assertEqual(len(calls), 4)
