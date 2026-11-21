"""544: a Codex caller's create/send/resume card names the recipient, never repeats the message; the document is unchanged."""
from contextlib import nullcontext
import copy
import json
from types import SimpleNamespace

import graftling
import pytest
import yaml

from graphtraj.interfaces import mcp

MESSAGE = '## Second message\n\n1. Answer in **Markdown**.\n2. Use `no tool`.\n'
DOCUMENT = {'action': 'send', 'agent': 'agent-7f3a', 'result': {
    'name': 'reader', 'resumed': True, 'execution_id': 'e' * 32,
    'last_result': {'id': 'execution-1', 'outcome': 'completed', 'last_message': '## Reply\n\n- one\n- two'}}}


def call(monkeypatch: pytest.MonkeyPatch, document: dict, meta: dict | None, *, failed: bool = False,
         feature: str = 'send', given: dict | None = None) -> dict:
    """Run the real MCP tool-call path with the shared agents operation replaced."""
    monkeypatch.setattr(mcp, '_caller_notices', lambda params: nullcontext(None))
    monkeypatch.setattr(graftling, 'handle_request',
                        lambda arguments, dispatch: SimpleNamespace(document=copy.deepcopy(document), failed=failed))
    params = {'name': 'agents', 'arguments': {
        'action': 'execute', 'feature': feature,
        'arguments': given if given is not None else {'agent': 'reader', 'message': MESSAGE}}}
    if meta is not None:
        params['_meta'] = meta
    return mcp._tool_call_response(1, params)['result']


def same_document(result: dict, document: dict) -> bool:
    return json.dumps(result['structuredContent'], sort_keys=False) == json.dumps(document, sort_keys=False)


def test_codex_send_card_is_only_the_recipient_even_with_an_earlier_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """last_result is the reply to an earlier message; under this send it would read as a reply to it."""
    result = call(monkeypatch, DOCUMENT, {'threadId': 'codex-main'})
    assert result['content'] == [{'type': 'text', 'text': '→ reader [agent-7f3a]'}]
    assert same_document(result, DOCUMENT) and result['isError'] is False


@pytest.mark.parametrize('feature,key', [('create', 'instruction'), ('resume', 'instruction'), ('send', 'message')])
def test_codex_card_never_repeats_the_message(monkeypatch: pytest.MonkeyPatch, feature: str, key: str) -> None:
    document = {'action': feature, 'agent': 'agent-1', 'result': {'name': 'n544'}}
    result = call(monkeypatch, document, {'threadId': 'codex-main'}, feature=feature,
                  given={key: 'line one\nline **two**'})
    assert result['content'][0]['text'] == '→ n544 [agent-1]'
    assert same_document(result, document)


@pytest.mark.parametrize('meta', [None, {'claudecode/toolUseId': 'toolu_1'}, {}])
def test_non_codex_callers_keep_the_yaml_content(monkeypatch: pytest.MonkeyPatch, meta: dict | None) -> None:
    result = call(monkeypatch, DOCUMENT, meta)
    assert result['content'][0]['text'] == yaml.safe_dump(DOCUMENT, sort_keys=False, allow_unicode=True)
    assert same_document(result, DOCUMENT)


@pytest.mark.parametrize('case', ['failed', 'wait-with-reply', 'status', 'describe', 'not-resumed'])
def test_codex_errors_and_other_features_keep_the_yaml_content(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    document, feature, failed = DOCUMENT, 'send', False
    if case == 'failed':
        document, failed = {'error': {'code': 'not-found', 'message': 'no such agent'}}, True
    elif case == 'wait-with-reply':
        document, feature = {**DOCUMENT, 'action': 'wait'}, 'wait'
    elif case == 'status':
        document, feature = {'action': 'status', 'agent': 'agent-1', 'result': {'name': 'n544'}}, 'status'
    elif case == 'describe':
        document = {'feature': 'send', 'input_schema': {}}
    else:
        document, feature = {'action': 'resume', 'agent': 'agent-1', 'result': {'name': 'n544', 'resumed': False}}, 'resume'
    result = call(monkeypatch, document, {'threadId': 'codex-main'}, failed=failed, feature=feature,
                  given={'agent': 'n544', 'instruction': 'go', 'message': 'go'})
    assert result['content'][0]['text'] == yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    assert same_document(result, document) and result['isError'] is failed
