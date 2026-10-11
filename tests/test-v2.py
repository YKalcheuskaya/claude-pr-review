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
from pr_review.v2 import policies, source_metadata, verify_sources


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


class V2(unittest.TestCase):
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
    def test_v2_metadata_policy_and_mode_invalidate_cache(self):
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
    def test_token_count_failure_closes_known_operation(self):
        client,calls=self.mock_client()
        client.messages.count_tokens=lambda **kwargs:(_ for _ in ()).throw(TimeoutError('sensitive'))
        with contextlib.redirect_stdout(io.StringIO()):
            diag=Diagnostics(self.root/'diagnostics','analyze')
            with self.assertRaises(ReviewError):analyze(self.data,client=client,repository_path=self.root,diagnostics=diag)
            manifest=diag.finalize('failure')
        self.assertNotIn('count-01',manifest.get('open_operations',{}));self.assertEqual(calls,[])
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
    def test_deadline_reserves_final_call(self):
        client,calls=self.mock_client()
        with patch('pr_review.v2.time',NS(monotonic=unittest.mock.Mock(side_effect=[0,241]))):
            with self.assertRaises(ReviewError):analyze(self.data,client=client,repository_path=self.root)
        self.assertEqual(calls,[])
    def test_unpriced_model_cannot_make_paid_call(self):
        client,calls=self.mock_client();data={**self.data,'model':'claude-other-123'}
        with self.assertRaises(ReviewError):analyze(data,client=client,repository_path=self.root)
        self.assertEqual(calls,[])
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
