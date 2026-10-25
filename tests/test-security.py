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
from pr_review.review import validate_input


SENSITIVE_FIELDS = (
    ('Cookie', 'session=cookie-first-canary; other=cookie-last-canary'),
    ('Set-Cookie', 'session=set-cookie-canary; Path=/; HttpOnly'),
    ('cOoKiE', 'session=mixed-cookie-canary; other=mixed-last-canary'),
    ('Cookie', '"quoted-first-canary"; other=quoted-last-canary'),
    ('Authorization', 'Custom custom-auth-canary'),
    ('DB_PASSWORD', 'db-password-canary'),
    ('CLIENT_SECRET', 'client-secret-canary'),
    ('AWS_SECRET_ACCESS_KEY', 'aws-secret-canary'),
    ('PRIVATE_KEY', 'private-key-canary'),
    ('db-password', 'hyphen-password-canary'),
    ('client_secret', 'lower-secret-canary'),
    ('aws_secret_access_key', 'lower-aws-canary'),
)


def sensitive_text_forms(name, value):
    structured = {name: value}
    return (f'{name}: {value}', f'{name} = "{value}"', f"'{name}': '{value}'",
            json.dumps(structured), json.dumps({'body': json.dumps(structured)}),
            json.dumps({'body': json.dumps({'body': json.dumps(structured)})}))


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

    def test_cookie_and_compound_fields_never_reach_provider(self):
        for name, value in SENSITIVE_FIELDS:
            for text in sensitive_text_forms(name, value):
                for boundary in ('diff', 'metadata'):
                    data = dict(self.data)
                    if boundary == 'diff':
                        data['diff'] = data['diff'].replace('+value = 2', '+' + text)
                    else:
                        data['metadata'] = dict(title='Change value', body=text)
                    client = Mock()
                    with self.subTest(name=name, boundary=boundary, text=text):
                        with self.assertRaises(ReviewError):
                            analyze(data, client=client, repository_path=self.root)
                        # No token-count, generation, or other provider interaction.
                        self.assertEqual(client.mock_calls, [])

    def test_cookie_and_compound_fields_are_removed_from_all_diagnostic_sinks(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as console:
            summary = self.root / 'step-summary'
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}):
                diagnostics = Diagnostics(directory, 'analyze')
                for name, value in SENSITIVE_FIELDS:
                    samples = ({name: value}, *sensitive_text_forms(name, value))
                    for sample in samples:
                        diagnostics.request('call', sample)
                        diagnostics.response('call', {'body': sample})
                        diagnostics.context([{'text': sample}])
                        diagnostics.event('probe', message=sample)
                        diagnostics.finalize('failure', note=sample)
                manifest = diagnostics.finalize('failure')
            combined = console.getvalue() + summary.read_text() + ''.join(
                path.read_text() for path in Path(directory).iterdir())
            for name, value in SENSITIVE_FIELDS:
                with self.subTest(name=name):
                    self.assertNotIn(value, combined)
            # Later cookies must not survive a partial first-token replacement.
            for fragment in ('cookie-first-canary', 'cookie-last-canary', 'set-cookie-canary',
                             'mixed-cookie-canary', 'mixed-last-canary',
                             'quoted-first-canary', 'quoted-last-canary', 'custom-auth-canary'):
                self.assertNotIn(fragment, combined)
            self.assertTrue(manifest['redacted'])
            self.assertFalse(manifest['complete'])

    def test_ordinary_credential_related_code_remains_admissible(self):
        for text in ('password_length = 12', 'db_password_length = 12',
                     'client_secret_name = "CLIENT_SECRET"', 'cookie_count = 2',
                     'secretary = "ordinary"'):
            with self.subTest(text=text):
                self.assertFalse(sensitive(text))
                self.assertEqual(sanitize(text), text)
                data = {**self.data, 'diff': self.data['diff'].replace('+value = 2', '+' + text)}
                validate_input(data)

    def test_sensitive_fields_are_denied_in_context_and_search(self):
        for index, (name, value) in enumerate(SENSITIVE_FIELDS):
            (self.root / f'settings-{index}.txt').write_text(f'{name}: {value}\n')
        self.git('add', '.'); self.git('commit', '-m', 'Sensitive field fixtures')
        data = {**self.data, 'head': self.git('rev-parse', 'HEAD')}
        for index, (name, value) in enumerate(SENSITIVE_FIELDS):
            with self.subTest(name=name):
                reader = ContextReader(self.root, data)
                self.assertFalse(reader.execute('read_file', {'path': f'settings-{index}.txt'})['ok'])
                self.assertFalse(reader.execute('search_text', {'query': f'{name}: {value}'})['ok'])
                self.assertNotIn(value, str(reader.sources) + str(reader.limitations))

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
