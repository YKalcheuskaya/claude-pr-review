"""Regression boundaries for source admission, provider transmission and traces."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pr_review.core import ReviewError, locations
from pr_review.diagnostics import Diagnostics, sanitize
from pr_review.security import sensitive
from pr_review.runtime import deadline
from pr_review.service import analyze, prepare
from pr_review.context import ContextReader


class SecurityBoundaries(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.DEVNULL).strip()
        self.git = git
        git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'app.py').write_text('value = 1\n')
        git('add', '.'); git('commit', '-m', 'Before'); self.before = git('rev-parse', 'HEAD')
        (self.root / 'app.py').write_text('value = 2\n')
        git('commit', '-am', 'After'); self.head = git('rev-parse', 'HEAD')
        self.github = SimpleNamespace(pr=lambda: dict(state='open', draft=False, title='Change value', body='',
            user={'type': 'User'}, base={'ref': 'main', 'sha': self.before},
            head={'sha': self.head, 'repo': {'full_name': 'fixture/repo'}}))
        self.data = prepare(self.github, 'fixture/repo', 1, self.root, mode='context')

    def test_sensitive_diff_metadata_never_reach_count_or_generation(self):
        samples = ['{"password": "quoted-canary-value"}', 'postgresql://user:url-canary-value@host/db',
                   '"api_key": "quoted-api-canary"', '-----BEGIN PRIVATE KEY-----\nprivate-canary\n-----END PRIVATE KEY-----']
        for text in samples:
            for boundary in ('diff', 'metadata'):
                data = dict(self.data)
                if boundary == 'diff':
                    data['diff'] = data['diff'].replace('+value = 2', '+' + text)
                else:
                    data['metadata'] = dict(title='Change value', body=text)
                client = Mock()
                with self.subTest(boundary=boundary, text=text), self.assertRaises(ReviewError):
                    analyze(data, client=client, repository_path=self.root)
                self.assertEqual(client.mock_calls, [])

    def test_restricted_changed_and_renamed_paths_fail_admission(self):
        for path in ('.env', '.env.production', 'config/secrets.json', '.aws/config', 'vendor/source.py', 'signing.pem'):
            with self.subTest(path=path), self.assertRaises(ReviewError):
                locations(self.data['diff'].replace('app.py', path))
        rename = 'diff --git a/.env b/app.py\nsimilarity index 50%\nrename from .env\nrename to app.py\nindex 1111111..2222222 100644\n--- a/.env\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n'
        with self.assertRaises(ReviewError):
            locations(rename)

    def test_all_runtime_credentials_and_serialized_patterns_are_redacted(self):
        samples = ['{"password": "quoted-canary-value"}', 'postgresql://user:url-canary-value@host/db', json.dumps({'body': json.dumps({'password': 'quoted-canary-value'})})]
        with patch.dict(os.environ, {'GH_TOKEN': 'runtime-gh-canary', 'OTHER_API_KEY': 'runtime-other-canary'}):
            samples += ['runtime-gh-canary', 'runtime-other-canary']
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as console:
                diagnostics = Diagnostics(directory, 'analyze')
                for sample in samples:
                    self.assertTrue(sensitive(sample))
                    diagnostics.request('call', sample)
                    diagnostics.response('call', json.dumps({'body': sample}))
                    diagnostics.context([{'text': sample}])
                    diagnostics.event('probe', message=sample)
                diagnostics.finalize('failure')
                combined = console.getvalue() + ''.join(path.read_text() for path in Path(directory).iterdir())
                for fragment in ('quoted-canary-value', 'url-canary-value', 'runtime-gh-canary', 'runtime-other-canary'):
                    self.assertNotIn(fragment, combined)

    def test_secret_scanning_is_bounded_for_long_nonmatching_text(self):
        with deadline(2):
            self.assertFalse(sensitive("a" * (256 * 1024)))
            self.assertEqual(sanitize("a" * (256 * 1024)), "a" * (256 * 1024))

    def test_quoted_credentials_are_denied_in_context_and_search(self):
        (self.root / 'settings.json').write_text(json.dumps({'body': json.dumps({'password': 'quoted-context-canary'})}) + '\n')
        self.git('add', '.'); self.git('commit', '-m', 'Sensitive context fixture')
        data = {**self.data, 'head': self.git('rev-parse', 'HEAD')}
        reader = ContextReader(self.root, data)
        self.assertFalse(reader.execute('read_file', {'path': 'settings.json'})['ok'])
        self.assertFalse(reader.execute('search_text', {'query': 'postgresql://u:query-canary@host/db'})['ok'])
        self.assertNotIn('quoted-context-canary', str(reader.sources) + str(reader.limitations))


if __name__ == '__main__':
    unittest.main()
