"""Drive the real hosts for the 392 steps and read what they show.

A step's zsh file sets RH_* (common.zsh ``run_python``) and runs ``checks.py``. This module starts
each host the way earlier real-host scripts did (realhost-381, 383, 403, 406), gives it one prompt
per turn, keeps its raw output in the step's evidence directory, and returns the public agents
results and notices the parent received. Nothing here reads agents' internal records to decide a
criterion unless the criterion names them. The DeepSeek value is never read here: it reaches a host
through the inherited environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

import yaml

ENV = os.environ
HERE = Path(__file__).resolve().parent
RUN = Path(ENV['RH_RUN'])
OUT = Path(ENV['RH_OUT'])
AG = Path(ENV['RH_AG'])
PYTHON = ENV['RH_PYTHON']
CLAUDE = ENV['RH_CLAUDE']
CODEX = ENV['RH_CODEX']
PI = ENV['RH_PI']
DSH = ENV['RH_DSH']
CLAUDE_MODEL = ENV['RH_CLAUDE_MODEL']
CODEX_MODEL = ENV['RH_CODEX_MODEL']
DEEPSEEK_MODEL = ENV['RH_DEEPSEEK_MODEL']
PI_PROVIDER = ENV['RH_PI_PROVIDER']
SANDBOX_PYTHON = ENV['RH_SANDBOX_PYTHON']
SANDBOX_PATH = ENV['RH_SANDBOX_PATH']
KEY_VARIABLE = 'DEEPSEEK_API_KEY'
CLAUDE_PROJECT = AG / 'claude-project'
# Dry runs route this one module to a stub; a real step never sets it.
CODEX_HOST = ENV.get('RH_DRY_CODEX_HOST')
RUNTIMES = ('claude', 'codex', 'pi', 'dsh')
DEFAULT_LIMIT = 900
# The parent's small model and each child's explicit model and effort.
CHILD_CHOICE = {
    'claude': (CLAUDE_MODEL, 'low'),
    'codex': (CODEX_MODEL, 'low'),
    'pi': (DEEPSEEK_MODEL, 'low'),
    'dsh': (DEEPSEEK_MODEL, 'low'),
}
# Runtimes that take a shell command for a long-running child with no approval on the way.
SLEEP = 'Run the shell command /bin/sleep {seconds}, then reply with exactly: {answer}'


def check(state: str, text: str) -> None:
    """Add one PASS, FAIL or CANNOT criterion line to the summary and the terminal."""
    line = f'{state} {text}'
    print(line, flush=True)
    with (OUT / 'summary.txt').open('a') as summary:
        summary.write(line + '\n')


def judge(passed: bool, name: str, observed: object = '') -> bool:
    """Record one criterion with its observable; return whether it passed."""
    check('PASS' if passed else 'FAIL', f'{name}: {observed}')
    return passed


def note(text: str) -> None:
    """Keep one observation in the summary without judging it."""
    print(f'note: {text}', flush=True)
    with (OUT / 'summary.txt').open('a') as summary:
        summary.write(f'note: {text}\n')


def call(feature: str, **arguments: object) -> str:
    """Return the exact tool arguments for one agents feature."""
    return json.dumps({'action': 'execute', 'feature': feature, 'arguments': arguments}, ensure_ascii=False)


def script_prompt(calls: list[str], tail: str = 'Then reply with one line and stop.') -> str:
    """Return a prompt asking the parent to make exactly these calls, in order."""
    lines = ['Use only the agents tool (on Claude Code it is mcp__agents__agents). Make these tool calls one '
             'at a time, in this order, with exactly these arguments. Where an argument says <agent from N>, '
             'use the "agent" field returned by call N.']
    lines += [f'{number}. {text}' for number, text in enumerate(calls, 1)]
    lines.append('A message starting with [agents notice, [GraphTraj notice or [agents ·, a host event from agents, '
                 'or a main_notices field in a result may arrive at any time. They are expected and change nothing: '
                 'keep to the calls above. A result with an "error" field is also expected here: go on to the next '
                 'call, except that a code of starting or stopping means make that same call once more.')
    lines.append(tail)
    return '\n'.join(lines)


def documents(value: object):
    """Yield public agents result documents inside one value, parsing JSON text (383, 403)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, dict):
        if isinstance(value.get('action'), str) and ('result' in value or 'error' in value):
            yield value
            return
        for item in value.values():
            yield from documents(item)
    elif isinstance(value, list):
        for item in value:
            yield from documents(item)


def error_code(document: dict) -> str | None:
    """Return a result document's public error code, if it failed."""
    error = document.get('error')
    return error.get('code') if isinstance(error, dict) else None


def last_result(document: dict) -> dict:
    """Return the Agent document's ``last_result``, or nothing."""
    return (document.get('result') or {}).get('last_result') or {}


class Turn:
    """One host process's run: its results, exit and evidence files."""

    def __init__(self, label: str, documents_seen: list[dict], exit_code: int | None, seconds: float,
                 limited: bool) -> None:
        """Keep the run's facts."""
        self.label, self.documents, self.exit_code = label, documents_seen, exit_code
        self.seconds, self.limited = seconds, limited

    def of(self, action: str, agent: str | None = None) -> list[dict]:
        """Return this turn's results for ``action``, optionally for one Agent."""
        return [item for item in self.documents if item.get('action') == action
                and (agent is None or item.get('agent') == agent)]

    def created(self, runtime: str | None = None) -> dict | None:
        """Return the first successful create, optionally for one Runtime."""
        for item in self.of('create'):
            if item.get('agent') and not item.get('error') and (
                    runtime is None or (item.get('result') or {}).get('runtime') == runtime):
                return item
        return None


def clean_environment(pi_home: Path) -> dict:
    """Return the host's environment: this shell's, without another host's markers.

    DEEPSEEK_BASE_URL stays when set: a DSH child must ignore it (411). The key stays too, by name only.
    """
    environment = {name: value for name, value in ENV.items()
                   if not name.startswith(('GRAPHTRAJ_', 'RH_'))
                   and name not in ('AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE', 'DSH_AGENT_PACKAGE')}
    environment['PI_CODING_AGENT_DIR'] = str(pi_home)
    return environment


def codex_settings(work: Path, **config: object) -> dict:
    """Return the Codex settings document the earlier real runs used, plus extra Codex config."""
    return {'adapter_request': {
        'arguments': [CODEX], 'worktree_path': str(work),
        'session_parameters': {
            'cwd': str(work), 'model': CODEX_MODEL, 'developerInstructions': '',
            'config': {'default_permissions': 'work', **config, 'permissions': {
                'work': {'extends': ':workspace', 'filesystem': {':workspace_roots': {'.': 'write'}}}}},
        }}}


def child_settings(host: str, runtime: str, work: Path, pi_home: Path) -> dict:
    """Return one Runtime's child settings under one host, the keys each host documents."""
    if runtime == 'claude':
        return {'executable': CLAUDE, 'permission_mode': 'default'}
    if runtime == 'codex':
        return codex_settings(work)
    if runtime == 'dsh':
        return {'executable': DSH, 'model': DEEPSEEK_MODEL, 'sandbox': 'read-only', 'api_key_env': KEY_VARIABLE}
    settings = {'provider': PI_PROVIDER, 'model': DEEPSEEK_MODEL, 'agent_dir': str(pi_home), 'instructions': '',
                'sandbox_python': SANDBOX_PYTHON, 'sandbox_path': SANDBOX_PATH, 'worktree_access': 'read',
                'api_key_env': KEY_VARIABLE}
    # Only DSH takes the whole request; the other hosts fill executable themselves.
    if host == 'dsh':
        settings['executable'] = PI
    return settings


def installed_package(name: str) -> Path:
    """Return the directory of one host's files in the venv's installed agents."""
    import agent_swarm

    return Path(agent_swarm.__file__).parent / name


def connection(runtime: str, models: list[str] | None = None, **extra: object) -> dict:
    """Return one declared connection: its models avoid native discovery; no home: the native login."""
    entry: dict = {'runtime': runtime, 'models': models or [CHILD_CHOICE[runtime][0]], **extra}
    if runtime == 'dsh':
        entry['api_key_env'] = KEY_VARIABLE
    if runtime == 'pi':
        entry.update(provider=PI_PROVIDER, api_key_env=KEY_VARIABLE)
    return entry


class Host:
    """One real host, with its own data root, for one or more turns of one parent Session."""

    def __init__(self, kind: str, name: str, runtimes: dict[str, dict | None], config: dict | None = None) -> None:
        """Write the host's configuration; ``runtimes`` maps a child Runtime to settings overrides.

        A ``None`` value takes that Runtime's defaults from :func:`child_settings`.
        """
        self.kind, self.name = kind, name
        self.directory = RUN / name
        self.data = self.directory / 'data'
        self.pi_home = RUN / 'pi-home'
        self.work = CLAUDE_PROJECT if kind == 'claude' else self.directory / 'work'
        for path in (self.data, self.pi_home, self.work):
            path.mkdir(parents=True, exist_ok=True)
        self.environment = clean_environment(self.pi_home)
        self.started = False
        self.session = str(uuid.uuid4())
        self.notices: list[dict] = []
        self.host_log_offset = 0
        settings = {runtime: {**child_settings(kind, runtime, self.work, self.pi_home), **(value or {})}
                    for runtime, value in runtimes.items()}
        self.config_file = self.directory / f'{kind}-host.json'
        getattr(self, f'_setup_{kind}')(settings)
        (self.data / 'config.yml').write_text(yaml.safe_dump(config or {}))
        shutil.copy2(self.config_file, OUT / f'{name}.{self.config_file.name}')
        shutil.copy2(self.data / 'config.yml', OUT / f'{name}.config.yml')

    # -- configuration ---------------------------------------------------

    def _setup_claude(self, settings: dict) -> None:
        """Generate the project's files, then set this run's root and Runtimes (scripts 381, 408, 419)."""
        subprocess.run([PYTHON, '-m', 'agent_swarm.claude.host', 'configuration', '--project', str(self.work),
                        '--claude', CLAUDE, '--write'], cwd=self.work, check=True, stdout=subprocess.DEVNULL)
        self.config_file = self.work / '.agents-control' / 'claude-host.json'
        document = json.loads(self.config_file.read_text())
        # A Pi entry needs the data root outside the project (408); a real step keeps it there always.
        document['root'] = str(self.data)
        document['settings'] = {'permission_mode': 'default'}
        claude = settings.pop('claude', {})
        document['settings'].update({key: value for key, value in claude.items() if key != 'executable'})
        document['runtimes'] = settings
        self.config_file.write_text(json.dumps(document, indent=2))
        self.host_log = self.work / '.agents-control' / 'host.log'

    def _setup_codex(self, settings: dict) -> None:
        """Write the settings file ``agent_swarm.codex.host --settings`` reads."""
        settings.pop('codex', None)
        self.config_file = self.directory / 'codex-settings.json'
        self.config_file.write_text(json.dumps({**codex_settings(self.work), 'runtimes': settings}, indent=2))

    def _setup_pi(self, settings: dict) -> None:
        """Write the Pi host file; the extension and session directory stay with this host."""
        self.sessions = self.directory / 'sessions'
        self.sessions.mkdir(exist_ok=True)
        self.config_file.write_text(json.dumps({'root': str(self.data), **settings}, indent=2))
        self.extension = str(installed_package('pi') / 'extension.mjs')
        self.session = f'rh392-{self.name}-{uuid.uuid4().hex[:8]}'
        self.environment['AGENT_SWARM_PYTHON'] = PYTHON
        self.entries_seen = 0

    def _setup_dsh(self, settings: dict) -> None:
        """Write the DSH host file and create the shared test profile once per step."""
        self.config_file.write_text(json.dumps({'root': str(self.data), **settings}, indent=2))
        self.home = RUN / 'dsh-home'
        self.home.mkdir(exist_ok=True)
        self.environment.update(DSH_HOME=str(self.home), AGENT_SWARM_PYTHON=PYTHON,
                                AGENT_SWARM_DSH_CONFIG=str(self.config_file))
        patch = RUN / 'dsh-main.patch.yml'
        # The Main's own endpoint is named here, so DEEPSEEK_BASE_URL can stay set for the children
        # (411) and the Main's key goes only to this root. The value stays in the environment.
        patch.write_text(yaml.safe_dump([
            {'id': 'llm-deepseek', 'config': {'apiKeyEnv': KEY_VARIABLE, 'baseURL': 'https://api.deepseek.com'}},
            {'insert': [{'id': 'agents-host', 'name': str(installed_package('dsh') / 'plugin.mjs')}]},
        ]))
        self.patch = patch
        self.profile = 'agents392'
        marker = RUN / 'dsh-profile-created'
        self.from_default = [] if marker.exists() else ['--from-default-profile', 'headless']
        marker.touch()

    # -- one turn --------------------------------------------------------

    def _argv(self, prompt: str, label: str) -> tuple[list[str], bytes | None]:
        """Return this kind's command for one turn, and its stdin."""
        if self.kind == 'claude':
            flag = '--resume' if self.started else '--session-id'
            return ([CLAUDE, '-p', '--model', CLAUDE_MODEL, '--output-format', 'stream-json', '--verbose',
                     '--mcp-config', str(self.work / '.mcp.json'), '--strict-mcp-config',
                     '--allowedTools', 'mcp__agents__agents', flag, self.session], prompt.encode())
        if self.kind == 'codex':
            command = [CODEX_HOST] if CODEX_HOST else [PYTHON, '-m', 'agent_swarm.codex.host']
            return ([*command, '--settings', str(self.config_file), '--directory', str(self.data),
                     '--output', str(OUT / f'{label}.output.json'),
                     *(['--resume'] if self.started else []), prompt], None)
        if self.kind == 'pi':
            return ([PI, '--mode', 'json', '--session-dir', str(self.sessions), '--session-id', self.session,
                     '--model', f'{PI_PROVIDER}/{DEEPSEEK_MODEL}', '-e', self.extension,
                     '--agents-config', str(self.config_file), prompt], b'')
        return ([DSH, '--profile', self.profile, *self.from_default, '--patch', str(self.patch), '--json',
                 *(['--session-id', self.session] if self.started else []), prompt], b'')

    def turn(self, label: str, prompt: str, limit: int = DEFAULT_LIMIT, during=None) -> Turn:
        """Run one turn to its end, bounded by ``limit`` seconds; a failed run still leaves evidence.

        ``during(process)`` runs on its own thread while the host runs.
        """
        argv, stdin = self._argv(prompt, label)
        stdout_file = OUT / f'{label}.stdout'
        stderr_file = OUT / f'{label}.stderr'
        (OUT / f'{label}.prompt.txt').write_text(prompt)
        if self.kind == 'claude' and self.host_log.exists():
            self.host_log_offset = self.host_log.stat().st_size
        print(f'-- {label}: {self.kind} host turn, at most {limit // 60} minutes; nothing to type', flush=True)
        begun = time.monotonic()
        with stdout_file.open('wb') as stdout, stderr_file.open('wb') as stderr:
            process = subprocess.Popen(argv, cwd=self.work, env=self.environment, stdout=stdout,
                                       stdin=subprocess.PIPE,
                                       stderr=subprocess.PIPE if self.kind == 'codex' else stderr)
            if self.kind == 'codex':
                threading.Thread(target=self._answer_codex, args=(process, stderr, label), daemon=True).start()
            elif stdin is not None:
                process.stdin.write(stdin)
                process.stdin.close()
            if during is not None:
                threading.Thread(target=during, args=(process,), daemon=True).start()
            limited = False
            try:
                process.wait(limit)
            except subprocess.TimeoutExpired:
                limited = True
                process.terminate()
                try:
                    process.wait(20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        seconds = time.monotonic() - begun
        note(f'{label}: exit {process.returncode}, {seconds:.0f} s' + (', STOPPED AT THE TIME LIMIT' if limited else ''))
        self.started = True
        if self.kind == 'dsh':
            self.from_default = []
        found = self._read(label, stdout_file)
        (OUT / f'{label}.results.json').write_text(json.dumps(found, indent=1, ensure_ascii=False))
        return Turn(label, found, process.returncode, seconds, limited)

    def _answer_codex(self, process: subprocess.Popen, log, label: str) -> None:
        """Answer the parent's own native requests so that nothing needs typing (381's two answers)."""
        for line in process.stderr:
            log.write(line)
            log.flush()
            try:
                request = json.loads(line).get('native_request')
            except (ValueError, AttributeError):
                continue
            if not request:
                continue
            accept = request.get('method') == 'mcpServer/elicitation/request' and 'agents' in json.dumps(request)
            answer = {'action': 'accept', 'content': {}} if accept else {'decision': 'decline'}
            note(f"{label}: Codex parent native request {request.get('method')} answered {json.dumps(answer)}")
            process.stdin.write((json.dumps(answer) + '\n').encode())
            process.stdin.flush()

    def _read(self, label: str, stdout_file: Path) -> list[dict]:
        """Return the public results of the turn, and extend ``notices``."""
        return getattr(self, f'_read_{self.kind}')(label, stdout_file)

    def _read_claude(self, label: str, stdout_file: Path) -> list[dict]:
        """Read tool results and main_notices from stream-json, and pushed notices from its text."""
        found = []
        for line in stdout_file.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get('message') if isinstance(record, dict) else None
            content = message.get('content') if isinstance(message, dict) else None
            for item in content if isinstance(content, list) else []:
                if not isinstance(item, dict) or item.get('type') != 'tool_result':
                    continue
                text = item.get('content')
                if isinstance(text, list):
                    text = ''.join(part.get('text', '') for part in text if isinstance(part, dict))
                for document in documents(text):
                    found.append(document)
                    for notice in document.get('main_notices', []):
                        body = notice.get('event') or {}
                        self.notices.append({'id': notice.get('id'), 'agent': body.get('alias'),
                                             'event': body.get('event'), 'body': str(body.get('message'))})
        if self.host_log.exists():
            with self.host_log.open('rb') as log:
                log.seek(self.host_log_offset)
                (OUT / f'{label}.host.log').write_bytes(log.read())
        return found

    def _read_codex(self, label: str, _: Path) -> list[dict]:
        """Read the ``--output`` document's operations and deliveries."""
        output = OUT / f'{label}.output.json'
        if not output.exists():
            return []
        document = json.loads(output.read_text())
        self.session_id_seen = document.get('parent_session')
        for delivery in document.get('deliveries', []):
            self.notices.append({'id': delivery.get('id'), 'agent': delivery.get('agent'),
                                 'event': delivery.get('event'), 'body': str(delivery.get('body'))})
        return [{'action': operation.get('action'), **(operation.get('result') or {})}
                for operation in document.get('operations', [])]

    def _read_pi(self, label: str, _: Path) -> list[dict]:
        """Read this turn's tool results and the Session's custom messages from the Pi Session file."""
        files = list(self.sessions.glob(f'*_{self.session}.jsonl'))
        if len(files) != 1:
            note(f'{label}: expected one Pi Session file for {self.session}, found {len(files)}')
            return []
        shutil.copy2(files[0], OUT / f'{self.name}.pi-session.jsonl')
        entries = [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]
        fresh, self.entries_seen = entries[self.entries_seen:], len(entries)
        found = []
        for entry in fresh:
            if entry.get('type') == 'custom_message' and entry.get('customType') == 'graphtraj:agent-communication':
                text = json.dumps(entry, ensure_ascii=False)
                fact = (entry.get('details') or {}).get('fact') or ''
                details = entry.get('details') or {}
                self.notices.append({'id': fact.removeprefix('notice:'), 'agent': details.get('agent'),
                                     'event': details.get('event'), 'body': text})
            if entry.get('type') == 'message' and (entry.get('message') or {}).get('role') == 'toolResult':
                for document in documents(entry['message']):
                    if document not in found:
                        found.append(document)
        return found

    def _read_dsh(self, label: str, stdout_file: Path) -> list[dict]:
        """Read tool results from --json events and notices from the Session logs' relay messages."""
        found = []
        for line in stdout_file.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'tool_result':
                for document in documents(event):
                    if document not in found:
                        found.append(document)
            if event.get('type') in ('session', 'final') and event.get('sessionId'):
                self.session = event['sessionId']
        relays = OUT / f'{label}.relays.jsonl'
        subprocess.run(['node', str(HERE / 'dsh_relay.mjs'), str(self.home), str(relays)],
                       stdout=(OUT / f'{label}.relays.txt').open('w'), stderr=subprocess.STDOUT)
        self.notices = []
        for line in relays.read_text().splitlines() if relays.exists() else []:
            relay = json.loads(line)
            if relay.get('type') == 'user/message':
                match = re.search(r'agents notice from ([^ ]+) · (\w+)', relay.get('text', ''))
                self.notices.append({'id': relay['communicationId'].removeprefix('agents-notice:'),
                                     'agent': match and match.group(1), 'event': match and match.group(2),
                                     'body': relay.get('text', '')})
        return found

    # -- after a turn ----------------------------------------------------

    def notices_of(self, agent: str) -> list[dict]:
        """Return every notice this parent received about one Agent."""
        return [notice for notice in self.notices if notice.get('agent') == agent]

    def transcript(self, label: str) -> str:
        """Copy the native Claude transcript of this Session to the evidence; return its text."""
        for path in (Path.home() / '.claude' / 'projects').glob(f'*/{self.session}.jsonl'):
            shutil.copy2(path, OUT / f'{label}.transcript.jsonl')
            return path.read_text(errors='replace')
        note(f'{label}: no native transcript named {self.session}')
        return ''

    def keep_data(self) -> None:
        """Copy this host's small records to the evidence: no venv, package or binary."""
        keep_tree(self.data, OUT / f'{self.name}.data')


def keep_tree(source: Path, target: Path) -> None:
    """Copy text records under ``source``; skip packages, ``auth.json`` and anything over 5 MB."""
    for path in source.rglob('*') if source.exists() else []:
        if (not path.is_file() or path.is_symlink() or 'node_modules' in path.parts or path.name == 'auth.json'
                or path.suffix not in ('.json', '.jsonl', '.log', '.yml', '.yaml', '.txt')
                or path.stat().st_size > 5_000_000):
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def shown_count(host: Host, turns: list[Turn], agent: str, token: str) -> int:
    """Count how often a body reached the parent: notices plus results that show it."""
    in_notices = sum(token in notice['body'] for notice in host.notices_of(agent))
    in_results = sum(token in str(last_result(document).get('last_message') or '')
                     for turn in turns for document in turn.documents if document.get('agent') == agent)
    return in_notices + in_results


def host_process(parent_pid: int, pattern: str) -> int | None:
    """Return a process under ``parent_pid`` (any depth) whose arguments match ``pattern``."""
    pending, seen = [parent_pid], set()
    while pending:
        current = pending.pop()
        children = subprocess.run(['pgrep', '-P', str(current)], capture_output=True, text=True).stdout.split()
        for child in children:
            if child in seen:
                continue
            seen.add(child)
            pending.append(int(child))
            arguments = subprocess.run(['ps', '-o', 'command=', '-p', child], capture_output=True, text=True).stdout
            if re.search(pattern, arguments):
                return int(child)
    return None


def alive(pid: int) -> bool:
    """Say whether a process exists, a stopped one included."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_process(pid: int, kind: int = signal.SIGSTOP) -> bool:
    """Send one signal to a process this step started; return whether it was delivered."""
    try:
        os.kill(pid, kind)
    except OSError:
        return False
    return True
