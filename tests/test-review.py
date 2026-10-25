"""Cross-file contracts, real SDK tool protocol, races and trace regression tests."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pr_review.core import ReviewError, cached_result, digest, gate, payload, validate_input, validate_result
from pr_review.context import ContextReader
from pr_review.diagnostics import Diagnostics
from pr_review.service import prepare, analyze, publish
from pr_review.review import policies, schema, source_metadata, system_prompt, verify_sources


class Github:
    def __init__(self,base,head):
        self.base,self.head=base,head
        self.title='Rename contract'; self.body='Review caller'; self.items=[]; self.posts=0; self.uncertain=False
    def pr(self):
        return dict(state='open',draft=False,title=self.title,body=self.body,user={'type':'User'},base={'ref':'main','sha':self.base},head={'sha':self.head,'repo':{'full_name':'fixture/repo'}})
    def reviews(self): return self.items
    def post(self,body):
        self.posts+=1
        self.items.append(dict(user={'login':'github-actions[bot]','type':'Bot'},state='COMMENTED',commit_id=body['commit_id'],body=body['body']))
        if self.uncertain: raise ReviewError('ambiguous')
        return {'id':42}


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        def git(*args): return subprocess.check_output(['git','-C',str(self.root),*args],text=True,stderr=subprocess.DEVNULL).strip()
        self.git=git
        git('init','-b','main');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
        (self.root/'contract.py').write_text('FIELD = "name"\n')
        (self.root/'caller.py').write_text('from contract import FIELD\nassert FIELD == "name"\n')
        git('add','.');git('commit','-m','base');base=git('rev-parse','HEAD')
        (self.root/'contract.py').write_text('FIELD = "label"\n')
        git('commit','-am','change');head=git('rev-parse','HEAD')
        self.github=Github(base,head)
        self.data=prepare(self.github,'fixture/repo',1,self.root,mode='context')
        self.clean=dict(status='complete',summary='No supported defect.',findings=[],limitations=[])
    def result(self,content=None): return analyze(self.data,recorded=content or self.clean,repository_path=self.root)
    def finding(self,anchor=True):
        reader=ContextReader(self.root,self.data)
        source=reader.execute('read_file',dict(path='caller.py'))['source']
        # caller is discovered separately by the model in the tool loop
        return dict(severity='high',description='Contract rename breaks the caller.',evidence='Caller expects name.',recommendation='Update caller together.',anchor=dict(file='contract.py',side='RIGHT',start=1,end=1) if anchor else None,references=[{k:v for k,v in source.items() if k!='text'}]),source
    def live(self):
        result=self.result(); result['live']=True;result['calls']=1
        return result
    def test_metadata_policy_and_mode_invalidate_cache(self):
        result=self.live(); publish(self.data,result,self.github,repository_path=self.root)
        self.assertEqual(cached_result(self.github.items,self.data),result)
        for variant in ({**self.data,'mode':'diff'},{**self.data,'metadata':dict(title='Edited',body='')},{**self.data,'head':'a'*40}):
            self.assertIsNone(cached_result(self.github.items,variant))
        with self.assertRaises(ReviewError):validate_input({**self.data,'policies':{}})
    def test_partial_success_high_still_fails(self):
        result=self.result({**self.clean,'status':'partial','limitations':['Caller not fully explored.']})
        self.assertTrue(gate(result));self.assertIn('INCOMPLETE REVIEW',payload(self.data,result)['body'])
        f,s=self.finding(); result['sources']=[source_metadata(s)];result['content']['findings']=[f];result['gate_outcome']='failure'
        validate_result(result,self.data);self.assertFalse(gate(result))
    def test_unavailable_or_tampered_citations_rejected(self):
        result=self.result();f,s=self.finding();result['content']['findings']=[f];result['gate_outcome']='failure'
        with self.assertRaises(ReviewError):validate_result(result,self.data)
        result['sources']=[source_metadata(s)]; validate_result(result,self.data);verify_sources(self.data,result,self.root)
        result['sources'][0]['text_hash']='0'*64
        with self.assertRaises(ReviewError):verify_sources(self.data,result,self.root)
    def test_body_only_finding_and_inline_anchor(self):
        result=self.result();f,s=self.finding(False);result['sources']=[source_metadata(s)];result['content']['findings']=[f];result['gate_outcome']='failure'
        body=payload(self.data,result);self.assertEqual(body['comments'],[]);self.assertIn('/blob/'+self.data['head']+'/caller.py#L1-L2',body['body'])
        result['content']['findings'][0]['anchor']=dict(file='contract.py',side='RIGHT',start=1,end=1)
        self.assertEqual(len(payload(self.data,result)['comments']),1)
        result['content']['findings'][0]['anchor']['end']=50
        with self.assertRaises(ReviewError):payload(self.data,result)
    def test_publication_uncertain_one_post_and_read_reconciliation(self):
        result=self.live();self.github.uncertain=True
        with contextlib.redirect_stdout(io.StringIO()):
            diag=Diagnostics(self.root/'diagnostics','publish')
            self.assertTrue(publish(self.data,result,self.github,repository_path=self.root,diagnostics=diag))
            diag.finalize('success')
        self.assertEqual(self.github.posts,1)
        self.assertIn('reconciliation.end',(self.root/'diagnostics/events.jsonl').read_text())
    def test_metadata_edit_prevents_paid_call(self):
        self.github.title='Edited'
        with self.assertRaises(ReviewError):analyze(self.data,github=self.github,client=NS(),repository_path=self.root)
    def test_cache_hit_new_trace_zero_calls(self):
        result=self.live();publish(self.data,result,self.github,repository_path=self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            diag=Diagnostics(self.root/'diagnostics','analyze')
            self.assertEqual(analyze(self.data,github=self.github,client=NS(),repository_path=self.root,diagnostics=diag),result)
        events=(self.root/'diagnostics/events.jsonl').read_text();self.assertIn('"current_calls": 0',events)
    def test_wrong_sources_and_diagnostic_bundle_cannot_be_results(self):
        with self.assertRaises(ReviewError):validate_result({'version':2,'events':[]},self.data)
        result=self.result();result['sources']=[{'source_id':'spoof'}]
        with self.assertRaises(ReviewError):validate_result(result,self.data)
    def mock_client(self,kind='success'):
        calls=[]
        def create(**kwargs):
            calls.append(kwargs)
            if kind=='timeout':raise TimeoutError('runtime-canary ::error::')
            if kind=='http':raise RuntimeError('runtime-canary')
            if 'tools' in kwargs and len(calls)==1:
                return NS(id='msg_tools',model=self.data['model'],stop_reason='tool_use',content=[NS(type='tool_use',id='tool_1',name='read_file',input=dict(path='caller.py'))],usage=NS(input_tokens=100,output_tokens=20))
            if 'tools' in kwargs:
                return NS(id='msg_done',model=self.data['model'],stop_reason='end_turn',content=[NS(type='text',text='Ready.')],usage=NS(input_tokens=100,output_tokens=20))
            content=copy.deepcopy(self.clean)
            if kind=='finding':
                f,s=self.finding();content['findings']=[f]
            text='invalid JSON' if kind=='malformed' else json.dumps(content)
            if kind=='validation':text=json.dumps({'bad':True})
            return NS(id='msg_final',model=self.data['model'],stop_reason='end_turn',content=[NS(type='text',text=text)],usage=NS(input_tokens=100,output_tokens=30))
        return NS(messages=NS(create=create)),calls
    def test_haiku_adaptive_thinking_survives_tool_replay_and_final_text_parsing(self):
        client, calls = self.mock_client()
        original = client.messages.create
        thinking = NS(type='thinking', thinking='fixture-private-reasoning', signature='fixture-signed-thinking')
        redacted = NS(type='redacted_thinking', data='fixture-opaque-block')
        def create(**kwargs):
            response = original(**kwargs)
            response.content[:0] = [thinking, redacted]
            return response
        client.messages.create = create
        with contextlib.redirect_stdout(io.StringIO()) as console:
            diagnostics = Diagnostics(self.root / 'thinking-diagnostics', 'analyze')
            result = analyze(self.data, client=client, repository_path=self.root, diagnostics=diagnostics)
            manifest = diagnostics.finalize('success')
        retained = console.getvalue() + ''.join(path.read_text() for path in (self.root / 'thinking-diagnostics').iterdir())
        for canary in ('fixture-private-reasoning', 'fixture-signed-thinking', 'fixture-opaque-block'):
            self.assertNotIn(canary, retained)
        self.assertTrue(manifest['redacted'])
        self.assertFalse(manifest['complete'])
        self.assertEqual(result['content']['summary'], self.clean['summary'])
        replay = calls[1]['messages'][1]['content']
        self.assertEqual(replay[:2], [vars(thinking), vars(redacted)])
        self.assertEqual(replay[2]['type'], 'tool_use')
        self.assertTrue(all(call['output_config']['effort'] == 'low' for call in calls))
        self.assertIn('format', calls[-1]['output_config'])
        self.assertTrue(all(not {'temperature', 'top_p', 'top_k'} & set(call) for call in calls))

    def test_tool_loop_final_has_no_tools_and_citations_are_in_context(self):
        client,calls=self.mock_client('finding')
        result=analyze(self.data,client=client,repository_path=self.root)
        self.assertEqual(result['calls'],3);self.assertEqual(len(calls),3);self.assertNotIn('tools',calls[-1])
        self.assertEqual(calls[1]['messages'][-1]['content'][0]['tool_use_id'],'tool_1')
        self.assertFalse(gate(result));verify_sources(self.data,result,self.root)
    def test_errors_have_requests_response_and_safe_failure_traces(self):
        for kind in ('timeout','http','malformed','validation'):
            client,calls=self.mock_client(kind);directory=self.root/kind
            with contextlib.redirect_stdout(io.StringIO()),patch.dict(os.environ,{'ANTHROPIC_API_KEY':'runtime-canary'}):
                diag=Diagnostics(directory,'analyze')
                with self.assertRaises(ReviewError) as caught:analyze(self.data,client=client,repository_path=self.root,diagnostics=diag)
                diag.error(caught.exception);diag.finalize('failure')
            text=''.join(p.read_text() for p in directory.iterdir());self.assertNotIn('runtime-canary',text);self.assertIn('sdk.start',text);self.assertIn('operation.error',text)
            self.assertTrue((directory/'context.json').exists())
    def test_stale_during_exploration_prevents_next_call(self):
        client,calls=self.mock_client();original=client.messages.create
        def change(**kwargs):
            answer=original(**kwargs);self.github.head='f'*40;return answer
        client.messages.create=change
        with self.assertRaises(ReviewError):analyze(self.data,github=self.github,client=client,repository_path=self.root)
        self.assertEqual(len(calls),1)
    def test_diff_and_pr_metadata_runtime_secret_rejected_before_provider(self):
        for field in ('diff','metadata'):
            data=copy.deepcopy(self.data)
            if field=='diff':data['diff']=data['diff'].replace('+FIELD', '+#runtime-canary-value\n+FIELD').replace('@@ -1 +1 @@','@@ -1 +1,2 @@')
            else:data['metadata']['title']='runtime-canary-value'
            client,calls=self.mock_client()
            with patch.dict(os.environ,{'GITHUB_TOKEN':'runtime-canary-value'}):
                with self.assertRaises(ReviewError):analyze(data,client=client,repository_path=self.root)
            self.assertEqual(calls,[])
    def test_github_malformed_body_retained_without_secret_or_retry(self):
        from pr_review.service import Github as Transport
        response=NS(status=200,headers={'x-github-request-id':'request_fixture'},read=lambda size:b'not-json runtime-canary-value')
        manager=contextlib.nullcontext(response)
        with contextlib.redirect_stdout(io.StringIO()),patch.dict(os.environ,{'GITHUB_TOKEN':'runtime-canary-value'}):
            diag=Diagnostics(self.root/'diagnostics','publish')
            transport=Transport('fixture/repo',1,'runtime-canary-value',diag)
            with patch('urllib.request.urlopen',return_value=manager) as urlopen:
                with self.assertRaises(ReviewError):transport.request()
            diag.finalize('failure')
        self.assertEqual(urlopen.call_count,1)
        saved=(self.root/'diagnostics/responses.jsonl').read_text()
        self.assertIn('not-json',saved);self.assertNotIn('runtime-canary-value',saved)
    def test_large_git_diff_rejected_before_materializing_patch(self):
        from pr_review.service import git
        (self.root/'large.py').write_text('x'*100000+'\n')
        self.git('add','.');self.git('commit','-m','large')
        with self.assertRaises(ReviewError):git(self.root,'diff',self.data['head'],'HEAD','--')
    def test_generation_retries_transient_errors_but_not_permanent_errors(self):
        class Rejected(Exception):
            status_code = 429
        client, calls = self.mock_client()
        original = client.messages.create
        attempts = []
        def create(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise Rejected()
            return original(**kwargs)
        client.messages.create = create
        with patch('pr_review.review.backoff'):
            result = analyze(self.data, client=client, repository_path=self.root)
        self.assertTrue(result['live'])
        self.assertEqual(len(attempts), len(calls) + 1)
        for status in (400, 401, 403, 404, 422):
            error = Rejected(); error.status_code = status
            with patch.object(client.messages, 'create', side_effect=error) as create:
                with self.assertRaises(ReviewError):
                    analyze(self.data, client=client, repository_path=self.root)
                self.assertEqual(create.call_count, 1)

    def test_retry_retains_cost_reservation_and_stops_at_ceiling(self):
        class Rejected(Exception):
            status_code = 429
        with patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': '.07',
                                           'CLAUDE_INPUT_USD_PER_MILLION': '1',
                                           'CLAUDE_OUTPUT_USD_PER_MILLION': '5'}):
            data = {**self.data, 'policies': policies(self.data['model'])}
            client = NS(messages=NS(create=unittest.mock.Mock(side_effect=Rejected())))
            with patch('pr_review.review.backoff'), self.assertRaisesRegex(ReviewError, 'budget.cost'):
                analyze(data, client=client, repository_path=self.root)
            self.assertEqual(client.messages.create.call_count, 1)

    def test_token_count_transient_retries_are_bounded(self):
        client, calls = self.mock_client()
        counter = unittest.mock.Mock(side_effect=[TimeoutError(), NS(input_tokens=100)])
        client.messages.count_tokens = counter
        # Subsequent successful counts use the last configured response.
        def count(**kwargs):
            return counter() if counter.call_count < 2 else NS(input_tokens=100)
        client.messages.count_tokens = count
        with patch('pr_review.review.backoff'):
            result = analyze(self.data, client=client, repository_path=self.root)
        self.assertTrue(result['live']); self.assertEqual(counter.call_count, 2)

    def test_generation_and_token_preflight_stop_after_three_retries(self):
        class Rejected(Exception):
            status_code = 429
        with patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': '.5'}):
            data = {**self.data, 'policies': policies(self.data['model'])}
            client = NS(messages=NS(create=unittest.mock.Mock(side_effect=Rejected())))
            with patch('pr_review.review.backoff') as delay, self.assertRaisesRegex(ReviewError, 'provider.call'):
                analyze(data, client=client, repository_path=self.root)
            self.assertEqual(client.messages.create.call_count, 4)
            self.assertEqual(delay.call_count, 3)
            client.messages.count_tokens = unittest.mock.Mock(side_effect=TimeoutError())
            client.messages.create.reset_mock()
            with patch('pr_review.review.backoff') as delay, self.assertRaisesRegex(ReviewError, 'provider.token_count'):
                analyze(data, client=client, repository_path=self.root)
            self.assertEqual(client.messages.count_tokens.call_count, 4)
            self.assertEqual(delay.call_count, 3)
            client.messages.create.assert_not_called()

    def test_generation_server_and_transport_failures_retry_with_cost_guard(self):
        class ServerError(Exception):
            status_code = 503
        for error in (ServerError(), TimeoutError()):
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': '.5'}):
                data = {**self.data, 'policies': policies(self.data['model'])}
                client = NS(messages=NS(create=unittest.mock.Mock(side_effect=error)))
                with patch('pr_review.review.backoff'), self.assertRaisesRegex(ReviewError, 'provider.call'):
                    analyze(data, client=client, repository_path=self.root)
                self.assertEqual(client.messages.create.call_count, 4)
            with patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': '.07',
                                           'CLAUDE_INPUT_USD_PER_MILLION': '1',
                                           'CLAUDE_OUTPUT_USD_PER_MILLION': '5'}):
                data = {**self.data, 'policies': policies(self.data['model'])}
                client = NS(messages=NS(create=unittest.mock.Mock(side_effect=error)))
                with patch('pr_review.review.backoff'), self.assertRaisesRegex(ReviewError, 'budget.cost'):
                    analyze(data, client=client, repository_path=self.root)
                self.assertEqual(client.messages.create.call_count, 1)

    def test_default_sdk_and_preflight_timeouts_precede_watchdogs(self):
        client, calls = self.mock_client()
        client.messages.count_tokens = unittest.mock.Mock(return_value=NS(input_tokens=100))
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch('anthropic.Anthropic', return_value=client) as sdk:
            analyze(self.data, repository_path=self.root)
        self.assertEqual(sdk.call_args.kwargs['timeout'], 50)
        self.assertEqual(sdk.call_args.kwargs['max_retries'], 0)
        self.assertEqual(client.messages.count_tokens.call_args.kwargs['timeout'], 20)

    def test_total_deadline_interrupts_blocking_token_preflight(self):
        from pr_review.runtime import bounded
        import time
        client, calls = self.mock_client()
        client.messages.count_tokens = lambda **kwargs: time.sleep(2)
        started = time.monotonic()
        with self.assertRaisesRegex(ReviewError, 'budget.time'):
            bounded(.1)(analyze)(self.data, client=client, repository_path=self.root)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(calls, [])

    def test_token_count_failure_closes_known_operation(self):
        client,calls=self.mock_client()
        client.messages.count_tokens=lambda **kwargs:(_ for _ in ()).throw(TimeoutError('sensitive'))
        with contextlib.redirect_stdout(io.StringIO()):
            diag=Diagnostics(self.root/'diagnostics','analyze')
            with self.assertRaises(ReviewError):analyze(self.data,client=client,repository_path=self.root,diagnostics=diag)
            manifest=diag.finalize('failure')
        self.assertNotIn('count-01',manifest.get('open_operations',{}));self.assertEqual(calls,[])
    def test_unusable_anchor_falls_back_to_body_with_verified_sources(self):
        result=self.result();f,source=self.finding()
        f['anchor']=dict(file='caller.py',side='RIGHT',start=2,end=2)
        result['sources']=[source_metadata(source)];result['content']['findings']=[f];result['gate_outcome']='failure'
        validate_result(result,self.data);verify_sources(self.data,result,self.root)
        body=payload(self.data,result)
        self.assertEqual(body['comments'],[]);self.assertIn('Contract rename breaks',body['body'])
        result['content']['findings'][0]['references'][0]['blob']='0'*40
        with self.assertRaises(ReviewError):validate_result(result,self.data)
    def test_cache_only_hit_reuses_and_miss_never_initializes_sdk(self):
        client,calls=self.mock_client()
        with patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(ReviewError):analyze(self.data,github=self.github,repository_path=self.root,cache_only=True)
            sdk.assert_not_called()
        self.assertEqual(calls,[])
        result=self.live();publish(self.data,result,self.github,repository_path=self.root)
        self.assertEqual(analyze(self.data,github=self.github,client=client,repository_path=self.root,cache_only=True),result)
        self.assertEqual(calls,[])
    def test_five_call_and_twelve_operation_limits_are_explicit(self):
        calls=[]
        def create(**kwargs):
            calls.append(kwargs)
            if 'tools' in kwargs:
                blocks=[NS(type='tool_use',id=f'tool_{len(calls)}_{n}',name='read_file',input={'path':'caller.py'}) for n in range(4)]
                return NS(model=self.data['model'],stop_reason='tool_use',content=blocks,usage=NS(input_tokens=100,output_tokens=20))
            return NS(model=self.data['model'],stop_reason='end_turn',content=[NS(type='text',text=json.dumps(self.clean))],usage=NS(input_tokens=100,output_tokens=20))
        result=analyze(self.data,client=NS(messages=NS(create=create)),repository_path=self.root)
        self.assertEqual(len(calls),5);self.assertTrue(gate(result));self.assertEqual(result['coverage'],'partial')
        self.assertTrue(any('operation limit' in x for x in result['content']['limitations']))
    def test_input_bound_rejects_before_sdk_call(self):
        client,calls=self.mock_client();data={**self.data,'metadata':dict(title='x'*30000,body='')}
        with self.assertRaises(ReviewError):analyze(data,client=client,repository_path=self.root)
        self.assertEqual(calls,[])

    def test_final_context_fits_complete_request_and_reports_source_omission(self):
        # Repeated quotes, backslashes and Unicode expose nested JSON overhead.
        (self.root / 'README.md').write_text('Example: "quoted" \\ path é\n' * 160)
        (self.root / 'contract.py').write_text('FIELD = "name"\n')
        self.git('add', '.'); self.git('commit', '-m', 'Base with escaped context')
        base = self.git('rev-parse', 'HEAD')
        (self.root / 'contract.py').write_text('FIELD = "label"\n')
        self.git('commit', '-am', 'Rename field')
        github = Github(base, self.git('rev-parse', 'HEAD'))
        limit = 11500
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0',
                                    'CLAUDE_MAX_INPUT_TOKENS': str(limit)}):
            data = prepare(github, 'fixture/repo', 1, self.root, mode='context')
            reader = ContextReader(self.root, data)
            sources = reader.initial_context()
            initial = dict(diff=data['diff'], metadata=data['metadata'], sources=sources,
                           limitations=['Exploration disabled by configuration.'])
            request = dict(model=data['model'], system=system_prompt(),
                           messages=[dict(role='user', content=json.dumps(initial))],
                           max_tokens=4000, output_config={'effort': 'low',
                               'format': {'type': 'json_schema', 'schema': schema()}})
            old_estimate = (len(json.dumps(initial).encode()) + len(system_prompt().encode())
                            + len(json.dumps(schema()).encode()) + 2048)
            self.assertLessEqual(old_estimate, limit)
            self.assertGreater(len(json.dumps(request, ensure_ascii=False).encode()) + 1024, limit)
            omitted = next(s for s in sources if s['path'] == 'README.md')
            client, calls = self.mock_client()
            client.messages.count_tokens = unittest.mock.Mock(return_value=NS(input_tokens=100))
            result = analyze(data, client=client, repository_path=self.root)
            self.assertEqual(len(calls), 1)
            self.assertEqual(client.messages.count_tokens.call_count, 1)
            self.assertLessEqual(len(json.dumps(calls[0], ensure_ascii=False).encode()) + 1024, limit)
            final = json.loads(calls[0]['messages'][0]['content'])
            self.assertEqual([s['path'] for s in final['sources']], ['contract.py'])
            self.assertNotIn(omitted['source_id'], calls[0]['messages'][0]['content'])
            self.assertNotIn(omitted['text'], calls[0]['messages'][0]['content'])
            limitation = 'Final context input budget reached; some sources omitted.'
            self.assertEqual(final['limitations'].count(limitation), 1)
            self.assertIn(limitation, result['content']['limitations'])
            self.assertEqual(result['coverage'], 'partial')

    def test_final_request_exact_limit_retains_context_and_one_over_trims(self):
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0'}):
            data = {**self.data, 'policies': policies(self.data['model'])}
            client, calls = self.mock_client()
            analyze(data, client=client, repository_path=self.root)
            exact = len(json.dumps(calls[0], ensure_ascii=False).encode()) + 1024
            self.assertGreater(exact - 1, 4096)
            for limit in (exact, exact - 1):
                with self.subTest(limit=limit), patch.dict(os.environ, {'CLAUDE_MAX_INPUT_TOKENS': str(limit)}):
                    data = {**self.data, 'policies': policies(self.data['model'])}
                    client, calls = self.mock_client()
                    result = analyze(data, client=client, repository_path=self.root)
                    final = json.loads(calls[0]['messages'][0]['content'])
                    self.assertEqual(bool(final['sources']), limit == exact)
                    self.assertLessEqual(len(json.dumps(calls[0], ensure_ascii=False).encode()) + 1024, limit)
                    omission = 'Final context input budget reached; some sources omitted.'
                    self.assertEqual(omission in result['content']['limitations'], limit != exact)

    def test_irreducible_final_input_fails_before_count_or_generation(self):
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0'}):
            data = {**self.data, 'metadata': dict(title='x' * 30000, body=''),
                    'policies': policies(self.data['model'])}
            client, calls = self.mock_client()
            client.messages.count_tokens = unittest.mock.Mock(return_value=NS(input_tokens=100))
            with self.assertRaisesRegex(ReviewError, 'budget.input: conservative'):
                analyze(data, client=client, repository_path=self.root)
            client.messages.count_tokens.assert_not_called()
            self.assertEqual(calls, [])
    def test_deadline_reserves_final_call(self):
        client,calls=self.mock_client()
        with patch('pr_review.review.time',NS(monotonic=unittest.mock.Mock(side_effect=[0,241]))):
            with self.assertRaises(ReviewError):analyze(self.data,client=client,repository_path=self.root)
        self.assertEqual(calls,[])
    def test_nondefault_model_reaches_preflight_and_generation_from_cli_environment(self):
        from pr_review.cli import main
        model = 'claude-selected-test-model'
        variables = {'CLAUDE_MODEL': model, 'CLAUDE_INPUT_USD_PER_MILLION': '3',
                     'CLAUDE_OUTPUT_USD_PER_MILLION': '15', 'CLAUDE_MAX_REVIEW_USD': '1'}
        event = self.root / 'event.json'
        event.write_text(json.dumps({'repository': {'full_name': 'fixture/repo'}, 'number': 1,
                                    'pull_request': self.github.pr()}))
        output = self.root / 'prepared.json'
        with patch.dict(os.environ, variables), patch('pr_review.cli.api', return_value=self.github):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['prepare', '--event', str(event), '--repository-path', str(self.root),
                                       '--output', str(output), '--diagnostics-dir', str(self.root/'prepare-trace')]), 0)
            data = json.loads(output.read_text())
            self.assertEqual(data['model'], model)
            client, calls = self.mock_client()
            original = client.messages.create
            def respond(**kwargs):
                response = original(**kwargs)
                response.model = model
                return response
            client.messages.create = respond
            counts = []
            def count(**kwargs):
                counts.append(kwargs)
                return NS(input_tokens=100)
            client.messages.count_tokens = count
            result = analyze(data, client=client, repository_path=self.root)
            self.assertEqual(result['model'], model)
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(call['model'] == model for call in calls + counts))
            changed = prepare(self.github, 'fixture/repo', 1, self.root, model=model, mode='context')
            self.assertEqual(data, changed)
            with patch.dict(os.environ, {'CLAUDE_MAX_REVIEW_USD': '2'}):
                with self.assertRaisesRegex(ReviewError, 'input.policy'):
                    analyze(data, recorded=self.clean, repository_path=self.root)
                fresh = prepare(self.github, 'fixture/repo', 1, self.root, model=model, mode='context')
                self.assertNotEqual(data['policies'], fresh['policies'])
                self.assertNotEqual(digest(data), digest(fresh))

    def test_selected_model_without_prices_fails_before_provider(self):
        client, calls = self.mock_client()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ReviewError, 'configuration'):
                prepare(self.github, 'fixture/repo', 1, self.root,
                        model='claude-selected-test-model', mode='context')
        self.assertEqual(calls, [])

    def test_configured_price_and_ceiling_bound_requests(self):
        with patch.dict(os.environ, {'CLAUDE_INPUT_USD_PER_MILLION': '30',
                                    'CLAUDE_OUTPUT_USD_PER_MILLION': '150',
                                    'CLAUDE_MAX_REVIEW_USD': '0.01'}):
            data = prepare(self.github, 'fixture/repo', 1, self.root, mode='context')
            client, calls = self.mock_client()
            with self.assertRaisesRegex(ReviewError, 'budget.cost'):
                analyze(data, client=client, repository_path=self.root)
            self.assertEqual(calls, [])

    def test_diff_mode_reads_distant_hunks_and_marks_budget_omissions(self):
        path = self.root / 'many.py'
        original = [f'value_{n} = {n}\n' for n in range(600)]
        path.write_text(''.join(original))
        self.git('add', '.'); self.git('commit', '-m', 'large fixture')
        self.github.base = self.git('rev-parse', 'HEAD')
        original[1] = 'value_1 = -1\n'; original[501] = 'value_501 = -1\n'
        path.write_text(''.join(original)); self.git('commit', '-am', 'two distant hunks')
        self.github.head = self.git('rev-parse', 'HEAD')
        for limit, expected in [('12', 'complete'), ('1', 'partial')]:
            with patch.dict(os.environ, {'CLAUDE_MAX_TOOL_OPERATIONS': limit}):
                data = prepare(self.github, 'fixture/repo', 1, self.root, mode='diff')
                retained = []
                original_context = ContextReader._source
                def capture(reader, *args):
                    source = original_context(reader, *args); retained.append(source); return source
                with patch.object(ContextReader, '_source', capture):
                    result = analyze(data, recorded=self.clean, repository_path=self.root)
                self.assertEqual(result['coverage'], expected)
                if expected == 'complete':
                    for snapshot in ('before', 'after'):
                        self.assertTrue(any(s['snapshot'] == snapshot and s['start_line'] <= 502 <= s['end_line'] for s in retained))
                else:
                    self.assertIn('tool operation limit reached', result['content']['limitations'])

    def test_diff_mode_reads_one_large_hunk_across_chunks_and_marks_budget_omissions(self):
        path = self.root / 'large-hunk.py'
        before = [f'value_{n} = {n}\n' for n in range(1, 451)]
        after = [f'value_{n} = -{n}\n' for n in range(1, 451)]
        path.write_text(''.join(before))
        self.git('add', '.'); self.git('commit', '-m', 'large hunk base fixture')
        self.github.base = self.git('rev-parse', 'HEAD')
        path.write_text(''.join(after))
        self.git('commit', '-am', 'one contiguous large hunk')
        self.github.head = self.git('rev-parse', 'HEAD')
        for limit, expected in [('6', 'complete'), ('5', 'partial')]:
            with self.subTest(limit=limit), patch.dict(os.environ, {'CLAUDE_MAX_TOOL_OPERATIONS': limit}):
                data = prepare(self.github, 'fixture/repo', 1, self.root, mode='diff')
                self.assertEqual(data['changed_files'], ['large-hunk.py'])
                self.assertEqual(data['diff'].count('\n@@ '), 1)
                self.assertIn('@@ -1,450 +1,450 @@', data['diff'])
                retained = []
                original_source = ContextReader._source
                def capture(reader, *args):
                    source = original_source(reader, *args)
                    retained.append(source)
                    return source
                with patch.object(ContextReader, '_source', capture):
                    result = analyze(data, recorded=copy.deepcopy(self.clean), repository_path=self.root)
                self.assertEqual(result['coverage'], expected)
                self.assertEqual(result['content']['status'], expected)
                covered = {'before': set(), 'after': set()}
                for source in retained:
                    self.assertEqual(source['path'], 'large-hunk.py')
                    start, end = source['start_line'], source['end_line']
                    self.assertLessEqual(end - start + 1, 200)
                    lines = before if source['snapshot'] == 'before' else after
                    self.assertEqual(source['text'], ''.join(lines[start - 1:end]))
                    covered[source['snapshot']].update(range(start, end + 1))
                if expected == 'complete':
                    self.assertEqual(result['content']['limitations'], [])
                    for snapshot in ('before', 'after'):
                        # Exact coverage includes both sides of 200/201 and
                        # 400/401, as well as the final changed line (450).
                        self.assertEqual(covered[snapshot], set(range(1, 451)))
                else:
                    self.assertIn('tool operation limit reached', result['content']['limitations'])
                    self.assertGreater(sum(map(len, covered.values())), 0)
                    self.assertLess(sum(map(len, covered.values())), 900)
                    self.assertTrue(any(450 not in lines for lines in covered.values()))

    def test_diff_mode_renamed_file_reads_original_before_path(self):
        self.github.base = self.github.head
        self.git('mv', 'contract.py', 'renamed.py')
        (self.root / 'renamed.py').write_text('FIELD = "renamed"\n')
        # A one-line complete rewrite is not considered a rename by Git. Keep
        # stable content so the rename-with-edit path is actually exercised.
        (self.root / 'stable.py').write_text(''.join(f'line_{n} = {n}\n' for n in range(30)))
        self.git('add', '.'); self.git('commit', '-m', 'rename fixture')
        self.github.base = self.git('rev-parse', 'HEAD')
        self.git('mv', 'stable.py', 'stable-renamed.py')
        p = self.root / 'stable-renamed.py'; p.write_text(p.read_text().replace('line_5 = 5', 'line_5 = 50'))
        self.git('commit', '-am', 'rename with edit'); self.github.head = self.git('rev-parse', 'HEAD')
        data = prepare(self.github, 'fixture/repo', 1, self.root, mode='diff')
        self.assertIn('rename from stable.py', data['diff'])
        result = analyze(data, recorded=self.clean, repository_path=self.root)
        self.assertEqual(result['coverage'], 'complete')

    def test_provider_usage_and_tool_protocol_fail_before_followup_calls(self):
        for kind in ('negative-input', 'boolean-output', 'too-many-output', 'end-turn-tools', 'bad-id', 'bad-name', 'bad-arguments', 'unknown-block'):
            with self.subTest(kind=kind):
                client, calls = self.mock_client(); original = client.messages.create
                def respond(**kwargs):
                    response = original(**kwargs)
                    if kind == 'negative-input': response.usage.input_tokens = -1
                    elif kind == 'boolean-output': response.usage.output_tokens = True
                    elif kind == 'too-many-output': response.usage.output_tokens = kwargs['max_tokens'] + 1
                    elif kind == 'end-turn-tools': response.stop_reason = 'end_turn'
                    elif kind == 'bad-id': response.content[0].id = []
                    elif kind == 'bad-name': response.content[0].name = []
                    elif kind == 'bad-arguments': response.content[0].input = []
                    elif kind == 'unknown-block': response.content.append(NS(type='server_tool_use'))
                    return response
                client.messages.create = respond
                with self.assertRaisesRegex(ReviewError, 'provider.'):
                    analyze(self.data, client=client, repository_path=self.root)
                self.assertEqual(len(calls), 1)

    def test_zero_diff_does_not_scan_context_or_initialize_provider(self):
        self.github.head = self.github.base
        data = prepare(self.github, 'fixture/repo', 1, self.root, mode='context')
        with patch.object(ContextReader, 'initial_context', side_effect=AssertionError('unexpected scan')), patch('anthropic.Anthropic') as sdk:
            result = analyze(data, repository_path=self.root)
        sdk.assert_not_called()
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['calls'], 0)
        self.assertFalse(result['live'])

    def test_provenance_rejects_impossible_offline_usage_or_call_counts(self):
        result = self.result()
        for mutation in ({'live': True}, {'calls': 1}, {'usage': {'input_tokens': 1, 'output_tokens': 0}}):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ReviewError, 'result.provenance'):
                validate_result({**result, **mutation}, self.data)

    def test_tool_identifiers_are_unique_across_exploration_turns(self):
        client, calls = self.mock_client()
        original = client.messages.create
        def respond(**kwargs):
            response = original(**kwargs)
            if len(calls) == 2:
                response.stop_reason = 'tool_use'
                response.content = [NS(type='tool_use', id='tool_1', name='read_file', input={'path': 'caller.py'})]
            return response
        client.messages.create = respond
        with self.assertRaisesRegex(ReviewError, 'provider.tools: reused'):
            analyze(self.data, client=client, repository_path=self.root)
        self.assertEqual(len(calls), 2)

    def test_preflight_count_increases_cost_reservation_before_generation(self):
        # The real preflight is authoritative if it exceeds local framing.
        with patch.dict(os.environ, {'CLAUDE_MAX_EXPLORATION_CALLS': '0',
                                    'CLAUDE_MAX_REVIEW_USD': '.02',
                                    'CLAUDE_INPUT_USD_PER_MILLION': '1',
                                    'CLAUDE_OUTPUT_USD_PER_MILLION': '1'}):
            data = {**self.data, 'policies': policies(self.data['model'])}
            client, calls = self.mock_client()
            client.messages.count_tokens = lambda **kwargs: NS(input_tokens=23000)
            with self.assertRaisesRegex(ReviewError, 'budget.cost: counted'):
                analyze(data, client=client, repository_path=self.root)
            self.assertEqual(calls, [])

    def test_every_executable_module_participates_in_cache_identity(self):
        root = Path(__file__).resolve().parents[1] / 'src' / 'pr_review'
        original = Path.read_text
        baseline = policies()['implementation']
        for name in ('core.py', 'service.py', 'diagnostics.py', 'context.py', 'cli.py'):
            def changed(path, *args, **kwargs):
                text = original(path, *args, **kwargs)
                return text + '\n# policy regression\n' if path.parent == root and path.name == name else text
            with self.subTest(name=name), patch.object(Path, 'read_text', changed):
                self.assertNotEqual(policies()['implementation'], baseline)

    def test_provider_model_substitution_is_rejected_without_fallback(self):
        client, calls = self.mock_client()
        original = client.messages.create
        def respond(**kwargs):
            response = original(**kwargs)
            response.model = 'claude-unrequested-model'
            return response
        client.messages.create = respond
        with self.assertRaisesRegex(ReviewError, 'provider.model'):
            analyze(self.data, client=client, repository_path=self.root)
        self.assertEqual(len(calls), 1)

    def test_tool_content_in_artifact_and_never_console(self):
        client,calls=self.mock_client()
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):
            diag=Diagnostics(self.root/'diagnostics','analyze')
            analyze(self.data,client=client,repository_path=self.root,diagnostics=diag)
            diag.finalize('success')
        self.assertNotIn('assert FIELD',capture.getvalue())
        self.assertIn('assert FIELD',(self.root/'diagnostics/responses.jsonl').read_text())
    def test_cache_record_bound_is_enforced(self):
        result=self.result();f,source=self.finding();result['sources']=[source_metadata(source)]
        result['content']['findings']=[{**f,'description':str(n)+'x'*1100,'evidence':'e'*1100,'recommendation':'r'*1100} for n in range(10)]
        result['gate_outcome']='failure'
        with self.assertRaises(ReviewError):payload(self.data,result)
    @unittest.skipUnless(importlib.util.find_spec('anthropic'),'installed SDK required')
    def test_real_sdk_http_transport_tool_loop_and_count_preflight(self):
        import anthropic,httpx2
        requests=[]
        def respond(request):
            body=json.loads(request.content);requests.append((request.url.path,body))
            if request.url.path.endswith('count_tokens'):return httpx2.Response(200,json={'input_tokens':300})
            if 'tools' in body and sum(p.endswith('/messages') for p,b in requests)==1:
                content=[dict(type='tool_use',id='tool_sdk',name='read_file',input={'path':'caller.py'})];stop='tool_use'
            else:content=[dict(type='text',text='Ready.' if 'tools' in body else json.dumps(self.clean))];stop='end_turn'
            return httpx2.Response(200,json=dict(id='msg_sdk',type='message',role='assistant',model=self.data['model'],stop_reason=stop,stop_sequence=None,content=content,usage={'input_tokens':300,'output_tokens':30}))
        with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
            client=anthropic.Anthropic(api_key='fixture-not-real',http_client=http,max_retries=0,timeout=60)
            result=analyze(self.data,client=client,repository_path=self.root)
        self.assertEqual(result['calls'],3);self.assertEqual(len(requests),6)
        self.assertTrue(gate(result));self.assertNotIn('tools',requests[-1][1])

if __name__=='__main__':unittest.main()
