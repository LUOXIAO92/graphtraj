#!/bin/bash
# Task 387 real-host check: the review plugin on real DSH and real Pi.
#
# Run in your own macOS Terminal (outside any Agent sandbox), in this order:
#   1. the installer, once:
#      /bin/bash /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/387-review-plugin-pi-dsh-adapters/scripts/real-host/install-pi-sandbox.sh
#   2. then this script:
#      bash /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/387-review-plugin-pi-dsh-adapters/scripts/real-host/387-review.sh [--only dsh|pi] [sandbox-location]
# No --only runs everything. --only dsh runs the preflight and steps 2 and 3. --only pi
# runs the preflight and steps 1 and 4, then 5 and 6 if step 4 passes. A scoped run says
# in its summary what it did not run: its exit 0 covers that scope, not the whole criterion.
#
# Expected native review dialog: NONE. The parent is this script (a Python caller of
# the public agents API), so no native dialog should appear. If one does, it is a
# finding: answer it, and report it.
#
# Steps, about 10 to 15 minutes (a child that stalls can add 5 per wait):
#   Preflight  shell, HEAD, versions, DSH's one-line answer, the Pi sandbox install.
#   1  Pi protocol probe: real `pi --mode rpc`, the real extension, a stub model on
#      127.0.0.1, no credentials. Proves the hook on the real binary only.
#   2  DSH, reviewer allow: a DeepSeek child and a real DeepSeek reviewer.
#   3  DSH, back to the parent: stub reviewers on 127.0.0.1 (escalate; breaks after
#      create), a real DeepSeek child, accept and decline.
#   4  The srt and agent-sandbox pair, with no model: which srt runs, and a harmless
#      write inside and outside a grant through agent_sandbox's wrap_command.
#   5  Pi, reviewer allow, under the installed sandbox.
#   6  Pi, back to the parent, under the installed sandbox.
# Steps 4 to 6 need <location>/pi-sandbox.env from scripts/real-host/install-pi-sandbox.sh,
# default location ~/agents-pi-sandbox, or the path given as an argument. Without it they
# print SKIPPED with the command to run, and the exit status says Pi was not shown. If
# step 4 fails, steps 5 and 6 are marked NOT RUN. This script never installs them.
#
# What it uses: real DSH and Pi, with children and one reviewer on DeepSeek, a few short
# turns each. DEEPSEEK_API_KEY comes from the environment or else from ~/.zshrc and is
# never printed, logged or stored; it is in the Python process's environment only during
# steps 2, 3, 5 and 6. Stub reviewers and the stub model bind 127.0.0.1 and never see it.
# Nothing is installed outside the run directory: a dedicated venv with an editable
# install of this Worktree, no PyPI; websockets is linked from the persistent .venv-runtime.
#
# Every fixture sits in a new directory under $HOME, because a child's sandbox may reach
# $TMPDIR and /tmp. The directory is printed and kept; delete it when done. Children only
# write inside it. It stops if the Worktree is not on the 387 branch or has uncommitted
# changes, because the venv imports the live tree. Written for macOS /bin/bash 3.2.
# Exit status: 0 only when every criterion printed PASS; 1 otherwise, SKIPPED and NOT RUN
# included; 2 when it stopped early.
set -uo pipefail

WORKTREE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/387-review-plugin-pi-dsh-adapters
PYTHON=/Users/luoxiao/miniconda3/bin/python3.13
BRANCH=agent/387-review-plugin-pi-dsh-adapters
WEBSOCKETS=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.venv-runtime/lib/python3.13/site-packages/websockets
SCOPE=all
SANDBOX_LOCATION=
while [ $# -gt 0 ]; do
  case "$1" in
    --only)
      case "${2:-}" in
        dsh|pi) SCOPE=$2; shift 2 ;;
        *) echo "STOP: --only takes dsh or pi, got: ${2:-nothing}"; exit 2 ;;
      esac ;;
    -*) echo "STOP: expected [--only dsh|pi] [sandbox-location], got: $1"; exit 2 ;;
    *)
      if [ -n "$SANDBOX_LOCATION" ]; then echo "STOP: give one sandbox location, got also: $1"; exit 2; fi
      SANDBOX_LOCATION=$1; shift ;;
  esac
done
SANDBOX_LOCATION=${SANDBOX_LOCATION:-$HOME/agents-pi-sandbox}
SANDBOX_ENV=$SANDBOX_LOCATION/pi-sandbox.env
INSTALLER=$WORKTREE/scripts/real-host/install-pi-sandbox.sh
# DSH takes this variable as its Messages root, and a child inherits this environment.
unset DEEPSEEK_BASE_URL
# The reviewer; checked against the endpoint's own list and replaced if it is not listed.
REVIEWER_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
# The children's models, from each Runtime's own catalog (as Task 383's tests and `pi --list-models`).
DSH_MODEL=deepseek-flash
PI_PROVIDER=deepseek
PI_MODEL=deepseek-flash

RUN=$(mktemp -d "$HOME/agents-387-review.XXXXXX") || exit 2
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
PI=$(command -v pi || true)
DSH=$(command -v dsh || true)
if [ -z "$PI" ] || [ -z "$DSH" ]; then
  echo "STOP: pi ($PI) or dsh ($DSH) is not on PATH."
  exit 2
fi
echo "pi:            $PI ($("$PI" --version 2>&1 | head -1))"
echo "dsh:           $DSH ($("$DSH" --version 2>&1 | head -1))"
echo "node:          $(command -v node) ($(node --version 2>&1))"
echo "python:        $("$PYTHON" --version 2>&1)"
echo "scope:         $SCOPE"
if [ -z "${DEEPSEEK_BASE_URL+set}" ]; then
  echo "DEEPSEEK_BASE_URL: absent"
else
  echo "DEEPSEEK_BASE_URL: PRESENT, which should not happen"
fi
RG=$(command -v rg || true)
if [ -z "$RG" ] && [ -x "$SANDBOX_LOCATION/bin/rg" ]; then RG=$SANDBOX_LOCATION/bin/rg; fi
RG_DIR=
if [ -n "$RG" ]; then
  RG_DIR=$(cd "$(dirname "$RG")" && pwd)
  echo "ripgrep:       $RG ($("$RG" --version 2>&1 | head -1)); its directory is added to sandbox_path for this run"
else
  echo "ripgrep:       absent, on PATH and at $SANDBOX_LOCATION/bin/rg; this script does not install it, and the srt pair step will fail with srt's own error"
fi
if [ -f "$SANDBOX_ENV" ]; then
  echo "pi sandbox:    $SANDBOX_ENV present"
else
  echo "pi sandbox:    $SANDBOX_ENV absent, so agent_sandbox and srt are not reported installed"
fi

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
  echo "DEEPSEEK_API_KEY: unset; steps 2, 3, 5 and 6 will FAIL with that reason"
fi

# begin one_line
mkdir -p "$RUN/preflight"
SELF_REPORT='In one line, state the model name you are running as. Do not run tools or print any key or token.'
printf '%s\n' "$SELF_REPORT" > "$RUN/preflight/task.txt"

redacted() {
  # Print one line without the key, whatever a Runtime's failure says.
  if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    printf '%s\n' "${1//"$DEEPSEEK_API_KEY"/[redacted]}"
  else
    printf '%s\n' "$1"
  fi
}

one_line() {
  # Run a command with stdin from $1, bounded at 120 s; print its answer, or the failure's
  # last line. Its output stays only in these files, removed here. Never fatal.
  local input=$1 out="$RUN/preflight/out.$$" err="$RUN/preflight/err.$$" status=0
  shift
  (cd "$RUN/preflight" && perl -e 'alarm shift; exec @ARGV' 120 "$@" <"$input" >"$out" 2>"$err") || status=$?
  if [ "$status" -eq 0 ]; then
    redacted "$(tail -1 "$out")"
  else
    local last
    last=$(tail -1 "$err")
    [ -n "$last" ] || last=$(tail -1 "$out")
    echo "(failed, exit $status; 142 is the 120 s limit)"
    redacted "$last"
  fi
  rm -f "$out" "$err"
}

echo "dsh one-line answer with its configured model (no reviewer, read-only, at most 120 s):"
one_line "$RUN/preflight/task.txt" "$DSH" headless --permission-mode read-only -
echo "pi one-line answer with $PI_PROVIDER/$PI_MODEL (no reviewer, no tools, at most 120 s); its key comes from the environment:"
mkdir -p "$RUN/preflight/pi-home"
one_line /dev/null env PI_CODING_AGENT_DIR="$RUN/preflight/pi-home" PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0 \
  "$PI" --print --no-tools --provider "$PI_PROVIDER" --model "$PI_MODEL" "$SELF_REPORT"
# end one_line

"$PYTHON" -m venv --system-site-packages "$VENV" || exit 2
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --no-index --no-deps \
  --no-build-isolation -e "$WORKTREE/src/agent_swarm" -e "$WORKTREE" || exit 2
if ! "$VENV/bin/python" -c 'import websockets' 2>/dev/null; then
  ln -s "$WEBSOCKETS" "$VENV/lib/python3.13/site-packages/websockets"
fi
cd "$RUN" || exit 2

cat > "$RUN/probe_sandbox.py" <<'PROBE_EOF'
"""Run one command through agent_sandbox as pi/launch.py does; print one JSON result."""
import json
import os
from pathlib import Path
import subprocess
import sys

from agent_sandbox import is_sandbox_available, resolve_profile, wrap_command

policy_file, granted, target = sys.argv[1:4]
if not is_sandbox_available():
    raise SystemExit('agent_sandbox reports no sandbox available')
selected = {'network': {'allowedDomains': [], 'deniedDomains': []},
            'filesystem': {'denyRead': [], 'allowRead': [], 'allowWrite': [granted], 'denyWrite': []}}
native = resolve_profile('locked')
for field in ('denyRead', 'denyWrite'):
    selected['filesystem'][field] = list(dict.fromkeys(
        native.get('filesystem', {}).get(field, []) + selected['filesystem'][field]))
Path(policy_file).write_text(json.dumps(selected), encoding='utf-8')
# srt joins argv with plain spaces, so this is one shell string for its inner bash.
argv = ['/bin/echo', 'ok', '>', target]
command = wrap_command(argv, policy_file)
if command == argv:
    raise SystemExit('wrap_command returned the command unwrapped')
environment = dict(os.environ)
environment.update({'ASB_SANDBOX': '1', 'ASB_PROFILE': 'custom',
                    'ASB_PROFILE_JSON': Path(policy_file).read_text(encoding='utf-8')})
done = subprocess.run(command, cwd='/', env=environment, capture_output=True, text=True, timeout=60)
print(json.dumps({'command': command, 'exit': done.returncode, 'stderr': done.stderr[-1500:], 'stdout': done.stdout[-300:]}))
PROBE_EOF

cat > "$RUN/parent.py" <<'PARENT_EOF'
"""Act as the direct parent of real children through the public agents API."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import yaml

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.dsh.driver import DshDriver
from agent_swarm.pi import PiDriver
from agent_swarm.pi import execution as pi_execution
from agent_swarm.review import _NoRedirect

RUN = Path(sys.argv[1])
ENV = os.environ
# Out of the environment now, so that no child inherits it outside its steps.
KEY = ENV.pop('DEEPSEEK_API_KEY', None)
DEEPSEEK_MODEL = ENV['DEEPSEEK_MODEL']
MODEL_PROBLEM: str | None = None
# The reviewer's own variable, so a child's connection does not also name it.
REVIEW_VARIABLE = 'AGENTS_387_REVIEW_KEY'
SCOPE = ENV.get('SCOPE', 'all')
OUT_OF_SCOPE = {'dsh': 'the Pi protocol probe, the srt pair and every Pi child step',
                'pi': 'every DSH child step'}
RESULTS: list[tuple[str, str]] = []
FOLLOW_UPS: list[str] = []
MISSING_SESSION = {'error': {'code': 'MissingSessionID', 'message': 'session id is required', 'type': 'invalid_request_error'}}
SANDBOX_ENV = Path(ENV['SANDBOX_ENV'])
SANDBOX: dict[str, str] = {}
REFUSE_NOTE = ('If the call is refused, do not try anything else and use no other tool: reply with one line saying it '
               'was refused. Then reply done.')


def clean(text: object) -> str:
    """Return ``text`` without the key, whatever a child or a tool printed."""
    text = str(text)
    return text.replace(KEY, '[redacted]') if KEY else text


def verdict(name: str, state: str | bool, *proof: object) -> None:
    """Print one criterion with the raw lines proving it."""
    state = {True: 'PASS', False: 'FAIL'}.get(state, state)
    print(f'{state}: {name}')
    for line in proof:
        print('    ' + clean(line))
    RESULTS.append((name, state))


def completion(decision: dict) -> tuple[int, dict]:
    """Return a valid chat completion holding one decision document."""
    return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(decision)}}]}


class Stub:
    """A chat completions reviewer on 127.0.0.1; passes the check at create, then ``answer()``."""

    def __init__(self, answer) -> None:
        stub = self
        self.calls = 0

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                """Answer one review."""
                body = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
                if 'agents/connectivity-check' in body:
                    status, document = completion({'decision': 'allow', 'reason': 'Stub is reachable.'})
                else:
                    stub.calls += 1
                    status, document = answer()
                payload = json.dumps(document).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

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


def refusal(request: dict) -> dict:
    """Return the reply that refuses one request in its own form."""
    method = str(request.get('method'))
    if method == 'dsh/approval-request':
        return {'decision': 'reject'}
    if method.startswith('pi/'):
        return {'cancelled': True}
    return {'decision': 'decline'}


class Child:
    """One step's data root, workspace and parent over one reviewed Runtime."""

    def __init__(self, step: str, runtime: str, reviewer: dict) -> None:
        self.runtime = runtime
        self.directory = RUN / step
        self.data = self.directory / 'data'
        self.work = self.directory / 'work'
        self.work.mkdir(parents=True)
        self.data.mkdir()
        (self.data / 'config.yml').write_text(yaml.safe_dump({
            'reviewers': {'checker': reviewer},
            'connections': {'reviewed': {'runtime': runtime, 'review': 'checker', 'api_key_env': 'DEEPSEEK_API_KEY'}},
        }))
        self.notices: list[dict] = []
        if runtime == 'dsh':
            driver = DshDriver(self.work, {'executable': ENV['DSH_BIN'], 'model': ENV['DSH_MODEL'],
                                           'reasoning_effort': 'low', 'sandbox': 'workspace-write'})
        else:
            # Empty, so this child reads no extension or login of yours; its key is the connection's.
            home, git = self.directory / 'pi-home', self.directory / 'git-common'
            home.mkdir()
            git.mkdir()
            driver = PiDriver({
                'executable': ENV['PI_BIN'], 'provider': ENV['PI_PROVIDER'], 'model': ENV['PI_MODEL'],
                'worktree_path': str(self.work), 'agent_dir': str(home), 'instructions': '',
                'sandbox_python': SANDBOX['sandbox_python'], 'sandbox_path': SANDBOX['sandbox_path'],
                'worktree_access': 'write', 'git_common_directory': str(git),
            })
        self.control = AgentControl(self.data, {runtime: driver}, event_receiver=self.notices.append,
                                    request_notices=True)
        self.call = bind(self.control, Caller('387-real-host', 'parent-387', 'parent-387-session', runtime))
        self.agent: str | None = None

    def invoke(self, action: str, **arguments: object) -> dict:
        """Return one public result document."""
        return self.call({'action': action, **arguments}).document

    def create(self, target: Path) -> dict:
        """Create the child with one harmless tool call that appends one line to ``target``."""
        instruction = (f'Run exactly one shell command, once: echo ran >> {target}\nRun nothing else and use no other '
                       f'tool. Your direct parent authorizes appending this one line in your own workspace. {REFUSE_NOTE}')
        document = self.invoke('create', runtime=self.runtime, instruction=instruction)
        if 'agent' not in document:
            raise RuntimeError(f'create failed: {json.dumps(document, ensure_ascii=False)}')
        self.agent = document['agent']
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
        """Wait for standby, declining anything further a child asks after the answer under test."""
        deadline = time.monotonic() + seconds
        refused: set = set()
        while time.monotonic() < deadline:
            result = self.invoke('status', agent=self.agent).get('result', {})
            if result.get('state') == 'standby':
                return result
            for request in self.requests():
                if request.get('request_id') in refused:
                    continue
                print('    a further request is declined:', request['method'], clean(json.dumps(request.get('params'))[:200]))
                receipt = self.invoke('reply', agent=self.agent, request=request, response=refusal(request))
                if receipt.get('error'):
                    print('    the decline was refused:', clean(json.dumps(receipt['error'])))
                    refused.add(request.get('request_id'))
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
        """Stop the child and keep follow-up commands with real identities."""
        try:
            for _ in self.control.interrupt_owned():
                self.standby(30)
        except Exception as error:
            print('    closing:', clean(type(error).__name__), clean(error))
        for path in self.data.rglob('review.jsonl'):
            FOLLOW_UPS.append(f'cat {path}')
        if self.agent is not None:
            FOLLOW_UPS.append(f'ls {self.data}/native/*')


def diagnosis(child: Child) -> list[str]:
    """Return how the child stands, so that a failed start never reads as 'no request arrived'."""
    if child.agent is None:
        return ['child: no Agent was created']
    result = child.invoke('status', agent=child.agent).get('result', {})
    last = result.get('last_result') or {}
    facts = {name: result[name] for name in ('state', 'session', 'stopping', 'diagnostic', 'pending_requests') if name in result}
    lines = [f'child: {json.dumps(facts, ensure_ascii=False)}',
             f"last result: {json.dumps({name: last.get(name) for name in ('outcome', 'error', 'last_message')}, ensure_ascii=False)[:1500]}"]
    for path in child.data.rglob('stderr.log'):
        tail = path.read_text(errors='replace').strip()[-1200:]
        if tail:
            lines.append(f'{path}: ...{tail}')
    lines.extend(turn_errors(child.data))
    return lines


def turn_errors(root: Path) -> list[str]:
    """Return the error of each native log's last turn/end, which the driver's message drops."""
    found = []
    for path in root.rglob('session.v4.jsonl'):
        last = None
        for line in path.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'turn/end':
                last = event
        reason = ((last or {}).get('data') or {}).get('reason') or {}
        if reason.get('error') is not None:
            found.append(clean(f"last turn/end in {path.name}: {reason.get('kind')}: {json.dumps(reason['error'], ensure_ascii=False)[:800]}"))
    return found


def judge(child: Child, name: str, state: bool, *proof: object) -> None:
    """Print a criterion, with the child's last result and error unless it passed."""
    verdict(name, state, *proof, *([] if state else diagnosis(child)))


def lines_of(path: Path) -> list[str]:
    """Return what the one allowed call wrote; once means exactly one line."""
    return path.read_text().splitlines() if path.exists() else []


@contextmanager
def child_keys():
    """Hold the real key in this process's environment only while a child or reviewer needs it."""
    ENV['DEEPSEEK_API_KEY'] = KEY or ''
    ENV[REVIEW_VARIABLE] = KEY or ''
    try:
        yield
    finally:
        ENV.pop('DEEPSEEK_API_KEY', None)
        ENV.pop(REVIEW_VARIABLE, None)


def pick_reviewer_model() -> None:
    """Check the reviewer's model against the endpoint's own list, printing what it lists."""
    global DEEPSEEK_MODEL, MODEL_PROBLEM
    print('\n== The models the reviewer endpoint lists')
    if not KEY:
        print('    skipped: DEEPSEEK_API_KEY is unset')
        return
    request = Request(ENV['REVIEWER_BASE_URL'].rstrip('/') + '/models', headers={'Authorization': 'Bearer ' + KEY})
    try:
        # No redirect: the key stays on the configured endpoint.
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            ids = [item['id'] for item in json.loads(response.read())['data'] if isinstance(item['id'], str)]
    except HTTPError as error:
        print(f'    listing failed with HTTP status {error.code}; keeping the configured model {DEEPSEEK_MODEL}')
        return
    except Exception as error:
        print(f'    listing failed ({type(error).__name__}); keeping the configured model {DEEPSEEK_MODEL}')
        return
    print('    ids:', ids)
    if DEEPSEEK_MODEL in ids:
        print(f'    using {DEEPSEEK_MODEL}: the configured model is listed')
        return
    for word in ('flash', 'chat'):
        chosen = next((item for item in ids if word in item), None)
        if chosen is not None:
            print(f'    using {chosen}: {DEEPSEEK_MODEL} is not listed, and this is the first id containing {word!r}')
            DEEPSEEK_MODEL = chosen
            return
    MODEL_PROBLEM = f"the endpoint lists neither {DEEPSEEK_MODEL} nor an id containing 'flash' or 'chat': {ids}"


def key_blocker() -> str | None:
    """Return why a step with a real child cannot run, if so."""
    return 'DEEPSEEK_API_KEY is unset' if not KEY else None


def allow_step(step: str, runtime: str) -> None:
    """A real child and a real reviewer: the call runs, and nothing reaches the parent."""
    name = f'{runtime}, reviewer allow: review.jsonl has allow, the file exists, no request reached the parent'
    print(f'\n== {runtime}: reviewer allow (real DeepSeek reviewer, model {DEEPSEEK_MODEL})')
    blocker = key_blocker() or MODEL_PROBLEM
    if blocker:
        verdict(name, False, blocker)
        return
    child = None
    with child_keys():
        try:
            child = Child(step, runtime, {'base_url': ENV['REVIEWER_BASE_URL'], 'model': DEEPSEEK_MODEL,
                                          'api_key_env': REVIEW_VARIABLE, 'json_mode': True, 'timeout_seconds': 60})
            target = child.work / 'allowed.txt'
            created = child.create(target)
            print('    created:', json.dumps({field: created['result'].get(field) for field in ('runtime', 'connection', 'review')}))
            state = child.settle()
            requests = child.requests() if state == 'request' else []
            final = child.standby() if state != 'request' else {}
            reviews = child.reviews()
            judge(child, name, state == 'standby' and lines_of(target) == ['ran']
                  and any(line['decision'] == 'allow' for line in reviews) and not child.request_notices() and not requests,
                  f'settled as: {state}; file lines: {lines_of(target)}',
                  f"decisions: {[(line['tool'], line['decision']) for line in reviews]}",
                  f"requests: {[(item['method'], item.get('params', {}).get('reason')) for item in requests]}",
                  f"final state: {final.get('state')}")
        except Exception:
            print(clean(traceback.format_exc()))
            verdict(name, False, 'the step ended with an unexpected error', *(diagnosis(child) if child else []))
        finally:
            if child is not None:
                child.close()


def held_step(step: str, runtime: str, stub_answer, kind: str, response: dict, expected_reason: str) -> None:
    """A real child and a stub reviewer: the request reaches the parent and its answer decides."""
    answer = response['decision']
    name = f'{runtime}, {kind}: agents/review reached the parent, the file was absent before the reply, {answer} ' + (
        'ran it once' if answer == 'accept' else 'left it absent')
    print(f'\n== {runtime}: {kind}, the parent answers {answer}')
    if key_blocker():
        verdict(name, False, key_blocker())
        return
    stub, child = Stub(stub_answer), None
    with child_keys():
        try:
            child = Child(step, runtime, stub.entry)
            target = child.work / 'held.txt'
            child.create(target)
            state = child.settle()
            requests = child.requests() if state == 'request' else []
            held = [item for item in requests if item['method'] == 'agents/review']
            before = lines_of(target)
            if not held:
                judge(child, name, False, f'settled as: {state}; requests: {requests}; file lines: {before}')
                return
            request = held[0]
            params = request['params']
            print('    held:', clean(json.dumps({field: request[field] for field in ('method', 'request_id')})),
                  clean(json.dumps(params)[:300]))
            receipt = child.invoke('reply', agent=child.agent, request=request, response=response)
            print('    reply:', clean(json.dumps(receipt.get('error') or {field: receipt['result'].get(field) for field in ('request_id', 'reply_status')})))
            final = child.standby()
            after = lines_of(target)
            judge(child, name, not before and request['request_id'].startswith('agents-review:')
                  and expected_reason in params['reason'] and stub.calls >= 1
                  and after == (['ran'] if answer == 'accept' else []) and final.get('state') == 'standby',
                  f'file lines before the reply: {before}; after: {after}',
                  f"reason: {params['reason']}; reviewer calls: {stub.calls}; final state: {final.get('state')}",
                  f"decisions: {[(line['tool'], line['decision']) for line in child.reviews()]}")
        except Exception:
            print(clean(traceback.format_exc()))
            verdict(name, False, 'the step ended with an unexpected error', *(diagnosis(child) if child else []))
        finally:
            if child is not None:
                child.close()
            stub.close()


def escalate() -> tuple[int, dict]:
    return completion({'decision': 'escalate', 'reason': 'Stub reviewer sends this to the parent.'})


def broken() -> tuple[int, dict]:
    return 400, MISSING_SESSION


def held_steps(prefix: str, runtime: str) -> None:
    """Every back-to-parent case of one Runtime."""
    held_step(f'{prefix}-escalate-accept', runtime, escalate, 'reviewer escalates', {'decision': 'accept'}, 'Stub reviewer')
    held_step(f'{prefix}-escalate-decline', runtime, escalate, 'reviewer escalates', {'decision': 'decline'}, 'Stub reviewer')
    held_step(f'{prefix}-broken-accept', runtime, broken, 'reviewer breaks after create', {'decision': 'accept'}, 'MissingSessionID')


# -- Pi protocol probe --------------------------------------------------------

def sse(document: dict) -> bytes:
    """Encode one event of a chat completions stream."""
    return b'data: ' + json.dumps(document).encode() + b'\n\n'


def stub_model(path: Path):
    """A streaming chat completions model on 127.0.0.1: one write call, then a final answer."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            """Ask for one tool call until the request carries its result."""
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            answered = any(message.get('role') == 'tool' for message in body.get('messages', []))
            base = {'id': 'probe', 'object': 'chat.completion.chunk', 'created': 1, 'model': body.get('model')}
            if answered:
                delta, finish = {'role': 'assistant', 'content': 'done'}, 'stop'
            else:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_probe', 'type': 'function', 'function': {
                    'name': 'write', 'arguments': json.dumps({'path': str(path), 'content': 'ran\n'})}}]}
                finish = 'tool_calls'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(sse({**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}))
            self.wfile.write(sse({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}))
            self.wfile.write(b'data: [DONE]\n\n')

        def log_message(self, *_: object) -> None:
            """Keep the output to the criteria."""

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def rpc_case(directory: Path, confirmed: bool) -> tuple[bool, list[str]]:
    """Drive real Pi over raw RPC with the real extension; return whether the case held."""
    directory.mkdir(parents=True)
    home, work = directory / 'pi-home', directory / 'work'
    home.mkdir()
    work.mkdir()
    target = work / 'probe.txt'
    server = stub_model(target)
    (home / 'models.json').write_text(json.dumps({'providers': {'stub': {
        'baseUrl': f'http://127.0.0.1:{server.server_address[1]}/v1', 'api': 'openai-completions', 'apiKey': 'none',
        'models': [{'id': 'stub-model'}]}}}))
    extension = Path(pi_execution.__file__).with_name('extension.mjs')
    environment = {**ENV, 'PI_CODING_AGENT_DIR': str(home), 'PI_OFFLINE': '1', 'PI_SKIP_VERSION_CHECK': '1',
                   'PI_TELEMETRY': '0', pi_execution.REVIEW_ENV: 'agents-review:probe'}
    environment.pop('DEEPSEEK_API_KEY', None)
    process = subprocess.Popen([ENV['PI_BIN'], '--mode', 'rpc', '--no-session', '--provider', 'stub', '--model', 'stub-model',
                                '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
                                '--extension', str(extension)],
                               cwd=work, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, bufsize=1)
    errors: list[str] = []
    threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True).start()

    def send(document: dict) -> None:
        process.stdin.write(json.dumps(document) + '\n')
        process.stdin.flush()

    proof: list[str] = []
    hooked, dialog_first, tool_error, settled = False, None, None, False
    timer = threading.Timer(120, process.kill)
    timer.start()
    try:
        send({'id': 'commands', 'type': 'get_commands'})
        send({'id': 'prompt', 'type': 'prompt', 'message': 'Call the tool.'})
        for line in process.stdout:
            event = json.loads(line)
            kind = event.get('type')
            if kind == 'response' and event.get('id') == 'commands':
                names = [item['name'] for item in event['data']['commands']]
                hooked = pi_execution.REVIEW_COMMAND in names
                proof.append(f'get_commands: {names}')
            elif kind == 'response' and not event.get('success'):
                proof.append(f"{event.get('command')} failed: {event.get('error')}")
            elif kind == 'extension_ui_request' and event.get('method') == 'confirm':
                dialog_first = not target.exists()
                proof.append(f"dialog: title {event.get('title')!r}, message {event.get('message')}, "
                             f"timeout {event.get('timeout')}, file absent at the dialog: {dialog_first}")
                send({'type': 'extension_ui_response', 'id': event['id'], 'confirmed': confirmed})
            elif kind == 'tool_execution_end':
                tool_error = event.get('isError')
                proof.append(f"tool {event.get('toolName')} ended, isError {tool_error}: {json.dumps(event.get('result'))[:200]}")
            elif kind == 'message_end' and (event.get('message') or {}).get('stopReason') == 'error':
                proof.append(f"model error: {(event.get('message') or {}).get('errorMessage')}")
            elif kind == 'agent_settled':
                settled = True
                break
    finally:
        timer.cancel()
        process.stdin.close()
        process.terminate()
        server.shutdown()
    exists = target.exists()
    proof.append(f'file exists after: {exists}; settled: {settled}')
    if errors:
        proof.append('stderr: ' + ''.join(errors)[-600:])
    holds = hooked and dialog_first is True and settled and exists is confirmed and tool_error is (not confirmed)
    return holds, proof


def step_probe() -> None:
    """Real pi --mode rpc: the reserved dialog arrives before the tool runs and decides it."""
    print('\n== Pi protocol probe: real `pi --mode rpc`, real extension.mjs, stub model on 127.0.0.1, no credentials')
    print('    This proves the hook on the real binary only, not the sandboxed child.')
    for confirmed in (True, False):
        name = ('Pi protocol probe: the reserved dialog arrives before the tool runs, confirmed:true runs it'
                if confirmed else 'Pi protocol probe: the reserved dialog arrives before the tool runs, confirmed:false blocks it')
        try:
            holds, proof = rpc_case(RUN / 'probe' / ('confirmed' if confirmed else 'refused'), confirmed)
            verdict(name, holds, *proof)
        except Exception:
            print(clean(traceback.format_exc()))
            verdict(name, False, 'the probe ended with an unexpected error')


# -- The srt and agent-sandbox pair ------------------------------------------

def read_sandbox() -> bool:
    """Load pi-sandbox.env, or report what is missing and how to get it."""
    if not SANDBOX_ENV.is_file():
        verdict('Pi child steps (4 to 6)', 'SKIPPED',
                f'missing: {SANDBOX_ENV}, so agent_sandbox and srt are not reported installed; Pi was not shown.',
                f"To install: /bin/bash {ENV['INSTALLER']}")
        return False
    for line in SANDBOX_ENV.read_text().splitlines():
        field, _, value = line.partition('=')
        SANDBOX[field] = value
    # In memory only: pi-sandbox.env stays as the installer wrote it.
    ripgrep = ENV.get('RG_DIR')
    if ripgrep and ripgrep not in SANDBOX['sandbox_path'].split(os.pathsep):
        SANDBOX['sandbox_path'] += os.pathsep + ripgrep
    print('sandbox_path for this run:', SANDBOX['sandbox_path'])
    return True


def srt_facts() -> list[str]:
    """Return which srt runs: path, manifest, lock entry and banner, which is not the version."""
    resolved = shutil.which('srt', path=SANDBOX['sandbox_path'])
    if resolved is None:
        return [f"no srt on sandbox_path {SANDBOX['sandbox_path']}"]
    package = Path(resolved).resolve()
    while package != package.parent and not (package / 'package.json').is_file():
        package = package.parent
    manifest = json.loads((package / 'package.json').read_text())
    lines = [f'srt on sandbox_path: {resolved}', f'resolved: {Path(resolved).resolve()}',
             f"package: {manifest.get('name')} {manifest.get('version')} ({package})"]
    root = Path(resolved).parent.parent.parent
    try:
        entry = json.loads((root / 'package-lock.json').read_text())['packages'][f"node_modules/{manifest.get('name')}"]
        lines.append(f"package-lock: {entry.get('resolved')} integrity {entry.get('integrity')}")
    except (OSError, ValueError, KeyError) as error:
        lines.append(f'package-lock unreadable: {type(error).__name__}: {error}')
    banner = subprocess.run([resolved, '--version'], capture_output=True, text=True, timeout=30,
                            env={**ENV, 'PATH': SANDBOX['sandbox_path']})
    lines.append(f"srt --version banner (not the package version): {(banner.stdout + banner.stderr).strip()[:100]}")
    return lines


def step_compatibility() -> bool:
    """Show the installed pair works, with no model: PASS only on both writes."""
    name = 'srt and agent-sandbox: through wrap_command a write inside a grant succeeds and one outside it is refused'
    print('\n== The srt and agent-sandbox pair, with no model')
    directory = RUN / 'compatibility'
    granted, other = directory / 'granted', directory / 'not-granted'
    granted.mkdir(parents=True)
    other.mkdir()
    proof: list[str] = []
    try:
        proof += srt_facts()
        outcomes = []
        for label, target in (('inside the grant', granted / 'file.txt'), ('outside the grant', other / 'file.txt')):
            done = subprocess.run([SANDBOX['sandbox_python'], ENV['PROBE_SANDBOX'], str(directory / f'{label[:6]}.json'),
                                   str(granted), str(target)], capture_output=True, text=True, timeout=120,
                                  env={**ENV, 'PATH': SANDBOX['sandbox_path']})
            if done.returncode != 0:
                proof.append(f'{label}: the probe itself failed with exit {done.returncode}: {done.stderr[-800:]}')
                outcomes.append(None)
                continue
            result = json.loads(done.stdout.splitlines()[-1])
            proof.append(f"{label}: exit {result['exit']}, file exists {target.exists()}, command {result['command'][:6]}, "
                         f"stderr {result['stderr'][-500:]!r}")
            outcomes.append((result['exit'], target.exists()))
        inside, outside = outcomes
        works = (inside is not None and outside is not None and inside == (0, True)
                 and outside[0] != 0 and outside[1] is False)
    except Exception as error:
        proof.append(f'{type(error).__name__}: {error}')
        works = False
    verdict(name, works, *proof)
    return works


def main() -> int:
    """Run every step and report."""
    print('\nDEEPSEEK_API_KEY in this process before the steps:', 'present' if 'DEEPSEEK_API_KEY' in ENV else 'absent')
    print('DEEPSEEK_BASE_URL in this process:', 'PRESENT' if 'DEEPSEEK_BASE_URL' in ENV else 'absent')
    print('scope:', SCOPE)
    if SCOPE != 'dsh':
        step_probe()
    pick_reviewer_model()
    if SCOPE != 'pi':
        for step in (lambda: allow_step('dsh-allow', 'dsh'), lambda: held_steps('dsh', 'dsh')):
            try:
                step()
            except Exception:
                print(clean(traceback.format_exc()))
                verdict('a DSH step finished without an unexpected error', False)
    if SCOPE != 'dsh' and read_sandbox():
        if step_compatibility():
            for step in (lambda: allow_step('pi-allow', 'pi'), lambda: held_steps('pi', 'pi')):
                try:
                    step()
                except Exception:
                    print(clean(traceback.format_exc()))
                    verdict('a Pi step finished without an unexpected error', False)
        else:
            verdict('Pi child steps (5 and 6)', 'NOT RUN',
                    'the srt and agent-sandbox pair failed above, so no Pi child ran; Pi was not shown.',
                    'Using another srt source needs the user\'s decision; this script does not fall back to one.')
    print('\n== Summary')
    for name, state in RESULTS:
        print(f'{state}: {name}')
    if SCOPE in OUT_OF_SCOPE:
        print(f'SCOPED RUN (--only {SCOPE}): not run: {OUT_OF_SCOPE[SCOPE]}. '
              'A PASS above covers this scope only, not the whole criterion.')
    print('\n== Follow-up commands')
    for command in FOLLOW_UPS:
        print(command)
    return 0 if RESULTS and all(state == 'PASS' for _, state in RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
PARENT_EOF

PI_BIN="$PI" DSH_BIN="$DSH" DSH_MODEL="$DSH_MODEL" PI_PROVIDER="$PI_PROVIDER" PI_MODEL="$PI_MODEL" \
  REVIEWER_BASE_URL="$REVIEWER_BASE_URL" DEEPSEEK_MODEL="$DEEPSEEK_MODEL" SANDBOX_ENV="$SANDBOX_ENV" \
  INSTALLER="$INSTALLER" PROBE_SANDBOX="$RUN/probe_sandbox.py" SCOPE="$SCOPE" RG_DIR="$RG_DIR" \
  "$VENV/bin/python" "$RUN/parent.py" "$RUN"
STATUS=$?
echo
echo "== Run directory (kept): $RUN"
echo "cat $RUN/output.log"
echo "== Expected native review dialog: none"
if [ "$SCOPE" != all ]; then
  echo "scope: --only $SCOPE; this exit status covers that scope, not the whole criterion"
fi
echo "exit status: $STATUS"
exit $STATUS
