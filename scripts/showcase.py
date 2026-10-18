"""Offline capability showcase with real Git evidence and synthetic SDK responses.

All provider HTTP requests terminate inside httpx2.MockTransport. GitHub reviews
exist only in memory. Authored responses exercise the harness, not model quality.
"""
import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pr_review.core import ReviewError, digest, gate
from pr_review.service import analyze, prepare, publish
from pr_review.review import payload

PYTHON_BEFORE = {
    'examples/python/contract.py': 'def summarize(value):\n    return {"total": value}\n',
    'examples/python/caller.py': 'from .contract import summarize\n\n\ndef display_total(value):\n    return summarize(value)["total"]\n',
}
JAVASCRIPT_BEFORE = {
    'examples/javascript/contract.js': 'export function summarize(value) {\n  return { total: value };\n}\n',
    'examples/javascript/caller.js': 'import { summarize } from "./contract.js";\n\nexport function displayTotal(value) {\n  return summarize(value).total.toFixed(2);\n}\n',
}
SCENARIOS = {
    'broken': {
        'title': 'Broken Python Response Contract',
        'before': PYTHON_BEFORE,
        'after': {**PYTHON_BEFORE, 'examples/python/contract.py': 'def summarize(value):\n    return {"amount": value}\n'},
        'caller': 'examples/python/caller.py', 'contract': 'examples/python/contract.py',
        'description': 'The renamed response key breaks the unchanged Python caller.',
        'evidence': 'The producer returns amount, but display_total still reads total.',
        'recommendation': 'Preserve the total key or update its callers together.',
        'expected_gate': 'failure',
    },
    'fixed': {
        'title': 'Clean Nonempty Python Refactor',
        'before': PYTHON_BEFORE,
        'after': {**PYTHON_BEFORE, 'examples/python/contract.py': 'def summarize(value):\n    total = value\n    return {"total": total}\n'},
        'caller': 'examples/python/caller.py', 'contract': 'examples/python/contract.py',
        'expected_gate': 'success',
    },
    'js': {
        'title': 'Broken JavaScript Response Contract',
        'before': JAVASCRIPT_BEFORE,
        'after': {**JAVASCRIPT_BEFORE, 'examples/javascript/contract.js': 'export function summarize(value) {\n  return { amount: value };\n}\n'},
        'caller': 'examples/javascript/caller.js', 'contract': 'examples/javascript/contract.js',
        'description': 'The renamed response key breaks the unchanged JavaScript caller.',
        'evidence': 'The producer returns amount; the caller reads total and calls toFixed on undefined.',
        'recommendation': 'Preserve the total property or update its callers together.',
        'expected_gate': 'failure',
    },
}


@contextmanager
def showcase_settings():
    """Keep outcomes independent of an operator's paid-run configuration."""
    previous = {key: value for key, value in os.environ.items() if key.startswith('CLAUDE_')}
    for key in previous:
        del os.environ[key]
    os.environ['CLAUDE_MAX_REVIEW_USD'] = '0.20'
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith('CLAUDE_'):
                del os.environ[key]
        os.environ.update(previous)


def git(repository, *arguments):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0',
               GIT_AUTHOR_DATE='2026-01-01T00:00:00+00:00',
               GIT_COMMITTER_DATE='2026-01-01T00:00:00+00:00')
    try:
        return subprocess.check_output(['git', '-C', str(repository), '-c', 'core.hooksPath=/dev/null',
            '-c', 'commit.gpgsign=false', *arguments], env=env, stderr=subprocess.DEVNULL,
            timeout=10).decode('utf-8')
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ReviewError('showcase.git: cannot read or create fixture snapshots') from None


def materialize(repository, scenario):
    repository.mkdir()
    git(repository, 'init', '-b', 'main', '--template=')
    git(repository, 'config', 'user.name', 'Offline Showcase')
    git(repository, 'config', 'user.email', 'showcase@example.invalid')
    commits = []
    for label in ('before', 'after'):
        for name, text in scenario[label].items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        git(repository, 'add', '--all')
        git(repository, 'commit', '--quiet', '-m', f'Synthetic showcase {label} snapshot')
        commits.append(git(repository, 'rev-parse', 'HEAD').strip())
    return commits


def verify_fixture(repository, base, head, scenario):
    """A showcase cannot claim a defect from arbitrary unrelated PR snapshots."""
    for commit, label in ((base, 'before'), (head, 'after')):
        if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
            raise ReviewError('showcase.snapshot: supply full immutable commit SHAs')
        if git(repository, 'cat-file', '-t', commit).strip() != 'commit':
            raise ReviewError('showcase.snapshot: snapshot must identify a Git commit')
        for path, expected in scenario[label].items():
            if git(repository, 'show', f'{commit}:{path}') != expected:
                raise ReviewError(f'showcase.fixture: {label} snapshot does not match {path}')


class InMemoryGithub:
    """Local publication/cache adapter; never constructs a GitHub HTTP client."""
    def __init__(self, base, head, title, repository_name='showcase/offline'):
        self.base, self.head, self.title = base, head, title
        self.repository_name = repository_name
        self.items, self.posts = [], []

    def pr(self):
        return dict(state='open', draft=False, title='Synthetic Showcase: ' + self.title,
            body='Offline authored transport simulation; no model inference or external publication.',
            user={'type': 'User'}, base={'ref': 'main', 'sha': self.base},
            head={'sha': self.head, 'repo': {'full_name': self.repository_name}})

    def reviews(self):
        return copy.deepcopy(self.items)

    def post(self, body):
        self.posts.append(copy.deepcopy(body))
        review = dict(id=len(self.posts), state='COMMENTED', commit_id=body['commit_id'],
            body=body['body'], user={'login': 'github-actions[bot]', 'type': 'Bot'})
        self.items.append(review)
        return {'id': review['id']}


class AuthoredTransport:
    """SDK HTTP handler whose tool requests and final answers are authored fixtures."""
    def __init__(self, scenario, model):
        self.scenario, self.model = scenario, model
        self.requests = []
        self.generation_requests = 0
        self.token_count_requests = 0

    def respond(self, request):
        import httpx2
        if request.url.host != 'api.anthropic.com':
            raise ReviewError('showcase.transport: unexpected SDK endpoint')
        body = json.loads(request.content)
        self.requests.append({'path': request.url.path, 'body': body})
        if request.url.path == '/v1/messages/count_tokens':
            self.token_count_requests += 1
            return httpx2.Response(200, json={'input_tokens': 1000})
        if request.url.path != '/v1/messages':
            raise ReviewError('showcase.transport: unsupported SDK route')
        self.generation_requests += 1
        if 'tools' in body and self.generation_requests == 1:
            prefix = str(Path(self.scenario['caller']).parent) + '/'
            blocks = [dict(type='tool_use', id='showcase_search', name='search_text',
                input={'snapshot': 'after', 'query': 'summarize', 'path_prefix': prefix}),
                dict(type='tool_use', id='showcase_read', name='read_file',
                input={'snapshot': 'after', 'path': self.scenario['caller']})]
            reason = 'tool_use'
        elif 'tools' in body:
            blocks = [dict(type='text', text='The related caller has been inspected.')]
            reason = 'end_turn'
        else:
            context = json.loads(body['messages'][0]['content'])
            content = dict(status='complete', summary='The nonempty refactor preserves the caller contract.',
                findings=[], limitations=[])
            if self.scenario['expected_gate'] == 'failure':
                source = next((source for source in context['sources']
                    if source['path'] == self.scenario['caller'] and source['start_line'] == 1), None)
                if source is None:
                    raise ReviewError('showcase.evidence: unchanged caller did not reach final context')
                content['summary'] = 'A response key change breaks an unchanged caller.'
                content['findings'] = [dict(severity='high', description=self.scenario['description'],
                    evidence=self.scenario['evidence'], recommendation=self.scenario['recommendation'],
                    anchor={'file': self.scenario['contract'], 'side': 'RIGHT', 'start': 2, 'end': 2},
                    references=[{key: value for key, value in source.items() if key != 'text'}])]
            blocks = [dict(type='text', text=json.dumps(content))]
            reason = 'end_turn'
        return httpx2.Response(200, json=dict(id=f'msg_showcase_{self.generation_requests}',
            type='message', role='assistant', model=self.model, stop_reason=reason,
            stop_sequence=None, content=blocks, usage={'input_tokens': 1000, 'output_tokens': 200}))


def run_scenario(name, repository, base, head, repository_name='showcase/offline'):
    import anthropic
    import httpx2
    scenario = SCENARIOS[name]
    verify_fixture(repository, base, head, scenario)
    github = InMemoryGithub(base, head, scenario['title'], repository_name)
    data = prepare(github, repository_name, 1, repository, mode='context')
    if not data['diff']:
        raise ReviewError('showcase.fixture: demonstration requires a nonempty diff')
    if scenario['caller'] in data['changed_files']:
        raise ReviewError('showcase.fixture: the evidence caller must remain unchanged')
    transport = AuthoredTransport(scenario, data['model'])
    with httpx2.Client(transport=httpx2.MockTransport(transport.respond)) as http:
        client = anthropic.Anthropic(api_key='offline-simulation-not-a-credential',
            http_client=http, base_url='https://api.anthropic.com', max_retries=0, timeout=10)
        result = analyze(data, github=github, client=client, repository_path=repository)
        first_gate = publish(data, result, github, repository_path=repository)
        review_payload = payload(data, result)
        counts_before = (transport.generation_requests, transport.token_count_requests, len(github.posts))
        rerun = analyze(data, github=github, client=client, repository_path=repository, cache_only=True)
        rerun_gate = publish(data, rerun, github, repository_path=repository)
    deltas = [after - before for after, before in zip(
        (transport.generation_requests, transport.token_count_requests, len(github.posts)), counts_before)]
    byte_identical = json.dumps(result, sort_keys=True) == json.dumps(rerun, sort_keys=True)
    expected_gate = scenario['expected_gate']
    if result['gate_outcome'] != expected_gate or first_gate != gate(result) or rerun_gate != first_gate:
        raise ReviewError('showcase.assertion: unexpected finding gate')
    if deltas != [0, 0, 0] or not byte_identical or len(github.posts) != 1:
        raise ReviewError('showcase.assertion: cache rerun made requests, changed output or duplicated a review')
    findings = result['content']['findings']
    if expected_gate == 'failure' and (len(findings) != 1 or len(review_payload['comments']) != 1):
        raise ReviewError('showcase.assertion: broken contract lacks its expected inline finding')
    return dict(scenario=name, title=scenario['title'], simulation=True,
        response_origin='authored-sdk-mock-transport', runtime_live_flag=result['live'],
        snapshots={key: data[key] for key in ('base', 'head', 'merge_base')},
        input_identity=digest(data), diff_nonempty=True, unchanged_caller=scenario['caller'],
        gate=result['gate_outcome'], coverage=result['coverage'], logical_calls=result['calls'],
        findings=findings, inline_comments=len(review_payload['comments']),
        limitations=result['content']['limitations'], simulated_provider_usage=result['usage'],
        simulated_http_requests=len(transport.requests), simulated_generation_requests=transport.generation_requests,
        simulated_token_count_requests=transport.token_count_requests, in_memory_review_posts=len(github.posts),
        real_network_requests=0, paid_provider_calls=0,
        cache_rerun=dict(byte_identical_result=byte_identical, gate=rerun['gate_outcome'],
            new_generation_requests=deltas[0], new_token_count_requests=deltas[1], new_review_posts=deltas[2]),
        sdk_requests=transport.requests, review_payload=review_payload)


def run_showcase(scenario='all', repository_path=None, base=None, head=None, repository_name='showcase/offline'):
    if scenario not in (*SCENARIOS, 'all'):
        raise ReviewError('showcase.scenario: unknown scenario')
    if repository_path is not None and (scenario == 'all' or not base or not head):
        raise ReviewError('showcase.arguments: repository mode requires one scenario and both snapshots')
    if repository_path is None and (base is not None or head is not None):
        raise ReviewError('showcase.arguments: snapshots require a repository path')
    names = list(SCENARIOS) if scenario == 'all' else [scenario]
    results = []
    with showcase_settings(), tempfile.TemporaryDirectory(prefix='claude-review-showcase-') as temporary:
        for name in names:
            if repository_path is None:
                repository = Path(temporary) / name
                scenario_base, scenario_head = materialize(repository, SCENARIOS[name])
            else:
                repository = Path(repository_path).resolve()
                scenario_base, scenario_head = base, head
            results.append(run_scenario(name, repository, scenario_base, scenario_head, repository_name))
    return dict(kind='synthetic-offline-capability-showcase', simulation=True,
        disclaimer='Authored SDK transport simulation. No live model inference, external review publication or model-accuracy measurement.',
        real_network_requests=0, paid_provider_calls=0, scenarios=results)


def summary(report):
    lines = ['# Offline Capability Showcase', '', report['disclaimer'], '',
        '| Scenario | Gate | Coverage | Findings | Inline | Logical Calls | Simulated HTTP | Local Review Posts |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in report['scenarios']:
        lines.append(f"| {row['title']} | {row['gate']} | {row['coverage']} | {len(row['findings'])} | {row['inline_comments']} | {row['logical_calls']} | {row['simulated_http_requests']} | {row['in_memory_review_posts']} |")
    lines.extend(['', 'Each cache-only rerun preserves the exact result and adds **0 generation requests, 0 token-count requests and 0 local review posts**.',
        '', '**Real network requests: 0. Paid provider calls: 0.** Findings and token usage are authored simulation data; citations are verified against real Git snapshots.', ''])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['all', *SCENARIOS], default='all')
    parser.add_argument('--repository-path', type=Path)
    parser.add_argument('--repository-name', default='showcase/offline', help='Optional owner/repository used only in generated source links')
    parser.add_argument('--base')
    parser.add_argument('--head')
    parser.add_argument('--output', type=Path, help='Optional JSON report destination')
    parser.add_argument('--summary', type=Path, help='Optional Markdown summary destination')
    args = parser.parse_args(argv)
    try:
        report = run_showcase(args.scenario, args.repository_path, args.base, args.head, args.repository_name)
    except (ReviewError, ImportError) as error:
        parser.exit(2, str(error) + '\n')
    human = summary(report)
    for destination, text in ((args.output, json.dumps(report, indent=2, sort_keys=True) + '\n'), (args.summary, human)):
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding='utf-8')
    print(human, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
