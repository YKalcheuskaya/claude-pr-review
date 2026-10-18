"""Structured review contracts and bounded context orchestration."""
import copy
import json
import os
import re
import time
from urllib.parse import quote

from .core import DEFAULT_MODEL, ReviewError, digest, locations, path_ok, safe_text
from .config import review_budget, review_controls
from .runtime import bounded, deadline, transient, backoff, MAX_ATTEMPTS, TIMERS
from decimal import Decimal

def system_prompt():
    from pathlib import Path
    try:
        text = Path(__file__).with_name('review-policy.md').read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        raise ReviewError('configuration.prompt: cannot read trusted review-policy.md') from None
    if not text or len(text.encode()) > 32768:
        raise ReviewError('configuration.prompt: prompt must be nonempty and at most 32 KiB')
    return text


def schema():
    text = {"type": "string"}
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    ref = obj({k: ({"type": "integer"} if k in ("start_line", "end_line") else text)
               for k in ("source_id", "snapshot", "path", "blob", "start_line", "end_line")})
    anchor = obj(dict(file=text, side={"type": "string", "enum": ["LEFT", "RIGHT"]}, start={"type": "integer"}, end={"type": "integer"}))
    finding = obj(dict(severity={"type": "string", "enum": ["low", "medium", "high", "critical"]},
                       description=text, evidence=text, recommendation=text,
                       anchor={"anyOf": [anchor, {"type": "null"}]}, references={"type": "array", "items": ref}))
    return obj(dict(status={"type": "string", "enum": ["complete", "partial"]}, summary=text,
                    findings={"type": "array", "items": finding}, limitations={"type": "array", "items": text}))


def policies(model=DEFAULT_MODEL):
    from .context import POLICY, TOOLS
    from pathlib import Path
    return dict(prompt=digest(system_prompt()), schema=digest(schema()), tools=digest(TOOLS),
                reader=digest([POLICY, Path(__file__).with_name('context.py').read_text()]),
                limits=digest([review_controls(), review_budget(model)]),
                implementation=digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))}))


def validate_input(data):
    from .core import validate_snapshot_fields
    fields = {'version','repository','pr','base','head','merge_base','diff','model',
              'config','mode','metadata','policies','changed_files'}
    if (not isinstance(data, dict) or set(data) != fields
            or type(data['version']) is not int or data['version'] != 2 or data['config'] != 'review'
            or data['mode'] not in ('diff', 'context')):
        raise ReviewError('input.contract: invalid review fields')
    locs = validate_snapshot_fields(data)
    if data['policies'] != policies(data['model']) or data['changed_files'] != list(locs):
        raise ReviewError('input.policy: policy or changes mismatch')
    meta = data['metadata']
    if (not isinstance(meta, dict)
            or set(meta) != {'title', 'body'}
            or any(not isinstance(v, str) or len(v.encode()) > 32768 for v in meta.values())):
        raise ReviewError('input.metadata: invalid title/body')
    from .diagnostics import sanitize
    if sanitize(dict(diff=data['diff'],metadata=meta)) != dict(diff=data['diff'],metadata=meta):
        raise ReviewError('input.secret: sensitive diff or PR metadata withheld')
    return locs


def source_metadata(source):
    return {**{k: v for k, v in source.items() if k != 'text'}, 'text_hash': digest(source['text'])}


def validate_result(result, data):
    locs = validate_input(data)
    required = {'version','identity','model','duration_ms','content','usage','live','sources','calls','coverage','gate_outcome'}
    if (not isinstance(result, dict)
            or set(result) != required
            or type(result['version']) is not int or result['version'] != 2
            or result['identity'] != digest(data)
            or result['model'] != data['model']):
        raise ReviewError('result.identity: mismatch')
    if type(result['duration_ms']) is not int or result['duration_ms'] < 0 or type(result['live']) is not bool:
        raise ReviewError('result.provenance: invalid')
    if type(result['calls']) is not int or not 0 <= result['calls'] <= (review_controls()['research_calls'] + 1 if data['mode'] == 'context' else 1):
        raise ReviewError('result.calls: invalid')
    if result['live'] != bool(result['calls']):
        raise ReviewError('result.provenance: calls and live status disagree')
    if not isinstance(result['usage'], dict) or set(result['usage']) != {'input_tokens','output_tokens'} or any(type(v) is not int or v < 0 for v in result['usage'].values()):
        raise ReviewError('result.usage: invalid')
    if not result['live'] and any(result['usage'].values()):
        raise ReviewError('result.provenance: offline result cannot report provider usage')
    content = result['content']
    if (not isinstance(content, dict)
            or set(content) != {'status','summary','findings','limitations'}
            or content['status'] not in ('complete','partial')):
        raise ReviewError('content.contract: invalid')
    if not isinstance(content['findings'], list) or len(content['findings']) > 10 or not isinstance(content['limitations'], list) or len(content['limitations']) > 30:
        raise ReviewError('content.collections: invalid')
    texts = [content['summary']] + content['limitations']
    if bool(content['limitations']) != (content['status'] == 'partial') or result['coverage'] != content['status']:
        raise ReviewError('content.coverage: inconsistent')
    sources = result['sources']
    if not isinstance(sources, list) or len(sources) > 400:
        raise ReviewError('sources.contract: invalid')
    indexed = {}
    for s in sources:
        if not isinstance(s, dict) or set(s) != {'source_id','snapshot','path','blob','start_line','end_line','text_hash'}:
            raise ReviewError('sources.fields: invalid')
        if (not isinstance(s['source_id'], str) or not re.fullmatch(r'source-[0-9a-f]{24}', s['source_id'])
                or s['source_id'] in indexed or s['snapshot'] not in ('before','after','target') or not path_ok(s['path'])):
            raise ReviewError('sources.identity: invalid')
        if any(type(s[k]) is not int for k in ('start_line','end_line')) or not 1 <= s['start_line'] <= s['end_line']:
            raise ReviewError('sources.range: invalid')
        if not isinstance(s['blob'], str) or not re.fullmatch('[0-9a-f]{40}', s['blob']) or not isinstance(s['text_hash'], str) or not re.fullmatch('[0-9a-f]{64}', s['text_hash']):
            raise ReviewError('sources.hash: invalid')
        indexed[s['source_id']] = s
    seen = set()
    for i, f in enumerate(content['findings']):
        if not isinstance(f, dict) or set(f) != {'severity','description','evidence','recommendation','anchor','references'} or f['severity'] not in ('low','medium','high','critical'):
            raise ReviewError(f'findings.{i}.contract: invalid')
        texts.extend(f[k] for k in ('description','evidence','recommendation'))
        if not isinstance(f['references'], list) or not 1 <= len(f['references']) <= 8:
            raise ReviewError(f'findings.{i}.references: required')
        for ref in f['references']:
            if not isinstance(ref, dict) or set(ref) != {'source_id','snapshot','path','blob','start_line','end_line'}:
                raise ReviewError(f'findings.{i}.reference.fields: invalid')
            if not isinstance(ref['source_id'], str):
                raise ReviewError(f'findings.{i}.reference: invalid source identifier')
            s = indexed.get(ref['source_id'])
            if (not s
                    or any(ref[k] != s[k] for k in ('snapshot','path','blob'))
                    or any(type(ref[k]) is not int for k in ('start_line','end_line'))
                    or not s['start_line'] <= ref['start_line'] <= ref['end_line'] <= s['end_line']):
                raise ReviewError(f'findings.{i}.reference: not in final context')
        a = f['anchor']
        if a is not None:
            if (not isinstance(a, dict)
                    or set(a) != {'file','side','start','end'}
                    or a['side'] not in ('LEFT','RIGHT')
                    or not path_ok(a['file'])
                    or any(type(a[k]) is not int for k in ('start','end'))
                    or not 1 <= a['start'] <= a['end'] <= a['start'] + 20):
                raise ReviewError(f'findings.{i}.anchor: invalid')
            # A well-formed unusable inline position is a body finding. Citations
            # remain mandatory and are independently validated above.
        key = digest(f)
        if key in seen:
            raise ReviewError('findings.duplicate')
        seen.add(key)
    if any(not isinstance(t, str) or not t.strip() or len(t) > 1200 for t in texts):
        raise ReviewError('content.text: invalid')
    if result['gate_outcome'] != ('success' if gate(result) else 'failure'):
        raise ReviewError('result.gate: inconsistent')
    from .diagnostics import sanitize
    if sanitize(result) != result:
        raise ReviewError('result.secret: unsafe output withheld')
    return result


def gate(result):
    # Coverage and failures remain independent of the configurable finding threshold.
    threshold = review_controls()['fail_severity']
    levels = ('low', 'medium', 'high', 'critical')
    return threshold == 'none' or not any(
        f.get('severity') in levels[levels.index(threshold):]
        for f in result['content']['findings'])


def verify_sources(data, result, repository_path):
    from .context import ContextReader
    reader = ContextReader(repository_path, data)
    for source in result['sources']:
        reader.verify_metadata(source)


def payload(data, result):
    validate_result(result, data)
    import base64
    record = base64.b64encode(json.dumps(result,separators=(',',':')).encode()).decode()
    if len(record.encode()) > 32768:
        raise ReviewError('cache.record: exceeds 32 KiB')
    body = 'Claude PR review\n\n' + safe_text(result['content']['summary'])
    body += '\nHead: ' + data['head'] + '\nGate: ' + result['gate_outcome']
    if result['coverage'] == 'partial':
        body += '\n\n**INCOMPLETE REVIEW** — success does not mean complete coverage.'
    for limitation in result['content']['limitations']:
        body += '\n' + safe_text(limitation)
    comments = []
    for f in result['content']['findings']:
        text = f['severity'].upper() + '\n' + safe_text(f['description']) + '\nEvidence:\n' + safe_text(f['evidence']) + '\nRecommendation:\n' + safe_text(f['recommendation'])
        for ref in f['references']:
            sha = data[{'before':'merge_base','after':'head','target':'base'}[ref['snapshot']]]
            text += f"\n[Source {ref['source_id']}](https://github.com/{data['repository']}/blob/{sha}/{quote(ref['path'],safe='/')}#L{ref['start_line']}-L{ref['end_line']})"
        a = f['anchor']
        inline = False
        if a is not None:
            positions=locations(data['diff']).get(a['file'],{}).get(a['side'],{})
            hunk_ids={positions.get(n) for n in range(a['start'],a['end']+1)}
            inline=None not in hunk_ids and len(hunk_ids)==1
        if not inline:
            body += '\n\n' + text
        else:
            a = f['anchor']
            c = dict(path=a['file'], side=a['side'], line=a['end'], body=text)
            if a['start'] != a['end']:
                c.update(start_line=a['start'],start_side=a['side'])
            comments.append(c)
    body += '\n<!-- claude-pr-review:' + digest(data) + ' -->\n<!-- result:' + record + ' -->'
    if len(body.encode()) > 60000:
        raise ReviewError('publication.body: too large')
    return dict(commit_id=data['head'],event='COMMENT',body=body,comments=comments)


@bounded(TIMERS['analysis'])
def analyze(data, github=None, recorded=None, client=None, repository_path='.', diagnostics=None, cache_only=False):
    from .context import ContextReader, TOOLS
    from .service import assert_current
    from .core import cached_result
    validate_input(data)
    def event(name, **fields):
        if diagnostics: diagnostics.event(name, **fields)
    if github:
        assert_current(github, data)
        reviews = github.reviews()
        old = cached_result(reviews, data)
        if old:
            event('cache.hit', origin_identity=old['identity'], origin_reviews=[dict(id=r.get('id'),url=r.get('html_url')) for r in reviews if '<!-- claude-pr-review:'+digest(data)+' -->' in (r.get('body') or '')], current_calls=0, current_cost=0)
            return old
    event('configuration', model=data['model'], mode=data['mode'], budget=review_budget(data['model']), controls=review_controls())
    event('cache.miss', reason='no matching review',cache_only=cache_only)
    if cache_only:
        raise ReviewError('cache.miss: cache-only mode prohibits model calls')
    started = time.monotonic()
    controls = review_controls()
    prompt = system_prompt()
    reader = ContextReader(repository_path, data, diagnostics=diagnostics)
    if data['diff'] and data['mode'] == 'context':
        reader.initial_context()
    # Request each displayed hunk separately; distant hunks must not disappear
    # inside an arbitrary first-to-last 200-line span. Reader limits still apply
    # and every denied/truncated range records an explicit coverage limitation.
    if data['mode'] == 'diff':
        old_paths = {new: old for old, new in re.findall(r'^diff --git a/(.+) b/(.+)$', data['diff'], re.M)}
        for path, sides in locations(data['diff']).items():
            for side, snapshot in [('RIGHT','after'),('LEFT','before')]:
                by_hunk = {}
                for line, hunk in sides[side].items():
                    by_hunk.setdefault(hunk, []).append(line)
                for lines in by_hunk.values():
                    end = max(lines)
                    for start in range(min(lines), end + 1, 200):
                        reader.execute('read_file', dict(snapshot=snapshot,
                            path=old_paths[path] if side == 'LEFT' else path,
                            start_line=start, end_line=min(end, start + 199)))
    usage = dict(input_tokens=0,output_tokens=0)
    calls = 0
    tool_ids = set()
    budget = review_budget(data['model'])
    reserved_cost = Decimal(0)
    input_rate = Decimal(budget['input_rate'])
    output_rate = Decimal(budget['output_rate'])
    ceiling = Decimal(budget['max_cost'] or ('.20' if data['mode'] == 'context' else '.05'))
    if recorded is None and data['diff']:
        if client is None:
            from anthropic import Anthropic
            key = os.environ.get('ANTHROPIC_API_KEY')
            if not key: raise ReviewError('provider.credential: missing ANTHROPIC_API_KEY')
            client = Anthropic(api_key=key, timeout=TIMERS['generation_http'], max_retries=0)
    def pack():
        return dict(diff=data['diff'], metadata=data['metadata'], sources=list(reader.sources), limitations=list(reader.limitations))
    def call(messages, final=False):
        nonlocal calls, reserved_cost
        if time.monotonic()-started > TIMERS['analysis'] - TIMERS['generation']:
            raise ReviewError('budget.time: final-call reserve exhausted')
        if github: assert_current(github,data)
        kwargs = dict(model=data['model'],system=prompt,messages=messages,max_tokens=controls['final_output'] if final else controls['research_output'])
        # Haiku 5.5 defaults to adaptive thinking; low effort leaves room for
        # useful output inside the bounded exploration/final output budgets.
        if data['model'] == DEFAULT_MODEL:
            kwargs['output_config'] = {'effort': 'low'}
        if final: kwargs.setdefault('output_config', {})['format'] = {'type':'json_schema','schema':schema()}
        else: kwargs['tools'] = TOOLS
        # Conservative UTF-8 byte bound: tokenization cannot use more tokens than
        # bytes plus framing. Count endpoint is deliberately not a paid model call.
        upper = len(json.dumps(kwargs,ensure_ascii=False).encode()) + 1024
        if upper > controls['input_tokens']:
            raise ReviewError('budget.input: conservative input bound exceeds configured token limit')
        # Reserve worst permitted final request before each exploration call.
        # Observed usage arrives too late to bound a request already sent; retain
        # conservative reservations instead of reclaiming estimated unused cost.
        cost = (upper * input_rate + kwargs['max_tokens'] * output_rate) / Decimal(1000000)
        final_reserve = (controls['input_tokens'] * input_rate + controls['final_output'] * output_rate) / Decimal(1000000) if not final else Decimal(0)
        if reserved_cost + cost + final_reserve > ceiling:
            raise ReviewError('budget.cost: request plus final reserve exceeds ceiling')
        if hasattr(client.messages, 'count_tokens'):
            count_args = {k:v for k,v in kwargs.items() if k in ('model','system','messages','tools','output_config')}
            count_args['timeout'] = TIMERS['token_count_http']  # Transport expiry precedes the 30 s watchdog.
            event('tokens.start', operation_id=f'count-{calls+1:02d}')
            if diagnostics: diagnostics.request(f'count-{calls+1:02d}', count_args)
            for attempt in range(MAX_ATTEMPTS):
                try:
                    with deadline(TIMERS['token_count']):
                        counted = client.messages.count_tokens(**count_args).input_tokens
                    break
                except Exception as error:
                    if attempt == MAX_ATTEMPTS - 1 or not transient(error):
                        if diagnostics: diagnostics.error(error,operation_id=f'count-{calls+1:02d}',error_code='provider.token_count')
                        raise ReviewError('provider.token_count: preflight failed; no model call') from None
                    event('transport.retry', provider='token_count', attempt=attempt + 2)
                    backoff(attempt)
            if diagnostics: diagnostics.response(f'count-{calls+1:02d}',dict(input_tokens=counted))
            event('tokens.end', operation_id=f'count-{calls+1:02d}', input_tokens=counted)
            if type(counted) is not int or counted > controls['input_tokens'] or counted < 0:
                raise ReviewError('budget.input: token preflight exceeds configured limit')
            # Provider framing can exceed the local serialization estimate.
            # Reserve the larger count before submitting a paid request.
            upper = max(upper, counted)
            cost = (upper * input_rate + kwargs['max_tokens'] * output_rate) / Decimal(1000000)
            if reserved_cost + cost + final_reserve > ceiling:
                raise ReviewError('budget.cost: counted request plus final reserve exceeds ceiling')
        if time.monotonic()-started > TIMERS['analysis'] - TIMERS['generation']:
            raise ReviewError('budget.time: preflight exhausted final-call reserve')
        if github: assert_current(github,data)
        reserved_cost += cost
        calls += 1
        op = f'call-{calls:02d}'
        event('sdk.start',operation_id=op,model=data['model'],timeout=TIMERS['generation'],max_tokens=kwargs['max_tokens'],prompt_hash=data['policies']['prompt'],schema_hash=data['policies']['schema'],input_upper_bound=upper)
        if diagnostics: diagnostics.context(reader.sources)
        if diagnostics: diagnostics.request(op, kwargs)
        call_started = time.monotonic()
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                # Keep each submitted attempt's conservative reservation even
                # including ambiguous transport failures; never reclaim estimated spend.
                if reserved_cost + cost + final_reserve > ceiling:
                    raise ReviewError('budget.cost: retry plus final reserve exceeds ceiling')
                if time.monotonic() - started > TIMERS['analysis'] - TIMERS['generation']:
                    raise ReviewError('budget.time: retry exhausted final-call reserve')
                if github: assert_current(github, data)
                reserved_cost += cost
            try:
                with deadline(TIMERS['generation']):
                    response = client.messages.create(**kwargs)
                break
            except Exception as error:
                if attempt == MAX_ATTEMPTS - 1 or not transient(error):
                    if diagnostics: diagnostics.error(error,operation_id=op,error_code='provider.call')
                    raise ReviewError('provider.call: failed after bounded retry policy') from None
                event('transport.retry', provider='generation', operation_id=op, attempt=attempt + 2, status=getattr(error, 'status_code', None), exception_class=type(error).__name__)
                backoff(attempt)
        try:
            blocks = [b.model_dump(exclude_none=True) if hasattr(b,'model_dump') else vars(b) for b in response.content]
            raw = dict(id=getattr(response,'id',None),request_id=getattr(response,'_request_id',None),model=response.model,stop_reason=response.stop_reason,content=blocks,usage=dict(input_tokens=response.usage.input_tokens,output_tokens=response.usage.output_tokens))
            valid_blocks = all(isinstance(b, dict) and b.get('type') in ('text','tool_use','thinking','redacted_thinking') for b in blocks)
        except (AttributeError, TypeError, ValueError):
            raise ReviewError('provider.response: malformed response') from None
        if not valid_blocks:
            raise ReviewError('provider.response: unsupported content block')
        if any(b['type'] == 'text' and not isinstance(b.get('text'), str) for b in blocks):
            raise ReviewError('provider.response: malformed text block')
        if any(type(v) is not int or v < 0 for v in raw['usage'].values()):
            raise ReviewError('provider.usage: invalid token usage')
        if raw['usage']['input_tokens'] > controls['input_tokens'] or raw['usage']['output_tokens'] > kwargs['max_tokens']:
            raise ReviewError('provider.usage: reported token usage exceeds request limits')
        if diagnostics: diagnostics.response(op,raw)
        event('sdk.end',operation_id=op,stop_reason=response.stop_reason,duration_ms=round((time.monotonic()-call_started)*1000),message_id=raw['id'],request_id=raw['request_id'],usage=raw['usage'],tool_calls=sum(b['type']=='tool_use' for b in blocks))
        if response.model != data['model']: raise ReviewError('provider.model: identity mismatch')
        if response.stop_reason == 'end_turn' and any(b['type'] == 'tool_use' for b in blocks):
            raise ReviewError('provider.tools: tool use without tool_use stop reason')
        for k in usage: usage[k] += raw['usage'][k]
        return response, blocks
    if recorded is not None:
        content = copy.deepcopy(recorded)
    elif not data['diff']:
        content = dict(status='complete',summary='No changes to review.',findings=[],limitations=[])
    else:
        messages = [{'role':'user','content':json.dumps(pack())}]
        if data['mode'] == 'context':
            if controls['research_calls'] == 0:
                reader.limitations.append('Exploration disabled by configuration.')
            for step in range(controls['research_calls']):
                # Leave room for a final call even when expanding history is too big.
                if len(json.dumps(messages).encode()) + len(json.dumps(TOOLS).encode()) + len(prompt.encode()) + 4096 > controls['input_tokens']:
                    reader.limitations.append('Exploration input budget reached.')
                    break
                response, blocks = call(messages)
                if response.stop_reason == 'end_turn':
                    break
                if response.stop_reason != 'tool_use':
                    raise ReviewError('provider.stop: incomplete exploration')
                uses = [b for b in blocks if b['type']=='tool_use']
                if (not uses or any(not {'type','id','name','input'} <= set(b) or set(b) - {'type','id','name','input','caller'}
                        or ('caller' in b and b['caller'] != {'type': 'direct'})
                        or not isinstance(b['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', b['id'])
                        or not isinstance(b['name'], str) or not isinstance(b['input'], dict) for b in uses)
                        or len({b['id'] for b in uses}) != len(uses)):
                    raise ReviewError('provider.tools: malformed tool use')
                if any(b['id'] in tool_ids for b in uses):
                    raise ReviewError('provider.tools: reused tool identifier')
                tool_ids.update(b['id'] for b in uses)
                messages.append(dict(role='assistant',content=blocks))
                replies = []
                for b in uses:
                    event('tool.start',operation_id=b['id'],parent_operation_id=f'call-{calls:02d}',tool_name=b['name'],arguments=b['input'])
                    if diagnostics: diagnostics.request(b['id'],dict(tool=b['name'],arguments=b['input']))
                    answer = reader.execute(b['name'],b['input'])
                    if diagnostics: diagnostics.response(b['id'],answer)
                    obtained = ([answer['source']] if 'source' in answer else answer.get('matches',[]))
                    event('tool.end',operation_id=b['id'],ok=answer.get('ok'),error=answer.get('error'),truncated=answer.get('truncated'),next_cursor=answer.get('next_cursor'),lines=sum(s['end_line']-s['start_line']+1 for s in obtained),bytes=sum(len(s['text'].encode()) for s in obtained),source_ids=[s['source_id'] for s in obtained],files=len(answer.get('files',[])),matches=len(answer.get('matches',[])))
                    replies.append(dict(type='tool_result',tool_use_id=b['id'],content=json.dumps(answer),is_error=not answer.get('ok',False)))
                messages.append(dict(role='user',content=replies))
                if step == controls['research_calls'] - 1:
                    reader.limitations.append(f"{controls['research_calls']} exploration calls reached; further exploration unavailable.")
        # Final context trimmed explicitly, never silently. Preserve evidence IDs.
        while len(json.dumps(pack()).encode()) + len(prompt.encode()) + len(json.dumps(schema()).encode()) + 2048 > controls['input_tokens'] and reader.sources:
            reader.sources.pop()
            if 'Final context input budget reached; some sources omitted.' not in reader.limitations:
                reader.limitations.append('Final context input budget reached; some sources omitted.')
        # Rebuild from bounded sources, omitting the exploration transcript so the
        # final request has one explicit evidence set for citation validation.
        response, blocks = call([dict(role='user',content=json.dumps(pack()))],final=True)
        if response.stop_reason != 'end_turn':
            raise ReviewError('provider.stop: no valid final response')
        try:
            content = json.loads(''.join(b['text'] for b in blocks if b['type']=='text'))
        except (ValueError,KeyError):
            raise ReviewError('provider.json: malformed final JSON') from None
    if isinstance(content,dict) and isinstance(content.get('limitations'),list):
        for limitation in reader.limitations:
            if limitation not in content['limitations']:
                content['limitations'].append(limitation)
        if content['limitations']:
            content['status']='partial'
    if diagnostics: diagnostics.context(reader.sources)
    result = dict(version=2,identity=digest(data),model=data['model'],duration_ms=round((time.monotonic()-started)*1000),content=content,usage=usage,live=recorded is None and bool(calls),sources=[source_metadata(s) for s in reader.sources],calls=calls,coverage=content.get('status') if isinstance(content,dict) else None)
    result['gate_outcome']='success' if isinstance(content,dict) and isinstance(content.get('findings'),list) and all(isinstance(f,dict) for f in content['findings']) and gate(result) else 'failure'
    event('validation.start',contract='review.result')
    validate_result(result,data)
    event('validation.end',contract='review.result',outcome='valid')
    # Only metadata cited by findings belongs in the durable cache record.
    cited={r['source_id'] for f in content['findings'] for r in f['references']}
    result['sources']=[s for s in result['sources'] if s['source_id'] in cited]
    validate_result(result,data)
    payload(data,result)  # Bound the durable cache before publication.
    return result
