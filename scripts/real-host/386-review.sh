#!/bin/bash
# Task 386 real-host check: the review plugin on real Claude Code and Codex.
#
# Run in your own macOS Terminal (outside any Agent sandbox), with no argument:
#   bash /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/386-review-plugin-core-claude-codex/scripts/real-host/386-review.sh
#
# Expected native review dialog: NONE. The parent is this script (a Python caller
# of the public agents API), so no Claude or Codex dialog should appear. If one
# does, it is a finding: answer it, and report it.
#
# What it uses: Claude Code and Codex with your existing logins (children run real
# models, a few short turns each); DEEPSEEK_API_KEY for the reviewer in steps 2
# and 3, from the environment or else from ~/.zshrc, never printed or stored. The
# local stub reviewers bind 127.0.0.1 and never see a key. Nothing is installed
# outside the run directory: a dedicated venv with an editable install of this
# Worktree, no PyPI; websockets is linked from the persistent .venv-runtime.
#
# Every fixture sits in a new directory under $HOME, because a child's sandbox may
# reach $TMPDIR and /tmp. The directory is printed and kept; delete it when done.
#
# It stops if the Worktree is not on the 386 branch or has uncommitted changes,
# because the venv imports the live tree. Written for macOS /bin/bash 3.2.
# Exit status: 0 only when every criterion printed PASS; 2 when it stopped early.
set -uo pipefail

WORKTREE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/386-review-plugin-core-claude-codex
PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
BRANCH=agent/386-review-plugin-core-claude-codex
WEBSOCKETS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages/websockets
# Reviewer for steps 2 and 3 (as accepted in Task 383's reports and tests).
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
# The Claude child's model, under your own login (used by Task 383's real host).
CLAUDE_MODEL=claude-sonnet-5-5
# The Codex child's model, required by its settings; empty: read from ~/.codex/config.toml.
CODEX_MODEL=

RUN=$(mktemp -d "$HOME/agents-386-review.XXXXXX") || exit 2
VENV=$RUN/venv
exec > >(tee "$RUN/output.log") 2>&1

echo "== preflight"
echo "shell:         $BASH ($BASH_VERSION)"
echo "run directory: $RUN (kept)"
echo "worktree:      $WORKTREE"
COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
EXPECTED=$(git -C "$WORKTREE" rev-parse "$BRANCH")
echo "HEAD:          $COMMIT"
echo "$BRANCH: $EXPECTED"
if [ "$COMMIT" != "$EXPECTED" ]; then
  echo "STOP: the Worktree HEAD is not $BRANCH."
  exit 2
fi
if [ -n "$(git -C "$WORKTREE" status --porcelain)" ]; then
  echo "STOP: $WORKTREE has uncommitted changes; the venv would import them, not $COMMIT."
  exit 2
fi
CLAUDE=$(command -v claude || true)
if [ -z "$CLAUDE" ] && [ -x "$HOME/.local/bin/claude" ]; then CLAUDE=$HOME/.local/bin/claude; fi
CODEX=$(command -v codex || true)
if [ -z "$CLAUDE" ] || [ -z "$CODEX" ]; then
  echo "STOP: claude ($CLAUDE) or codex ($CODEX) is not on PATH."
  exit 2
fi
echo "claude:        $CLAUDE ($("$CLAUDE" --version 2>&1 | head -1))"
echo "codex:         $CODEX ($("$CODEX" --version 2>&1 | head -1))"
echo "python:        $("$PYTHON" --version 2>&1)"
if [ -z "$CODEX_MODEL" ]; then
  CODEX_MODEL=$(sed -n 's/^model *= *"\(.*\)"$/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | head -1)
fi
if [ -z "$CODEX_MODEL" ]; then
  echo "STOP: no Codex model; set CODEX_MODEL at the top of this script."
  exit 2
fi
echo "codex model:   $CODEX_MODEL"
mkdir -p "$RUN/preflight"
SELF_REPORT='In one line, state the model name you are running as and whether you are logged in. Do not run tools or print any key or token.'
echo "claude one-line self-report (configured model and login, no reviewer):"
(cd "$RUN/preflight" && "$CLAUDE" -p "$SELF_REPORT" </dev/null 2>/dev/null | tail -1) || echo "(claude self-report failed)"
echo "codex one-line self-report (configured model and login, no reviewer):"
"$CODEX" exec --skip-git-repo-check --ephemeral -s read-only -C "$RUN/preflight" "$SELF_REPORT" </dev/null 2>/dev/null | tail -1 \
  || echo "(codex self-report failed)"

# The key stays out of every log: tracing stays off, only its state is printed.
set +x
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  DEEPSEEK_API_KEY=$(/bin/zsh -c 'source ~/.zshrc >/dev/null 2>&1; printf %s "${DEEPSEEK_API_KEY:-}"' </dev/null 2>/dev/null) || true
fi
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  export DEEPSEEK_API_KEY
  echo "DEEPSEEK_API_KEY: set"
else
  unset DEEPSEEK_API_KEY
  echo "DEEPSEEK_API_KEY: unset; steps 2 and 3 will FAIL with that reason"
fi

"$PYTHON" -m venv --system-site-packages "$VENV" || exit 2
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-index --no-deps \
  --no-build-isolation -e "$WORKTREE/src/agent_swarm" -e "$WORKTREE" || exit 2
if ! "$VENV/bin/python" -c 'import websockets' 2>/dev/null; then
  ln -s "$WEBSOCKETS" "$VENV/lib/python3.13/site-packages/websockets"
fi
cd "$RUN" || exit 2

cat > "$RUN/parent.py" <<'PARENT_EOF'
"""Act as the direct parent of real children through the public agents API."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.claude.driver import ClaudeDriver
from agent_swarm.claude.execution import review_hook_timeout
from agent_swarm.codex.driver import CodexDriver

RUN = Path(sys.argv[1])
ENV = os.environ
RESULTS: list[tuple[str, str]] = []
FOLLOW_UPS: list[str] = []
MISSING_SESSION = {'error': {'code': 'MissingSessionID', 'message': 'session id is required', 'type': 'invalid_request_error'}}
ALLOW = {'decision': 'allow', 'reason': 'Stub reviewer allows this call.'}
REFUSE_NOTE = ('If the call is refused, do not try anything else and use no other tool: reply with one line saying '
               'it was refused. If you are later told you may retry, retry exactly the same call. Then reply done.')


def verdict(name: str, state: str | bool, *proof: object) -> None:
    """Print one criterion with the raw lines proving it."""
    state = {True: 'PASS', False: 'FAIL'}.get(state, state)
    print(f'{state}: {name}')
    for line in proof:
        print('    ' + str(line))
    RESULTS.append((name, state))


def instruction(runtime: str, name: str, path: Path) -> str:
    """Return the child's task for one file; a dry run against a peer may replace it."""
    dry = ENV.get(f'AGENTS_386_DRY_{runtime.upper()}')
    if dry:
        return dry.replace('@NAME@', name)
    if runtime == 'claude':
        return (f'Use the Write tool, once, to create the file {path} containing exactly: ok\n'
                f'Use no other tool. {REFUSE_NOTE}')
    return f'Run exactly one shell command, once: touch {path}\nRun nothing else. {REFUSE_NOTE}'


class Stub:
    """A chat completions reviewer on 127.0.0.1; ``answer`` returns (status, document)."""

    def __init__(self, answer) -> None:
        stub = self
        self.calls = 0

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                """Answer one review."""
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                stub.calls += 1
                status, document = answer()
                body = json.dumps(document).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                """Keep the output to the criteria."""

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.entry = {'base_url': f'http://127.0.0.1:{self.server.server_address[1]}/v1', 'model': 'stub',
                      'timeout_seconds': 30}

    def close(self) -> None:
        """Stop serving."""
        self.server.shutdown()


def completion(decision: dict) -> tuple[int, dict]:
    """Return a valid chat completion holding one decision document."""
    return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(decision)}}]}


def yaml_value(value: object) -> str:
    """Render one config value (the file's own simple forms)."""
    if isinstance(value, list):
        return '[' + ', '.join(json.dumps(item) for item in value) + ']'
    return json.dumps(value)


class Child:
    """One step's data root, workspace and parent over one reviewed Runtime."""

    def __init__(self, step: str, runtime: str, reviewer: dict, *, configure=None) -> None:
        self.runtime = runtime
        self.directory = RUN / step
        self.data = self.directory / 'data'
        self.work = self.directory / 'work'
        self.work.mkdir(parents=True)
        self.data.mkdir()
        lines = ['reviewers:', '  checker:'] + [f'    {key}: {yaml_value(value)}' for key, value in reviewer.items()]
        (self.data / 'config.yml').write_text('\n'.join(lines + [
            'connections:', '  reviewed:', f'    runtime: {runtime}', '    review: checker', '']))
        self.notices: list[dict] = []
        self.started: list[str] = []
        recorder = self.started

        class CountedClaude(ClaudeDriver):
            def start(self, run):
                recorder.append(run.agent)
                return super().start(run)

        class CountedCodex(CodexDriver):
            def start(self, run):
                recorder.append(run.agent)
                return super().start(run)

        if runtime == 'claude':
            driver = CountedClaude(self.work, {'executable': ENV['CLAUDE_BIN'], 'model': ENV['CLAUDE_MODEL'],
                                               'permission_mode': 'default'}, configure=configure)
        else:
            # What makes Codex ask: approval_policy untrusted asks before any command
            # outside its known-safe list, such as touch, even inside the workspace.
            driver = CountedCodex({'adapter_request': {
                'arguments': [ENV['CODEX_BIN']], 'worktree_path': str(self.work),
                'session_parameters': {'cwd': str(self.work), 'model': ENV['CODEX_MODEL'], 'developerInstructions': '', 'config': {
                    'approval_policy': 'untrusted', 'default_permissions': 'work',
                    'permissions': {'work': {'extends': ':workspace',
                                             'filesystem': {':workspace_roots': {'.': 'write'}}}}}}}})
        self.control = AgentControl(self.data, {runtime: driver}, event_receiver=self.notices.append,
                                    request_notices=True)
        self.call = bind(self.control, Caller('386-real-host', 'parent-386', 'parent-386-session', runtime))
        self.agent: str | None = None

    def invoke(self, action: str, **arguments: object) -> dict:
        """Return one public result document."""
        return self.call({'action': action, **arguments}).document

    def create(self, name: str) -> dict:
        """Create the child with one file task."""
        document = self.invoke('create', runtime=self.runtime, instruction=instruction(self.runtime, name, self.work / name))
        if 'agent' not in document:
            raise RuntimeError(f'create failed: {json.dumps(document, ensure_ascii=False)}')
        self.agent = document['agent']
        return document

    def send(self, name: str) -> dict:
        """Give the child the next file task."""
        document = self.invoke('send', agent=self.agent, message=instruction(self.runtime, name, self.work / name))
        if document.get('error'):
            raise RuntimeError(f'send failed: {json.dumps(document, ensure_ascii=False)}')
        return document

    def settle(self, seconds: int = 300) -> str:
        """Wait for a pending request or standby; say which, or ``timeout``."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = self.invoke('wait', agent=self.agent, timeout_seconds=20).get('result', {})
            if result.get('pending_requests'):
                return 'request'
            if result.get('state') == 'standby':
                return 'standby'
        return 'timeout'

    def requests(self) -> list[dict]:
        """Return the requests the parent can read now."""
        return self.invoke('requests', agent=self.agent).get('result', {}).get('requests', [])

    def standby(self, seconds: int = 300) -> dict:
        """Wait for standby even while a retained request ends each ``wait``."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = self.invoke('status', agent=self.agent).get('result', {})
            if result.get('state') == 'standby':
                return result
            time.sleep(1)
        return self.invoke('status', agent=self.agent).get('result', {})

    def reviews(self) -> list[dict]:
        """Return the child's retained decisions, oldest first."""
        lines = [line for path in self.data.rglob('review.jsonl') for line in path.read_text().splitlines()]
        return sorted(map(json.loads, lines), key=lambda line: line['at'])

    def request_notices(self) -> list[dict]:
        """Return the parent's request notices."""
        return [notice for notice in self.notices if notice['outcome'] == 'request']

    def close(self) -> None:
        """Stop the child and print follow-up commands with real identities."""
        for owned in self.control.interrupt_owned():
            self.standby(30)
        for path in self.data.rglob('review.jsonl'):
            FOLLOW_UPS.append(f'cat {path}')
        if self.agent is not None:
            FOLLOW_UPS.append(f'cd {RUN} && {sys.executable} {RUN}/parent.py {RUN} status {self.data} {self.agent}')


def reason_of(request: dict) -> str:
    """Return a held request's review reason, in the Runtime's own form."""
    params = request.get('params', {})
    return str(params.get('reason') or params.get('review', {}).get('reason'))


def fields(value: object) -> list[str]:
    """Return field names only."""
    return sorted(value) if isinstance(value, dict) else []


def step_1() -> None:
    """Claude protocol probe: field names of the hook and prompt, and their order."""
    print('\n== Step 1: Claude protocol probe (stub reviewer that takes 3 s to allow)')
    seen: dict[str, float] = {}
    hook_identity: list[str] = []

    def configure(turn, run) -> None:
        """Observe control requests in this script, leaving the driver as it is."""
        control_event, reply = turn._control_event, turn._reply
        seen['turn'] = turn

        def observe(event: dict) -> None:
            request = event.get('request', {})
            if request.get('callback_id') == 'agents_review':
                native = request.get('input', {})
                if native.get('tool_name') != 'mcp__agents__agents':
                    seen.setdefault('hook', time.time())
                    hook_identity.append(event.get('request_id'))
                    print('    hook_callback fields:', fields(request), 'input fields:', fields(native))
            elif request.get('subtype') == 'can_use_tool':
                seen.setdefault('prompt', time.time())
                print('    can_use_tool fields:', fields(request), 'input fields:', fields(request.get('input')))
            control_event(event)

        def observe_reply(identity: str, response: dict) -> None:
            if identity in hook_identity:
                seen.setdefault('answer', time.time())
            reply(identity, response)

        turn._control_event, turn._reply = observe, observe_reply

    def slow_allow() -> tuple[int, dict]:
        time.sleep(3)
        return completion(ALLOW)

    # The connectivity check at create answers at once.
    answers = iter([completion(ALLOW)])
    stub = Stub(lambda: next(answers, None) or slow_allow())
    child = Child('step1', 'claude', stub.entry, configure=configure)
    try:
        created = child.create('probe.txt')
        print('    create:', json.dumps({key: created.get(key) for key in ('agent', 'error')}))
        state = child.settle()
        target = child.work / 'probe.txt'
        turn = seen.get('turn')
        initialize = turn.diagnostics.get('initialize', {}) if turn is not None else {}
        print('    registered PreToolUse timeout:', review_hook_timeout(stub.entry), 'seconds; initialize control_status:',
              initialize.get('control_status'), '(a refused hook registration ends the execution)')
        print('    can_use_tool arrived:', 'prompt' in seen)
        print('    settled:', state, '; reviews:', [line['decision'] for line in child.reviews()])
        mtime = target.stat().st_mtime if target.exists() else None
        verdict('PreToolUse fired before the tool ran', bool(
            mtime and 'hook' in seen and 'answer' in seen and seen['hook'] < seen['answer'] <= mtime + 1),
            f"hook at {seen.get('hook')}, hook answered at {seen.get('answer')}, file written at {mtime}")
    finally:
        child.close()
        stub.close()


def deepseek() -> dict:
    """Return the reviewer on a provider different from the child's own login."""
    return {'base_url': ENV['DEEPSEEK_BASE_URL'], 'model': ENV['DEEPSEEK_MODEL'], 'api_key_env': 'DEEPSEEK_API_KEY',
            'json_mode': True, 'timeout_seconds': 60}


def step_2() -> None:
    """A Claude child under its own login, reviewed by DeepSeek."""
    print('\n== Step 2: Claude child (own login) with a DeepSeek reviewer')
    if not ENV.get('DEEPSEEK_API_KEY'):
        verdict('review connection on a different provider works (Claude)', False, 'DEEPSEEK_API_KEY is unset')
        return
    child = Child('step2', 'claude', deepseek())
    try:
        created = child.create('ordinary.txt')
        print('    create:', json.dumps({'agent': created.get('agent'), 'error': created.get('error'),
                                          'connection': created.get('result', {}).get('connection'),
                                          'review': created.get('result', {}).get('review')}))
        state = child.settle()
        reviews = child.reviews()
        target = child.work / 'ordinary.txt'
        print('    settled:', state, '; file exists:', target.exists())
        verdict('review connection on a different provider works (Claude)',
                target.exists() and any(line['decision'] == 'allow' and line['tool'] == 'Write' for line in reviews),
                *[json.dumps(line, ensure_ascii=False) for line in reviews],
                *[json.dumps({'pending': request['method'], 'reason': reason_of(request)}) for request in
                  (child.requests() if state == 'request' else [])])
    finally:
        child.close()


def step_3() -> None:
    """A Codex child under its own login, reviewed by the same DeepSeek reviewer."""
    print('\n== Step 3: Codex child (own login) with the same DeepSeek reviewer')
    print('    Codex asks because approval_policy is untrusted and touch is not on its known-safe list; '
          'the sandbox is workspace write, approvals_reviewer is user.')
    if not ENV.get('DEEPSEEK_API_KEY'):
        verdict('review connection on a different provider works (Codex)', False, 'DEEPSEEK_API_KEY is unset')
        return
    child = Child('step3', 'codex', deepseek())
    try:
        created = child.create('ordinary.txt')
        print('    create:', json.dumps({'agent': created.get('agent'), 'error': created.get('error'),
                                          'connection': created.get('result', {}).get('connection'),
                                          'review': created.get('result', {}).get('review')}))
        state = child.settle()
        reviews = child.reviews()
        asked = [line for line in reviews if line['tool'].endswith('/requestApproval')]
        target = child.work / 'ordinary.txt'
        print('    settled:', state, '; /requestApproval arrived:', bool(asked), '; file exists:', target.exists())
        proof = [json.dumps(line, ensure_ascii=False) for line in reviews]
        if not asked:
            verdict('review connection on a different provider works (Codex)', 'NOT SHOWN',
                    'No /requestApproval arrived, so the reviewer was not asked.', *proof)
        else:
            verdict('review connection on a different provider works (Codex)',
                    target.exists() and any(line['decision'] == 'allow' for line in asked), *proof)
    finally:
        child.close()


def step_4() -> None:
    """A reviewer that is broken at create: refused at once, with nothing started."""
    print('\n== Step 4: create with a broken reviewer, for each child Runtime')
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    stub = Stub(lambda: (400, MISSING_SESSION))
    try:
        for runtime in ('claude', 'codex'):
            for case, reviewer, expected in (
                ('a-http-400', stub.entry, 'MissingSessionID'),
                ('b-unreachable', {'base_url': f'http://127.0.0.1:{closed_port}/v1', 'model': 'stub',
                                   'timeout_seconds': 10}, 'cannot reach'),
                ('c-command-exit', {'command': ['/bin/sh', '-c', 'echo reviewer broke >&2; exit 3']}, 'status 3'),
            ):
                child = Child(f'step4-{runtime}-{case}', runtime, reviewer)
                began = time.monotonic()
                document = child.invoke('create', runtime=runtime, instruction='You must not be started.')
                elapsed = time.monotonic() - began
                error = document.get('error') or {}
                listed = child.invoke('status').get('result', {}).get('agents')
                records = [str(path) for path in child.data.rglob('agent-*.json')]
                verdict(f'{runtime} {case}: create fails at once, reason visible, nothing started',
                        error.get('code') == 'review-unavailable' and expected in error.get('message', '')
                        and elapsed < 15 and listed == [] and not records and not child.started,
                        f'{elapsed:.1f} s; error: {json.dumps(error, ensure_ascii=False)}',
                        f'agents listed: {listed}; records: {records}; native starts: {child.started}')
    finally:
        stub.close()


def step_5(runtime: str) -> None:
    """A reviewer that breaks after creation goes to the parent; it blocks nothing for good."""
    print(f'\n== Step 5 ({runtime}): the reviewer starts answering 400 MissingSessionID after creation')
    flag = RUN / f'step5-{runtime}.broken'
    stub = Stub(lambda: (400, MISSING_SESSION) if flag.exists() else completion(ALLOW))
    child = Child(f'step5-{runtime}', runtime, stub.entry)
    work = child.work
    try:
        print('    create:', json.dumps({key: child.create('first.txt').get(key) for key in ('error',)}))
        state = child.settle()
        print('    first call while the reviewer works:', state, '; file exists:', (work / 'first.txt').exists())
        if state != 'standby' or not (work / 'first.txt').exists():
            verdict(f'{runtime}: the first call runs while the reviewer works', False, json.dumps(child.reviews()))
            return
        flag.touch()
        print('    the stub now answers 400; flag:', flag)
        child.send('second.txt')
        state = child.settle()
        time.sleep(15)  # Let a model that keeps trying show any further request.
        held = child.requests()
        ran_early = (work / 'second.txt').exists()
        notices = child.request_notices()
        verdict(f'{runtime}: the next tool call does not run; exactly one request reaches the parent, with the reason',
                state == 'request' and len(held) == 1 and len(notices) == 1 and not ran_early
                and 'MissingSessionID' in reason_of(held[0]),
                f'settled: {state}; file exists: {ran_early}; notices: {len(notices)}',
                *[json.dumps({'method': item['method'], 'request_id': item['request_id'], 'reason': reason_of(item)},
                             ensure_ascii=False) for item in held])
        if not held:
            return
        receipt = child.invoke('reply', agent=child.agent, request=held[0], response={'decision': 'accept'})
        print('    accept:', json.dumps({key: receipt.get('result', {}).get(key) for key in ('request_id', 'reply_status')}),
              receipt.get('error') or '')
        final = child.standby()
        verdict(f"{runtime}: the parent's accept lets exactly that call run",
                (work / 'second.txt').exists() and final.get('state') == 'standby'
                and (runtime != 'claude' or any(line['decision'] == 'released' for line in child.reviews())),
                f"state: {final.get('state')}; file exists: {(work / 'second.txt').exists()}",
                *[json.dumps(line, ensure_ascii=False) for line in child.reviews()])
        child.send('third.txt')
        state = child.settle()
        time.sleep(5)
        third = child.requests()
        verdict(f'{runtime}: a second distinct call also reaches the parent rather than the child hanging',
                state == 'request' and len(third) >= 1 and not (work / 'third.txt').exists(),
                f'settled: {state}; requests: {len(third)}; file exists: {(work / "third.txt").exists()}')
        for item in third:
            child.invoke('reply', agent=child.agent, request=item, response={'decision': 'decline'})
        final = child.standby()
        verdict(f'{runtime}: decline keeps that call from running',
                bool(third) and not (work / 'third.txt').exists() and final.get('state') == 'standby',
                f"state: {final.get('state')}; file exists: {(work / 'third.txt').exists()}",
                f"last message: {str((final.get('last_result') or {}).get('last_message'))[:200]}")
        print('    Compare: DSH 0.2.2-alpha.2 on opencode-go answered its review with 400 MissingSessionID and every '
              'tool call stayed blocked; here the same 400 went to the parent, which released or refused each call.')
    finally:
        child.close()
        stub.close()


def step_6() -> None:
    """A slow reviewer: Claude must wait for the answer, not run the tool at a default limit."""
    print('\n== Step 6: slow reviewer on Claude (command reviewer sleeps 45 s, timeout 60 s, then denies)')
    script = RUN / 'slow-reviewer.py'
    script.write_text(
        'import json, sys, time\n'
        "tool = json.load(sys.stdin)['request']['tool']\n"
        "if tool != 'agents/connectivity-check':\n"
        '    time.sleep(45)\n'
        "print(json.dumps({'decision': 'deny', 'reason': 'Slow stub reviewer refuses this call.'}))\n")
    seen: dict[str, float] = {}

    def configure(turn, run) -> None:
        """Note when the hook arrives."""
        control_event = turn._control_event

        def observe(event: dict) -> None:
            if event.get('request', {}).get('callback_id') == 'agents_review':
                seen.setdefault('hook', time.time())
            control_event(event)

        turn._control_event = observe

    child = Child('step6', 'claude', {'command': [sys.executable, str(script)], 'timeout_seconds': 60}, configure=configure)
    target = child.work / 'target.txt'
    try:
        print('    create:', json.dumps({key: child.create('target.txt').get(key) for key in ('error',)}))
        state = child.settle()
        waited = time.time() - seen['hook'] if 'hook' in seen else None
        during = target.exists()
        held = child.requests() if state == 'request' else []
        for item in held:
            child.invoke('reply', agent=child.agent, request=item, response={'decision': 'decline'})
        final = child.standby()
        verdict('the file does not exist afterwards: Claude waited for the answer instead of failing open',
                state == 'request' and waited is not None and waited >= 45 and not during and not target.exists(),
                f'request seen {waited} s after the hook; file existed then: {during}; exists now: {target.exists()}',
                f"final state: {final.get('state')}",
                *[json.dumps(line, ensure_ascii=False) for line in child.reviews()])
    finally:
        child.close()


def main() -> int:
    """Run every step, or answer one follow-up command."""
    if sys.argv[2:3] == ['status']:
        # Show one Agent as the same parent caller sees it.
        control = AgentControl(Path(sys.argv[3]), {'claude': ClaudeDriver(RUN, {}), 'codex': CodexDriver({})})
        call = bind(control, Caller('386-real-host', 'parent-386', 'parent-386-session', 'claude'))
        print(json.dumps(call({'action': 'status', 'agent': sys.argv[4]}).document, indent=2, ensure_ascii=False))
        return 0
    steps = {'1': [step_1], '2': [step_2], '3': [step_3], '4': [step_4],
             '5': [lambda: step_5('claude'), lambda: step_5('codex')], '6': [step_6]}
    for number in steps:
        for step in steps[number]:
            try:
                step()
            except Exception:
                traceback.print_exc()
                verdict(f'step {number} finished without an unexpected error', False)
    print('\n== Summary')
    for name, state in RESULTS:
        print(f'{state}: {name}')
    print('\n== Follow-up commands')
    for command in FOLLOW_UPS:
        print(command)
    return 0 if RESULTS and all(state == 'PASS' for _, state in RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
PARENT_EOF

CLAUDE_BIN="$CLAUDE" CODEX_BIN="$CODEX" CLAUDE_MODEL="$CLAUDE_MODEL" CODEX_MODEL="$CODEX_MODEL" \
  DEEPSEEK_BASE_URL="$DEEPSEEK_BASE_URL" DEEPSEEK_MODEL="$DEEPSEEK_MODEL" \
  "$VENV/bin/python" "$RUN/parent.py" "$RUN"
STATUS=$?
echo
echo "== Run directory (kept): $RUN"
echo "cat $RUN/output.log"
echo "== Expected native review dialog: none"
echo "exit status: $STATUS"
exit $STATUS
