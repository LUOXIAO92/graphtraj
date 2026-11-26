"""Task 643, VM side: where Codex's tool-process exit -1073741502 (0xC0000142, STATUS_DLL_INIT_FAILED) comes from.

Run by steps.zsh over ``gcloud compute ssh`` as ``<venv python> C:\\v643\\drive643.py <command> ...`` (B and C
interactive: by a scheduled task in the VM user's interactive console session, through ``schedule``):

  config [mode]         write %USERPROFILE%\\.codex\\config.toml from settings.json (no secret; ``env_key`` names
                        the variable); ``mode`` adds ``[windows] sandbox = "<mode>"``.
  versions <step>       Windows build, Python, Node, npm, Codex, git, graftling, elevation into out/<step>/.
  r0                    versions, then one ``codex exec`` with a one-line prompt (as 640): RESULT R0 PASS|FAIL|STOP.
  case <case>           one case with ``[windows] sandbox = "unelevated"`` in a fresh work dir: A and B run
                        ``codex exec`` (outside graftling), C-interactive and C-ssh a graftling Codex child (as 640's
                        R1). The SAME tool command (TOOL_COMMAND) in each. Prints ``CASE <case> <observable>: <value>``
                        lines (tool executed, marker, rollout calls and exit codes, wall time, the launching process's
                        session, window station, desktop, integrity, elevation, logon type and logon-type SIDs, job
                        membership with limit and UI-restriction flags, the optional ``codex sandbox`` runner) and
                        last ``RESULT <case> TOOL-RAN | TOOL-FAILED <code> | NO-TOOL-CALL | STOP <reason>``.
  session               the VM user's console session from ``query user``: ``SESSION ACTIVE <id> <name>`` or
                        ``SESSION NONE`` (the user name is never printed); kept in out/I/console.txt.
  schedule <case> <s>   run ``case <case>`` as a scheduled task (LogonType Interactive, RunLevel Highest) for this
                        user, wait at most <s> seconds for its done file, print its console, remove the task.
  task <case>           what the scheduled task runs: ``case <case>`` with its output in out/<case>/task-output.txt,
                        then out/<case>/done.json (always written).
  verdict <case>        ``VERDICT-OF <case> <verdict>`` from out/<case>/result.json (``none`` when absent).
  scan <step>           before evidence leaves the VM: fail (exit 3) if the key's value or the autologon password is
                        in out/<step> (never printed); then replace every settings value and IP address with its
                        placeholder; print counts only.
  scrub <dir> <json>    the same replacement on any directory (the Mac's second pass), values from <json>.

Layout (``HOME``: C:\\v643 on Windows, V643_HOME elsewhere): settings.json, venv\\, graftling\\, work\\<case>\\
(a fresh ASCII work dir per case), out\\<step>\\ (evidence). Everything printed passes through the scrub first.
Rehearsal only: V643_STANDIN names graftling's tests directory (the stand-in Codex peer replaces Codex for the C
cases); V643_STANDIN_ROLLOUT injects a rollout; off Windows ``schedule`` starts ``task`` as a plain subprocess and
the Win32 facts read NOT-WINDOWS.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

WINDOWS = sys.platform == 'win32'
_HOME = os.environ.get('V643_HOME') or (r'C:\v643' if WINDOWS else '')
# Resolved: a bound cwd must equal the MCP server's real cwd (a /tmp symbolic link on macOS would not).
HOME = Path(_HOME).resolve() if _HOME else Path()
STANDIN = os.environ.get('V643_STANDIN')
MODE = 'unelevated'  # Codex 0.172 [windows] sandbox for every case
MARKER = 'marker-643.txt'
MARKER_TEXT = 'tool-ran'
TOOL_COMMAND = f'Set-Content -Path {MARKER} -Value {MARKER_TEXT}'
CASES = ('A', 'B', 'C-interactive', 'C-ssh')
CALLER = ('controlled-host', 'actual-parent', 'parent-session', 'codex')
OWNER = r'''
import json, os, sys
from pathlib import Path
from graftling import AgentControl, Caller, bind
from graftling.codex.driver import CodexDriver
control = AgentControl(Path(sys.argv[1]), {'codex': CodexDriver(json.loads(sys.argv[2]))})
call = bind(control, Caller(*json.loads(sys.argv[3])))
print(json.dumps({'pid': os.getpid()}), flush=True)
for line in sys.stdin:
    print(json.dumps(call(json.loads(line)).document), flush=True)
'''


# --- settings, scrubbing, output -----------------------------------------------------------------------------

def settings() -> dict:
    return json.loads((HOME / 'settings.json').read_text(encoding='utf-8'))


def key_value() -> str | None:
    """The temporary key, from this process or the VM user's registry (never printed)."""
    name = settings()['provider']['key_env']
    value = os.environ.get(name)
    if not value and WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                value = winreg.QueryValueEx(key, name)[0]
        except OSError:
            value = None
    return value or None


WINLOGON = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'


def password_value() -> str | None:
    """The autologon password step I set (Winlogon DefaultPassword; never printed). Rehearsal: V643_PASSWORD."""
    if not WINDOWS:
        return os.environ.get('V643_PASSWORD') or None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINLOGON) as key:
            return winreg.QueryValueEx(key, 'DefaultPassword')[0] or None
    except OSError:
        return None


def secrets() -> list[str]:
    """Values that must never leave the VM: the provider key and the autologon password."""
    return [value for value in (key_value(), password_value()) if value]


IPV4 = re.compile(rb'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
# A candidate must stand alone (not inside a word, so 'codex_core::tools' is no candidate) and is replaced only when
# it is a real address: global, or with at least 3 non-empty groups (correction 3).
IPV6 = re.compile(rb'(?<![\w:.])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])')
KEEP_IPS = {'127.0.0.1', '0.0.0.0', '255.255.255.255', '::1', '::'}


def _ip(match: re.Match) -> bytes | None:
    text = match.group(0).decode('ascii')
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if str(address) in KEEP_IPS or text in KEEP_IPS:
        return None
    if address.version == 6 and not address.is_global and len([g for g in text.split(':') if g]) < 3:
        return None
    return b'<IP>'


def scrub_bytes(data: bytes, pairs: list[list[str]], counts: dict) -> bytes:
    """Replace each value (case-insensitive, UTF-8 and UTF-16-LE) and each IP address by its placeholder."""
    for placeholder, value in sorted(pairs, key=lambda pair: -len(pair[1])):
        if not value:
            continue
        for encoding in ('utf-8', 'utf-16-le'):
            pattern = re.compile(re.escape(value.encode(encoding)), re.IGNORECASE)
            data, number = pattern.subn(placeholder.encode(encoding), data)
            if number:
                counts[placeholder] = counts.get(placeholder, 0) + number
    for pattern in (IPV4, IPV6):
        def replace(match: re.Match) -> bytes:
            found = _ip(match)
            if found is None:
                return match.group(0)
            counts['<IP>'] = counts.get('<IP>', 0) + 1
            return found
        data = pattern.sub(replace, data)
    return data


_PAIRS: list | None = None


def pairs() -> list:
    global _PAIRS
    if _PAIRS is None:
        try:
            _PAIRS = settings().get('scrub', [])
        except (OSError, ValueError):
            _PAIRS = []
        if HOME.parts:
            _PAIRS = [*_PAIRS, *[['<SECRET>', value] for value in secrets()]]
    return _PAIRS


def clean(text: str) -> str:
    return scrub_bytes(text.encode('utf-8'), pairs(), {}).decode('utf-8', 'replace')


class Log:
    """The step's console: printed scrubbed, kept in out/<step>/console.txt (scrubbed again by scan)."""

    def __init__(self, step: str) -> None:
        self.dir = HOME / 'out' / step
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = (self.dir / 'console.txt').open('a', encoding='utf-8')
        self.items: list[dict] = []

    def say(self, text: str) -> None:
        text = clean(str(text))
        print(text, flush=True)
        self.file.write(text + '\n')
        self.file.flush()

    def item(self, ident: str, verdict: str, observable: str, **facts: object) -> None:
        self.items.append({'item': ident, 'verdict': verdict, 'observable': observable, **facts})
        self.say(f'ITEM {ident} {verdict} {observable}')
        self.save('items.json', self.items)

    def save(self, name: str, document: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        return path


# --- the VM's tools ------------------------------------------------------------------------------------------

def tool_path() -> None:
    """Put the provisioned tools first on PATH (an ssh session may predate the installers' PATH changes)."""
    if not WINDOWS:
        return
    extra = [r'C:\Program Files\nodejs', os.path.join(os.environ.get('APPDATA', ''), 'npm'),
             r'C:\Program Files\Git\cmd', r'C:\Program Files\Python313']
    os.environ['PATH'] = os.pathsep.join([*extra, os.environ.get('PATH', '')])
    name = settings()['provider']['key_env']
    if not os.environ.get(name) and key_value():
        os.environ[name] = key_value()  # the VM user's own variable, for the Codex service graftling starts


def codex_command() -> str:
    """The ``codex`` a user gets from the npm install (Windows: the codex.cmd shim)."""
    found = shutil.which('codex')
    if not found:
        raise SystemExit('codex is not on PATH; run step V again')
    return found


def run(argv: list, timeout: float = 120, **options: object) -> dict:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=timeout, **options)
        return {'argv': argv, 'exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'argv': argv, 'exit': None, 'error': repr(error)}


def processes() -> dict[int, dict]:
    """pid -> {ppid, name, cmd, user?} for every process (Windows: Win32_Process)."""
    if WINDOWS:
        script = ('[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | '
                  'Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress')
        out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], 60)
        try:
            rows = json.loads(out.get('stdout') or '[]')
        except ValueError:
            return {}
        return {row['ProcessId']: {'ppid': row['ParentProcessId'], 'name': row['Name'],
                                   'cmd': row.get('CommandLine') or ''} for row in rows}
    # POSIX (rehearsal): graftling's own same-user listing (libproc/procfs), as its 462 tests use.
    from graftling.member_processes import _user_pids, parent_pid
    from graftling.tool_descendants import _argv
    found = {}
    for pid in _user_pids():
        try:
            argv = _argv(pid)
        except OSError:
            continue
        if argv:
            found[pid] = {'ppid': parent_pid(pid) or 0, 'name': Path(argv[0]).name, 'cmd': ' '.join(argv)}
    return found


def chain(table: dict, pid: int, depth: int = 6) -> list[dict]:
    """``pid`` and its recorded parents (a reused parent PID is possible on Windows; inference only)."""
    out, seen = [], set()
    while pid in table and pid not in seen and len(out) < depth:
        seen.add(pid)
        row = table[pid]
        out.append({'pid': pid, 'name': row['name'], 'cmd': row['cmd'][:400]})
        pid = row['ppid']
    return out


# --- Win32 (helper-local ctypes, only what graftling._win32 does not offer) ----------------------------------

# --- config and versions -------------------------------------------------------------------------------------

def codex_home() -> Path:
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def write_config(mode: str | None) -> Path:
    """config.toml from settings.json: the provider names its key by ``env_key``; no secret is written."""
    provider = settings()['provider']
    q = lambda text: json.dumps(text, ensure_ascii=False)
    lines = [f'model = {q(provider["model"])}', f'model_provider = {q(provider["id"])}',
             'web_search = "disabled"', '', f'[model_providers.{q(provider["id"])}]',
             f'name = {q(provider["name"])}', f'base_url = {q(provider["base_url"])}',
             f'env_key = {q(provider["key_env"])}', f'wire_api = {q(provider["wire_api"])}']
    if mode:
        lines += ['', '[windows]', f'sandbox = {q(mode)}']
    home = codex_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / 'config.toml'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def versions(log: Log) -> dict:
    tool_path()
    facts: dict = {'platform': sys.platform, 'python': sys.version, 'executable': sys.executable,
                   'filesystem_encoding': sys.getfilesystemencoding(), 'stdout_encoding': sys.stdout.encoding}
    import locale
    facts['preferred_encoding'] = locale.getpreferredencoding(False)
    if WINDOWS:
        import platform
        import winreg
        facts['windows'] = platform.platform()
        facts['windows_build'] = run(['cmd', '/c', 'ver'])['stdout'].strip()
        facts['code_page'] = run(['cmd', '/c', 'chcp'])['stdout'].strip()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock') as key:
                facts['developer_mode'] = winreg.QueryValueEx(key, 'AllowDevelopmentWithoutDevLicense')[0]
        except OSError as error:
            facts['developer_mode'] = f'unset ({error})'
        groups = run(['whoami', '/groups'])['stdout']
        facts['integrity'] = 'high (elevated)' if 'S-1-16-12288' in groups else 'medium or other'
        facts['node'] = run(['node', '--version']).get('stdout', '').strip()
        facts['npm'] = run(['cmd', '/c', 'npm', '--version']).get('stdout', '').strip()
        facts['npm_codex'] = run(['cmd', '/c', 'npm', 'ls', '-g', '@openai/codex', '--depth=0']).get('stdout', '')
        exe = [str(path) for path in (Path(os.environ.get('APPDATA', '')) / 'npm' / 'node_modules').rglob('codex.exe')]
        facts['codex_native_exe'] = exe
    try:
        command = codex_command()
        facts['codex_command'] = command
        facts['codex_version'] = run([command, '--version']).get('stdout', '').strip()
    except SystemExit as error:
        facts['codex_command'] = str(error)
    facts['git'] = run(['git', '--version']).get('stdout', '').strip()
    graft = HOME / 'graftling'
    facts['graftling_head'] = run(['git', '-C', str(graft), 'rev-parse', 'HEAD']).get('stdout', '').strip()
    facts['graftling_expected'] = settings().get('candidate')
    try:
        from graftling.links import symbolic_links_available
        facts['symbolic_links'] = symbolic_links_available()
    except Exception as error:  # an import failure is itself the finding
        facts['symbolic_links'] = repr(error)
    log.save('versions.json', facts)
    for name in ('windows', 'windows_build', 'code_page', 'python', 'node', 'npm', 'codex_version', 'codex_command',
                 'codex_native_exe', 'git', 'graftling_head', 'developer_mode', 'symbolic_links', 'integrity',
                 'preferred_encoding', 'filesystem_encoding'):
        if name in facts:
            log.say(f'  {name}: {str(facts[name]).splitlines()[0] if str(facts[name]) else ""}')
    return facts


# --- R0 ------------------------------------------------------------------------------------------------------

def walk(document: object, path: str = ''):
    if isinstance(document, dict):
        for key, value in document.items():
            yield path + '/' + key, key, value
            yield from walk(value, path + '/' + key)
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from walk(value, f'{path}[{index}]')


def r0() -> int:
    log = Log('R0')
    log.say('[R0] versions, then one codex exec call with a one-line prompt (no tool)')
    facts = versions(log)
    provider = settings()['provider']
    if facts.get('graftling_head') != facts.get('graftling_expected'):
        log.item('R0.candidate', 'FAIL', 'graftling HEAD on the VM is not the candidate')
    else:
        log.item('R0.candidate', 'PASS', 'graftling HEAD on the VM is the candidate')
    if not key_value():
        log.say('STOP: the key variable is not set for this user; run step K first')
        log.say('RESULT R0 STOP')
        return 2
    config = write_config(None)
    shutil.copyfile(config, log.dir / 'config.toml')
    work = HOME / 'work' / 'r0'
    work.mkdir(parents=True, exist_ok=True)
    sessions = codex_home() / 'sessions'
    started = time.time()
    token = 'PONG643'
    out = run([codex_command(), 'exec', '--json', '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(work),
               f'Reply with exactly the word {token} and nothing else. Do not run any command.'], 300)
    (log.dir / 'exec-stdout.jsonl').write_text(out.get('stdout') or '', encoding='utf-8')
    (log.dir / 'exec-stderr.txt').write_text((out.get('stderr') or '') + (out.get('error') or ''), encoding='utf-8')
    log.say(f'codex exec exit: {out.get("exit")}')
    events = []
    for line in (out.get('stdout') or '').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    rollouts = sorted((path for path in sessions.rglob('rollout-*.jsonl') if path.stat().st_mtime >= started - 5),
                      key=lambda path: path.stat().st_mtime) if sessions.is_dir() else []
    records = []
    if rollouts:
        shutil.copyfile(rollouts[-1], log.dir / 'rollout.jsonl')
        for line in rollouts[-1].read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    answer = ' '.join(str(value) for document in events for _, key, value in walk(document)
                      if key == 'text' and isinstance(value, str))
    configured_provider = [value for record in records if record.get('type') == 'session_meta'
                           for _, key, value in walk(record) if key == 'model_provider']
    configured_model = [value for record in records if record.get('type') == 'turn_context'
                        for _, key, value in walk(record) if key == 'model']
    reported = sorted({value for document in [*events, *[r for r in records if r.get('type') not in
                                                           ('turn_context', 'session_meta')]]
                       for _, key, value in walk(document) if key == 'model' and isinstance(value, str)})
    log.save('r0.json', {'exit': out.get('exit'), 'answer': answer, 'provider_in_rollout': configured_provider,
                         'model_in_turn_context': configured_model, 'model_reported': reported,
                         'rollout': [str(path) for path in rollouts[-1:]], 'events': len(events)})
    if out.get('exit') != 0 or token not in answer:
        log.say('STOP: the provider call did not answer; raw error follows (scrubbed), no fallback model is tried:')
        for line in ((out.get('stderr') or '') + (out.get('error') or '')).splitlines()[-40:]:
            log.say('  | ' + line)
        for document in events:
            if document.get('type') in ('error', 'turn.failed') or 'error' in document:
                log.say('  | ' + json.dumps(document, ensure_ascii=False)[:2000])
        log.item('R0.answer', 'FAIL', f'codex exec exit {out.get("exit")}; answer token absent')
        log.say('RESULT R0 STOP')
        return 2
    log.item('R0.answer', 'PASS', f'codex exec answered with {token}')
    ok_provider = configured_provider and set(configured_provider) == {provider['id']}
    log.item('R0.provider', 'PASS' if ok_provider else 'FAIL',
             f'rollout session_meta model_provider: {configured_provider or "absent"} (configured: <PROVIDER_ID>)')
    ok_model = configured_model and set(configured_model) == {provider['model']}
    log.item('R0.model', 'PASS' if ok_model else 'FAIL',
             f'rollout turn_context model: {configured_model or "absent"} (configured: <MODEL>)')
    if not reported:
        log.item('R0.model-reported', 'OBSERVED', 'Codex exposes no provider-reported model in its JSON events or '
                                                 'rollout; only the configured one is recorded')
    elif set(reported) == {provider['model']}:
        log.item('R0.model-reported', 'PASS', 'the model the provider reported equals the configured one')
    else:
        log.item('R0.model-reported', 'FAIL', 'the model the provider reported differs from the configured one')
    bad = [item for item in log.items if item['verdict'] == 'FAIL']
    log.say(f'RESULT R0 {"FAIL" if bad else "PASS"}')
    return 1 if bad else 0


# --- R1-R5 ---------------------------------------------------------------------------------------------------


def child_settings(work: Path, codex: list[str], mode: str = '', host: bool = False) -> dict:
    """Run.settings for a child (R1-R3) or the parent host (R4).

    Children run with approvalPolicy 'never' (their shell commands stay inside the sandbox). The parent host uses
    the documented path for its own MCP call: an approval_policy that asks ('on-request') and graftling's default
    approvals_reviewer 'auto_review' (PUBLIC_API.md 4.1; driver.py prepare), so Codex's reviewer decides; any request
    Codex still hands over reaches CodexHost._request (stderr, answered on stdin). Mode 'none': the profile extends
    Codex's built-in ':danger-full-access' (sandbox off; graftling refuses legacy sandbox_mode, context.py:120).
    """
    base = ':danger-full-access' if mode == 'none' else ':workspace'
    parameters = {'cwd': str(work), 'developerInstructions': '',
                  'config': {'default_permissions': 'chosen', 'permissions': {
                      'chosen': {'extends': base, 'filesystem': {str(work): 'write'}}}}}
    if STANDIN:
        parameters['model'] = 'chosen-model'
    else:
        parameters.update(model=settings()['provider']['model'], approvalPolicy='on-request' if host else 'never')
    return {'adapter_request': {'arguments': codex, 'worktree_path': str(work), 'session_parameters': parameters}}


def standin(work: Path) -> list[str]:
    """Rehearsal: graftling's controlled peer as ``codex`` (tests/codex_stdio_peer.py), POSIX only."""
    tests = Path(STANDIN)
    peer = work.parent / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + (tests / 'codex_stdio_peer.py').read_text(encoding='utf-8'))
    peer.chmod(0o755)
    os.environ['PEER_TOOL_COMMAND'] = os.environ.get('V643_PEER_TOOL', f'printf "{MARKER_TEXT}\\n" > {MARKER}')
    return [str(peer)]


def wait_for(predicate, seconds: float, step: float = 2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def record(root: Path, agent: str) -> dict:
    return json.loads((root / 'control/agents' / f'{agent}.json').read_text(encoding='utf-8'))['executions'][-1]



def collect(root: Path, target: Path) -> None:
    """Copy the control records, termination reports and stderr logs (no symbolic link is followed)."""
    for path in root.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix in ('.json', '.yml', '.log') or path.name.startswith('codex-termination'):
            destination = target / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)




SHELL_FAILED = re.compile(r'(?i)(failed to create unified exec process[^\n]*|failed to start the process[^\n]*|'
                          r'unsupportedoperation[^\n]*|native mxc is unavailable[^\n]*|connecting runner pipe[^\n]*)')
SHELL_TOOLS = {'shell', 'shell_command', 'exec_command', 'local_shell', 'container.exec', 'unified_exec'}



def injected_rollout() -> Path | None:
    """Rehearsal only: V643_STANDIN_ROLLOUT names a fake rollout used for every turn (labelled as injected)."""
    value = os.environ.get('V643_STANDIN_ROLLOUT') if STANDIN else None
    return Path(value) if value else None


def rollout_records(session: str | None) -> tuple[Path | None, list[dict]]:
    """The Codex rollout of ``session`` (sessions/**/rollout-*<session>*.jsonl, newest), parsed line by line."""
    path = injected_rollout()
    if path is None and session:
        sessions = codex_home() / 'sessions'
        found = sorted(sessions.rglob(f'rollout-*{session}*.jsonl'), key=lambda item: item.stat().st_mtime) \
            if sessions.is_dir() else []
        path = found[-1] if found else None
    records = []
    if path is not None and path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    return path, records


def tool_calls(records: list[dict]) -> list[dict]:
    """Shell/exec tool calls in Codex rollout records, with their command, exit code and error text.

    Fields read: ``type: response_item`` with ``payload.type`` function_call / custom_tool_call / local_shell_call
    (``payload.name``, ``payload.arguments`` or ``input`` or ``action`` -> ``command``/``cmd``, ``payload.call_id``);
    ``payload.type`` function_call_output / custom_tool_call_output (``payload.call_id``, ``payload.output``); and
    ``type: event_msg`` with ``payload.type`` exec_command_end (``payload.call_id``, ``exit_code``, ``stderr``).
    """
    calls: dict = {}
    order: list = []
    outputs: dict = {}
    ends: dict = {}
    for record in records:
        payload = record.get('payload') or {}
        kind = payload.get('type')
        if record.get('type') == 'response_item' and kind in ('function_call', 'custom_tool_call', 'local_shell_call'):
            name = payload.get('name') or ('local_shell' if kind == 'local_shell_call' else '')
            if kind != 'local_shell_call' and name not in SHELL_TOOLS:
                continue
            arguments = payload.get('arguments') or payload.get('input') or payload.get('action') or ''
            command = arguments
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    command = parsed.get('command') or parsed.get('cmd') or arguments
            elif isinstance(arguments, dict):
                command = arguments.get('command') or arguments.get('cmd') or arguments
            if isinstance(command, list):
                command = ' '.join(map(str, command))
            ident = payload.get('call_id') or payload.get('id') or f'call-{len(order)}'
            calls[ident] = {'tool': name, 'command': str(command)[:160]}
            order.append(ident)
        elif record.get('type') == 'response_item' and kind in ('function_call_output', 'custom_tool_call_output',
                                                                'local_shell_call_output'):
            output = payload.get('output')
            if isinstance(output, dict):
                output = output.get('content') or json.dumps(output, ensure_ascii=False)
            outputs[payload.get('call_id')] = str(output or '')
        elif record.get('type') == 'event_msg' and kind == 'exec_command_end':
            ends[payload.get('call_id')] = payload
    found = []
    for ident in order:
        output, end = outputs.get(ident, ''), ends.get(ident, {})
        code = end.get('exit_code')
        if code is None:
            # Codex 0.172 exec_command output says 'Process exited with code -1073741502' (Task 640's real rollouts);
            # the 640 driver matched only 'exit code' and reported None (the defect fixed here).
            match = (re.search(r'(?i)\bexit(?:ed with)? code:?\s*(-?\d+)', output)
                     or re.search(r'"exit_code"\s*:\s*(-?\d+)', output))
            code = int(match.group(1)) if match else None
        failed = SHELL_FAILED.search(output) or re.search(r'(?im)^(error|failed)\b[^\n]*', output)
        error = failed.group(0).strip()[:200] if failed else (
            f'exit code {code}: {str(end.get("stderr") or output).strip()[:160]}' if code not in (None, 0) else None)
        found.append({**calls[ident], 'exit_code': code, 'error': error, 'output': output.strip()[:160]})
    return found


# --- evidence ------------------------------------------------------------------------------------------------

def scrub_tree(directory: Path, pair_list: list, hidden: list[str]) -> tuple[dict, list[str]]:
    counts: dict[str, int] = {}
    hits: list[str] = []
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if any(value.encode(encoding) in data for value in hidden for encoding in ('utf-8', 'utf-16-le')):
            hits.append(str(path.relative_to(directory)))
            continue
        new = scrub_bytes(data, pair_list, counts)
        if new != data:
            path.write_bytes(new)
    return counts, hits


def scan(step: str) -> int:
    directory = HOME / 'out' / step
    if not directory.is_dir():
        print(f'SCAN FAIL no evidence directory out/{step}')
        return 1
    hidden = secrets()
    counts, hits = scrub_tree(directory, settings().get('scrub', []), hidden)
    if hits:
        print(f'SCAN FAIL the key or the autologon password is in {len(hits)} file(s) (value not printed): {hits}')
        return 3
    files = sum(1 for path in directory.rglob('*') if path.is_file() and not path.is_symlink())
    print(f'SCAN PASS key {"checked" if key_value() else "not set on this VM"}, autologon password '
          f'{"checked" if password_value() else "not set on this VM"}; replacements: '
          f'{json.dumps(counts, sort_keys=True) if counts else "none"}; files {files}')
    return 0




# --- the launching process's context (Win32; recorded, never assumed) -----------------------------------------

LOGON_SIDS = {'S-1-5-4': 'INTERACTIVE', 'S-1-5-2': 'NETWORK', 'S-1-5-3': 'BATCH', 'S-1-5-6': 'SERVICE',
              'S-1-2-1': 'CONSOLE LOGON', 'S-1-5-14': 'REMOTE INTERACTIVE LOGON'}
LABELS = {'S-1-16-0': 'untrusted', 'S-1-16-4096': 'low', 'S-1-16-8192': 'medium', 'S-1-16-8448': 'medium plus',
          'S-1-16-12288': 'high', 'S-1-16-16384': 'system'}
LOGON_TYPES = {2: 'Interactive', 3: 'Network', 4: 'Batch', 5: 'Service', 7: 'Unlock', 8: 'NetworkCleartext',
               9: 'NewCredentials', 10: 'RemoteInteractive', 11: 'CachedInteractive'}
LIMIT_FLAGS = {0x1: 'WORKINGSET', 0x2: 'PROCESS_TIME', 0x4: 'JOB_TIME', 0x8: 'ACTIVE_PROCESS', 0x10: 'AFFINITY',
               0x20: 'PRIORITY_CLASS', 0x40: 'PRESERVE_JOB_TIME', 0x80: 'SCHEDULING_CLASS', 0x100: 'PROCESS_MEMORY',
               0x200: 'JOB_MEMORY', 0x400: 'DIE_ON_UNHANDLED_EXCEPTION', 0x800: 'BREAKAWAY_OK',
               0x1000: 'SILENT_BREAKAWAY_OK', 0x2000: 'KILL_ON_JOB_CLOSE', 0x4000: 'SUBSET_AFFINITY'}
UI_FLAGS = {0x1: 'HANDLES', 0x2: 'READCLIPBOARD', 0x4: 'WRITECLIPBOARD', 0x8: 'SYSTEMPARAMETERS',
            0x10: 'DISPLAYSETTINGS', 0x20: 'GLOBALATOMS', 0x40: 'DESKTOP', 0x80: 'EXITWINDOWS'}


def flags(value: int, table: dict) -> str:
    names = [name for bit, name in table.items() if value & bit]
    return f'{value:#x} ({", ".join(names) if names else "none"})'


def logon_session(luid: bytes) -> dict:
    """The token's logon session (LsaGetLogonSessionData): its logon type and authentication package."""
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

    class TEXT(ctypes.Structure):
        _fields_ = [('Length', ctypes.c_ushort), ('MaximumLength', ctypes.c_ushort), ('Buffer', ctypes.c_void_p)]

    class DATA(ctypes.Structure):
        _fields_ = [('Size', wintypes.ULONG), ('LogonId', LUID), ('UserName', TEXT), ('LogonDomain', TEXT),
                    ('AuthenticationPackage', TEXT), ('LogonType', wintypes.ULONG), ('Session', wintypes.ULONG)]

    secur = ctypes.WinDLL('secur32')
    secur.LsaGetLogonSessionData.argtypes = [ctypes.POINTER(LUID), ctypes.POINTER(ctypes.POINTER(DATA))]
    secur.LsaGetLogonSessionData.restype = wintypes.LONG
    secur.LsaFreeReturnBuffer.argtypes = [ctypes.c_void_p]
    ident = LUID.from_buffer_copy(luid)
    data = ctypes.POINTER(DATA)()
    code = secur.LsaGetLogonSessionData(ctypes.byref(ident), ctypes.byref(data))
    if code != 0 or not data:
        return {'logon_type': f'unknown (LsaGetLogonSessionData status {code & 0xffffffff:#x})'}
    try:
        package = data.contents.AuthenticationPackage
        kind = data.contents.LogonType
        return {'logon_type': f'{kind} ({LOGON_TYPES.get(kind, "other")})',
                'authentication_package': ctypes.wstring_at(package.Buffer, package.Length // 2) if package.Buffer else '',
                'logon_session_id': data.contents.Session}
    finally:
        secur.LsaFreeReturnBuffer(data)


def context() -> dict:
    """This process's session, window station, desktop, token (integrity, elevation, logon type, logon-type SIDs) and
    job (membership; when in one: its basic limit flags, UI restrictions and process count)."""
    facts: dict = {'pid': os.getpid()}
    try:
        table = processes()
        facts['parent_chain'] = ' <- '.join(f"{row['name']}({row['pid']})" for row in chain(table, os.getpid()))
    except Exception as error:  # a listing failure is recorded, not fatal
        facts['parent_chain'] = f'unknown: {error!r}'
    if not WINDOWS:
        facts['windows'] = 'NOT-WINDOWS (rehearsal): session, window station, desktop, token and job are Windows-only'
        return facts
    import csv
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    last = lambda: f'error {ctypes.get_last_error()}'
    number = wintypes.DWORD()
    k32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    facts['session_id'] = number.value if k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(number)) else last()
    k32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    facts['active_console_session_id'] = k32.WTSGetActiveConsoleSessionId()
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.GetProcessWindowStation.restype = wintypes.HANDLE
        u32.GetThreadDesktop.argtypes = [wintypes.DWORD]
        u32.GetThreadDesktop.restype = wintypes.HANDLE
        u32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.POINTER(wintypes.DWORD)]

        def object_name(handle) -> str:
            if not handle:
                return last()
            buffer, need = ctypes.create_unicode_buffer(512), wintypes.DWORD()
            ok = u32.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(need))  # UOI_NAME
            return buffer.value if ok else last()
        facts['window_station'] = object_name(u32.GetProcessWindowStation())
        facts['desktop'] = object_name(u32.GetThreadDesktop(k32.GetCurrentThreadId()))
    except OSError as error:
        facts['window_station'] = facts['desktop'] = f'user32 not loaded: {error}'
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    adv.IsTokenRestricted.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    if adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        def information(kind: int, size: int = 4) -> bytes | None:
            buffer, got = ctypes.create_string_buffer(size), wintypes.DWORD()
            return buffer.raw if adv.GetTokenInformation(token, kind, buffer, size, ctypes.byref(got)) else None
        raw = information(20)  # TokenElevation
        facts['token_elevated'] = bool(int.from_bytes(raw, 'little')) if raw else last()
        raw = information(18)  # TokenElevationType
        facts['token_elevation_type'] = ({1: 'default', 2: 'full', 3: 'limited'}.get(int.from_bytes(raw, 'little'))
                                         if raw else last())
        facts['token_restricted'] = bool(adv.IsTokenRestricted(token))
        raw = information(10, 64)  # TokenStatistics; AuthenticationId (the logon session LUID) at offset 8
        try:
            facts.update(logon_session(raw[8:16]) if raw else {'logon_type': f'unknown ({last()})'})
        except OSError as error:
            facts['logon_type'] = f'unknown ({error})'
        k32.CloseHandle(token)
    else:
        facts['token'] = f'OpenProcessToken failed: {last()}'
    rows = list(csv.reader(run(['whoami', '/groups', '/fo', 'csv', '/nh']).get('stdout', '').splitlines()))
    sids = {row[2]: row[3] for row in rows if len(row) >= 4}
    facts['logon_sids'] = '; '.join(f'{name} {sid} {"present" if sid in sids else "absent"}'
                                    for sid, name in LOGON_SIDS.items())
    facts['integrity'] = ', '.join(LABELS.get(sid, sid) for sid in sids if sid.startswith('S-1-16-')) or 'unknown'
    facts['administrators_group'] = sids.get('S-1-5-32-544', 'absent')
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    inside = wintypes.BOOL()
    facts['in_job'] = bool(inside.value) if k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(inside)) \
        else last()
    if facts['in_job'] is True:
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.POINTER(wintypes.DWORD)]

        class BASIC(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                        ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                        ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                        ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]
        # A NULL job handle queries the calling process's own (innermost) job.
        basic, ui, accounting = BASIC(), wintypes.DWORD(), ACCOUNTING()
        query = k32.QueryInformationJobObject
        facts['job_limit_flags'] = (flags(basic.LimitFlags, LIMIT_FLAGS)
                                    if query(None, 2, ctypes.byref(basic), ctypes.sizeof(basic), None) else last())
        facts['job_ui_restrictions'] = flags(ui.value, UI_FLAGS) if query(None, 4, ctypes.byref(ui), 4, None) else last()
        facts['job_active_processes'] = (accounting.ActiveProcesses if query(None, 1, ctypes.byref(accounting),
                                                                              ctypes.sizeof(accounting), None) else last())
    return facts


CONTEXT_LINES = ('pid', 'parent_chain', 'windows', 'session_id', 'active_console_session_id', 'window_station',
                 'desktop', 'integrity', 'token_elevated', 'token_elevation_type', 'token_restricted', 'logon_type',
                 'authentication_package', 'logon_sids', 'administrators_group', 'in_job', 'job_limit_flags',
                 'job_ui_restrictions', 'job_active_processes', 'token')


# --- the cases ----------------------------------------------------------------------------------------------

def say_shell(command: str, reply: str) -> str:
    return (f'Use your shell tool to run exactly this PowerShell command and wait for it to finish. Run nothing '
            f'else. Then reply with exactly {reply}.\n\n{command}')


def signed(code: object) -> object:
    """Windows exit codes arrive unsigned from Python (3221225794); shown signed as Codex shows them."""
    return code - 2 ** 32 if isinstance(code, int) and code >= 2 ** 31 else code


def newest_rollout(since: float) -> Path | None:
    sessions = codex_home() / 'sessions'
    found = sorted((path for path in sessions.rglob('rollout-*.jsonl') if path.stat().st_mtime >= since - 5),
                   key=lambda path: path.stat().st_mtime) if sessions.is_dir() else []
    return found[-1] if found else None


def read_records(path: Path | None) -> list[dict]:
    records = []
    if path is not None and path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    return records


def through_exec(log: Log, work: Path, codex: list[str], since: float) -> tuple[dict, Path | None, list[dict]]:
    """A and B: ``codex exec`` outside graftling, unelevated Codex sandbox, workspace-write, in ``work``."""
    out = run([*codex, 'exec', '--json', '--skip-git-repo-check', '--sandbox', 'workspace-write', '-C', str(work),
               say_shell(TOOL_COMMAND, 'CASE-DONE')], 600)
    (log.dir / 'exec-stdout.jsonl').write_text(out.get('stdout') or '', encoding='utf-8')
    (log.dir / 'exec-stderr.txt').write_text((out.get('stderr') or '') + (out.get('error') or ''), encoding='utf-8')
    thread = None
    for line in (out.get('stdout') or '').splitlines():
        try:
            document = json.loads(line)
        except ValueError:
            continue
        if isinstance(document, dict) and document.get('type') == 'thread.started':
            thread = document.get('thread_id')
    path, records = rollout_records(thread) if thread else (None, [])
    if path is None:
        path = newest_rollout(since)
        records = read_records(path)
    facts = {'launcher': 'codex exec (outside graftling)', 'codex_exit': out.get('exit'), 'thread': thread}
    if out.get('exit') is None or not path:
        facts['stop'] = (f'codex exec did not run or wrote no rollout (exit {out.get("exit")}): '
                         f'{((out.get("stderr") or "") + (out.get("error") or "")).strip()[-300:]}')
    return facts, path, records


def through_graftling(log: Log, work: Path, codex: list[str]) -> tuple[dict, Path | None, list[dict]]:
    """C: a graftling Codex child (AgentControl + CodexDriver, as 640's R1) whose instruction runs the tool."""
    root = work.parent / f'agents-{work.name}'
    shutil.rmtree(root, ignore_errors=True)
    native = child_settings(work, codex, MODE)
    log.save('child-settings.json', native)
    owner = subprocess.Popen([sys.executable, '-c', OWNER, str(root), json.dumps(native), json.dumps(CALLER)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
    facts: dict = {'launcher': 'graftling AgentControl + CodexDriver child'}
    path, records = None, []

    def ask(request: dict) -> dict:
        owner.stdin.write(json.dumps(request) + '\n')
        owner.stdin.flush()
        return json.loads(owner.stdout.readline())

    try:
        facts['owner_pid'] = json.loads(owner.stdout.readline())['pid']
        created = ask({'action': 'create', 'runtime': 'codex',
                       'instruction': 'tool-end' if STANDIN else say_shell(TOOL_COMMAND, 'CASE-DONE')})
        if 'error' in created:
            facts['stop'] = f'graftling create refused: {json.dumps(created["error"], ensure_ascii=False)[:400]}'
            return facts, None, []
        agent, session = created['agent'], created['session']
        done = ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 600})
        last = (done.get('result') or {}).get('last_result') or {}
        execution = record(root, agent)
        process = execution.get('process', {})
        facts.update(session=session, outcome=last.get('outcome'), last_message=str(last.get('last_message'))[:120],
                     runtime_job='recorded' if process.get('runtime_job') else 'absent', process=process)
        path, records = rollout_records(session)
        try:
            ask({'action': 'retire', 'agent': agent})
        except (OSError, ValueError):
            pass
    except Exception as error:
        facts['stop'] = f'driver error with graftling: {type(error).__name__}: {error}'
    finally:
        try:
            owner.stdin.close()
            owner.wait(30)
        except (OSError, subprocess.TimeoutExpired):
            owner.kill()
            owner.wait(30)
        collect(root, log.dir / 'agents')
    return facts, path, records


def sandbox_runner(log: Log, case: str, codex: list[str]) -> str:
    """Optional, model-free: the same command through ``codex sandbox windows`` when this Codex offers it."""
    shown = run([*codex, 'sandbox', '--help'], 60)
    text = (shown.get('stdout') or '') + (shown.get('stderr') or '') + (shown.get('error') or '')
    (log.dir / 'codex-sandbox-help.txt').write_text(text, encoding='utf-8')
    if not re.search(r'(?im)^\s*windows\b', text):
        return f'codex sandbox offers no windows runner (help exit {shown.get("exit")})'
    sub = run([*codex, 'sandbox', 'windows', '--help'], 60)
    extra = ['--full-auto'] if '--full-auto' in (sub.get('stdout') or '') + (sub.get('stderr') or '') else []
    where = HOME / 'work' / f'{case}-sandbox'
    shutil.rmtree(where, ignore_errors=True)
    where.mkdir(parents=True)
    began = time.monotonic()
    out = run([*codex, 'sandbox', 'windows', *extra, '--', 'powershell', '-NoProfile', '-Command', TOOL_COMMAND],
              120, cwd=str(where))
    (log.dir / 'codex-sandbox-run.txt').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    marker = where / MARKER
    return (f'codex sandbox windows {" ".join(extra)} -- powershell ... : exit {signed(out.get("exit"))}; marker '
            f'{"present" if marker.exists() else "absent"}; {time.monotonic() - began:.1f} s')


def run_case(case: str, fresh: bool = True) -> int:
    if fresh:
        shutil.rmtree(HOME / 'out' / case, ignore_errors=True)
    log = Log(case)
    log.say(f'[{case}] the tool command {TOOL_COMMAND!r} with [windows] sandbox = "{MODE}" in a fresh work dir')

    def line(name: str, value: object) -> None:
        log.say(f'CASE {case} {name}: {value}')

    verdict, facts = 'STOP the driver ended early', {}
    try:
        tool_path()
        place = context()
        log.save('context.json', place)
        for name in CONTEXT_LINES:
            if name in place:
                line(f'launcher {name}', place[name])
        work = HOME / 'work' / case
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        graft = case.startswith('C')
        if STANDIN and graft:
            codex = standin(work)
        elif not key_value():
            raise LookupError('the key variable is not set for this user; run step K first')
        else:
            config = write_config(MODE)
            shutil.copyfile(config, log.dir / 'config.toml')
            codex = [codex_command()]
        line('codex', ' '.join(codex))
        since, began = time.time(), time.monotonic()
        facts, path, records = (through_graftling(log, work, codex) if graft else
                                through_exec(log, work, codex, since))
        wall = time.monotonic() - began
        for name in ('launcher', 'codex_exit', 'thread', 'owner_pid', 'session', 'outcome', 'last_message',
                     'runtime_job'):
            if name in facts:
                line(name.replace('_', ' '), facts[name])
        if graft and facts.get('process'):
            line('graftling process record', json.dumps(facts['process'], ensure_ascii=False)[:400])
        if path is not None:
            target = log.dir / 'rollouts'
            target.mkdir(exist_ok=True)
            shutil.copyfile(path, target / path.name)
        line('rollout', f'{path.name} (kept in rollouts/)' if path else 'none found')
        calls = tool_calls(records)
        line('tool calls in the rollout', len(calls))
        for index, call in enumerate(calls, 1):
            line(f'call {index}', f"{call['tool']} {call['command'][:80]!r} -> exit {call['exit_code']}"
                                  f"{'; ' + ' '.join(call['error'].split()) if call['error'] else ''}")
        marker = work / MARKER
        content = marker.read_text(encoding='utf-8', errors='replace').strip() if marker.exists() else None
        line('marker file', f'present, content {content!r}' if content is not None else 'absent')
        line('wall time', f'{wall:.1f} s')
        if content is not None:
            verdict = 'TOOL-RAN'
        elif facts.get('stop'):
            verdict = f'STOP {facts["stop"]}'
        elif path is None:
            verdict = 'STOP no Codex rollout found; whether a tool call was made is unknown'
        elif not calls:
            verdict = 'NO-TOOL-CALL'
        else:
            codes = [call['exit_code'] for call in calls]
            failed = next((code for code in codes if code not in (None, 0)), codes[-1])
            verdict = f'TOOL-FAILED {failed}' if failed is not None else f'TOOL-FAILED unknown ({calls[-1]["error"]})'
        if not (STANDIN and graft):
            try:
                line('codex sandbox runner (OBSERVED, never blocks)', sandbox_runner(log, case, codex))
            except Exception as error:
                line('codex sandbox runner (OBSERVED, never blocks)', f'not run: {type(error).__name__}: {error}')
    except LookupError as error:
        verdict = f'STOP {error}'
    except Exception as error:
        verdict = f'STOP driver error: {type(error).__name__}: {error}'
    log.save('result.json', {'case': case, 'verdict': verdict, 'facts': facts})
    log.say(f'RESULT {case} {verdict}')
    return 2 if verdict.startswith('STOP') else 0


# --- the interactive session and the scheduled task ---------------------------------------------------------

STATES = ('Active', 'Disc', 'Conn', 'Listen', 'Down', 'Idle')


def console_session() -> tuple[str, list[str]]:
    """('ACTIVE <id> <name>' | 'NONE', printable lines) for this user from ``query user`` (name never printed)."""
    if WINDOWS:
        out = run(['query', 'user'], 60)
        text = (out.get('stdout') or '') + (out.get('stderr') or '')
    else:  # rehearsal: a sample of query user's output
        sample = os.environ.get('V643_QUSER_FILE')
        text = Path(sample).read_text(encoding='utf-8') if sample else 'No User exists for *'
    me = (os.environ.get('USERNAME') or os.environ.get('USER') or '').lower()[:20]
    found, shown = 'NONE', []
    for raw in text.splitlines():
        parts = raw.replace('>', ' ', 1).split()
        if not parts:
            continue
        index = next((i for i, part in enumerate(parts) if part in STATES), None)
        if index is None:
            shown.append(raw.strip() if parts[0] in ('USERNAME', 'No') else '(unparsed line)')
            continue
        who = '<VM_USER>' if parts[0].lower() == me else '<other user>'
        name = parts[1] if index == 3 else ''
        shown.append(f'{who} session {name or "(none)"} id {parts[index - 1]} state {parts[index]}')
        if who == '<VM_USER>' and parts[index] == 'Active' and name.lower() == 'console':
            found = f'ACTIVE {parts[index - 1]} {name}'
    return found, shown


def ps(script: str, seconds: float = 120) -> dict:
    return run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], seconds)


def task_state(name: str) -> str:
    out = ps(f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; if ($t) {{ $i = $t | "
             f"Get-ScheduledTaskInfo; 'state ' + $t.State + ', last result ' + $i.LastTaskResult + ', last run ' + "
             f"$i.LastRunTime + ', logon type ' + $t.Principal.LogonType + ', run level ' + $t.Principal.RunLevel }} "
             f"else {{ 'task absent' }}", 60)
    return (out.get('stdout') or out.get('error') or '').strip()


def schedule(case: str, seconds: float) -> int:
    """B and C-interactive: ``task <case>`` as a scheduled task in this user's interactive console session."""
    directory = HOME / 'out' / case
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    done = directory / 'done.json'
    found, shown = console_session()
    print(clean(f'session of the VM user: {found}; query user: {" | ".join(shown)}'), flush=True)
    if not found.startswith('ACTIVE'):
        print(f'RESULT {case} STOP the VM user has no Active console session (run step I first)', flush=True)
        return 2
    name = f'v643-{case}'
    script = Path(__file__).resolve()
    if WINDOWS:
        limit = int(seconds // 60) + 5
        out = ps(f"$ErrorActionPreference = 'Stop'\n"
                 f"$a = New-ScheduledTaskAction -Execute '{sys.executable}' -Argument '\"{script}\" task {case}' "
                 f"-WorkingDirectory '{HOME}'\n"
                 f"$p = New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN + '\\' + $env:USERNAME) -LogonType "
                 f"Interactive -RunLevel Highest\n"
                 f"$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes {limit}) "
                 f"-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew\n"
                 f"Register-ScheduledTask -TaskName '{name}' -Action $a -Principal $p -Settings $s -Force | Out-Null\n"
                 f"Start-ScheduledTask -TaskName '{name}'\n'started'")
        if out.get('exit') != 0:
            print(clean(f'RESULT {case} STOP the scheduled task could not be registered or started: '
                        f'{(out.get("stderr") or out.get("error") or "").strip()[-400:]}'), flush=True)
            ps(f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false -ErrorAction SilentlyContinue")
            return 2
        print(clean(f'scheduled task {name} registered (LogonType Interactive, RunLevel Highest) and started: '
                    f'{task_state(name)}'), flush=True)
    else:  # rehearsal: the same task body as a plain subprocess (no Task Scheduler off Windows)
        subprocess.Popen([sys.executable, str(script), 'task', case], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        print(f'stand-in (not Windows): task {case} started as a plain subprocess, not a scheduled task', flush=True)
    began = time.monotonic()
    while not done.exists() and time.monotonic() - began < seconds:
        time.sleep(5)
        if int(time.monotonic() - began) % 60 < 5:
            print(clean(f'  waiting for the task ({time.monotonic() - began:.0f} s): '
                        f'{task_state(name) if WINDOWS else "stand-in"}'), flush=True)
    state = task_state(name) if WINDOWS else 'stand-in'
    if WINDOWS:
        ps(f"Stop-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
           f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false")
        print(clean(f'scheduled task at the end: {state}; removed: {task_state(name)}'), flush=True)
    console = directory / 'console.txt'
    print(f'--- the task\'s console (out/{case}/console.txt):', flush=True)
    if console.exists():
        print(clean(console.read_text(encoding='utf-8', errors='replace')).rstrip(), flush=True)
    if not done.exists():
        print(clean(f'RESULT {case} STOP the task did not finish within {seconds:.0f} s ({state})'), flush=True)
        return 2
    return 0


def task(case: str) -> int:
    """The scheduled task's body: ``case`` with its output kept, then done.json (always)."""
    directory = HOME / 'out' / case
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / 'task-output.txt').open('w', encoding='utf-8')
    sys.stdout = sys.stderr = stream
    code = 2
    try:
        code = run_case(case, fresh=False)
    except BaseException as error:
        print(clean(f'task error: {type(error).__name__}: {error}'), flush=True)
    finally:
        (directory / 'done.json').write_text(json.dumps({'exit': code, 'finished': time.time()}) + '\n',
                                             encoding='utf-8')
        stream.flush()
    return code


def verdict_of(case: str) -> int:
    path = HOME / 'out' / case / 'result.json'
    try:
        found = json.loads(path.read_text(encoding='utf-8'))['verdict']
    except (OSError, ValueError, KeyError):
        found = 'none'
    print(clean(f'VERDICT-OF {case} {found}'))
    return 0


def main() -> int:
    if not HOME.parts:
        raise SystemExit('V643_HOME is required off Windows')
    command, *rest = sys.argv[1:] or ['']
    if command == 'config':
        path = write_config(rest[0] if rest else None)
        print(f'config written: {path.name} (provider, env_key, web_search disabled'
              f'{", windows.sandbox" if rest else ""}; no secret)')
        return 0
    if command == 'versions':
        versions(Log(rest[0] if rest else 'V'))
        return 0
    if command == 'r0':
        return r0()
    if command in ('case', 'schedule', 'task', 'verdict') and (not rest or rest[0] not in CASES):
        print(f'usage: drive643.py {command} {"|".join(CASES)}')
        return 2
    if command == 'case':
        return run_case(rest[0])
    if command == 'schedule':
        return schedule(rest[0], float(rest[1]) if len(rest) > 1 else 900)
    if command == 'task':
        return task(rest[0])
    if command == 'verdict':
        return verdict_of(rest[0])
    if command == 'session':
        log = Log('I')  # step I's evidence: every poll's answer, with the time
        found, shown = console_session()
        log.say(f'session poll at {time.strftime("%H:%M:%S")} (query user; the user name is never printed)')
        for text in shown:
            log.say(f'SESSION line: {text}')
        log.say(f'SESSION {found}')
        return 0 if found.startswith('ACTIVE') else 1
    if command == 'scan':
        return scan(rest[0])
    if command == 'scrub':
        counts, _ = scrub_tree(Path(rest[0]), json.loads(Path(rest[1]).read_text(encoding='utf-8')), [])
        print(f'SCRUB replacements: {json.dumps(counts, sort_keys=True) if counts else "none"}')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
