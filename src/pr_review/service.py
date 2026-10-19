"""GitHub transport, immutable preparation and reconciled publication."""
import json
import os
import subprocess
import urllib.error
import urllib.request

from .runtime import bounded, deadline, backoff, transient, MAX_ATTEMPTS, TIMERS

from .core import (DEFAULT_MODEL, ReviewError, cached_result, gate, locations,
                   payload, validate_input, validate_result)
from .config import review_controls


class Github:
    def __init__(self, repository, pr, token, diagnostics=None):
        self.root = f"https://api.github.com/repos/{repository}/pulls/{pr}"
        self.token = token
        self.diagnostics = diagnostics
        self.operations = 0

    @bounded(TIMERS["github_operation"])
    def request(self, suffix="", body=None):
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._request(suffix, body, retry_read=body is None)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                if body is not None or attempt == MAX_ATTEMPTS - 1 or not (transient(error) or (isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError))):
                    raise ReviewError("GitHub read failed after bounded retries") from None
                if self.diagnostics:
                    self.diagnostics.event("transport.retry", provider="github", attempt=attempt + 2)
                backoff(attempt)

    def _request(self, suffix="", body=None, retry_read=False):
        self.operations += 1
        op = f'github-{self.operations:03d}'
        if self.diagnostics:
            self.diagnostics.event('github.start',operation_id=op,method='POST' if body is not None else 'GET',route='/pulls'+suffix)
            self.diagnostics.request(op,dict(method='POST' if body is not None else 'GET',route='/pulls'+suffix,body=body))
        request = urllib.request.Request(self.root + suffix,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json",
                     "X-GitHub-Api-Version": "2026-03-10"})
        try:
            with urllib.request.urlopen(request, timeout=TIMERS["github_http"]) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                status = response.status
                request_id = response.headers.get("x-github-request-id")
            if self.diagnostics:
                self.diagnostics.response(op,raw.decode('utf-8',errors='replace'),status=status,request_id=request_id,truncated=len(raw)>2*1024*1024)
            if len(raw) > 2 * 1024 * 1024:
                raise ReviewError('github.response: exceeds bound')
            try:
                value = json.loads(raw)
            except (ValueError,UnicodeError):
                raise ReviewError('github.json: malformed response',status_code=status,request_id=request_id) from None
            if self.diagnostics:
                self.diagnostics.event('github.end',operation_id=op,status=status,request_id=request_id)
            return value
        except ReviewError as error:
            if self.diagnostics: self.diagnostics.error(error,operation_id=op,error_code=error.code)
            raise
        except urllib.error.HTTPError as error:
            if self.diagnostics:
                self.diagnostics.response(op,error.read(16384).decode('utf-8',errors='replace'),status=error.code)
                self.diagnostics.error(error,operation_id=op,error_code='github.http')
            if retry_read: raise
            raise ReviewError(f"GitHub request failed (HTTP {error.code}); no write retry") from None
        except (urllib.error.URLError, TimeoutError) as error:
            if self.diagnostics: self.diagnostics.error(error,operation_id=op,error_code='github.uncertain')
            if retry_read: raise
            raise ReviewError("GitHub request outcome uncertain; no write retry") from None

    def pr(self):
        return self.request()

    def reviews(self):
        values = []
        for page in range(1, 101):
            batch = self.request(f"/reviews?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ReviewError("invalid GitHub review response")
            values.extend(batch)
            if len(batch) < 100:
                return values
        raise ReviewError("review pagination bound exceeded")

    def post(self, body):
        return self.request("/reviews", body)


def eligible(pr, repository):
    return (pr.get("state") == "open" and not pr.get("draft")
            and pr.get("base", {}).get("ref") == "main"
            and pr.get("head", {}).get("repo", {}).get("full_name") == repository
            and pr.get("user", {}).get("type") != "Bot")


def assert_current(github, data):
    pr = github.pr()
    if {"title": pr.get("title") or "", "body": pr.get("body") or ""} != data["metadata"]:
        raise ReviewError("PR metadata changed; rerun on current title/body")
    if not eligible(pr, data["repository"]) or pr["base"]["sha"] != data["base"] or pr["head"]["sha"] != data["head"]:
        raise ReviewError("PR eligibility or snapshot changed; rerun on current commits")


@bounded(TIMERS["snapshot_git"] + TIMERS["git_cleanup"])
def git(repository_path, *args):
    """Bound stdout before decoding; never retain an arbitrarily large patch."""
    from .core import MAX_BYTES
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
    try:
        with deadline(TIMERS["snapshot_git"]):
            with subprocess.Popen(['git','-C',str(repository_path),*args],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env) as process:
                try:
                    raw=process.stdout.read(MAX_BYTES+1)
                    if len(raw)>MAX_BYTES:
                        raise ReviewError('snapshot.diff: output exceeds 60 KiB')
                    if process.wait(timeout=TIMERS["snapshot_git"]):
                        raise ReviewError('snapshot.git: collection failed')
                    return raw.decode('utf-8')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=TIMERS["git_cleanup"])
    except (subprocess.SubprocessError,UnicodeError,TimeoutError):
        raise ReviewError('snapshot.git: collection failed or timed out') from None


def prepare(github, repository, pr_number, repository_path, model=DEFAULT_MODEL, mode=None):
    pr = github.pr()
    if not eligible(pr, repository):
        raise ReviewError("PR is outside supported scope")
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    # Validate API values before passing them as Git arguments.
    from .core import SHA
    if not all(isinstance(v, str) and SHA.fullmatch(v) for v in (base, head)):
        raise ReviewError("invalid API snapshot")
    merge_base = git(repository_path, "merge-base", base, head).strip()
    diff = git(repository_path, "-c", "core.quotePath=false", "diff",
        "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3",
        "--find-renames", merge_base, head, "--")
    from .review import policies
    data = {"version": 2, "repository": repository, "pr": pr_number,
            "base": base, "head": head, "merge_base": merge_base, "diff": diff,
            "model": model, "config": "review", "mode": mode or review_controls()["mode"],
            "metadata": {"title": pr.get("title") or "", "body": pr.get("body") or ""},
            "policies": policies(model), "changed_files": list(locations(diff))}
    validate_input(data)
    assert_current(github, data)
    return data


def analyze(data, github=None, recorded=None, client=None, repository_path=".", diagnostics=None, cache_only=False):
    """Run the current bounded reviewer through the stable service interface."""
    from .review import analyze as review
    return review(data, github, recorded, client, repository_path, diagnostics, cache_only)


def publish(data, result, github, repository_path=".", diagnostics=None):
    validate_result(result, data)
    if not result["live"] and data["diff"]:
        raise ReviewError("recorded results cannot be published to GitHub")
    from .review import verify_sources
    verify_sources(data, result, repository_path)
    assert_current(github, data)
    previous = cached_result(github.reviews(), data)
    if previous is not None:
        if diagnostics:
            diagnostics.event("cache.hit", current_calls=0, current_cost=0, origin_identity=previous["identity"])
        if previous != result:
            raise ReviewError("published result conflicts with this artifact")
        return gate(previous)
    try:
        if diagnostics:
            diagnostics.event("publication.start", method="POST", route="/pulls/reviews", commit=data["head"])
        published = github.post(payload(data, result))
        if diagnostics:
            diagnostics.event("publication.end", review_id=(published or {}).get("id"), review_url=(published or {}).get("html_url"), comments=len(result["content"]["findings"]))
    except ReviewError:
        if diagnostics:
            diagnostics.event("reconciliation.start", writes=1)
        # A failed response can follow a successful write. Reconcile the cached
        # result with a read; a second POST could duplicate the review.
        recovered = cached_result(github.reviews(), data)
        if diagnostics:
            diagnostics.event("reconciliation.end", recovered=recovered == result)
        if recovered != result:
            raise ReviewError("publication uncertain or failed; inspect GitHub before retry") from None
    assert_current(github, data)
    return gate(result)
