"""The review plugin (386): config, both transports, the check at create, the Codex adapter.

HTTP runs through urllib's real opener and redirect handling with only the
socket replaced, because local port binding may be off. The local-process
transport runs real small scripts. Codex runs the controlled stdio peer. Keys
are fake.
"""

from __future__ import annotations

from dataclasses import replace
from email.message import Message
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.response

import pytest

import agent_swarm
from agent_swarm import AgentControl, AgentsError, Caller, read_connections, write_config
from agent_swarm import review
from agent_swarm.codex import driver as codex_driver
from agent_swarm.codex.app_server import CodexAppServer
from agent_swarm.codex.driver import CodexDriver
from agent_swarm.codex.managed_session import CodexManagedExecution
from agent_swarm.control import _request_message
from agent_swarm.review import REVIEW_TIMEOUT_DEFAULT, build_request, check_reviewer, record_decision, review_call

MAIN = Caller('test-host', None)
KEY = 'fake-review-key-0123456789'
URL = 'http://127.0.0.1:9/v1'
REQUEST = build_request('codex', 'item/commandExecution/requestApproval',
                        {'command': 'printf the-planned-action-text'}, cwd='/work',
                        instruction='Build the assigned feature in the work directory.')
ALLOW = json.dumps({'decision': 'allow', 'reason': 'Inside the task.'})


def call(control, caller=MAIN, **request):
    """Invoke the bound agents function and return its document and failure flag."""
    result = agent_swarm.bind(control, caller)(request)
    return result.document, result.failed


# -- HTTP through urllib's real stack ---------------------------------------

class Endpoint(urllib.request.HTTPHandler):
    """Answer every call with one status and body instead of opening a socket."""

    def __init__(self, status=200, body=b'', headers=None, delay=0, error=None):
        """Keep the canned answer and the calls received."""
        super().__init__()
        self.status, self.body, self.headers, self.delay, self.error = status, body, headers or {}, delay, error
        self.calls = []

    def http_open(self, req):
        """Record the request and return the canned response."""
        self.calls.append(req)
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        headers = Message()
        for name, value in self.headers.items():
            headers[name] = value
        response = urllib.response.addinfourl(io.BytesIO(self.body), headers, req.full_url, self.status)
        response.msg = 'canned'
        return response


def completion(content, finish_reason='stop'):
    """Return a chat completions body holding one message."""
    return json.dumps({'choices': [{'finish_reason': finish_reason,
                                    'message': {'role': 'assistant', 'content': content}}]}).encode()


@pytest.fixture
def endpoint(monkeypatch):
    """Route review.py's opener to a settable fake endpoint."""
    served = Endpoint(body=completion(ALLOW))
    monkeypatch.setattr(review, 'build_opener',
                        lambda *handlers: urllib.request.build_opener(*handlers, served))
    monkeypatch.setenv('REVIEW_KEY', KEY)
    return served


def http_reviewer(**fields):
    """Return an HTTP reviewer mapping, as the config reader gives it."""
    return {'name': 'http-review', 'base_url': URL, 'model': 'review-model', **fields}


def test_http_call_is_one_plain_post_with_the_shared_policy(endpoint):
    """One POST, stream false, no response_format by default; policy as system, request as user."""
    decision = review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)
    assert decision == {'decision': 'allow', 'reason': 'Inside the task.'}
    [sent] = endpoint.calls
    assert sent.full_url == URL + '/chat/completions' and sent.get_method() == 'POST'
    assert sent.get_header('Authorization') == 'Bearer ' + KEY
    body = json.loads(sent.data)
    assert body['model'] == 'review-model' and body['stream'] is False and 'response_format' not in body
    [system, user] = body['messages']
    assert system == {'role': 'system', 'content': review.review_policy()}
    assert '{"decision":"allow|deny|escalate","reason":"..."}' in system['content']
    assert 'uncertain' in system['content'] and 'escalate' in system['content']
    assert json.loads(user['content']) == REQUEST


def test_http_key_and_json_mode_only_when_configured(endpoint):
    """A local server gets no Authorization header; json_mode turns on response_format."""
    review_call(http_reviewer(json_mode=True), REQUEST)
    [sent] = endpoint.calls
    assert sent.get_header('Authorization') is None
    assert json.loads(sent.data)['response_format'] == {'type': 'json_object'}


@pytest.mark.parametrize('document', [
    {'decision': 'deny', 'reason': 'Outside the task.'},
    {'decision': 'escalate', 'reason': 'Needs the parent.'},
])
def test_http_other_decisions_pass_through(endpoint, document):
    """deny and escalate are the reviewer's own answers, not failures."""
    endpoint.body = completion(json.dumps(document))
    assert review_call(http_reviewer(), REQUEST) == document


MISSING_SESSION = json.dumps({'error': {'code': 'MissingSessionID', 'type': 'invalid_request',
                                        'message': 'The request needs a session id.'}}).encode()


@pytest.mark.parametrize(('answer', 'expected'), [
    ({'status': 400, 'body': MISSING_SESSION}, ['HTTP 400', 'MissingSessionID', 'invalid_request']),
    ({'status': 500, 'body': b'upstream exploded'}, ['HTTP 500', 'upstream exploded']),
    ({'status': 302, 'headers': {'Location': 'https://elsewhere.example/v1'}}, ['HTTP 302']),
    ({'body': b'not json'}, ['not a chat completion']),
    ({'body': b'{"choices": []}'}, ['not a chat completion']),
    ({'body': json.dumps({'error': {'code': 'quota', 'message': 'Out of quota.'}}).encode()},
     ['not a chat completion', 'quota', 'Out of quota.']),
    ({'body': completion(ALLOW, 'length')}, ['finish_reason is length']),
    ({'body': completion(None)}, ['not text']),
    ({'body': json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
        'content': {'decision': 'allow', 'reason': 'Not text.'}}}]}).encode()}, ['not text']),
    ({'body': completion('')}, ['not one JSON object']),
    ({'body': completion('Sure, go ahead: ' + ALLOW)}, ['not one JSON object']),
    ({'body': completion('```json\n' + ALLOW + '\n```')}, ['not one JSON object']),
    ({'body': completion('[' + ALLOW + ']')}, ['not a JSON object']),
    ({'body': completion(json.dumps({'decision': 'allow', 'reason': 'x', 'category': 'safe'}))},
     ['exactly decision and reason']),
    ({'body': completion(json.dumps({'decision': 'ALLOW', 'reason': 'x'}))}, ['decision must be']),
    ({'body': completion(json.dumps({'decision': 'allow', 'reason': ' '}))}, ['reason must be']),
    ({'body': completion('{"decision":"deny","decision":"allow","reason":"x"}')}, ['repeated field']),
    ({'body': b' ' * (review.RESPONSE_LIMIT + 1)}, ['larger than 1 MiB']),
    ({'error': urllib.error.URLError(ConnectionRefusedError(61, 'Connection refused'))}, ['Connection refused']),
    ({'error': OSError('stack gone: ' + KEY)}, ['OSError']),
])
def test_every_http_failure_escalates_with_its_reason(endpoint, answer, expected):
    """A failed review never allows, shows its cause, and holds no key."""
    endpoint.body = b''
    for name, value in answer.items():
        setattr(endpoint, name, value)
    decision = review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)
    assert decision['decision'] == 'escalate' and decision['reason'].startswith('Failed review: ')
    for text in expected:
        assert text in decision['reason']
    assert KEY not in decision['reason'] and len(endpoint.calls) == 1


def test_redirect_is_not_followed(endpoint):
    """The key and request stay on the configured host."""
    endpoint.status, endpoint.headers = 302, {'Location': 'http://127.0.0.1:9/elsewhere'}
    assert review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)['decision'] == 'escalate'
    assert [sent.full_url for sent in endpoint.calls] == [URL + '/chat/completions']


def test_http_timeout_bounds_a_stalled_exchange(endpoint):
    """A stalled exchange ends the review at the reviewer's timeout."""
    endpoint.delay = 5
    started = time.monotonic()
    decision = review_call(http_reviewer(timeout_seconds=0.05), REQUEST)
    assert decision['decision'] == 'escalate' and 'no answer within 0.05 seconds' in decision['reason']
    assert time.monotonic() - started < 2


def test_missing_key_variable_is_named_without_a_call(endpoint, monkeypatch):
    """Only the variable's name appears; no unauthenticated call goes out."""
    monkeypatch.delenv('REVIEW_KEY')
    decision = review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)
    assert decision['decision'] == 'escalate' and 'REVIEW_KEY is unset or empty' in decision['reason']
    assert endpoint.calls == []
    monkeypatch.setenv('REVIEW_KEY', '')
    assert 'unset or empty' in review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)['reason']


def test_provider_text_loses_credentials_and_request_echoes(endpoint):
    """A provider's message keeps its diagnosis without the key, a token or the request."""
    endpoint.status = 401
    endpoint.body = json.dumps({'error': {
        'code': 'bad_auth', 'message': f'Key {KEY} rejected, token Bearer abc.def-123 at https://u:p@host/x',
    }}).encode()
    reason = review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)['reason']
    assert 'HTTP 401' in reason and 'bad_auth' in reason and 'rejected' in reason
    assert KEY not in reason and 'abc.def-123' not in reason and 'u:p@' not in reason

    endpoint.body = json.dumps({'error': {
        'code': 'too_long', 'message': 'Rejected: printf the-planned-action-text is too long.',
    }}).encode()
    reason = review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST)['reason']
    assert 'too_long' in reason and 'planned-action' not in reason and 'Rejected' not in reason


def test_a_key_in_an_allowed_reason_is_removed(endpoint):
    """Even a valid decision's reason never carries the key to the parent or the record."""
    endpoint.body = completion(json.dumps({'decision': 'deny', 'reason': f'It sends {KEY} out.'}))
    assert review_call(http_reviewer(api_key_env='REVIEW_KEY'), REQUEST) == {
        'decision': 'deny', 'reason': 'It sends [redacted] out.'}


def test_loopback_reviewer_ignores_environment_proxies(endpoint, monkeypatch):
    """A local reviewer's key never leaves through a configured proxy; a remote one may use it."""
    opened = []
    real = review.build_opener

    def recording(*handlers):
        """Record the handlers review.py chose."""
        opened.append(handlers)
        return real(*handlers)

    monkeypatch.setattr(review, 'build_opener', recording)
    review_call(http_reviewer(), REQUEST)
    assert any(isinstance(item, urllib.request.ProxyHandler) and item.proxies == {} for item in opened[0])
    endpoint.error = urllib.error.URLError('no route')
    review_call(http_reviewer(base_url='http://reviewer.example/v1'), REQUEST)
    assert not any(isinstance(item, urllib.request.ProxyHandler) for item in opened[1])


# -- Local process ----------------------------------------------------------

def process_reviewer(tmp_path, source, **fields):
    """Return a reviewer running one small Python script."""
    script = tmp_path / f'reviewer-{len(list(tmp_path.glob("reviewer-*")))}.py'
    script.write_text(source)
    return {'name': 'own-script', 'command': [sys.executable, str(script)], **fields}


def test_process_gets_policy_and_request_and_answers_on_stdout(tmp_path):
    """stdin is {policy, request}; a trailing newline on stdout is still one document."""
    seen = tmp_path / 'stdin.json'
    reviewer = process_reviewer(tmp_path, f'import sys; open({str(seen)!r}, "w").write(sys.stdin.read()); '
                                          f'print({ALLOW!r})')
    assert review_call(reviewer, REQUEST)['decision'] == 'allow'
    assert json.loads(seen.read_text()) == {'policy': review.review_policy(), 'request': REQUEST}


@pytest.mark.parametrize(('source', 'expected'), [
    ('import sys; sys.stderr.write("model not loaded " + "fake-review-key-0123456789"); sys.exit(3)',
     ['status 3', 'model not loaded']),
    ('raise SystemExit(4)', ['status 4']),
    ('print()', ['not one JSON object']),
    ('print("```json"); print(\'{"decision":"allow","reason":"x"}\'); print("```")', ['not one JSON object']),
    ('print(\'{"decision":"allow","reason":"x","extra":1}\')', ['exactly decision and reason']),
])
def test_every_process_failure_escalates(tmp_path, monkeypatch, source, expected):
    """A non-zero exit or a bad document is a failed review, scrubbed of the key."""
    monkeypatch.setenv('REVIEW_KEY', KEY)
    reviewer = process_reviewer(tmp_path, source)
    decision = review_call({**reviewer, 'api_key_env': 'REVIEW_KEY'}, REQUEST)
    assert decision['decision'] == 'escalate' and decision['reason'].startswith('Failed review: ')
    for text in expected:
        assert text in decision['reason']
    assert KEY not in decision['reason']


def test_process_timeout_kills_its_session(tmp_path):
    """A child holding stdout open does not outlive the bound."""
    pidfile = tmp_path / 'child.pid'
    reviewer = process_reviewer(tmp_path, (
        'import subprocess, sys\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f'open({str(pidfile)!r}, "w").write(str(child.pid))\n'
        'child.wait()\n'), timeout_seconds=1)
    started = time.monotonic()
    decision = review_call(reviewer, REQUEST)
    assert decision['decision'] == 'escalate' and 'no answer within 1 seconds' in decision['reason']
    assert time.monotonic() - started < 10
    child = int(pidfile.read_text())
    for _ in range(100):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail('the reviewer child outlived the timeout')


def test_process_that_cannot_start_is_a_failed_review(tmp_path):
    """A missing executable names the command, not a traceback."""
    decision = review_call({'name': 'gone', 'command': [str(tmp_path / 'gone')]}, REQUEST)
    assert decision['decision'] == 'escalate' and str(tmp_path / 'gone') in decision['reason']


def test_process_holds_no_way_to_control_agents(tmp_path, monkeypatch):
    """The owner connection stays out of the reviewer's environment."""
    monkeypatch.setenv('AGENT_SWARM_CONNECTION', 'owner-address')
    reviewer = process_reviewer(tmp_path, (
        'import json, os\n'
        'held = "AGENT_SWARM_CONNECTION" in os.environ\n'
        'print(json.dumps({"decision": "deny" if held else "allow", "reason": "Checked."}))\n'))
    assert review_call(reviewer, REQUEST)['decision'] == 'allow'


def test_malformed_reviewer_never_raises():
    """A broken reviewer mapping is a failed review too."""
    assert review_call({}, REQUEST)['decision'] == 'escalate'
    assert review_call({'name': 'x', 'command': None}, REQUEST)['decision'] == 'escalate'


# -- Request, record, policy ------------------------------------------------

def test_request_shape_and_instruction_bound():
    """The request is versioned, and a long instruction is bounded with a marker."""
    request = build_request('codex', 'tool', {'a': 1}, cwd='/w', instruction='x' * 25_000, native={'b': 2})
    assert set(request) == {'version', 'runtime', 'tool', 'input', 'cwd', 'instruction', 'native'}
    assert request['version'] == 1 and request['native'] == {'b': 2}
    assert request['instruction'].startswith('x' * 20_000)
    assert request['instruction'].endswith('<truncated omitted_chars="5000" />')
    assert build_request('codex', 'tool', {}, cwd='/w', instruction='short')['native'] is None
    assert REVIEW_TIMEOUT_DEFAULT == 20


def test_record_keeps_the_decision_without_input_or_credentials(tmp_path, monkeypatch):
    """One JSON line per decision; a credential in a reason is removed."""
    monkeypatch.setenv('REVIEW_API_KEY', KEY)
    record_decision(tmp_path / 'new', 'codex', 'tool-a', 'req-1', {'decision': 'allow', 'reason': 'Fine.'})
    record_decision(tmp_path / 'new', 'codex', 'tool-b', None, {'decision': 'deny', 'reason': f'Uses {KEY}.'})
    first, second = map(json.loads, (tmp_path / 'new' / 'review.jsonl').read_text().splitlines())
    assert set(first) == {'at', 'runtime', 'tool', 'request_id', 'decision', 'reason'}
    assert (first['tool'], first['request_id'], first['decision']) == ('tool-a', 'req-1', 'allow')
    assert second['request_id'] is None and KEY not in second['reason']


def test_policy_is_a_copy_and_the_plugin_imports_no_graphtraj():
    """The policy files equal their source, unmodified, and agents imports nothing from GraphTraj."""
    source = Path(agent_swarm.__file__).parent
    copied = source / 'review_policy'
    original = source.parent / 'graphtraj' / 'runtimes' / 'codex' / 'policy'
    for name in ('policy.md', 'policy_template.md', 'LICENSE', 'NOTICE', 'SOURCE.md'):
        assert (copied / name).read_bytes() == (original / name).read_bytes()
    assert list(copied.glob('*.py')) == []
    for path in (source / 'review.py', source / 'codex' / 'driver.py', source / 'codex' / 'managed_session.py'):
        assert not re.search(r'^\s*(import|from)\s+graphtraj', path.read_text(), re.MULTILINE)
    assert 'review_policy/*' in (source / 'pyproject.toml').read_text()


# -- Config -----------------------------------------------------------------

def configured(root, text):
    """Write config.yml and return the root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text(text)
    return root


def test_reviewers_are_read_in_both_forms(tmp_path):
    """Entries are the file's fields plus name; a connection names one, in any file order."""
    root = configured(tmp_path, '''\
connections:
  work:
    runtime: codex
    review: local
reviewers:
  local:
    base_url: http://localhost:1234/v1
    model: tuned-model
    api_key_env: LOCAL_KEY
    json_mode: true
    timeout_seconds: 7.5
  hosted:
    base_url: https://reviewer.example/v1
    api_key_env: HOSTED_KEY
    model: hosted-model
  plain:
    base_url: http://reviewer.lan/v1
    model: no-key
  own:
    command: [/abs/reviewer, --strict]
    timeout_seconds: 30
''')
    declared = read_connections(root)
    assert declared['connections']['work']['review'] == 'local'
    assert declared['reviewers']['local'] == {
        'name': 'local', 'base_url': 'http://localhost:1234/v1', 'model': 'tuned-model',
        'api_key_env': 'LOCAL_KEY', 'json_mode': True, 'timeout_seconds': 7.5}
    assert declared['reviewers']['own'] == {'name': 'own', 'command': ['/abs/reviewer', '--strict'],
                                            'timeout_seconds': 30}
    assert sorted(declared['reviewers']) == ['hosted', 'local', 'own', 'plain']


def test_a_file_without_reviewers_reads_as_before(tmp_path):
    """read_connections keeps its shape, and write_config keeps the new section."""
    root = configured(tmp_path, 'connections:\n  work:\n    runtime: codex\n')
    assert set(read_connections(root)) == {'connections', 'presets'}
    root = configured(tmp_path, 'reviewers:\n  r:\n    command: [/abs/x]\n')
    write_config(root, save_normalized_sessions=True)
    assert read_connections(root)['reviewers']['r']['command'] == ['/abs/x']


@pytest.mark.parametrize(('entry', 'field'), [
    ('{command: [/x], base_url: "https://h/v1", model: m}', 'reviewers.r: give either'),
    ('{command: [/x], json_mode: true}', 'reviewers.r: give either'),
    ('{command: [/x], api_key_env: KEY}', 'reviewers.r: give either'),
    ('{}', 'reviewers.r: give either'),
    ('{base_url: "https://h/v1"}', 'reviewers.r: give either'),
    ('{model: m}', 'reviewers.r: give either'),
    ('{timeout_seconds: 5}', 'reviewers.r: give either'),
    ('{command: /x}', 'reviewers.r.command: expected'),
    ('{command: []}', 'reviewers.r.command: expected'),
    ('{command: [/x, 1]}', 'reviewers.r.command: expected'),
    ('{command: [/x], preset: p}', 'reviewers.r.preset: unknown field'),
    ('{command: [/x], timeout_seconds: 0}', 'reviewers.r.timeout_seconds: expected'),
    ('{command: [/x], timeout_seconds: -1}', 'reviewers.r.timeout_seconds: expected'),
    ('{command: [/x], timeout_seconds: .inf}', 'reviewers.r.timeout_seconds: expected'),
    ('{command: [/x], timeout_seconds: .nan}', 'reviewers.r.timeout_seconds: expected'),
    ('{command: [/x], timeout_seconds: true}', 'reviewers.r.timeout_seconds: expected'),
    ('{command: [/x], timeout_seconds: "20"}', 'reviewers.r.timeout_seconds: expected'),
    ('{base_url: "https://h/v1", model: m, json_mode: yes}', 'reviewers.r.json_mode: expected'),
    ('{base_url: "https://h/v1", model: m, json_mode: 1}', 'reviewers.r.json_mode: expected'),
    ('{base_url: "ftp://h/v1", model: m}', 'reviewers.r.base_url: expected'),
    ('{base_url: "https://u:p@h/v1", model: m}', 'reviewers.r.base_url: expected'),
    ('{base_url: "https://h/v1?key=x", model: m}', 'reviewers.r.base_url: expected'),
    ('{base_url: "https://h/v1", model: m, api_key_env: sk-real-key}', 'reviewers.r.api_key_env: expected'),
    ('{base_url: "http://reviewer.example/v1", model: m, api_key_env: KEY}', 'reviewers.r.api_key_env: a key'),
    ('{base_url: "http://10.0.0.5/v1", model: m, api_key_env: KEY}', 'reviewers.r.api_key_env: a key'),
])
def test_invalid_reviewer_fails_with_file_line_and_field(tmp_path, entry, field):
    """The reader is strict and names the file, the line and the field."""
    root = configured(tmp_path, f'save_normalized_sessions: false\nreviewers:\n  r: {entry}\n')
    with pytest.raises(ValueError) as caught:
        read_connections(root)
    assert re.fullmatch(rf'{re.escape(str(root / "config.yml"))}:3: {re.escape(field)}.*', str(caught.value))


@pytest.mark.parametrize('base_url', ['http://127.0.0.1:1/v1', 'http://localhost:1/v1', 'http://[::1]:1/v1'])
def test_a_key_may_go_over_plain_http_only_on_this_machine(tmp_path, base_url):
    """Loopback is the one plain-http destination for a key."""
    root = configured(tmp_path, f'reviewers:\n  r: {{base_url: "{base_url}", model: m, api_key_env: KEY}}\n')
    assert read_connections(root)['reviewers']['r']['api_key_env'] == 'KEY'


def test_connection_review_must_name_a_declared_reviewer(tmp_path):
    """An undeclared name or a wrong shape fails at its own line; no default reviewer exists."""
    root = configured(tmp_path, 'connections:\n  work:\n    runtime: codex\n    review: missing\n')
    with pytest.raises(ValueError, match=r'config\.yml:4: connections\.work\.review: no reviewer'):
        read_connections(root)
    root = configured(tmp_path, 'connections:\n  work:\n    runtime: codex\n    review: [a]\n')
    with pytest.raises(ValueError, match=r'config\.yml:4: connections\.work\.review: expected'):
        read_connections(root)
    control = AgentControl(root, {'codex': PlainDriver()})
    document, failed = call(control, action='create', runtime='codex', instruction='x')
    assert failed and document['error']['code'] == 'invalid-config'
    with pytest.raises(AgentsError) as caught:
        control.require_connections()
    assert caught.value.code == 'invalid-config'


# -- The check at create ----------------------------------------------------

class PlainDriver:
    """A driver that records what it receives and finishes at once."""

    supports_review = True

    def __init__(self):
        """Start with nothing prepared."""
        self.prepared = []

    def prepare(self, runtime, caller, *, configuration=None, selection=None, workspace=None):
        """Record the selection and retain nothing."""
        self.prepared.append(selection)
        return {}

    def start(self, run):
        """Finish the execution immediately."""
        run.events.session('native-session')
        run.events.process(runtime_pid=os.getpid())
        run.events.finished('completed', last_message='done')

    def interrupt(self, run):
        """Nothing to stop."""
        return False


class UnreviewedDriver(PlainDriver):
    """A Runtime whose adapter does not exist yet."""

    supports_review = False


def review_config(reviewer):
    """Return a config.yml whose only Codex connection names ``reviewer``."""
    return (f'connections:\n  work:\n    runtime: codex\n    review: chosen\n'
            f'reviewers:\n  chosen: {json.dumps({k: v for k, v in reviewer.items() if k != "name"})}\n')


def probing(tmp_path, source='print({allow!r})'):
    """Return a reviewer counting its calls in a file, and that file."""
    calls = tmp_path / 'review-calls'
    return process_reviewer(tmp_path, (
        'import json, sys\n'
        f'request = json.load(sys.stdin)["request"]\n'
        f'open({str(calls)!r}, "a").write(request["tool"] + "\\n")\n'
        + source.format(allow=ALLOW))), calls


def agent_files(root):
    """Return the Agent records under a data root."""
    return list((root / 'control' / 'agents').glob('*.json'))


def test_check_passes_on_any_well_formed_decision(tmp_path):
    """The check tests the connection and the format, not the verdict."""
    for decision in ('allow', 'deny', 'escalate'):
        reviewer = process_reviewer(tmp_path, f'print(\'{{"decision":"{decision}","reason":"Probe."}}\')')
        check_reviewer(reviewer)


def test_check_uses_a_real_review_request(tmp_path):
    """The probe has the real shape, with a fixed harmless tool."""
    seen = tmp_path / 'stdin.json'
    check_reviewer(process_reviewer(tmp_path, f'import sys; open({str(seen)!r}, "w").write(sys.stdin.read()); '
                                              f'print({ALLOW!r})'))
    document = json.loads(seen.read_text())
    assert document['policy'] == review.review_policy()
    assert set(document['request']) == set(REQUEST) and document['request']['tool'] == 'agents/connectivity-check'


def test_check_raises_review_unavailable_with_the_reason(endpoint, tmp_path):
    """The 400 MissingSessionID endpoint fails here, not on every later tool call."""
    endpoint.status, endpoint.body = 400, MISSING_SESSION
    with pytest.raises(AgentsError) as caught:
        check_reviewer(http_reviewer())
    assert caught.value.code == 'review-unavailable'
    assert 'http-review' in caught.value.message
    assert 'HTTP 400' in caught.value.message and 'MissingSessionID' in caught.value.message
    with pytest.raises(AgentsError, match='exited with status 5') as caught:
        check_reviewer(process_reviewer(tmp_path, 'raise SystemExit(5)'))
    assert caught.value.code == 'review-unavailable'
    with pytest.raises(AgentsError, match='exactly decision and reason') as caught:
        check_reviewer(process_reviewer(tmp_path, 'print(\'{"decision":"allow","reason":"x","y":1}\')'))
    assert caught.value.code == 'review-unavailable'


def test_unreachable_reviewer_refuses_create_before_any_record(tmp_path):
    """The parent hears the reason at once, and no Agent or native work exists."""
    root = configured(tmp_path / 'data', review_config(process_reviewer(tmp_path, 'raise SystemExit(7)')))
    driver = PlainDriver()
    document, failed = call(AgentControl(root, {'codex': driver}), action='create', runtime='codex', instruction='x')
    assert failed and document['error']['code'] == 'review-unavailable'
    assert 'exited with status 7' in document['error']['message']
    assert driver.prepared == [] and agent_files(root) == []


def test_driver_without_the_plugin_is_refused_and_the_reviewer_not_asked(tmp_path):
    """Pi and DSH stay refused until 387; nothing silently runs unreviewed."""
    reviewer, calls = probing(tmp_path)
    root = configured(tmp_path / 'data', review_config(reviewer))
    driver = UnreviewedDriver()
    document, failed = call(AgentControl(root, {'codex': driver}), action='create', runtime='codex', instruction='x')
    assert failed and document['error']['code'] == 'invalid-config'
    assert "review plugin is not available for Runtime 'codex'" in document['error']['message']
    assert not calls.exists() and driver.prepared == [] and agent_files(root) == []


def test_create_checks_once_and_send_does_not_repeat(tmp_path):
    """The reviewer reaches the driver and the document; later executions skip the check."""
    reviewer, calls = probing(tmp_path)
    root = configured(tmp_path / 'data', review_config(reviewer))
    driver = PlainDriver()
    control = AgentControl(root, {'codex': driver})
    document, failed = call(control, action='create', runtime='codex', instruction='x')
    assert not failed
    assert document['result']['review'] == 'chosen' and document['result']['connection'] == 'work'
    assert driver.prepared[0]['review']['command'] == reviewer['command']
    assert driver.prepared[0]['review']['name'] == 'chosen'
    agent = document['agent']
    _, failed = call(control, action='send', agent=agent, message='again')
    assert not failed
    _, failed = call(control, action='resume', agent=agent, message='and again')
    assert not failed
    assert calls.read_text() == 'agents/connectivity-check\n'
    assert call(control, action='status', agent=agent)[0]['result']['review'] == 'chosen'


def test_connection_without_review_keeps_native_approval(tmp_path):
    """No reviewer is declared for this connection, so none runs."""
    reviewer, calls = probing(tmp_path)
    fields = json.dumps({k: v for k, v in reviewer.items() if k != 'name'})
    root = configured(tmp_path / 'data', f'connections:\n  work:\n    runtime: codex\nreviewers:\n  idle: {fields}\n')
    driver = PlainDriver()
    document, failed = call(AgentControl(root, {'codex': driver}), action='create', runtime='codex', instruction='x')
    assert not failed and document['result']['review'] is None and driver.prepared[0]['review'] is None
    assert not calls.exists()


# -- Codex adapter ----------------------------------------------------------

COMMAND = 'item/commandExecution/requestApproval'


@pytest.fixture
def native(tmp_path, monkeypatch):
    """Run the controlled app-server peer as an installed, logged-in Codex."""
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + Path(__file__).with_name('codex_stdio_peer.py').read_text())
    peer.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(tmp_path / 'protocol.jsonl'))
    (tmp_path / 'home').mkdir()
    (tmp_path / 'home' / 'auth.json').write_text('{}')
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'chosen-model',
            'developerInstructions': 'Retain native settings.',
            'config': {'default_permissions': 'chosen', 'permissions': {
                'chosen': {'extends': ':workspace', 'filesystem': {str(tmp_path): 'write'}},
            }}},
    }}


@pytest.fixture
def plugin(tmp_path, native):
    """Return a factory for one control whose Codex connection has a reviewer."""
    made = []

    def plugin(source, settings=None):
        """Build the control around a reviewer answering probes with allow, others with ``source``."""
        reviewer = process_reviewer(tmp_path, (
            'import json, sys\n'
            'request = json.load(sys.stdin)["request"]\n'
            f'open({str(tmp_path / "requests.jsonl")!r}, "a").write(json.dumps(request) + "\\n")\n'
            'if request["tool"] == "agents/connectivity-check":\n'
            f'    print({ALLOW!r})\n'
            '    raise SystemExit(0)\n'
            + source))
        fields = json.dumps({k: v for k, v in reviewer.items() if k != 'name'})
        root = configured(tmp_path / 'data', (
            f'connections:\n  work:\n    runtime: codex\n    home: {tmp_path / "home"}\n    review: chosen\n'
            f'reviewers:\n  chosen: {fields}\n'))
        control = AgentControl(root, {'codex': CodexDriver(settings or native)})
        made.append(control)
        return control

    yield plugin
    for control in made:
        for owned in control.interrupt_owned():
            call(control, action='wait', agent=owned, timeout_seconds=10)


def decided(decision, reason='Judged.'):
    """Return a reviewer body printing one decision document."""
    return f'print(json.dumps({{"decision": {decision!r}, "reason": {reason!r}}}))\n'


def reviewed(tmp_path):
    """Return the review requests the reviewer received, probes excluded."""
    requests = map(json.loads, (tmp_path / 'requests.jsonl').read_text().splitlines())
    return [item for item in requests if item['tool'] != 'agents/connectivity-check']


def records(control, agent):
    """Return the Agent's decision records."""
    return [json.loads(line) for line in (control.root / 'native' / agent / 'review.jsonl').read_text().splitlines()]


def client_requests(tmp_path, method):
    """Return the client requests of one method the peer received."""
    lines = (tmp_path / 'protocol.jsonl').read_text().splitlines()
    return [message for message in map(json.loads, lines) if message.get('method') == method]


def held(control, instruction):
    """Create a child and return its Agent and the one request held for the parent."""
    created, failed = call(control, action='create', runtime='codex', instruction=instruction)
    assert not failed, created
    agent = created['agent']
    waited = call(control, action='wait', agent=agent, timeout_seconds=10)[0]['result']
    assert waited['pending_requests'] == 1, waited
    [request] = call(control, action='requests', agent=agent)[0]['result']['requests']
    return agent, request


def finished(control, agent):
    """Wait for standby and return the Agent's last result."""
    waited = call(control, action='wait', agent=agent, timeout_seconds=10)[0]['result']
    assert waited['state'] == 'standby', waited
    return waited['last_result']


def test_allow_runs_the_call_and_records_without_input(tmp_path, plugin):
    """allow answers the native request as accepted; the record holds no tool input."""
    control = plugin(decided('allow'))
    created, failed = call(control, action='create', runtime='codex', instruction='request:' + COMMAND)
    assert not failed, created
    assert created['result']['review'] == 'chosen'
    agent = created['agent']
    assert finished(control, agent)['last_message'] == 'request accepted'

    [request] = reviewed(tmp_path)
    assert request['tool'] == COMMAND and request['runtime'] == 'codex'
    assert request['input']['command'] == 'printf approved'
    assert request['instruction'] == 'request:' + COMMAND and request['cwd'] == str(tmp_path)
    assert request['native']['default_permissions'] == 'chosen'

    [record] = records(control, agent)
    assert (record['runtime'], record['tool'], record['decision']) == ('codex', COMMAND, 'allow')
    assert 'printf approved' not in json.dumps(record)


@pytest.mark.parametrize(('body', 'decision', 'reason'), [
    (decided('deny', 'Outside the task.'), 'deny', 'Outside the task.'),
    (decided('escalate', 'Pushes to a remote.'), 'escalate', 'Pushes to a remote.'),
    ('raise SystemExit(3)\n', 'escalate', 'Failed review: the process exited with status 3'),
    ('print("not a document")\n', 'escalate', 'Failed review: the answer is not one JSON object'),
])
def test_anything_but_allow_holds_the_same_request_for_the_parent(tmp_path, plugin, body, decision, reason):
    """The call waits; the parent reads the review and its accept answers the native request."""
    control = plugin(body)
    agent, request = held(control, 'request:' + COMMAND)
    assert request['method'] == COMMAND and request['params']['command'] == 'printf approved'
    assert request['params']['review']['decision'] == decision
    assert request['params']['review']['reason'].startswith(reason)
    assert len(reviewed(tmp_path)) == 1

    answer, failed = call(control, action='reply', agent=agent, request=request, response={'decision': 'accept'})
    assert not failed and answer['result']['reply_status'] == 'submitted'
    assert finished(control, agent)['last_message'] == 'request accepted'

    # No retry and no second review, and the record names the outcome.
    assert len(reviewed(tmp_path)) == 1
    [record] = records(control, agent)
    assert record['decision'] == decision and record['reason'].startswith(reason)


def test_parent_decline_answers_a_held_request(tmp_path, plugin, monkeypatch):
    """A declining parent keeps the call from running."""
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps({
        'method': COMMAND, 'response': {'decision': 'decline'},
        'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'itemId': 'command', 'command': 'rm x'},
    }))
    control = plugin(decided('deny'))
    agent, request = held(control, 'configured-request')
    call(control, action='reply', agent=agent, request=request, response={'decision': 'decline'})
    assert finished(control, agent)['last_message'] == 'request accepted'
    [answer] = [item for item in map(json.loads, (tmp_path / 'protocol.jsonl').read_text().splitlines())
                if item.get('id') == 'native-request-1']
    assert answer['result'] == {'decision': 'decline'}


def test_parent_reply_is_still_checked_on_a_held_request(plugin):
    """A parent may not widen a reviewed request either."""
    control = plugin(decided('deny'))
    agent, request = held(control, 'request:' + COMMAND)
    document, failed = call(control, action='reply', agent=agent, request=request,
                            response={'decision': 'acceptForSession'})
    assert failed and document['error']['code'] == 'authority-denied'
    assert call(control, action='requests', agent=agent)[0]['result']['requests'] == [request]
    call(control, action='reply', agent=agent, request=request, response={'decision': 'decline'})


def test_interrupt_drops_a_held_review(plugin):
    """Interrupting the child ends it; the hold does not outlive the execution."""
    control = plugin(decided('escalate'))
    agent, _ = held(control, 'request:' + COMMAND)
    document, failed = call(control, action='interrupt', agent=agent)
    assert not failed and document['result']['interrupt'] == 'requested'
    # wait ends early on the unanswered request, so watch the state.
    deadline = time.monotonic() + 10
    while (current := call(control, action='status', agent=agent)[0]['result'])['state'] != 'standby':
        assert time.monotonic() < deadline, current
        time.sleep(0.05)
    assert current['last_result']['outcome'] == 'interrupted'
    assert 'pending_requests' not in current


@pytest.mark.parametrize(('method', 'params', 'response'), [
    ('item/permissions/requestApproval', {'permissions': {'network': {'enabled': True}}},
     {'permissions': {'network': {'enabled': True}}}),
    ('mcpServer/elicitation/request', {'mode': 'form', '_meta': {'codex_approval_kind': 'mcp_tool_call'},
                                       'message': 'Run the tool?'}, {'action': 'accept'}),
    (COMMAND, {'availableDecisions': ['accept', 'cancel'], 'command': 'true'}, {'decision': 'accept'}),
])
def test_allow_answers_each_method_with_its_exact_native_form(tmp_path, plugin, monkeypatch, method, params, response):
    """Exact requested profile, the elicitation action, or plain accept; never for longer."""
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps({
        'method': method, 'response': response,
        'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'itemId': 'x', **params},
    }))
    control = plugin(decided('allow'))
    created, _ = call(control, action='create', runtime='codex', instruction='configured-request')
    assert finished(control, created['agent'])['last_message'] == 'request accepted'
    assert reviewed(tmp_path)[0]['tool'] == method


@pytest.mark.parametrize(('method', 'params', 'reason'), [
    (COMMAND, {'availableDecisions': ['cancel'], 'command': 'true'}, 'offers no answer accepting'),
    ('item/permissions/requestApproval', {}, 'offers no answer accepting'),
    ('item/somethingNew/requestApproval', {}, 'offers no answer accepting'),
    ('item/fileChange/requestApproval', {'changes': []}, 'file changes are not available'),
])
def test_what_cannot_be_reviewed_or_accepted_goes_to_the_parent(tmp_path, plugin, monkeypatch, method, params, reason):
    """No reviewer call is wasted and the call does not run: it is a failed review."""
    monkeypatch.setenv('PEER_REQUEST_EXCHANGE', json.dumps({
        'method': method, 'response': {'decision': 'decline'},
        'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'itemId': 'x', **params},
    }))
    control = plugin(decided('allow'))
    agent, request = held(control, 'configured-request')
    assert request['params']['review']['decision'] == 'escalate'
    assert reason in request['params']['review']['reason']
    assert reviewed(tmp_path) == []
    call(control, action='reply', agent=agent, request=request, response={'decision': 'decline'})
    finished(control, agent)


def test_failing_record_refuses_the_call(tmp_path, plugin, monkeypatch):
    """An allow that cannot be recorded does not run."""
    from agent_swarm.codex import managed_session

    def broken(*arguments):
        """Fail as a full disk would."""
        raise OSError('no space')

    monkeypatch.setattr(managed_session, 'record_decision', broken)
    control = plugin(decided('allow'))
    agent, request = held(control, 'request:' + COMMAND)
    assert 'could not be recorded (OSError)' in request['params']['review']['reason']
    call(control, action='reply', agent=agent, request=request, response={'decision': 'accept'})
    finished(control, agent)


def test_review_continues_on_a_later_execution_without_a_new_check(tmp_path, plugin):
    """A resumed Session keeps its reviewer; only create probes."""
    control = plugin(decided('allow'))
    created, _ = call(control, action='create', runtime='codex', instruction='request:' + COMMAND)
    agent = created['agent']
    finished(control, agent)
    _, failed = call(control, action='send', agent=agent, message='request:' + COMMAND)
    assert not failed
    assert finished(control, agent)['last_message'] == 'request accepted'
    assert len(reviewed(tmp_path)) == 2 and len(records(control, agent)) == 2
    tools = [json.loads(line)['tool'] for line in (tmp_path / 'requests.jsonl').read_text().splitlines()]
    assert tools.count('agents/connectivity-check') == 1


def test_the_reviewer_is_user_only_with_review(tmp_path, plugin, native):
    """Codex is asked to hand requests to the client, truthfully recorded; nothing else changes."""
    control = plugin(decided('allow'))
    created, _ = call(control, action='create', runtime='codex', instruction='plain turn')
    agent = created['agent']
    finished(control, agent)
    [start] = client_requests(tmp_path, 'thread/start')
    assert start['params']['approvalsReviewer'] == 'user'
    assert start['params']['config']['approvals_reviewer'] == 'user'
    assert start['params']['config']['features'] == {'exec_permission_approvals': True}
    import yaml

    evidence = yaml.safe_load((control.root / 'native' / agent / 'session.yml').read_text())['permissions']
    assert (evidence['requested'], evidence['source']) == ('user', 'review-plugin')
    # A plain turn asked nothing, so nothing was reviewed.
    assert reviewed(tmp_path) == []


def test_prepare_without_review_is_unchanged(native):
    """No review: exactly the settings before 386, byte for byte."""
    config = native['adapter_request']['session_parameters']['config']
    config.update(approval_policy='on-request', sandbox_mode='workspace-writable',
                  sandbox_workspace_write={'network_access': False, 'writable_roots': []})
    caller = Caller('controlled-host', 'actual-parent', 'parent-session', 'codex')
    expected = {**native, 'evidence': {}}
    expected['adapter_request'] = {**native['adapter_request'], 'session_parameters': {
        **native['adapter_request']['session_parameters'], 'config': {
            **config, 'approvals_reviewer': 'auto_review', 'features': {'exec_permission_approvals': True}}}}
    assert json.dumps(CodexDriver(native).prepare('codex', caller)) == json.dumps(expected)
    selection = {'preset': None, 'connection': None, 'model': None, 'reasoning_effort': None,
                 'provider': None, 'settings': None, 'review': None}
    assert json.dumps(CodexDriver(native).prepare('codex', caller, selection=selection)) == json.dumps(expected)


def test_prepare_with_review_keeps_every_other_setting(native):
    """Only the reviewer changes; a supplied auto_review gives way, limits stay."""
    config = native['adapter_request']['session_parameters']['config']
    config.update(approval_policy='on-request', sandbox_mode='workspace-writable', approvals_reviewer='auto_review',
                  sandbox_workspace_write={'network_access': False, 'writable_roots': []})
    caller = Caller('controlled-host', 'actual-parent', 'parent-session', 'codex')
    selection = {'review': {'name': 'chosen', 'command': ['/abs/x']}}
    prepared = CodexDriver(native).prepare('codex', caller, selection=selection)
    assert prepared['review'] == selection['review']
    parameters = prepared['adapter_request']['session_parameters']
    generated = parameters['config']
    assert parameters['approvalsReviewer'] == 'user'
    assert generated.pop('approvals_reviewer') == 'user' and generated.pop('features') == {
        'exec_permission_approvals': True}
    del config['approvals_reviewer']
    assert generated == config


@pytest.mark.parametrize('where', ['config', 'parameters'])
def test_approval_policy_never_is_refused(tmp_path, plugin, native, where):
    """No request would ever reach the reviewer: a silent bypass, so create fails."""
    parameters = native['adapter_request']['session_parameters']
    if where == 'config':
        parameters['config']['approval_policy'] = 'never'
    else:
        parameters['approvalPolicy'] = 'never'
    control = plugin(decided('allow'), native)
    document, failed = call(control, action='create', runtime='codex', instruction='x')
    assert failed and document['error']['code'] == 'invalid-config'
    assert 'approval_policy' in document['error']['message']
    assert agent_files(control.root) == []
    # Without a reviewer the same setting stays the host's own choice.
    caller = Caller('controlled-host', 'actual-parent', 'parent-session', 'codex')
    CodexDriver(native).prepare('codex', caller)


def test_native_never_from_the_home_also_stops_the_execution(tmp_path, plugin, monkeypatch):
    """A policy agents did not supply cannot turn the review plugin off silently."""
    original = CodexAppServer.create_session

    async def reporting_never(self, context, **options):
        """Report the policy the native home selected."""
        session = await original(self, context, **options)
        return replace(session, configuration={**session.configuration, 'approvalPolicy': 'never'})

    monkeypatch.setattr(CodexAppServer, 'create_session', reporting_never)
    control = plugin(decided('allow'))
    document, failed = call(control, action='create', runtime='codex', instruction='x')
    assert failed
    assert document['result']['last_result']['error']['code'] == 'RUNTIME_REQUEST_FAILED'
    assert 'approval_policy' in document['result']['last_result']['error']['message']


def test_without_review_a_native_request_is_held_unreviewed(tmp_path, native, monkeypatch):
    """No reviewer runs and no record is written for a connection without review."""
    control = AgentControl(tmp_path / 'data', {'codex': CodexDriver(native)})
    agent, request = held(control, 'request:' + COMMAND)
    assert 'review' not in request['params'] and not (control.root / 'native' / agent / 'review.jsonl').exists()
    assert call(control, action='status', agent=agent)[0]['result']['review'] is None
    call(control, action='reply', agent=agent, request=request, response={'decision': 'accept'})
    assert finished(control, agent)['last_message'] == 'request accepted'


@pytest.fixture
def child_environment(tmp_path, native, monkeypatch):
    """Record the variable NAMES of the Codex child's environment, never a value."""
    names = tmp_path / 'child-variable-names'
    wrapper = tmp_path / 'codex-recording'
    wrapper.write_text("#!/bin/sh\n"
                       f"awk 'BEGIN {{ for (name in ENVIRON) print name }}' > {names}\n"
                       f'exec {tmp_path / "codex"} "$@"\n')
    wrapper.chmod(0o755)
    native['adapter_request']['arguments'][0] = str(wrapper)
    return lambda: set(names.read_text().splitlines())


def keyed_control(tmp_path, native, connection, variable='REVIEW_KEY'):
    """Return a control whose reviewer reads ``variable``; ``connection`` adds connection lines."""
    root = configured(tmp_path / 'data', (
        f'connections:\n  work:\n    runtime: codex\n    home: {tmp_path / "home"}\n{connection}'
        f'reviewers:\n  chosen: {{base_url: "{URL}", model: m, api_key_env: {variable}}}\n'))
    return AgentControl(root, {'codex': CodexDriver(native)})


def test_reviewer_key_stays_out_of_the_codex_child(tmp_path, native, endpoint, child_environment):
    """The host reads the key for review_call; the child it judges never holds it."""
    control = keyed_control(tmp_path, native, '    review: chosen\n')
    created, failed = call(control, action='create', runtime='codex', instruction='request:' + COMMAND)
    assert not failed, created
    assert finished(control, created['agent'])['last_message'] == 'request accepted'
    assert 'REVIEW_KEY' not in child_environment()
    assert {sent.get_header('Authorization') for sent in endpoint.calls} == {'Bearer ' + KEY}
    assert len(endpoint.calls) == 2


def test_reviewer_key_named_openai_is_withheld_without_a_mismatch(tmp_path, native, endpoint, monkeypatch,
                                                                  child_environment):
    """Codex's own variable is withheld too when the child's connection does not give it."""
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    control = keyed_control(tmp_path, native, '    review: chosen\n', 'OPENAI_API_KEY')
    created, failed = call(control, action='create', runtime='codex', instruction='plain turn')
    assert not failed, created
    assert finished(control, created['agent'])['outcome'] == 'completed'
    assert 'OPENAI_API_KEY' not in child_environment()


def test_reviewer_key_that_is_the_childs_own_stays(tmp_path, native, endpoint, child_environment):
    """The connection gives its child this variable, so it is not the reviewer's to remove."""
    control = keyed_control(tmp_path, native, '    api_key_env: REVIEW_KEY\n    review: chosen\n')
    created, failed = call(control, action='create', runtime='codex', instruction='plain turn')
    assert not failed, created
    finished(control, created['agent'])
    assert 'REVIEW_KEY' in child_environment()


def test_without_review_the_child_environment_is_unchanged(tmp_path, native, endpoint, child_environment):
    """A declared but unused reviewer removes nothing."""
    control = keyed_control(tmp_path, native, '')
    created, failed = call(control, action='create', runtime='codex', instruction='plain turn')
    assert not failed, created
    finished(control, created['agent'])
    assert 'REVIEW_KEY' in child_environment()


def test_notice_names_the_tool_without_its_input():
    """A plugin request's notice names its tool; the input never appears."""
    message = _request_message({'method': 'agents/review', 'params': {'tool': 'Bash', 'input': {'command': 'rm x'}}})
    assert 'agents/review for Bash' in message and 'rm x' not in message
    assert 'claude/can_use_tool for Read' in _request_message({
        'method': 'claude/can_use_tool', 'params': {'tool_name': 'Read', 'tool': 'ignored'}})
    assert 'for' not in _request_message({'method': 'm', 'params': {'tool': 5}}).split('waits')[0]


def test_a_consumer_execution_is_not_offered_the_plugin(tmp_path, native):
    """A subclass binds its own review policy, so a selected reviewer is refused, never ignored."""
    class Consumer(CodexManagedExecution):
        """A consumer's execution with its own review policy."""

    assert CodexDriver(native).supports_review is True
    assert CodexDriver(native, execution=Consumer).supports_review is False
    assert codex_driver.CodexManagedExecution is CodexManagedExecution
