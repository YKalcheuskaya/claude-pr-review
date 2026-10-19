"""Fail-closed wall-clock bounds and explicit transport retry policy."""
from contextlib import contextmanager
from functools import wraps
import signal
import threading
import time
import urllib.error

from .core import ReviewError


TIMERS = {
    "analysis": 300, "generation": 60, "generation_http": 50,
    "token_count": 30, "token_count_http": 20,
    "github_operation": 100, "github_http": 30,
    "snapshot_git": 60, "git_cleanup": 5, "context_git": 10,
}

MAX_ATTEMPTS = 4  # Initial request plus three retries.

_active = threading.local()


class DeadlineExpired(BaseException):
    """Bypass broad provider/tool exception handlers until the outer guard."""


@contextmanager
def deadline(seconds):
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, 'setitimer'):
        raise ReviewError('runtime.deadline: requires a Unix main-thread process')
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expire(signum, frame):
        raise DeadlineExpired()
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, max(.001, min(seconds, previous_delay) if previous_delay else seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay:
            signal.setitimer(signal.ITIMER_REAL, max(.001, previous_delay - (time.monotonic() - started)), previous_interval)


def bounded(seconds):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            outermost = not getattr(_active, 'depth', 0)
            _active.depth = getattr(_active, 'depth', 0) + 1
            try:
                with deadline(seconds):
                    return function(*args, **kwargs)
            except DeadlineExpired:
                if not outermost:
                    raise
                raise ReviewError('budget.time: execution deadline reached; no result published') from None
            finally:
                _active.depth -= 1
        return run
    return decorate


def transient(error):
    """Retry only transport failures, throttling and transient HTTP status codes."""
    status = error.code if isinstance(error, urllib.error.HTTPError) else getattr(error, 'status_code', None)
    try:
        from anthropic import APIConnectionError
        connection_errors = (TimeoutError, ConnectionError, APIConnectionError)
    except ImportError:
        connection_errors = (TimeoutError, ConnectionError)
    return (status in (408, 429) or (isinstance(status, int) and 500 <= status <= 599)) or isinstance(error, connection_errors)


def backoff(attempt):
    # Three bounded delays (0.5 s, 1 s, 2 s); the outer deadline covers waits.
    time.sleep(.5 * 2 ** attempt)
