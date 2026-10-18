"""Offline transport retries, real blocking subprocesses and nested deadlines."""
import contextlib
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pr_review.context import ContextReader
from pr_review.core import ReviewError
from pr_review.runtime import bounded, deadline
from pr_review.service import Github


class Runtime(unittest.TestCase):
    def test_github_reads_retry_three_times_but_posts_once(self):
        github = Github('fixture/repo', 1, 'fixture')
        for error in (HTTPError('fixture', 503, 'unavailable', {}, None), URLError('offline')):
            with patch('urllib.request.urlopen', side_effect=error) as send, patch('pr_review.service.backoff'):
                with self.assertRaises(ReviewError): github.pr()
                self.assertEqual(send.call_count, 4)
            with patch('urllib.request.urlopen', side_effect=error) as send:
                with self.assertRaises(ReviewError): github.post({})
                self.assertEqual(send.call_count, 1)

    def test_github_read_recovers_without_retrying_authentication_failure(self):
        github = Github('fixture/repo', 1, 'fixture')
        response = SimpleNamespace(status=200, headers={}, read=lambda n: b'{"state":"open"}')
        with patch('urllib.request.urlopen', side_effect=[URLError('offline'), contextlib.nullcontext(response)]) as send, patch('pr_review.service.backoff'):
            self.assertEqual(github.pr()['state'], 'open')
            self.assertEqual(send.call_count, 2)
        with patch('urllib.request.urlopen', side_effect=HTTPError('fixture', 401, 'unauthorized', {}, None)) as send:
            with self.assertRaises(ReviewError): github.pr()
            self.assertEqual(send.call_count, 1)

    def test_nested_deadline_preserves_enclosing_budget_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGALRM)
        @bounded(.08)
        def work():
            with deadline(10):
                time.sleep(.04)
            time.sleep(.1)
        started = time.monotonic()
        with self.assertRaisesRegex(ReviewError, 'budget.time'): work()
        self.assertLess(time.monotonic() - started, .3)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_blocked_git_tree_is_interrupted_and_child_reaped(self):
        reader = ContextReader('.', dict(merge_base='a'*40, head='b'*40, base='c'*40))
        popen = subprocess.Popen
        children = []
        def stalled(*args, **kwargs):
            child = popen([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
            children.append(child)
            return child
        with patch('pr_review.context.subprocess.Popen', side_effect=stalled):
            with self.assertRaisesRegex(ReviewError, 'budget.time'):
                bounded(.1)(reader._tree)('after')
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_nested_deadline_cannot_be_swallowed_as_recoverable_error(self):
        continued = []
        @bounded(10)
        def inner():
            time.sleep(.2)
        @bounded(.05)
        def outer():
            try:
                inner()
            except ReviewError:
                continued.append(True)
            continued.append(True)
        with self.assertRaisesRegex(ReviewError, 'budget.time'): outer()
        self.assertEqual(continued, [])

    def test_installed_sdk_connection_errors_are_retryable(self):
        import anthropic
        import httpx2
        from pr_review.runtime import transient
        request = httpx2.Request('POST', 'https://fixture.invalid')
        for error in (anthropic.APIConnectionError(request=request), anthropic.APITimeoutError(request=request)):
            self.assertTrue(transient(error))

    def test_standalone_git_tree_timeout_is_a_review_error_after_eof(self):
        reader = ContextReader('.', dict(merge_base='a'*40, head='b'*40, base='c'*40))
        reader._deadline = time.monotonic() + .1
        popen = subprocess.Popen
        children = []
        def stalled(*args, **kwargs):
            child = popen([sys.executable, '-c', 'import os,time; os.close(1); time.sleep(10)'], **kwargs)
            children.append(child)
            return child
        started = time.monotonic()
        with patch('pr_review.context.subprocess.Popen', side_effect=stalled):
            with self.assertRaises(ReviewError): reader._tree('after')
        self.assertLess(time.monotonic() - started, 1)
        self.assertIsNotNone(children[0].poll())

    def test_three_retry_delays_are_bounded(self):
        from pr_review.runtime import backoff
        with patch('pr_review.runtime.time.sleep') as sleep:
            for attempt in range(3): backoff(attempt)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [.5, 1, 2])
