"""Task 650, VM side: Claude Code, Pi and DSH as graftling hosts on real Windows x64 (W8-W11).

Run by steps.zsh over ``gcloud compute ssh`` as ``C:\\v650\\driver.cmd <command> ...`` (provision.ps1 writes driver.cmd;
it runs this file on graftling's uv tool venv python). Every case runs in the VM user's interactive console session, as
a scheduled task started from SSH (``schedule``; Tasks 643/644's arrangement):

  versions <step>        Windows, uv, graftling, Node, npm, pnpm, Claude Code, Pi, DSH, Git into out/<step>/.
  session                the VM user's console session from ``query user`` (SESSION ACTIVE <id> console | NONE).
  schedule <case> <s>    run ``task <case>`` as a scheduled task (principal: the SID of this SSH token, LogonType
                         Interactive, RunLevel Highest), wait at most <s> s for its done file, print its console,
                         remove the task.
  task <case>            the scheduled task's body: ``case <case>``, output kept, then out/<case>/done.json.
  case <case>            one case (CASES). Each item prints ``CASE <case> <item>: PASS|FAIL|OBSERVED <observable>``;
                         last ``RESULT <case> PASS | FAIL (<items>) | NO-TOOL-CALL (<why>) | STOP <reason>``.
  cleanup <case>         end what a case may have left (hosts, Runtimes, DSH services, holding tools, owners).
  scan <step>            before evidence leaves the VM: fail (exit 3) if the key or the autologon password is in
                         out/<step> (never printed); then replace every settings value and IP address; counts only.
  scrub <dir> <json>     the same replacement on any directory (the Mac's second pass), values from <json>.

CASES: r0 (preflight: each host answers one line with its configured model and login), venv (I1/H2, D2, I6),
claude (O1-O3, O5, required result 1), claude-refuse (O6, O7), claude-caller (O4), claude-probe (O8),
claude-market (O9), pi (H1, H3-H6, H9, required result 2), pi-refuse (H8), pi-caller (H6, H7), pi-nonascii (H11),
pi-kill (H10), dsh (D3-D5, required result 3), dsh-nonascii (D9), dsh-stop (D5 stop, D8), dsh-kill (D6, D7).
Each host's child is a DSH child (runtime dsh) created by the host's real model through graftling's MCP tool.
Layout (``HOME``: C:\\v650 on Windows, V650_HOME elsewhere): settings.json, trace.ps1, mcp_probe.py, work\\<case>\\,
out\\<step>\\. Everything printed passes through the scrub first. Rehearsal only (off Windows): V650_STANDIN names
rehearsal/standin_runtime.py, which replaces claude, pi, dsh and the DSH owner; V650_VENV replaces the venv paths;
``schedule`` starts ``task`` as a plain subprocess and the Win32 facts read NOT-WINDOWS.
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
_HOME = os.environ.get('V650_HOME') or (r'C:\v650' if WINDOWS else '')
HOME = Path(_HOME).resolve() if _HOME else Path()
STANDIN = os.environ.get('V650_STANDIN')
# graftling's uv tool venv: this driver runs on its python (driver.cmd). Rehearsal: V650_VENV.
VENV = Path(os.environ.get('V650_VENV') or sys.prefix)
VENVPY = VENV / ('Scripts/python.exe' if WINDOWS else 'bin/python')
SITE = VENV / 'Lib' / 'site-packages' if WINDOWS else VENV / 'site'
SUBAGENTS = VENV / ('Scripts/subagents.exe' if WINDOWS else 'bin/subagents')
BASEPY = Path(getattr(sys, '_base_executable', sys.executable))
USERHOME = Path.home()
CLAUDE = USERHOME / '.local' / 'bin' / 'claude.exe'
NPMBIN = Path(os.environ.get('APPDATA', '')) / 'npm'
PI = NPMBIN / 'pi.cmd'
DSH = NPMBIN / 'dsh.cmd'
CHILD_TOKEN = 'CHILD-650-OK'
# The subagents CLI takes one JSON request (graftling.cli); a bare word such as `status` is invalid-input.
STATUS_REQUEST = '{"action":"execute","feature":"status","arguments":{}}'
NONASCII = '项目-ü-650'
NONASCII_TOKEN = '完成-ü-650'
CASES = ('r0', 'venv', 'claude', 'claude-refuse', 'claude-caller', 'claude-probe', 'claude-market',
         'pi', 'pi-refuse', 'pi-caller', 'pi-nonascii', 'pi-kill', 'dsh', 'dsh-nonascii', 'dsh-stop', 'dsh-kill')
SLEEPS = {'pi-kill': '6503', 'dsh-stop': '6501', 'dsh-kill': '6502'}
# 648's record line (handoff H4), written as <site>\zz_record_648.pth while a host case runs.
RECORD_LINE = ("import json, os, sys; open(os.path.join(sys.prefix, 'starts-648.jsonl'), 'a', encoding='utf-8')"
               ".write(json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'prefix': sys.prefix, "
               "'executable': sys.executable, 'argv': sys.orig_argv}) + '\\n')")
CALLER = ('controlled-host', 'actual-parent', 'parent-session', 'dsh')
OWNER_MARK = 'from graftling.dsh.driver import DshDriver'
OWNER = r'''
import json, os, sys
from pathlib import Path
from graftling import AgentControl, Caller, bind
from graftling.dsh.driver import DshDriver
control = AgentControl(Path(sys.argv[1]), {'dsh': DshDriver(Path(sys.argv[2]), json.loads(sys.argv[3]))})
call = bind(control, Caller(*json.loads(sys.argv[4])))
print(json.dumps({'pid': os.getpid()}), flush=True)
for line in sys.stdin:
    print(json.dumps(call(json.loads(line)).document), flush=True)
'''


# --- settings, scrubbing, output -----------------------------------------------------------------------------

def settings() -> dict:
    return json.loads((HOME / 'settings.json').read_text(encoding='utf-8'))


def key_value() -> str | None:
    """The temporary key, from this process or the VM user's registry (never printed)."""
    name = settings()['key_env']
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
    """The autologon password step I set (Winlogon DefaultPassword; never printed). Rehearsal: V650_PASSWORD."""
    if not WINDOWS:
        return os.environ.get('V650_PASSWORD') or None
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


# PROTECTED public product strings (correction 1): DSH's npm scope token. Every form in which DSH's package occurs in
# paths, command lines, npm logs and URLs contains it: '@<scope>/dsh', '@<scope>\dsh', '@<scope>\\dsh' (JSON),
# '%40<scope>%2fdsh', any case. It names the product, not the user's provider choice, and is already in committed
# files. The scrub masks it before replacing settings values and restores it afterwards; the 00/V guard (steps.zsh,
# which reads this list) ignores occurrences of a value that lie only inside it, and refuses a value containing it.
PROTECTED = ('deepseek-ai',)
_SENTINELS = (re.compile(rb'\x01\x00V\x006\x005\x000\x00P\x00((?:\d\x00)+)\x02\x00'),  # UTF-16-LE
              re.compile(rb'\x01V650P(\d+)\x02'))  # UTF-8


def protect(data: bytes) -> tuple[bytes, list[bytes]]:
    """Each PROTECTED occurrence (any case, UTF-8 and UTF-16-LE) -> a numbered sentinel; the originals in order."""
    kept: list[bytes] = []
    for name in PROTECTED:
        for encoding in ('utf-8', 'utf-16-le'):
            def hide(match: re.Match, encoding: str = encoding) -> bytes:
                kept.append(match.group(0))
                return f'\x01V650P{len(kept) - 1}\x02'.encode(encoding)
            data = re.sub(re.escape(name.encode(encoding)), hide, data, flags=re.IGNORECASE)
    return data, kept


def unprotect(data: bytes, kept: list[bytes]) -> bytes:
    if not kept:
        return data
    for sentinel in _SENTINELS:
        def back(match: re.Match) -> bytes:
            index = int(match.group(1).replace(b'\x00', b''))
            return kept[index] if index < len(kept) else match.group(0)
        data = sentinel.sub(back, data)
    return data


def scrub_bytes(data: bytes, pairs: list[list[str]], counts: dict) -> bytes:
    """Replace each value (case-insensitive, UTF-8 and UTF-16-LE) and each IP address by its placeholder; the
    PROTECTED product strings are masked meanwhile and come back unchanged."""
    data, kept = protect(data)
    data = _replace(data, pairs, counts)
    return unprotect(data, kept)


def _replace(data: bytes, pairs: list[list[str]], counts: dict) -> bytes:
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
        self.step = step
        self.dir = HOME / 'out' / step
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = (self.dir / 'console.txt').open('a', encoding='utf-8')
        self.items: list[dict] = []

    def say(self, text: str) -> None:
        text = clean(str(text))
        print(text, flush=True)
        self.file.write(text + '\n')
        self.file.flush()

    def item(self, name: str, verdict: str, observable: str, **facts: object) -> None:
        """One handoff item: ``CASE <case> <name>: PASS|FAIL|OBSERVED <observable>`` (one line)."""
        self.items.append({'item': name, 'verdict': verdict, 'observable': observable, **facts})
        self.say(f'CASE {self.step} {name}: {verdict} {" ".join(str(observable).split())}')
        self.save('items.json', self.items)

    def save(self, name: str, document: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        return path

    def text(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.write_text(content, encoding='utf-8')
        return path


class NoToolCall(Exception):
    """The model made no tool call (the step offers one rerun)."""


# --- processes -------------------------------------------------------------------------------------------------

def run(argv: list, timeout: float = 120, **options: object) -> dict:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=timeout, **options)
        return {'argv': [str(a) for a in argv], 'exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'argv': [str(a) for a in argv], 'exit': None, 'error': repr(error)}


def ps(script: str, seconds: float = 120) -> dict:
    return run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], seconds)


def processes() -> dict[int, dict]:
    """pid -> {ppid, name, exe, cmd} for every process (Windows: Win32_Process; POSIX: graftling's listing)."""
    if WINDOWS:
        out = ps('[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | Select-Object '
                 'ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress', 60)
        try:
            rows = json.loads(out.get('stdout') or '[]')
        except ValueError:
            return {}
        if isinstance(rows, dict):
            rows = [rows]
        return {row['ProcessId']: {'ppid': row['ParentProcessId'], 'name': row['Name'],
                                   'exe': row.get('ExecutablePath') or '', 'cmd': row.get('CommandLine') or ''}
                for row in rows}
    from graftling.member_processes import _user_pids, parent_pid
    from graftling.tool_descendants import _argv
    found = {}
    for pid in _user_pids():
        try:
            argv = _argv(pid)
        except OSError:
            continue
        if argv:
            found[pid] = {'ppid': parent_pid(pid) or 0, 'name': Path(argv[0]).name, 'exe': argv[0],
                          'cmd': ' '.join(argv)}
    return found


def alive(pid: int) -> bool:
    from graftling.tool_descendants import identity
    return identity(pid) is not None


def wait_for(predicate, seconds: float, step: float = 2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def kill(pid: int) -> None:
    try:
        os.kill(pid, 9)  # TerminateProcess on Windows, SIGKILL elsewhere
    except OSError:
        pass


def same_path(one: object, other: object) -> bool:
    norm = lambda text: re.sub(r'^\\\\\?\\', '', str(text)).rstrip('\\/').replace('/', '\\').casefold()
    return bool(one) and bool(other) and norm(one) == norm(other)


def short(text: object, size: int = 160) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= size else text[:size] + '...'


def in_any_job(pid: int | None = None) -> bool | None:
    if not WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000, False, pid or os.getpid())
    if not handle:
        return None
    try:
        result = wintypes.BOOL()
        return bool(result.value) if k32.IsProcessInJob(handle, None, ctypes.byref(result)) else None
    finally:
        k32.CloseHandle(handle)


def in_job(pid: int, name: str | None) -> bool | str | None:
    if not WINDOWS or not name:
        return None
    from graftling import _win32
    try:
        job = _win32.open_job(name)
    except OSError as error:
        return f'job not open: {error}'
    try:
        return _win32.process_in_job(pid, job)
    except OSError as error:
        return f'process not readable: {error}'
    finally:
        _win32.close_handle(job)


# --- the Runtimes' settings (no secret is written; the key goes only into a started process's environment) -----

def ambient_endpoints() -> tuple[str, ...]:
    from graftling.dsh.settings import AMBIENT_ENDPOINTS
    return tuple(AMBIENT_ENDPOINTS)


def tool_path() -> None:
    """Put the provisioned tools first on PATH (a session may predate the installers' PATH changes)."""
    os.environ['DISABLE_AUTOUPDATER'] = '1'  # Claude Code stays at the pinned version during the run
    if not WINDOWS:
        return
    extra = [str(USERHOME / '.local' / 'bin'), r'C:\Program Files\nodejs', str(NPMBIN), r'C:\Program Files\Git\cmd']
    os.environ['PATH'] = os.pathsep.join([*extra, os.environ.get('PATH', '')])


def base_env() -> dict:
    """This session's environment without graftling's, the Runtimes' and DSH's ambient endpoint variables, plus
    the shared key under KEY_ENV (the DSH child connection's api_key_env)."""
    env = dict(os.environ)
    drop = {'GRAFTLING_CONNECTION', 'GRAFTLING_PYTHON', 'GRAFTLING_DATA_ROOT', 'GRAFTLING_DSH_CONFIG',
            '__PYVENV_LAUNCHER__', *ambient_endpoints()}
    for name in list(env):
        if name in drop or name.startswith(('ANTHROPIC_', 'CLAUDE_CODE_', 'GRAFTLING_CLAUDE_HOST_')):
            env.pop(name)
    key = key_value()
    if key:
        env[settings()['key_env']] = key
    env['PYTHONUTF8'] = '1'
    return env


def claude_env() -> dict:
    claude, key = settings()['claude'], key_value() or ''
    env = base_env()
    env.update({'ANTHROPIC_BASE_URL': claude['base_url'], claude['auth_var']: key,
                'ANTHROPIC_MODEL': claude['model'], 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
    for field, name in (('haiku', 'ANTHROPIC_DEFAULT_HAIKU_MODEL'), ('sonnet', 'ANTHROPIC_DEFAULT_SONNET_MODEL'),
                        ('opus', 'ANTHROPIC_DEFAULT_OPUS_MODEL'), ('subagent', 'CLAUDE_CODE_SUBAGENT_MODEL'),
                        ('api_timeout_ms', 'API_TIMEOUT_MS')):
        if claude.get(field):
            env[name] = claude[field]
    return env


def pi_env() -> dict:
    pi, env = settings()['pi'], base_env()
    if pi['route'] == 'builtin':
        env[pi['key_var']] = key_value() or ''
    return env


def dsh_env() -> dict:
    main, env = settings()['dsh_main'], base_env()
    env[main['key_var']] = key_value() or ''
    if main.get('base_url'):
        env[ambient_endpoints()[0]] = main['base_url']
    return env


def write_pi_models() -> str:
    """Pi's custom route: %USERPROFILE%\\.pi\\agent\\models.json names the key by its variable, never its value."""
    pi = settings()['pi']
    if pi['route'] != 'custom':
        return 'built-in provider (no models.json written)'
    agent = Path(os.environ.get('PI_CODING_AGENT_DIR') or USERHOME / '.pi' / 'agent')
    agent.mkdir(parents=True, exist_ok=True)
    document = {'providers': {pi['provider']: {'baseUrl': pi['base_url'], 'api': pi['api'],
                                               'apiKey': settings()['key_env'], 'models': [{'id': pi['model']}]}}}
    (agent / 'models.json').write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return 'custom provider in models.json (apiKey names the key variable)'


def dsh_child() -> dict:
    """The DSH child connection: model, sandbox, api_key_env = KEY_ENV, and provider/base_url when set."""
    child = settings()['dsh_child']
    entry = {'model': child['model'], 'sandbox': 'read-only', 'api_key_env': settings()['key_env']}
    entry.update({name: child[name] for name in ('provider', 'base_url') if child.get(name)})
    return entry


def connection_yml(root: Path) -> None:
    """<root>/config.yml: one connection, runtime dsh, for the Pi and DSH hosts' DSH child."""
    child = dsh_child()
    lines = ['connections:', '  child-dsh:', '    runtime: dsh']
    for name in ('provider', 'base_url', 'api_key_env'):
        if child.get(name):
            lines.append(f'    {name}: {json.dumps(child[name])}')
    lines += ['    models:', f'      - {json.dumps(child["model"])}']
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.yml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def runtime_argv(kind: str, arguments: list[str]) -> list[str]:
    """The Runtime's real entry: claude.exe (native installer), npm's pi.cmd and dsh.cmd (run through cmd.exe as a
    PowerShell prompt would). Rehearsal: the stand-in."""
    if STANDIN:
        return [sys.executable, STANDIN, kind, *arguments]
    return [str({'claude': CLAUDE, 'pi': PI, 'dsh': DSH}[kind]), *arguments]


def claude_args(prompt: str, *extra: str) -> list[str]:
    return ['-p', prompt, '--output-format', 'stream-json', '--verbose', '--max-turns', '15', *extra]


def pi_args(prompt: str) -> list[str]:
    pi = settings()['pi']
    return ['--provider', pi['provider'], '--model', pi['model'], '-p', '--mode', 'json', prompt]


def dsh_args(prompt: str) -> list[str]:
    return ['--profile', 'headless', *settings()['dsh_main'].get('app_args', []), prompt]


# --- one host run: started, watched (process shape, trace, channel), ended ---------------------------------------

class Tracer:
    """Win32_ProcessStartTrace/StopTrace through trace.ps1 (every process start with its parent, command line and
    path while it is alive; every stop with its exit status). Off Windows: nothing."""

    def __init__(self, log: Log, label: str) -> None:
        self.out = log.dir / f'{label}-trace.jsonl'
        self.stop_file = log.dir / f'{label}-trace.stop'
        self.process = None
        if not WINDOWS:
            return
        self.out.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.process = subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(HOME / 'trace.ps1'), '-Out', str(self.out),
                                         '-StopFile', str(self.stop_file)],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: self.out.exists() and '"ready"' in self.out.read_text(encoding='utf-8', errors='replace'),
                 30, 0.5)

    def close(self) -> list[dict]:
        if self.process is not None:
            self.stop_file.write_text('stop', encoding='utf-8')
            try:
                self.process.wait(20)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.stop_file.unlink(missing_ok=True)
        return read_jsonl(self.out)


def read_jsonl(path: Path) -> list[dict]:
    found = []
    if path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                found.append(value)
    return found


def descends(table: dict, pid: int, root: int) -> bool:
    seen = set()
    while pid in table and pid not in seen:
        if pid == root:
            return True
        seen.add(pid)
        pid = table[pid]['ppid']
    return pid == root


def host_run(log: Log, label: str, argv: list[str], cwd: Path, env: dict, seconds: float,
             markers: tuple[str, ...] = (), channel: Path | None = None, during=None, after_s: float = 10) -> dict:
    """Start the Runtime, sample Win32_Process every ~3 s (its tree and every process naming a marker), copy
    ``channel`` while it exists, call ``during(table, run)`` on each sample, wait at most ``seconds``; then watch
    for ``after_s`` which host processes outlive it (session end)."""
    tracer = Tracer(log, label)
    out, err = (log.dir / f'{label}-stdout.txt').open('w', encoding='utf-8'), \
        (log.dir / f'{label}-stderr.txt').open('w', encoding='utf-8')
    began = time.monotonic()
    shown = [Path(argv[0]).name, *[('<prompt>' if len(a) > 60 else a) for a in argv[1:]]]
    log.say(f'[{label}] $ {" ".join(shown)}   (cwd {cwd}; bound {seconds:.0f} s)')
    result: dict = {'label': label, 'rows': {}, 'channel': None, 'timed_out': False}
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
    except OSError as error:
        out.close(), err.close(), tracer.close()
        raise RuntimeError(f'{label}: the Runtime did not start: {error}') from None
    result['pid'] = process.pid
    mine = set()
    while True:
        table = processes()
        if not mine:
            mine = set(ancestry(table, os.getpid()))
        for pid, row in table.items():
            if pid in mine:
                continue
            if pid == process.pid or descends(table, pid, process.pid) or any(m in row['cmd'] for m in markers):
                kept = result['rows'].setdefault(pid, {**row, 'pid': pid, 'first_s': round(time.monotonic() - began, 1)})
                kept['last_s'] = round(time.monotonic() - began, 1)
        if channel is not None and channel.exists() and result['channel'] is None:
            try:
                result['channel'] = json.loads(channel.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        if during is not None:
            during(table, result)
        if process.poll() is not None:
            break
        if time.monotonic() - began > seconds:
            result['timed_out'] = True
            process.kill()
            process.wait(30)
            break
        time.sleep(3 if WINDOWS else 0.5)
    result['exit'] = process.returncode
    result['seconds'] = round(time.monotonic() - began, 1)
    out.close(), err.close()
    hosts = [pid for pid, row in result['rows'].items() if any(m in row['cmd'] for m in markers)]
    gone_at: dict[int, float | None] = {}
    watch_began = time.monotonic()
    while time.monotonic() - watch_began < after_s:
        for pid in hosts:
            if pid not in gone_at and not alive(pid):
                gone_at[pid] = round(time.monotonic() - watch_began, 1)
        if len(gone_at) == len(hosts):
            break
        time.sleep(0.5)
    result['host_gone_after_exit_s'] = {pid: gone_at.get(pid) for pid in hosts}
    result['left_after'] = [pid for pid in hosts if pid not in gone_at]
    result['trace'] = tracer.close()
    result['stdout'] = (log.dir / f'{label}-stdout.txt').read_text(encoding='utf-8', errors='replace')
    result['stderr'] = (log.dir / f'{label}-stderr.txt').read_text(encoding='utf-8', errors='replace')
    log.save(f'{label}-processes.json', {key: value for key, value in result.items() if key not in ('stdout', 'stderr')})
    log.say(f'[{label}] exit {result["exit"]} after {result["seconds"]} s{" (BOUND REACHED, ended)" if result["timed_out"] else ""}; '
            f'{len(result["rows"])} process(es) seen; trace events {len(result["trace"])}')
    return result


def rows_with(run_: dict, marker: str) -> list[dict]:
    """Processes (sampled or traced) whose command line names ``marker``, each with its parent's row."""
    table = dict(run_['rows'])
    for event in run_.get('trace', []):
        if event.get('kind') == 'start' and event.get('pid') not in table:
            table[event['pid']] = {'pid': event['pid'], 'ppid': event.get('ppid'), 'name': event.get('name') or '',
                                   'exe': event.get('exe') or '', 'cmd': event.get('cmd') or '', 'traced_only': True}
    found = []
    for pid, row in table.items():
        if marker in (row.get('cmd') or ''):
            parent = table.get(row.get('ppid')) or {}
            found.append({**row, 'pid': pid, 'parent': {key: parent.get(key) for key in ('pid', 'name', 'exe', 'cmd')}
                          if parent else {'pid': row.get('ppid'), 'name': 'not seen'}})
    return found


def shape_text(row: dict) -> str:
    parent = row.get('parent') or {}
    return (f'pid {row.get("pid")} exe {row.get("exe") or row.get("name")} cmd {short(row.get("cmd"), 120)!r} <- parent '
            f'pid {parent.get("pid")} {parent.get("exe") or parent.get("name")} cmd {short(parent.get("cmd"), 100)!r}')


def stops(run_: dict) -> dict[int, dict]:
    return {event['pid']: event for event in run_.get('trace', []) if event.get('kind') == 'stop' and 'pid' in event}


# --- the venv record (648's .pth line) -----------------------------------------------------------------------------

class Recording:
    """While a host case runs: <site>\\zz_record_648.pth appends one line per venv-prefixed Python start to
    <venv>\\starts-648.jsonl. Removed afterwards (always)."""

    def __init__(self, log: Log) -> None:
        self.log = log
        self.pth = SITE / 'zz_record_648.pth'
        self.starts = VENV / 'starts-648.jsonl'

    def __enter__(self) -> 'Recording':
        SITE.mkdir(parents=True, exist_ok=True)
        self.starts.unlink(missing_ok=True)
        self.pth.write_text(RECORD_LINE + '\n', encoding='utf-8')
        return self

    def __exit__(self, *exc: object) -> None:
        self.pth.unlink(missing_ok=True)
        if self.starts.exists():
            shutil.copyfile(self.starts, self.log.dir / 'starts-648.jsonl')

    def records(self, marker: str) -> list[dict]:
        """Records whose argv names ``marker``, one per pid (CPython 3.13 runs a venv .pth twice: 648)."""
        found: dict = {}
        for record in read_jsonl(self.starts):
            if any(marker in str(part) for part in record.get('argv') or []):
                found.setdefault(record.get('pid'), record)
        return list(found.values())


# --- criteria as pure functions (correction 3; also used offline by rehearsal/rejudge.py on retained evidence) ----

def own_records(records: list[dict], parent_pid: object, venv: object = None) -> tuple[bool, str, str]:
    """H5/D4: only records whose parent is the host's own node count; the others (e.g. a DSH child's graftling.mcp
    started through Scripts\\python.exe under the child service's node) are listed separately."""
    venv = venv or VENV
    mine = [r for r in records if r.get('ppid') == parent_pid]
    others = [r for r in records if r.get('ppid') != parent_pid]
    ok = bool(mine) and all(same_path(r.get('prefix'), venv) for r in mine)
    text = (f'{len(mine)} record(s) with parent {parent_pid}: ' + '; '.join(
        f'pid {r.get("pid")} prefix is the venv {same_path(r.get("prefix"), venv)} executable {r.get("executable")}'
        for r in mine[:3])) if mine else f'no record with parent {parent_pid}'
    other = ('; '.join(f'pid {r.get("pid")} ppid {r.get("ppid")} executable {r.get("executable")}' for r in others[:4])
             or 'none')
    return ok, text, other


def o3_judgement(stream: dict) -> tuple[str, str]:
    """O3 from Claude's own tool results: FAIL if any subagents result is authority-denied or names the native call
    association; PASS needs at least one subagents call answered without an error."""
    uses = [use for use in stream['uses'] if 'subagents' in str(use.get('name'))]
    results = [stream['results'].get(use.get('id')) or {} for use in uses]
    refused = [r.get('text', '') for r in results if 'authority-denied' in r.get('text', '')
               or 'native call association' in r.get('text', '')]
    answered = [r for r in results if r and not r.get('is_error') and '"error"' not in r.get('text', '')]
    verdict = 'FAIL' if refused or not answered else 'PASS'
    return verdict, (f'{len(uses)} subagents call(s) in stream-json: {len(answered)} answered without an error, '
                     f'{len(refused)} refused (authority-denied / native call association)'
                     + (f'; first refusal {short(refused[0], 200)!r}' if refused else ''))


def deep_json(value: object):
    """Every value inside ``value``, decoding JSON found in strings however deeply it is escaped."""
    yield value
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ('{', '['):
            try:
                inner = json.loads(text)
            except ValueError:
                return
            yield from deep_json(inner)
    elif isinstance(value, dict):
        for item in value.values():
            yield from deep_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from deep_json(item)


def status_answered(events: list[dict]) -> bool:
    """H6: a subagents status result {"result": {"agents": [...]}} among ``events``, at any escaping depth."""
    return any(isinstance(v, dict) and isinstance(v.get('result'), dict) and isinstance(v['result'].get('agents'), list)
               for event in events for v in deep_json(event))


def first_bash(events: list[dict]) -> int:
    """Index of Pi's first bash tool execution (the prompt's own text also names the script, so it does not count)."""
    return next((index for index, event in enumerate(events) if event.get('type') == 'tool_execution_start'
                 and str(event.get('toolName', '')).lower() == 'bash'), len(events))


HANDOFF_O4 = 'launched directly by the selected Claude CLI'


def o4_judgement(text: str, code: int | None) -> tuple[str, str]:
    """O4: PASS on a refusal (non-zero exit, no {"prepared": true}); the refusal text verbatim."""
    prepared = re.search(r'"prepared"\s*:\s*true', text) is not None
    verdict = 'PASS' if code not in (0, None) and not prepared else 'FAIL'
    body = ' '.join(line for line in text.splitlines() if not line.startswith('exit=')).strip()
    note = '' if HANDOFF_O4 in text else f' (not the handoff\'s "{HANDOFF_O4}" text)'
    return verdict, (f'exit {code}; prepared {prepared}; refusal text verbatim: {body[:400]!r}{note}')


def record_text(records: list[dict], parent_pid: object) -> tuple[bool, str]:
    ok = bool(records) and all(same_path(r.get('prefix'), VENV) and r.get('ppid') == parent_pid for r in records)
    return ok, (f'{len(records)} record(s) (one per pid): ' + '; '.join(
        f'pid {r.get("pid")} ppid {r.get("ppid")} prefix is the venv {same_path(r.get("prefix"), VENV)} executable '
        f'{r.get("executable")}' for r in records[:3]) if records else 'no record line')


# --- reading what the Runtimes and graftling wrote -----------------------------------------------------------------

def walk(document: object, where: str = ''):
    if isinstance(document, dict):
        for key, value in document.items():
            yield where + '/' + key, key, value
            yield from walk(value, where + '/' + key)
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from walk(value, f'{where}[{index}]')


def claude_stream(text: str) -> dict:
    """Claude Code's stream-json: the init event (MCP server status, model, version), tool uses and their results
    (by tool_use id), the result event and the models it used."""
    found: dict = {'init': {}, 'uses': [], 'results': {}, 'result': {}, 'models': []}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if kind == 'system' and event.get('subtype') == 'init':
            found['init'] = event
        elif kind in ('assistant', 'user'):
            for part in (event.get('message') or {}).get('content') or []:
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'tool_use':
                    found['uses'].append({'id': part.get('id'), 'name': part.get('name'), 'input': part.get('input')})
                elif part.get('type') == 'tool_result':
                    content = part.get('content')
                    if isinstance(content, list):
                        content = ' '.join(str(item.get('text', '')) for item in content if isinstance(item, dict))
                    found['results'][part.get('tool_use_id')] = {'text': str(content or ''),
                                                                 'is_error': part.get('is_error')}
        elif kind == 'result':
            found['result'] = event
            found['models'] = sorted((event.get('modelUsage') or {}).keys())
    return found


def mcp_status(init: dict, name_part: str) -> list[str]:
    return [f'{server.get("name")}={server.get("status")}' for server in init.get('mcp_servers') or []
            if isinstance(server, dict) and name_part in str(server.get('name'))]


def json_events(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def subagent_calls(events: list[dict]) -> int:
    """How many tool calls of graftling's subagents tool a Runtime's JSON events show (any field naming it)."""
    count = 0
    for event in events:
        for _, key, value in walk(event):
            if key in ('name', 'toolName', 'tool_name', 'tool') and isinstance(value, str) and 'subagents' in value:
                count += 1
    return count


def models_in(events: list[dict]) -> list[str]:
    found = []
    for event in events:
        for _, key, value in walk(event):
            if key in ('model', 'modelId', 'model_id') and isinstance(value, str) and value not in found:
                found.append(value)
    return found


def agent_records(root: Path) -> list[dict]:
    found = []
    directory = root / 'control' / 'agents'
    for path in sorted(directory.glob('*.json')) if directory.is_dir() else []:
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        found.append({'file': path.name, 'document': document})
    return found


def record_runtime(record: dict) -> str | None:
    document = record['document']
    for _, key, value in walk(document):
        if key == 'runtime' and isinstance(value, str):
            return value
    return None


def child_answer(records: list[dict], token: str) -> dict:
    """The DSH child whose graftling record holds ``token`` and its last outcome."""
    for record in records:
        text = json.dumps(record['document'], ensure_ascii=False)
        if token in text:
            outcomes = [value for _, key, value in walk(record['document']) if key == 'outcome' and isinstance(value, str)]
            return {'agent': record['file'], 'runtime': record_runtime(record), 'outcomes': outcomes}
    return {}


def collect(root: Path, target: Path) -> None:
    """Copy graftling's records and logs under ``root`` (no symbolic link is followed; no Runtime session logs)."""
    if not root.is_dir():
        return
    for path in root.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix in ('.json', '.yml', '.log', '.txt') and path.stat().st_size < 2_000_000:
            destination = target / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def file_text(path: Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''


def npm_added(text: str) -> str:
    """npm's own summary line, e.g. 'added 670 packages in 18m' (649's runner log is the real sample)."""
    found = re.findall(r'added \d+ packages?(?:, [^\n]*?)? in [\d.]+\s*[a-z]+', text)
    return found[-1] if found else 'no npm summary line'


# --- preflight R0 --------------------------------------------------------------------------------------------------

def say_reported(log: Log, label: str, reported: list[str], configured: str) -> str:
    verdict = 'PASS' if reported and configured in reported else ('OBSERVED' if not reported else 'FAIL')
    log.item(f'{label} model', verdict,
             f'model(s) reported {reported or "none found in its output"}; configured {configured}')
    return verdict


def case_r0(log: Log) -> None:
    """Each host answers a one-line prompt with its configured model and login, in this console session."""
    token = 'PONG650'
    prompt = f'Reply with exactly the word {token} and nothing else. Do not use any tool.'
    log.say('versions first, then one line per Runtime (no tool, no graftling call)')
    facts = versions(log)
    same = facts.get('graftling_head') == settings().get('candidate')
    log.item('graftling candidate', 'PASS' if same else 'FAIL',
             f'graftling installed from the bundle checkout at {facts.get("graftling_head")}; candidate '
             f'{settings().get("candidate")}')
    work = HOME / 'work'
    claude = settings()['claude']
    directory = work / 'r0-claude'
    directory.mkdir(parents=True, exist_ok=True)
    done = host_run(log, 'claude', runtime_argv('claude', claude_args(prompt)), directory, claude_env(), 300)
    stream = claude_stream(done['stdout'])
    answer = str(stream['result'].get('result') or '')
    log.item('claude answer', 'PASS' if token in answer else 'FAIL',
             f'exit {done["exit"]}; result {short(answer, 80)!r}; is_error {stream["result"].get("is_error")}; '
             f'claude_code_version {stream["init"].get("claude_code_version")}; stderr tail '
             f'{short(done["stderr"][-200:], 200)!r}')
    reported = [value for value in [stream['init'].get('model'), *stream['models']] if value]
    say_reported(log, 'claude', sorted(set(reported)), claude['model'])
    log.say(f'claude login: {claude["auth_var"]} from the shared key, ANTHROPIC_BASE_URL set (value not shown)')
    pi = settings()['pi']
    log.say(f'pi route: {write_pi_models()}')
    directory = work / 'r0-pi'
    directory.mkdir(parents=True, exist_ok=True)
    done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 300)
    events = json_events(done['stdout'])
    text = done['stdout']
    log.item('pi answer', 'PASS' if token in text else 'FAIL',
             f'exit {done["exit"]}; {len(events)} JSON event(s); answer token present {token in text}; stderr tail '
             f'{short(done["stderr"][-200:], 200)!r}')
    say_reported(log, 'pi', models_in(events), pi['model'])
    directory = work / 'r0-dsh'
    directory.mkdir(parents=True, exist_ok=True)
    helped = run(runtime_argv('dsh', ['--profile', 'headless', '--help']), 60, cwd=str(directory), env=dsh_env())
    log.text('dsh-headless-help.txt', (helped.get('stdout') or '') + (helped.get('stderr') or ''))
    began = time.time()
    done = host_run(log, 'dsh', runtime_argv('dsh', dsh_args(prompt)), directory, dsh_env(), 420)
    logs = dsh_session_logs(USERHOME / '.dsh', began) + dsh_session_logs(directory, began)
    reported = []
    for path in logs:
        for value in models_in(read_jsonl(path)):
            if value not in reported:
                reported.append(value)
    log.item('dsh answer', 'PASS' if token in done['stdout'] else 'FAIL',
             f'exit {done["exit"]}; stdout {short(done["stdout"][-120:], 120)!r}; stderr tail '
             f'{short(done["stderr"][-200:], 200)!r}; its headless app flags: out/r0/dsh-headless-help.txt')
    log.item('dsh model', 'OBSERVED', f'model(s) in its new session log(s) {reported or "none found"} '
             f'({len(logs)} log(s)); the main Session runs on its profile and DSH_MAIN_* settings')


def dsh_session_logs(base: Path, since: float) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted((path for path in base.rglob('v4.jsonl') if path.stat().st_mtime >= since - 5),
                  key=lambda path: path.stat().st_mtime)


# --- the venv (I1/H2, D2, I6) --------------------------------------------------------------------------------------

def case_venv(log: Log) -> None:
    out = run([str(VENVPY), '-c', 'import sys; print(sys.executable); print(sys._base_executable); print(sys.prefix)'])
    lines = (out.get('stdout') or '').splitlines()
    differ = len(lines) >= 2 and not same_path(lines[0], lines[1])
    child = []
    if WINDOWS:
        sleeper = subprocess.Popen([str(VENVPY), '-c', 'import time; time.sleep(30)'])
        time.sleep(3)
        child = [{'pid': pid, **row} for pid, row in processes().items() if row['ppid'] == sleeper.pid]
        sleeper.kill()
        sleeper.wait(30)
    log.save('venv.json', {'venvpy': str(VENVPY), 'lines': lines, 'children_of_launcher': child})
    log.item('H2/I1 uv venv launcher', 'OBSERVED',
             f'sys.executable and sys._base_executable differ: {differ} ({lines[:2]}); a Start-Process of the venv '
             f'python has child process(es) {[(row["pid"], row["name"], row["exe"]) for row in child]}'
             f'{"" if WINDOWS else " (not Windows: no launcher)"}')
    config = VENV / 'pyvenv.cfg'
    home = next((line.split('=', 1)[1].strip() for line in file_text(config).splitlines()
                 if line.split('=', 1)[0].strip() == 'home'), None)
    log.item('I6 pyvenv.cfg home', 'OBSERVED',
             f'home {home}; holds python.exe {bool(home) and (Path(home) / "python.exe").exists()}; site-packages '
             f'{SITE} exists {SITE.is_dir()}; base executable {BASEPY}')
    probe = ('import shutil; from graftling.dsh.settings import dsh_package; '
             "print(dsh_package(shutil.which('dsh')))")
    out = run([str(VENVPY), '-c', probe], 60, env={**os.environ, 'PATH': os.environ.get('PATH', '')})
    package = (out.get('stdout') or '').strip()
    want = NPMBIN / 'node_modules' / '@deepseek-ai' / 'dsh' / 'package.json'
    log.item('D2 graftling finds DSH through the shim', ('PASS' if same_path(package, want) else 'FAIL') if WINDOWS
             else 'OBSERVED', f'dsh_package(shutil.which("dsh")) -> {package or short(out.get("stderr"), 200)}; expected '
                          f'{want}')


# --- Claude Code host --------------------------------------------------------------------------------------------

def claude_project(log: Log, directory: Path, runtimes: dict | None = None) -> tuple[Path, Path]:
    """configuration --write (as docs/install/claude-code.md), runtimes.dsh added to claude-host.json, and the
    project MCP server approved in .claude/settings.local.json (what Claude Code's approval prompt writes)."""
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    out = run([str(VENVPY), '-m', 'graftling.claude.host', 'configuration', '--project', str(directory),
               '--claude', str(CLAUDE), '--write'], 120)
    log.text('configuration-write.txt', json.dumps(out, ensure_ascii=False, indent=2))
    if out.get('exit') != 0:
        raise RuntimeError(f'configuration --write failed: {short(out.get("stderr") or out.get("error"), 300)}')
    config = directory / '.agents-control' / 'claude-host.json'
    document = json.loads(config.read_text(encoding='utf-8'))
    if runtimes:
        document['runtimes'] = runtimes
        config.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    local = directory / '.claude' / 'settings.local.json'
    settings_local = json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    settings_local['enabledMcpjsonServers'] = ['graftling']
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(settings_local, indent=2) + '\n', encoding='utf-8')
    for name in ('.mcp.json', '.claude/settings.local.json', '.agents-control/claude-host.json'):
        if (directory / name).exists():
            shutil.copyfile(directory / name, log.dir / ('written-' + name.replace('/', '_').lstrip('.')))
    return config, directory / '.agents-control'


# CLAUDE_HOST_LOAD (correction 3): how the Claude host cases make Claude Code load the generated plugin
# .claude/skills/agents-claude-host. none (empty): as the first sitting (left to Claude Code). trust: the folder trust
# the interactive dialog records, projects[<abs path>].hasTrustDialogAccepted = true in Claude Code's global config
# (<CLAUDE_CONFIG_DIR or home>/.claude.json; step M checks the key in the 2.1.314 binary). plugin-dir: --plugin-dir
# <that directory>, which is NOT graftling's documented route.
CLAUDE_TRUST_KEY = 'hasTrustDialogAccepted'


def claude_load(log: Log, directory: Path) -> list[str]:
    mode = settings()['claude'].get('host_load') or 'none'
    plugin = directory / '.claude' / 'skills' / 'agents-claude-host'
    if mode == 'trust':
        config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or USERHOME) / '.claude.json'
        document = json.loads(file_text(config) or '{}')
        keys = list(dict.fromkeys([str(directory), directory.as_posix()]))
        for key in keys:
            document.setdefault('projects', {}).setdefault(key, {})[CLAUDE_TRUST_KEY] = True
        config.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        log.item('CLAUDE_HOST_LOAD trust', 'OBSERVED',
                 f'wrote projects[<project>].{CLAUDE_TRUST_KEY} = true for {keys} into {config} before the run')
        return []
    if mode == 'plugin-dir':
        log.item('CLAUDE_HOST_LOAD plugin-dir', 'OBSERVED',
                 f'--plugin-dir {plugin}: NOT graftling\'s documented route (that is the project plugin loaded by '
                 'Claude Code itself)')
        return ['--plugin-dir', str(plugin)]
    log.item('CLAUDE_HOST_LOAD none', 'OBSERVED', 'no load aid: the generated plugin is left to Claude Code (documented route)')
    return []


def mcp_json_item(log: Log, directory: Path) -> None:
    server = (json.loads(file_text(directory / '.mcp.json') or '{}').get('mcpServers') or {}).get('graftling') or {}
    env = server.get('env') or {}
    ok = same_path(server.get('command'), BASEPY) and same_path(env.get('__PYVENV_LAUNCHER__'), VENVPY)
    log.item('.mcp.json from the uv venv', 'PASS' if ok or not WINDOWS else 'FAIL',
             f'command {server.get("command")} (base interpreter {BASEPY}); env {env}; args {server.get("args")}')


def claude_end(log: Log, done: dict, root: Path, hosts: list[dict], tag: str = 'O5 session end') -> None:
    """O5/M18: after Claude Code exits (print mode ends the session the way Claude Code stops stdio servers)."""
    hostlog = file_text(root / 'host.log')
    lines = [line for line in hostlog.splitlines() if line.strip()]
    channel = (root / 'live' / 'channel.json').exists()
    left = done['left_after']
    stopped = stops(done)
    order = []
    for row in hosts:
        event = stopped.get(row['pid'])
        if event:
            order.append(f'host {row["pid"]} stopped {event.get("t")} exit status {event.get("exit")}')
    claude_stop = stopped.get(done['pid'], {})
    ok = bool(lines) and lines[-1].endswith('subagents host recorded its children stopped.') and not channel and not left
    log.item(tag, 'PASS' if ok else 'FAIL',
             f'host.log last line {short(lines[-1] if lines else "(empty)", 110)!r}; channel.json '
             f'{"REMAINS" if channel else "gone"}; host python alive 10 s after Claude Code exited: {left}; gone after '
             f'(s) {done["host_gone_after_exit_s"]}; trace: {"; ".join(order) or "no host stop event"}; claude.exe '
             f'stopped {claude_stop.get("t")}; Claude Code {claude_version()} in print mode (-p): the session ends '
             'at the end of the turn, not at /exit')


_CLAUDE_VERSION: str | None = None


def claude_version() -> str:
    global _CLAUDE_VERSION
    if _CLAUDE_VERSION is None:
        _CLAUDE_VERSION = (run(runtime_argv('claude', ['--version']), 60).get('stdout') or '').strip() or 'unknown'
    return _CLAUDE_VERSION


def no_tool(done: dict, why: str) -> None:
    """NO-TOOL-CALL only when the Runtime ended normally; a Runtime that failed or hit the bound is a STOP."""
    if done.get('timed_out') or done.get('exit') not in (0, None):
        raise RuntimeError(f'{done.get("label")} exited {done.get("exit")}{" at the bound" if done.get("timed_out") else ""} '
                           f'without the call ({why}); stderr tail {short(done.get("stderr", "")[-300:], 300)!r}; '
                           f'stdout tail {short(done.get("stdout", "")[-200:], 200)!r}')
    raise NoToolCall(why)


def require_tool_call(done: dict, stream: dict, hostlog: str, what: str) -> None:
    used = [use for use in stream['uses'] if 'subagents' in str(use.get('name'))]
    if not used and 'subagents-call' not in hostlog:
        no_tool(done, f'the model made no {what} call (tool uses: {[u.get("name") for u in stream["uses"]]})')


def case_claude(log: Log) -> None:
    """O1, O2, O3, O5 and required result 1: Claude Code creates a DSH child through graftling's MCP tool."""
    directory = HOME / 'work' / 'claude-host'
    config, root = claude_project(log, directory, {'dsh': dsh_child()})
    load = claude_load(log, directory)
    mcp_json_item(log, directory)
    prompt = (f'Use the subagents tool (mcp__graftling__subagents), not your own Task subagents. First call it with '
              f'action execute, feature create and arguments runtime dsh, model {settings()["dsh_child"]["model"]}, '
              f'instruction "Reply with exactly {CHILD_TOKEN} and nothing else. Do not use any tool." Then call it '
              f'with action execute, feature wait, the new agent and timeout_seconds 300. Then call it with action '
              f'execute, feature retire and that agent. Finally reply with the child\'s answer.')
    with Recording(log) as recording:
        done = host_run(log, 'claude', runtime_argv('claude', claude_args(
            prompt, '--allowedTools', 'mcp__graftling__subagents', *load)), directory, claude_env(), 600,
            markers=('graftling.claude.host',), channel=root / 'live' / 'channel.json')
    collect(root, log.dir / 'agents-control')
    stream = claude_stream(done['stdout'])
    hostlog = file_text(root / 'host.log')
    log.save('claude-stream-summary.json', {'init': {k: stream['init'].get(k) for k in (
        'mcp_servers', 'model', 'claude_code_version', 'cwd')}, 'uses': stream['uses'], 'results': stream['results'],
        'result': {k: stream['result'].get(k) for k in ('subtype', 'is_error', 'result', 'num_turns')}})
    hosts = [row for row in rows_with(done, 'graftling.claude.host') if ' serve' in row['cmd']]
    # The host's actual parent; it must be the configured claude.exe (the native installer's
    # %USERPROFILE%\.local\bin\claude.exe, which the driver started; a launcher hop would show here).
    claude_pid = hosts[0].get('ppid') if hosts else done['pid']
    parent_exe = (hosts[0].get('parent') or {}).get('exe') if hosts else None
    parent_ok = same_path(parent_exe, CLAUDE) if WINDOWS else claude_pid == done['pid']
    status = mcp_status(stream['init'], 'graftling')
    channel = done.get('channel') or {}
    host_ok = bool(hosts) and parent_ok and all(row.get('ppid') == claude_pid and same_path(row.get('exe'), BASEPY)
                                                 for row in hosts)
    refused = 'did not start' in hostlog
    o1 = status == ['graftling=connected'] and channel.get('parent') == claude_pid and host_ok and not refused
    log.item('O1 MCP server is claude.exe\'s direct child', 'PASS' if o1 else 'FAIL',
             f'init mcp_servers {status or "none"}; channel.json parent {channel.get("parent")}; host\'s parent '
             f'{claude_pid} is the configured claude.exe {parent_ok} (the started claude.exe pid {done["pid"]}); host '
             f'{"; ".join(shape_text(row) for row in hosts[:2]) or "not seen"}; host.log '
             f'{"has a did-not-start line: " + short(hostlog[hostlog.find("did not start"):], 200) if refused else "no did-not-start line"}')
    records = recording.records('graftling.claude.host')
    ok, text = record_text(records, claude_pid)
    log.item('O2 .mcp.json env reaches the server', 'PASS' if o1 and ok else 'FAIL',
             f'{text}; the base interpreter imports graftling only through __PYVENV_LAUNCHER__')
    require_tool_call(done, stream, hostlog, 'subagents')
    verdict, observable = o3_judgement(stream)
    log.item('O3 mod context call (direct child)', verdict, observable)
    contexts = [row for row in rows_with(done, ' -I -c ') if 'context' in row['cmd']]
    log.item('O3 traced context process(es)', 'OBSERVED',
             f'{"; ".join(shape_text(row) for row in contexts[:2]) or "none traced"}')
    answer = child_answer(agent_records(root), CHILD_TOKEN)
    final = str(stream['result'].get('result') or '')
    log.item('child created through MCP and answered (required result 1)',
             'PASS' if answer.get('runtime') == 'dsh' and 'completed' in answer.get('outcomes', []) else 'FAIL',
             f'child record {answer.get("agent") or "with the token: none"} runtime {answer.get("runtime")} outcomes '
             f'{answer.get("outcomes")}; Claude\'s final reply holds the token {CHILD_TOKEN in final}; subagents tool '
             f'uses {len([u for u in stream["uses"] if "subagents" in str(u.get("name"))])}')
    claude_end(log, done, root, hosts)
    log.item('629 s6.4 process shape (Claude host)', 'OBSERVED',
             f'claude.exe pid {claude_pid}; hosts: {"; ".join(shape_text(row) for row in hosts) or "none"}; DSH child '
             f'service: {"; ".join(shape_text(row) for row in rows_with(done, "@deepseek-ai")[:2]) or "not seen"}')


def case_claude_refuse(log: Log) -> None:
    """O6 (and O7 noted): a Claude child is refused on the Windows host."""
    directory = HOME / 'work' / 'claude-refuse'
    _, root = claude_project(log, directory)
    load = claude_load(log, directory)
    prompt = ('Use the subagents tool (mcp__graftling__subagents), not your own Task subagents: call it once with '
              'action execute, feature create and arguments runtime claude, instruction "Reply with OK." Then reply '
              'with the error code and the first sentence of the error message it returned. Do not retry.')
    done = host_run(log, 'claude', runtime_argv('claude', claude_args(
        prompt, '--allowedTools', 'mcp__graftling__subagents', *load)), directory, claude_env(), 420,
        markers=('graftling.claude.host',), channel=root / 'live' / 'channel.json')
    collect(root, log.dir / 'agents-control')
    stream = claude_stream(done['stdout'])
    hostlog = file_text(root / 'host.log')
    log.save('claude-stream-summary.json', {'uses': stream['uses'], 'results': stream['results']})
    require_tool_call(done, stream, hostlog, 'subagents create')
    texts = ' '.join(result['text'] for result in stream['results'].values())
    message = 'A Claude child cannot run on native Windows'
    claudes = [row for row in done['rows'].values() if row['name'].lower() == 'claude.exe' and row['pid'] != done['pid']]
    runtimes = [record_runtime(record) for record in agent_records(root)]
    ok = 'unsupported-runtime' in texts and message in texts and 'claude' not in runtimes and not claudes
    log.item('O6 Claude child refused', 'PASS' if ok else 'FAIL',
             f'tool result has unsupported-runtime {"unsupported-runtime" in texts}, the message {message in texts} '
             f'({short(texts[texts.find(message):] if message in texts else texts, 160)!r}); agent records '
             f'{runtimes}; other claude.exe processes {[(row["pid"], row["ppid"]) for row in claudes]}')
    log.item('O7 failIfUnavailable and rule syntax', 'OBSERVED',
             'not exercised: no Claude child starts on native Windows (O6); Claude Code documents that with '
             'sandbox.failIfUnavailable it exits at startup there (inference from its documents)')
    hosts = [row for row in rows_with(done, 'graftling.claude.host') if ' serve' in row['cmd']]
    claude_end(log, done, root, hosts, 'O5 session end (no child)')


def bash_script(path: Path, lines: list[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    return path.as_posix()


def outcome_file(path: Path) -> tuple[str, int | None]:
    text = file_text(path)
    match = re.findall(r'exit=(-?\d+)', text)
    return text, int(match[-1]) if match else None


def case_claude_caller(log: Log) -> None:
    """O4: a Bash-tool caller is not Claude Code's direct child: context and the subagents CLI are refused."""
    directory = HOME / 'work' / 'claude-caller'
    config, root = claude_project(log, directory)
    load = claude_load(log, directory)
    (directory / 'prepare.json').write_text('{}\n', encoding='utf-8')
    out1, out2 = directory / 'o4-context.txt', directory / 'o4-cli.txt'
    script = bash_script(directory / 'o4.sh', [
        f'"{VENVPY.as_posix()}" -m graftling.claude.host context --config "{config.as_posix()}" '
        f'< "{(directory / "prepare.json").as_posix()}" > "{out1.as_posix()}" 2>&1',
        f'echo "exit=$?" >> "{out1.as_posix()}"',
        f'"{SUBAGENTS.as_posix()}" \'{STATUS_REQUEST}\' > "{out2.as_posix()}" 2>&1',
        f'echo "exit=$?" >> "{out2.as_posix()}"', 'echo O4-DONE'])
    prompt = (f'Use your Bash tool to run exactly this command and wait for it: bash {script}   Run nothing else. '
              'Then reply with exactly O4-DONE.')
    done = host_run(log, 'claude', runtime_argv('claude', claude_args(prompt, '--allowedTools', 'Bash', *load)),
                    directory, claude_env(), 420, markers=('graftling.claude.host', 'o4.sh'),
                    channel=root / 'live' / 'channel.json')
    collect(root, log.dir / 'agents-control')
    stream = claude_stream(done['stdout'])
    log.save('claude-stream-summary.json', {'uses': stream['uses'], 'results': stream['results']})
    for path in (out1, out2):
        if path.exists():
            shutil.copyfile(path, log.dir / path.name)
    if not out1.exists() and not [u for u in stream['uses'] if u.get('name') in ('Bash', 'PowerShell')]:
        no_tool(done, f'the model made no Bash call (tool uses: {[u.get("name") for u in stream["uses"]]})')
    text1, code1 = outcome_file(out1)
    verdict, observable = o4_judgement(text1, code1)
    log.item('O4 context from a Bash-tool caller', verdict, observable)
    text2, code2 = outcome_file(out2)
    codes = re.findall(r'"code":\s*"([^"]+)"', text2)
    log.item('O4 subagents CLI from a Bash-tool caller', 'PASS' if code2 not in (0, None) and codes else 'FAIL',
             f'exit {code2}; refused with {codes or "no error code"} (the handoff expects authority-denied; without '
             f'GRAFTLING_CONNECTION graftling may refuse earlier); {short(text2, 200)!r}')
    log.item('629 s6.1 pipe identity (Claude, tool caller)', 'OBSERVED',
             f'shells and launchers between claude.exe and the caller: '
             f'{"; ".join(shape_text(row) for row in rows_with(done, "graftling.claude.host context")[:2]) or "not sampled (short-lived)"}')


def case_claude_probe(log: Log) -> None:
    """O8 probe: does ${VAR:-default} expand in a plugin mcpServers command on native Windows? The default is the
    base interpreter, so the probe server's own record tells: venv python = expanded with the variable, base python
    = expanded with the default, no record and a failed server = no expansion."""
    directory = HOME / 'work' / 'claude-probe'
    shutil.rmtree(directory, ignore_errors=True)
    plugin = directory / 'probe-plugin'
    (plugin / '.claude-plugin').mkdir(parents=True)
    started = directory / 'probe-started.jsonl'
    manifest = {'name': 'probe650', 'version': '0.0.1', 'description': 'Task 650 probe',
                'mcpServers': {'probe650': {'command': '${PROBE_650_PYTHON:-' + BASEPY.as_posix() + '}',
                                            'args': [(HOME / 'mcp_probe.py').as_posix(), started.as_posix()]}}}
    (plugin / '.claude-plugin' / 'plugin.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(plugin / '.claude-plugin' / 'plugin.json', log.dir / 'probe-plugin.json')
    project = directory / 'project'
    project.mkdir()
    env = {**claude_env(), 'PROBE_650_PYTHON': str(VENVPY)}
    done = host_run(log, 'claude', runtime_argv('claude', claude_args(
        'Reply with exactly PROBE-650-OK.', '--plugin-dir', str(plugin), '--debug')), project, env, 300,
        markers=('mcp_probe.py',))
    stream = claude_stream(done['stdout'])
    status = mcp_status(stream['init'], 'probe650')
    records = read_jsonl(started)
    if started.exists():
        shutil.copyfile(started, log.dir / started.name)
    lines = [line for line in (done['stderr'] + '\n' + debug_lines(done)).splitlines() if 'probe650' in line]
    log.text('probe-debug-lines.txt', '\n'.join(lines) + '\n')
    executables = [record.get('executable') for record in records]
    if any(same_path(one, VENVPY) for one in executables):
        reading = 'expanded with the variable (the venv python ran)'
    elif any(same_path(one, BASEPY) for one in executables):
        reading = 'expanded with the default (the variable was not seen)'
    elif records:
        reading = f'another command ran: {executables}'
    else:
        reading = 'no probe process started: no expansion (the literal ${...} command) or another start failure; see the debug lines'
    log.item('O8 ${VAR:-default} in a plugin mcpServers command', 'OBSERVED',
             f'init mcp_servers {status or "none named probe650"}; probe records {len(records)} {executables}; '
             f'reading: {reading}; debug lines naming probe650: {len(lines)} '
             f'(first {short(lines[0], 160) if lines else "none"!r})')


def debug_lines(run_: dict) -> str:
    """Claude Code --debug writes ~/.claude/debug/*.txt; only lines naming probe650 or graftling are kept."""
    directory = USERHOME / '.claude' / 'debug'
    kept = []
    if directory.is_dir():
        for path in directory.glob('*.txt'):
            if path.stat().st_mtime >= time.time() - run_['seconds'] - 60:
                kept += [line for line in file_text(path).splitlines() if 'probe650' in line or 'graftling' in line]
    return '\n'.join(kept)


def case_claude_market(log: Log) -> None:
    """O9: the marketplace plugin on native Windows fails clearly, without and with a sh on Claude Code's PATH."""
    directory = HOME / 'work' / 'claude-market'
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    package = run([str(VENVPY), '-c', 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent)'])
    market = (package.get('stdout') or '').strip()
    env = claude_env()
    steps = [run(runtime_argv('claude', ['plugin', 'marketplace', 'add', market]), 120, cwd=str(directory), env=env),
             run(runtime_argv('claude', ['plugin', 'install', 'graftling@graftling', '--scope', 'project']), 120,
                 cwd=str(directory), env=env)]
    log.save('plugin-install.json', steps)
    log.say(f'marketplace add exit {steps[0].get("exit")}; plugin install exit {steps[1].get("exit")}')
    findings = []
    try:
        for label, extra in (('no-sh', None), ('with-sh', r'C:\Program Files\Git\usr\bin')):
            run_env = dict(env)
            if extra:
                run_env['PATH'] = extra + os.pathsep + run_env.get('PATH', '')
            hostlog = directory / '.agents-control' / 'host.log'
            before = file_text(hostlog)
            done = host_run(log, f'claude-{label}', runtime_argv('claude', claude_args(
                'Reply with exactly MARKET-650-OK.')), directory, run_env, 300, markers=('graftling',))
            stream = claude_stream(done['stdout'])
            status = mcp_status(stream['init'], 'graftling')
            added = file_text(hostlog)[len(before):]
            unsupported = 'not supported on native Windows' in added
            started = [row for row in rows_with(done, 'graftling.claude.host') if 'serve' in row['cmd']]
            findings.append(f'{label}: mcp_servers {status or "none named graftling"}; host.log new lines '
                            f'{short(added, 200)!r}; unsupported line {unsupported}; a host started {bool(started)}')
            log.item(f'O9 marketplace plugin ({label.replace("-", " ")})', 'OBSERVED', findings[-1])
    finally:
        cleanup_steps = [run(runtime_argv('claude', ['plugin', 'uninstall', 'graftling@graftling', '--scope',
                                                     'project']), 120, cwd=str(directory), env=env),
                         run(runtime_argv('claude', ['plugin', 'marketplace', 'remove', 'graftling']), 120,
                             cwd=str(directory), env=env)]
        log.save('plugin-remove.json', cleanup_steps)
        collect(directory / '.agents-control', log.dir / 'agents-control')


# --- Pi host -------------------------------------------------------------------------------------------------------

def pi_project(directory: Path) -> Path:
    shutil.rmtree(directory, ignore_errors=True)
    root = directory / '.agents-control'
    connection_yml(root)
    return root


def pi_hosts(done: dict) -> tuple[list[dict], list[dict], int | None]:
    hosts = rows_with(done, 'graftling.pi.host')
    servers = rows_with(done, 'graftling.mcp')
    node = hosts[0].get('ppid') if hosts else None
    return hosts, servers, node


def pi_end(log: Log, done: dict, hosts: list[dict], servers: list[dict], node: object, tag: str = 'H9 session end') -> None:
    stopped = stops(done)
    failed = 'Independent Pi host failed' in done['stdout'] + done['stderr']
    left = [row['pid'] for row in hosts + servers if alive(row['pid'])]
    node_stop = (stopped.get(node) or {}).get('t') if isinstance(node, int) else None
    order = [f'{"host" if row in hosts else "mcp"} {row["pid"]} stop {(stopped.get(row["pid"]) or {}).get("t")} '
             f'exit {(stopped.get(row["pid"]) or {}).get("exit")}' for row in hosts + servers]
    log.item(tag, 'PASS' if not left and not failed and hosts else 'FAIL',
             f'host/MCP processes alive 10 s after Pi ended: {left}; "Independent Pi host failed" in Pi\'s output '
             f'{failed}; trace: {"; ".join(order) or "no stop events"}; node {node} stop {node_stop}; print mode (-p): '
             'a host stop before node\'s means session_shutdown closed its stdin, after it means stdin EOF at node\'s '
             'exit (I5/I6 reading)')


def require_pi_call(done: dict, events: list[dict], root: Path, what: str) -> None:
    if not subagent_calls(events) and not agent_records(root):
        no_tool(done, f'the model made no {what} call ({len(events)} JSON event(s))')


def case_pi(log: Log) -> None:
    """H1, H3-H6, H9 and required result 2: Pi creates a DSH child through graftling's MCP tool."""
    directory = HOME / 'work' / 'pi-host'
    root = pi_project(directory)
    log.say(f'pi route: {write_pi_models()}')
    prompt = (f'Use the subagents tool of the MCP server graftling (mcp__graftling__subagents). First call it with '
              f'action execute, feature create and arguments runtime dsh, model {settings()["dsh_child"]["model"]}, '
              f'instruction Reply with exactly {CHILD_TOKEN} and nothing else. Do not use any tool. Then call it with '
              'action execute, feature wait, the new agent and timeout_seconds 300. Then call it with action execute, '
              'feature retire and that agent. Finally reply with the child answer.')
    with Recording(log) as recording:
        done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 600,
                        markers=('graftling.pi.host', 'graftling.mcp'))
    collect(root, log.dir / 'agents-control')
    events = json_events(done['stdout'])
    hosts, servers, node = pi_hosts(done)
    extension_error = re.findall(r'Extension error[^\n]*', done['stdout'] + done['stderr'])
    live = root / 'live' / 'pi-host'
    log.item('H1 extension loads, host starts', 'PASS' if hosts and not extension_error else 'FAIL',
             f'host process(es) {len(hosts)}; extension errors {[short(e, 120) for e in extension_error[:2]]}; '
             f'live/pi-host exists {live.exists()} (entries {sorted(p.name for p in live.iterdir())[:3] if live.exists() else []})')
    node_row = done['rows'].get(node) or {}
    cmd_parent = done['rows'].get(node_row.get('ppid')) or {}
    entry_ok = 'pi-coding-agent' in node_row.get('cmd', '') and node_row.get('name', '').lower().startswith('node')
    h3 = bool(hosts) and entry_ok and all(same_path(row.get('exe'), BASEPY) for row in hosts)
    log.item('H3 process shape pi.cmd -> cmd.exe -> node.exe -> host', 'PASS' if h3 or STANDIN and hosts else 'FAIL',
             f'host {"; ".join(shape_text(row) for row in hosts[:1]) or "not seen"}; node cmd names Pi\'s entry '
             f'{entry_ok}; node\'s parent {cmd_parent.get("name")} {short(cmd_parent.get("cmd"), 80)!r}')
    ok, text = record_text(recording.records('graftling.pi.host'), node)
    log.item('H4 the host runs as the tool venv', 'PASS' if ok else 'FAIL', text)
    ok5, text5, other5 = own_records(recording.records('graftling.mcp'), node)
    own_servers = [row for row in servers if row.get('ppid') == node]
    log.item('H5 Pi passes the registered env to the MCP server', 'PASS' if ok5 else 'FAIL',
             f'{text5}; MCP server process(es) of node {"; ".join(shape_text(row) for row in own_servers[:1]) or "not seen"}')
    log.item('H5 other graftling.mcp processes', 'OBSERVED',
             f'records not under Pi\'s node: {other5}; processes: '
             f'{"; ".join(shape_text(row) for row in servers if row.get("ppid") != node)[:400] or "none"}')
    require_pi_call(done, events, root, 'subagents')
    answer = child_answer(agent_records(root), CHILD_TOKEN)
    denied = 'authority-denied' in done['stdout']
    log.item('H6 MCP calls pass the direct-child check', 'PASS' if answer and not denied else 'FAIL',
             f'subagents tool calls in Pi\'s events {subagent_calls(events)}; authority-denied in Pi\'s output {denied}')
    log.item('child created through MCP and answered (required result 2)',
             'PASS' if answer.get('runtime') == 'dsh' and 'completed' in answer.get('outcomes', []) else 'FAIL',
             f'child record {answer.get("agent") or "with the token: none"} runtime {answer.get("runtime")} outcomes '
             f'{answer.get("outcomes")}; Pi\'s output holds the token {CHILD_TOKEN in done["stdout"]}')
    pi_end(log, done, hosts, servers, node)
    log.item('629 s6.4/s6.5 process shape and end (Pi host)', 'OBSERVED',
             f'node {node} cmd {short(node_row.get("cmd"), 120)!r}; servers '
             f'{"; ".join(shape_text(row) for row in servers[:2]) or "none"}')


def case_pi_refuse(log: Log) -> None:
    """H8: a Pi child is refused on Windows, with its reason."""
    directory = HOME / 'work' / 'pi-refuse'
    root = pi_project(directory)
    write_pi_models()
    prompt = ('Use the subagents tool of the MCP server graftling (mcp__graftling__subagents): call it once with action '
              'execute, feature create and arguments runtime pi, instruction Reply with OK. Then reply with the error '
              'code and the first sentence of the error message it returned. Do not retry.')
    done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 420,
                    markers=('graftling.pi.host', 'graftling.mcp'))
    collect(root, log.dir / 'agents-control')
    events = json_events(done['stdout'])
    require_pi_call(done, events, root, 'subagents create')
    message = 'Pi children are not supported on Windows: a Pi child runs only inside srt'
    text = done['stdout']
    runtimes = [record_runtime(record) for record in agent_records(root)]
    ok = 'unsupported-runtime' in text and message in text and 'pi' not in runtimes
    log.item('H8 Pi child refused', 'PASS' if ok else 'FAIL',
             f'unsupported-runtime in Pi\'s events {"unsupported-runtime" in text}; message {message in text}; agent '
             f'records {runtimes}')
    hosts, servers, node = pi_hosts(done)
    pi_end(log, done, hosts, servers, node, 'H9 session end (no child)')


def case_pi_caller(log: Log) -> None:
    """H6 (status) and H7: a caller under Pi's bash tool is not a direct child of Pi's node."""
    directory = HOME / 'work' / 'pi-caller'
    root = pi_project(directory)
    write_pi_models()
    out = directory / 'h7.txt'
    script = bash_script(directory / 'h7.sh', [
        f'd=$(ls -d "{(root / "live" / "pi-host").as_posix()}"/control-* 2>/dev/null | head -1)',
        f'echo "connection=$d" > "{out.as_posix()}"',
        f'GRAFTLING_CONNECTION="$d" "{SUBAGENTS.as_posix()}" \'{STATUS_REQUEST}\' >> "{out.as_posix()}" 2>&1',
        f'echo "exit=$?" >> "{out.as_posix()}"', 'echo H7-DONE'])
    prompt = ('Do these two things in order. 1. Call the subagents tool of the MCP server graftling '
              '(mcp__graftling__subagents) with action execute, feature status and no arguments. 2. Use your bash tool '
              f'to run exactly this command and wait for it: bash {script}   Run nothing else. Then reply with the '
              'status result and H7-DONE.')
    done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 420,
                    markers=('graftling.pi.host', 'graftling.mcp', 'h7.sh'))
    collect(root, log.dir / 'agents-control')
    events = json_events(done['stdout'])
    if out.exists():
        shutil.copyfile(out, log.dir / out.name)
    if not out.exists() and not subagent_calls(events):
        no_tool(done, f'the model made neither call ({len(events)} JSON event(s))')
    text = done['stdout']
    before = events[:first_bash(events)]  # the status result, however deeply its JSON is escaped, before the bash call
    status_ok = status_answered(before) and 'authority-denied' not in json.dumps(before)
    log.item('H6 status through MCP', 'PASS' if subagent_calls(events) and status_ok else 'FAIL',
             f'subagents calls {subagent_calls(events)}; an agents list before the bash call {status_ok}')
    text7, code = outcome_file(out)
    refused = code not in (0, None) and 'authority-denied' in text7
    log.item('H7 caller under Pi\'s bash tool refused', 'PASS' if refused else 'FAIL',
             f'exit {code}; {short(text7, 220)!r} (expected "The client is not owned by this native Pi host.")')
    log.item('629 s6.1 pipe identity (Pi, tool caller)', 'OBSERVED',
             f'{"; ".join(shape_text(row) for row in rows_with(done, "subagents")[:2]) or "caller not sampled (short-lived)"}')


def case_pi_nonascii(log: Log) -> None:
    """H11 (optional): H1, H6 and H9 with the project under a non-ASCII directory."""
    directory = HOME / 'work' / NONASCII / 'pi'
    root = pi_project(directory)
    write_pi_models()
    prompt = ('Call the subagents tool of the MCP server graftling (mcp__graftling__subagents) with action execute, '
              'feature status and no arguments, then reply with STATUS-650-DONE.')
    done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 420,
                    markers=('graftling.pi.host', 'graftling.mcp'))
    collect(root, log.dir / 'agents-control')
    events = json_events(done['stdout'])
    require_pi_call(done, events, root, 'subagents status')
    hosts, servers, node = pi_hosts(done)
    live = root / 'live' / 'pi-host'
    log.item('H11 H1 under a non-ASCII project', 'PASS' if hosts and live.exists() else 'FAIL',
             f'project {directory}; host process(es) {len(hosts)}; live/pi-host exists {live.exists()}')
    log.item('H11 H6 status', 'PASS' if subagent_calls(events) and 'authority-denied' not in done['stdout'] else 'FAIL',
             f'subagents calls {subagent_calls(events)}; authority-denied {"authority-denied" in done["stdout"]}')
    pi_end(log, done, hosts, servers, node, 'H11 H9 session end')


def case_pi_kill(log: Log) -> None:
    """H10 (optional): Pi's node.exe is killed while a tool holds; the host sees stdin close and exits."""
    directory = HOME / 'work' / 'pi-kill'
    root = pi_project(directory)
    write_pi_models()
    number = SLEEPS['pi-kill']
    prompt = (f'Use your bash tool to run exactly: sleep {number}   and wait for it. Then reply with DONE.')
    killed: dict = {}

    def during(table: dict, run_: dict) -> None:
        if killed:
            return
        hosts = [pid for pid, row in table.items() if 'graftling.pi.host' in row['cmd']]
        holding = [pid for pid, row in table.items() if f'sleep {number}' in row['cmd']]
        if hosts and holding:
            node = table[hosts[0]]['ppid']
            killed.update(node=node, host=hosts[0], at=time.monotonic(), sleep=holding)
            kill(node)

    done = host_run(log, 'pi', runtime_argv('pi', pi_args(prompt)), directory, pi_env(), 300,
                    markers=('graftling.pi.host', 'graftling.mcp'), during=during)
    collect(root, log.dir / 'agents-control')
    if not killed:
        events = json_events(done['stdout'])
        if not [row for row in done['rows'].values() if f'sleep {number}' in row['cmd']]:
            no_tool(done, f'no sleep {number} appeared (the model made no bash call; {len(events)} event(s))')
        log.item('H10 Pi ends without its shutdown handler', 'FAIL', 'the host and the holding tool were never seen together')
        return
    host = killed['host']
    gone = wait_for(lambda: not alive(host), 10, 0.5)
    stopped = stops(done).get(host) or {}
    left_sleep = [pid for pid in killed['sleep'] if alive(pid)]
    log.item('H10 Pi ends without its shutdown handler', 'PASS' if gone else 'FAIL',
             f'node {killed["node"]} killed (TerminateProcess); host {host} gone within 10 s {bool(gone)}; host stop '
             f'event exit status {stopped.get("exit")}; holding bash sleep still alive: {left_sleep} (Pi\'s own tool, '
             'not graftling\'s)')
    for pid in left_sleep:
        kill(pid)


# --- DSH host ------------------------------------------------------------------------------------------------------

def dsh_project(directory: Path) -> Path:
    shutil.rmtree(directory, ignore_errors=True)
    root = directory / '.agents-control'
    connection_yml(root)
    return root


def patch_rows(root: Path) -> list[str]:
    """Lines of graftling's DSH patch files under ``root`` naming agents-mcp (D5: its row as a file: URL)."""
    found = []
    for path in root.rglob('*.yml') if root.is_dir() else []:
        lines = file_text(path).splitlines()
        for index, line in enumerate(lines):
            if 'agents-mcp' in line:
                found += [short(item, 160) for item in lines[index:index + 3] if 'name' in item or 'agents-mcp' in item]
    return found


def dsh_host_case(log: Log, directory: Path, token: str, extra: str = '') -> None:
    root = dsh_project(directory)
    prompt = (f'Use the subagents tool of the MCP server graftling (mcp__graftling__subagents), not your own '
              f'subagents. First call it with action execute, feature create and arguments runtime dsh, model '
              f'{settings()["dsh_child"]["model"]}, instruction Reply with exactly {token} and nothing else. Do not '
              'use any tool. Then call it with action execute, feature wait, the new agent and timeout_seconds 300. '
              f'Then call it with action execute, feature retire and that agent. Finally reply with the child answer.{extra}')
    with Recording(log) as recording:
        done = host_run(log, 'dsh', runtime_argv('dsh', dsh_args(prompt)), directory, dsh_env(), 720,
                        markers=('graftling.dsh.host', 'graftling.mcp', '@deepseek-ai'))
    collect(root, log.dir / 'agents-control')
    hosts, servers = rows_with(done, 'graftling.dsh.host'), rows_with(done, 'graftling.mcp')
    node = hosts[0].get('ppid') if hosts else None
    node_row = done['rows'].get(node) or {}
    live = root / 'live' / 'dsh-host'
    refused = re.findall(r'graftling-dsh: [^\n]*', done['stdout'] + done['stderr'])
    records = agent_records(root)
    if not records and 'subagents' not in done['stdout'] and not refused:
        no_tool(done, 'the model made no subagents call (no agent record, no mention in its output)')
    answer = child_answer(records, token)
    log.item('D3 DSH host with a real MCP call', 'PASS' if records and not refused and
             'authority-denied' not in done['stdout'] else 'FAIL',
             f'agent records {len(records)}; live/dsh-host existed {live.exists() or bool(hosts)}; refusals '
             f'{[short(r, 120) for r in refused[:2]]}; authority-denied in its output {"authority-denied" in done["stdout"]}')
    entry = 'dsh' in node_row.get('cmd', '') and 'bin.js' in node_row.get('cmd', '') or bool(STANDIN and hosts)
    own_servers = [row for row in servers if row.get('ppid') == node]
    base = all(same_path(row.get('exe'), BASEPY) for row in hosts + own_servers)
    ok_h, text_h, _ = own_records(recording.records('graftling.dsh.host'), node)
    ok_m, text_m, other_m = own_records(recording.records('graftling.mcp'), node)
    log.item('D4 other graftling.mcp processes', 'OBSERVED',
             f'records not under the DSH host\'s node (e.g. a child\'s tool server): {other_m}; processes: '
             f'{"; ".join(shape_text(row) for row in servers if row.get("ppid") != node)[:400] or "none"}')
    venv_named = all(same_path(r.get('executable'), VENVPY) for r in recording.records('graftling.dsh.host'))
    log.item('D4 process shape of the host', 'PASS' if hosts and own_servers and entry and base and ok_h and ok_m else 'FAIL',
             f'host {"; ".join(shape_text(row) for row in hosts[:1]) or "not seen"}; MCP '
             f'{"; ".join(shape_text(row) for row in own_servers[:1]) or "not seen"}; node runs DSH\'s bin.js {entry}; base '
             f'interpreter {base}; host record {text_h}; MCP record {text_m}; __PYVENV_LAUNCHER__ named the venv python '
             f'(record executable) {venv_named}')
    log.item('D5 DSH child: create and a real turn (required result 3)',
             'PASS' if answer.get('runtime') == 'dsh' and 'completed' in answer.get('outcomes', []) else 'FAIL',
             f'child record {answer.get("agent") or "with the token: none"} outcomes {answer.get("outcomes")}; token '
             f'in DSH\'s reply {token in done["stdout"]}; agents-mcp patch rows {patch_rows(root)[:2] or "not found"}')
    services = [row for row in done['rows'].values() if row['name'].lower().startswith('node')
                and row['pid'] != node and 'web' in row.get('cmd', '')]
    left = [row['pid'] for row in services if alive(row['pid'])] + done['left_after']
    log.item('D3 session end: host and child services gone', 'PASS' if not left and hosts else 'FAIL',
             f'host/MCP alive 10 s after DSH exited {done["left_after"]}; child DSH service node(s) seen '
             f'{[row["pid"] for row in services]}, alive after {[pid for pid in left if pid not in done["left_after"]]}')


def case_dsh(log: Log) -> None:
    dsh_host_case(log, HOME / 'work' / 'dsh-host', CHILD_TOKEN)


def case_dsh_nonascii(log: Log) -> None:
    """D9: code page and a non-ASCII project path, prompt and answer."""
    facts = {'ansi_code_page': ps('(Get-Culture).TextInfo.ANSICodePage').get('stdout', '').strip() if WINDOWS else None,
             'chcp': run(['cmd', '/c', 'chcp']).get('stdout', '').strip() if WINDOWS else None,
             'filesystem_encoding': sys.getfilesystemencoding()}
    log.save('code-page.json', facts)
    log.item('D9 code page', 'OBSERVED', f'ANSI code page {facts["ansi_code_page"]}; chcp {facts["chcp"]}')
    directory = HOME / 'work' / NONASCII / 'dsh'
    dsh_host_case(log, directory, NONASCII_TOKEN)
    root = directory / '.agents-control'
    texts = [json.dumps(record['document'], ensure_ascii=False) for record in agent_records(root)]
    log.item('D9 non-ASCII prompt and answer intact', 'PASS' if any(NONASCII_TOKEN in text for text in texts) else 'FAIL',
             f'project {directory}; the token {NONASCII_TOKEN} in graftling\'s records {any(NONASCII_TOKEN in t for t in texts)}')


class Owner:
    """An owner process (AgentControl + DshDriver) in this session; requests on stdin, documents on stdout."""

    def __init__(self, root: Path, cwd: Path, config: dict, env: dict) -> None:
        code = ['-c', OWNER] if not STANDIN else [STANDIN, 'owner']
        self.process = subprocess.Popen([sys.executable, *code, str(root), str(cwd), json.dumps(config),
                                         json.dumps(CALLER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding='utf-8', env=env)
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('the owner process ended before it answered')
        self.pid = json.loads(line)['pid']

    def ask(self, request: dict) -> dict:
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f'the owner process ended during {request.get("action")}')
        return json.loads(line)

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(60)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(30)


def last_result(document: dict) -> dict:
    return (document.get('result') or {}).get('last_result') or {}


def held_tool(number: str) -> str:
    return (f'Use your shell tool to run exactly this PowerShell command and wait for it to finish: Start-Sleep '
            f'{number}   Run nothing else. Then reply with HOLD-DONE.')


def sleeping(number: str) -> list[int]:
    return [pid for pid, row in processes().items() if f'Start-Sleep {number}' in row['cmd']
            and 'Use your shell' not in row['cmd'] and pid != os.getpid()]


def tree_of(table: dict, root_pid: int) -> list[dict]:
    return [{**row, 'pid': pid} for pid, row in table.items() if pid != root_pid and descends(table, pid, root_pid)]


def owner_turn1(log: Log, owner: Owner) -> tuple[str, dict]:
    created = owner.ask({'action': 'create', 'runtime': 'dsh', 'instruction':
                         'Reply with exactly TURN1-650-OK and nothing else. Do not use any tool.'})
    log.save('create.json', created)
    if 'error' in created:
        raise RuntimeError(f'graftling create refused: {json.dumps(created["error"], ensure_ascii=False)[:400]}')
    agent = created['agent']
    done = owner.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 300})
    log.save('turn1.json', done)
    return agent, done


def case_dsh_stop(log: Log) -> None:
    """D5's stop and D8: a DSH child's tool holds; its process shape; graftling's stop; nothing of the service left."""
    work = HOME / 'work' / 'dsh-stop'
    root = work.parent / 'agents-dsh-stop'
    for path in (work, root):
        shutil.rmtree(path, ignore_errors=True)
    work.mkdir(parents=True)
    number = SLEEPS['dsh-stop']
    owner = Owner(root, work, dsh_child(), base_env())
    try:
        log.say(f'owner pid {owner.pid}; work dir {work}')
        agent, turn1 = owner_turn1(log, owner)
        log.item('turn 1 completes', 'PASS' if last_result(turn1).get('outcome') == 'completed' else 'FAIL',
                 f'outcome {last_result(turn1).get("outcome")}; last message {short(last_result(turn1).get("last_message"), 60)!r}')
        sent = owner.ask({'action': 'send', 'agent': agent, 'message': held_tool(number)})
        log.save('send.json', sent)
        held = wait_for(lambda: sleeping(number), 240, 3) or []
        table = processes()
        service = tree_of(table, owner.pid)
        execution = json.loads((root / 'control/agents' / f'{agent}.json').read_text(encoding='utf-8'))['executions'][-1] \
            if (root / 'control/agents' / f'{agent}.json').exists() else {}
        job = (execution.get('process') or {}).get('runtime_job')
        chains = {pid: [(p, table.get(p, {}).get('name')) for p in ancestry(table, pid)] for pid in held}
        log.save('held.json', {'held': held, 'chains': chains, 'service': service, 'runtime_job': job,
                               'in_job': {pid: in_job(pid, job) for pid in held}})
        if not held:
            owner.ask({'action': 'interrupt', 'agent': agent})
            raise NoToolCall(f'no Start-Sleep {number} appeared within 240 s (the model made no shell call)')
        under_node = all(any((name or '').lower().startswith('node') for _, name in chains[pid]) for pid in held)
        log.item('D8 process shape of the child\'s tool', 'PASS' if under_node else 'FAIL',
                 f'Start-Sleep {number} pid(s) {held}, ancestry {chains}; in graftling\'s job {job}: '
                 f'{[in_job(pid, job) for pid in held]}')
        time.sleep(5)
        stop = owner.ask({'action': 'interrupt', 'agent': agent})
        stopped = owner.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 120})
        log.save('stop.json', {'interrupt': stop, 'wait': stopped})
        outcome = last_result(stopped).get('outcome')
        wait_for(lambda: not [pid for pid in held if alive(pid)], 30)
        tools_left = [pid for pid in held if alive(pid)]
        log.item('D5 stop during the second turn', 'PASS' if outcome in ('interrupted', 'stopped') and not tools_left
                 else 'FAIL', f'outcome {outcome}; state {(stopped.get("result") or {}).get("state")}; tool alive 30 s '
                              f'after the stop {tools_left}')
        owner.ask({'action': 'retire', 'agent': agent})
        nodes = [row['pid'] for row in service if row['name'].lower().startswith('node')]
        wait_for(lambda: not [pid for pid in nodes if alive(pid)], 30)
        left = [pid for pid in nodes if alive(pid)]
        log.item('D5 no node.exe of the child\'s DSH service left', 'PASS' if nodes and not left else 'FAIL',
                 f'service processes under the owner {[(row["pid"], row["name"]) for row in service][:6]}; node(s) '
                 f'{nodes} alive 30 s after retire {left}')
    finally:
        owner.close()
        for pid in sleeping(number):
            kill(pid)
        collect(root, log.dir / 'agents')


def ancestry(table: dict, pid: int, depth: int = 8) -> list[int]:
    out, seen = [], set()
    while pid in table and pid not in seen and len(out) < depth:
        seen.add(pid)
        out.append(pid)
        pid = table[pid]['ppid']
    return out


def case_dsh_kill(log: Log) -> None:
    """D6 and D7: the owner is killed hard during a turn; its DSH service ends within 15 s; the session log."""
    work = HOME / 'work' / 'dsh-kill'
    root = work.parent / 'agents-dsh-kill'
    for path in (work, root):
        shutil.rmtree(path, ignore_errors=True)
    work.mkdir(parents=True)
    number = SLEEPS['dsh-kill']
    first = Owner(root, work, dsh_child(), base_env())
    second = None
    try:
        agent, turn1 = owner_turn1(log, first)
        if last_result(turn1).get('outcome') != 'completed':
            raise RuntimeError(f'turn 1 did not complete: {short(json.dumps(turn1), 300)}')
        first.ask({'action': 'send', 'agent': agent, 'message': held_tool(number)})
        held = wait_for(lambda: sleeping(number), 240, 3) or []
        if not held:
            raise NoToolCall(f'no Start-Sleep {number} appeared within 240 s (the model made no shell call)')
        table = processes()
        service = tree_of(table, first.pid)
        log.save('before-kill.json', {'owner': first.pid, 'service': service, 'held': held})
        kill(first.pid)  # the owner itself (on Windows the venv launcher's child), as Stop-Process -Force would
        killed_at = time.monotonic()
        try:
            first.process.wait(30)
        except subprocess.TimeoutExpired:
            first.process.kill()
        pids = [row['pid'] for row in service]
        gone = wait_for(lambda: not [pid for pid in pids if alive(pid)], 15, 0.5)
        left = [pid for pid in pids if alive(pid)]
        log.item('D6 the DSH service ends with its owner', 'PASS' if pids and not left else 'FAIL',
                 f'owner {first.pid} killed hard; its {len(pids)} service process(es) '
                 f'{[(row["pid"], row["name"]) for row in service][:8]}; alive {time.monotonic() - killed_at:.1f} s '
                 f'later {left}; gone within 15 s {bool(gone)}')
        logs = sorted((path for base in (root, work) for path in (base.rglob('v4.jsonl') if base.is_dir() else [])),
                      key=lambda path: path.stat().st_mtime)
        parsed, bad, turn = 0, 0, False
        for path in logs:
            for line in file_text(path).splitlines():
                try:
                    json.loads(line)
                    parsed += 1
                except ValueError:
                    bad += 1
                turn = turn or 'TURN1-650-OK' in line
            (log.dir / 'session-logs').mkdir(exist_ok=True)
            tail = file_text(path).splitlines()[-200:]
            (log.dir / 'session-logs' / f'{path.parent.name}-v4-tail.jsonl').write_text('\n'.join(tail) + '\n', encoding='utf-8')
        locks = [str(path) for base in (root, work) for path in (base.rglob('session.lock') if base.is_dir() else [])]
        second = Owner(root, work, dsh_child(), base_env())
        sent = second.ask({'action': 'send', 'agent': agent, 'message': 'Reply with exactly AFTER-650-OK and nothing else.'})
        after = second.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 300}) if 'error' not in sent else {}
        log.save('after-kill.json', {'send': sent, 'wait': after, 'locks': locks, 'logs': [str(p) for p in logs]})
        log.item('D7 session data after a hard kill', 'OBSERVED',
                 f'{len(logs)} v4.jsonl log(s): {parsed} line(s) parse, {bad} do not; the completed turn 1 is in it '
                 f'{turn}; session.lock left {locks or "none"}; a later send: '
                 f'{"error " + short(json.dumps(sent.get("error"), ensure_ascii=False), 200) if "error" in sent else "outcome " + str(last_result(after).get("outcome")) + ", session " + str((sent.get("result") or sent).get("session"))}')
        try:
            second.ask({'action': 'retire', 'agent': agent})
        except (OSError, ValueError, RuntimeError):
            pass
    finally:
        if first.process.poll() is None:
            first.process.kill()
            first.process.wait(30)
        if second is not None:
            second.close()
        for pid in sleeping(number):
            kill(pid)
        collect(root, log.dir / 'agents')


# --- versions, context, cases, the interactive session and the scheduled task ----------------------------------

def versions(log: Log) -> dict:
    tool_path()
    facts: dict = {'platform': sys.platform, 'python': sys.version, 'executable': sys.executable,
                   'base_executable': str(BASEPY), 'venv': str(VENV), 'filesystem_encoding': sys.getfilesystemencoding()}
    if WINDOWS:
        import platform
        facts['windows'] = platform.platform()
        facts['code_page'] = run(['cmd', '/c', 'chcp'])['stdout'].strip()
        facts['node'] = run(['node', '--version']).get('stdout', '').strip()
        for name in ('npm', 'pnpm', 'pi', 'dsh', 'uv'):
            facts[name] = (run(['cmd', '/c', name, '--version'], 120).get('stdout') or '').strip().splitlines()[-1:]
        facts['defender_realtime'] = ps('(Get-MpComputerStatus).RealTimeProtectionEnabled', 60).get('stdout', '').strip()
    facts['claude'] = claude_version() if WINDOWS else 'not Windows'
    facts['git'] = run(['git', '--version']).get('stdout', '').strip()
    facts['graftling_head'] = run(['git', '-C', str(HOME / 'graftling'), 'rev-parse', 'HEAD']).get('stdout', '').strip()
    facts['graftling_installed'] = run([str(VENVPY), '-c', 'import graftling; print(graftling.__version__, graftling.__file__)']
                                       ).get('stdout', '').strip()
    log.save('versions.json', facts)
    for name, value in facts.items():
        log.say(f'  {name}: {str(value).splitlines()[0] if str(value) else ""}')
    return facts


LOGON_TYPES = {2: 'Interactive', 3: 'Network', 4: 'Batch', 5: 'Service', 10: 'RemoteInteractive'}


def context() -> dict:
    """This process's session, elevation and job (Task Scheduler's, for a case)."""
    facts: dict = {'pid': os.getpid()}
    if not WINDOWS:
        facts['windows'] = 'NOT-WINDOWS (rehearsal)'
        return facts
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    number = wintypes.DWORD()
    k32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    facts['session_id'] = number.value if k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(number)) else None
    k32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    facts['active_console_session_id'] = k32.WTSGetActiveConsoleSessionId()
    groups = run(['whoami', '/groups']).get('stdout', '')
    facts['elevated'] = 'S-1-16-12288' in groups
    facts['interactive_sid'] = 'S-1-5-4' in groups
    facts['in_job'] = in_any_job()
    return facts


CASE_FUNCTIONS = {'r0': case_r0, 'venv': case_venv, 'claude': case_claude, 'claude-refuse': case_claude_refuse,
                  'claude-caller': case_claude_caller, 'claude-probe': case_claude_probe,
                  'claude-market': case_claude_market, 'pi': case_pi, 'pi-refuse': case_pi_refuse,
                  'pi-caller': case_pi_caller, 'pi-nonascii': case_pi_nonascii, 'pi-kill': case_pi_kill,
                  'dsh': case_dsh, 'dsh-nonascii': case_dsh_nonascii, 'dsh-stop': case_dsh_stop,
                  'dsh-kill': case_dsh_kill}


def run_case(case: str, fresh: bool = True) -> int:
    if fresh:
        shutil.rmtree(HOME / 'out' / case, ignore_errors=True)
    log = Log(case)
    log.say(f'[{case}] in this session')
    verdict = 'STOP the driver ended early'
    try:
        tool_path()
        try:
            place = context()
        except Exception as error:  # never blocks the case
            place = {'pid': os.getpid(), 'windows': f'context not fully read: {type(error).__name__}: {error}'}
        log.save('context.json', place)
        log.item('launcher', 'OBSERVED',
                 f'pid {place.get("pid")}; session {place.get("session_id")} (console session '
                 f'{place.get("active_console_session_id")}); elevated {place.get("elevated")}; INTERACTIVE SID '
                 f'{place.get("interactive_sid")}; in a job {place.get("in_job")}'
                 f'{"; " + place["windows"] if place.get("windows") else ""}')
        if case not in ('venv',) and not key_value():
            raise LookupError('the key variable is not set for this user; run step K first')
        began = time.monotonic()
        CASE_FUNCTIONS[case](log)
        log.say(f'wall time {time.monotonic() - began:.1f} s')
        bad = [item['item'] for item in log.items if item['verdict'] == 'FAIL']
        verdict = f'FAIL ({", ".join(bad)})' if bad else 'PASS'
    except NoToolCall as error:
        verdict = f'NO-TOOL-CALL ({error})'
    except LookupError as error:
        verdict = f'STOP {error}'
    except Exception as error:
        verdict = f'STOP driver error: {type(error).__name__}: {error}'
    log.save('result.json', {'case': case, 'verdict': verdict, 'items': log.items})
    log.say(f'RESULT {case} {verdict}')
    return 2 if verdict.startswith('STOP') else 0


def cleanup(case: str) -> int:
    """End what a case may have left: graftling hosts and MCP servers, Claude/Pi/DSH processes, DSH services,
    holding tools and owners on this disposable VM. Never this process or its parents."""
    table = processes()
    mine, pid = set(), os.getpid()
    while pid in table and pid not in mine:
        mine.add(pid)
        pid = table[pid]['ppid']
    mine.add(os.getpid())
    ended = []
    marks = ('graftling.claude.host', 'graftling.pi.host', 'graftling.dsh.host', 'graftling.mcp', 'mcp_probe.py',
             OWNER_MARK, 'pi-coding-agent', '@deepseek-ai', 'trace.ps1', *[f'leep {n}' for n in SLEEPS.values()])
    for pid, row in table.items():
        cmd = row['cmd']
        if pid in mine or 'drive650.py cleanup' in cmd or 'drive650.py" cleanup' in cmd or 'driver.cmd' in cmd:
            continue
        ours = any(mark in cmd for mark in marks) or re.search(r'drive650\.py"? task ', cmd) or \
            (WINDOWS and row['name'].lower() == 'claude.exe') or (not WINDOWS and STANDIN and STANDIN in cmd)
        if ours:
            kill(pid)
            ended.append(f'{row["name"]}({pid})')
    for name in ('zz_record_648.pth',):
        (SITE / name).unlink(missing_ok=True)
    print(clean(f'CLEANUP {case}: {len(ended)} leftover process(es) ended{": " + ", ".join(ended) if ended else ""}'),
          flush=True)
    return 0


STATES = ('Active', 'Disc', 'Conn', 'Listen', 'Down', 'Idle')


def console_session() -> tuple[str, list[str]]:
    """('ACTIVE <id> <name>' | 'NONE', printable lines) for this user from ``query user`` (name never printed)."""
    if WINDOWS:
        out = run(['query', 'user'], 60)
        text = (out.get('stdout') or '') + (out.get('stderr') or '')
    else:  # rehearsal: a sample of query user's output
        sample = os.environ.get('V650_QUSER_FILE')
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


def task_state(name: str) -> str:
    out = ps(f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; if ($t) {{ $i = $t | "
             f"Get-ScheduledTaskInfo; 'state ' + $t.State + ', last result ' + $i.LastTaskResult + ', logon type ' + "
             f"$t.Principal.LogonType + ', run level ' + $t.Principal.RunLevel }} else {{ 'task absent' }}", 60)
    return (out.get('stdout') or out.get('error') or '').strip()


def task_script(case: str, name: str, script: Path | str, minutes: int) -> str:
    """Register and start the task. The principal is the SID of this process's own token (643 correction 1)."""
    return (f"$ErrorActionPreference = 'Stop'\n"
            f"$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n"
            f"'PRINCIPAL from the token (SID of the current identity): ' + [bool]($sid -like 'S-1-5-*')\n"
            f"$a = New-ScheduledTaskAction -Execute '{sys.executable}' -Argument '\"{script}\" task {case}' "
            f"-WorkingDirectory '{HOME}'\n"
            f"$p = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Highest\n"
            f"$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes {minutes}) "
            f"-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew\n"
            f"Register-ScheduledTask -TaskName '{name}' -Action $a -Principal $p -Settings $s -Force | Out-Null\n"
            f"Start-ScheduledTask -TaskName '{name}'\n'started'")


def schedule(case: str, seconds: float) -> int:
    """``task <case>`` as a scheduled task in this user's interactive console session; the wait is bounded."""
    directory = HOME / 'out' / case
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    done = directory / 'done.json'
    found, shown = console_session()
    print(clean(f'session of the VM user: {found}; query user: {" | ".join(shown)}'), flush=True)
    if not found.startswith('ACTIVE'):
        print(f'RESULT {case} STOP the VM user has no Active console session (run step I first)', flush=True)
        return 2
    name = f'v650-{case}'
    script = Path(__file__).resolve()
    if WINDOWS:
        out = ps(task_script(case, name, script, int(seconds // 60) + 5))
        for text in (out.get('stdout') or '').splitlines():
            if text.startswith('PRINCIPAL '):
                print(clean(text.strip()), flush=True)
        if out.get('exit') != 0:
            print(clean(f'RESULT {case} STOP the scheduled task could not be registered or started: '
                        f'{" ".join((out.get("stderr") or out.get("error") or "").split())[:600]}'), flush=True)
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
        time.sleep(5 if WINDOWS else 0.5)
        if WINDOWS and int(time.monotonic() - began) % 60 < 5:
            print(clean(f'  waiting for the task ({time.monotonic() - began:.0f} s): {task_state(name)}'), flush=True)
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
        print(clean(f'RESULT {case} STOP the case did not finish within {seconds:.0f} s ({state}); its task was '
                    'stopped and removed'), flush=True)
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
    counts, hits = scrub_tree(directory, settings().get('scrub', []), secrets())
    if hits:
        print(f'SCAN FAIL the key or the autologon password is in {len(hits)} file(s) (value not printed): {hits}')
        return 3
    files = sum(1 for path in directory.rglob('*') if path.is_file() and not path.is_symlink())
    print(f'SCAN PASS key {"checked" if key_value() else "not set on this VM"}, autologon password '
          f'{"checked" if password_value() else "not set on this VM"}; replacements: '
          f'{json.dumps(counts, sort_keys=True) if counts else "none"}; files {files}')
    return 0


def main() -> int:
    if not HOME.parts:
        raise SystemExit('V650_HOME is required off Windows')
    command, *rest = sys.argv[1:] or ['']
    if command == 'versions':
        versions(Log(rest[0] if rest else 'V'))
        return 0
    if command in ('case', 'schedule', 'task', 'cleanup') and (not rest or rest[0] not in CASES):
        print(f'usage: drive650.py {command} {"|".join(CASES)}')
        return 2
    if command == 'case':
        return run_case(rest[0])
    if command == 'schedule':
        return schedule(rest[0], float(rest[1]) if len(rest) > 1 else 900)
    if command == 'task':
        return task(rest[0])
    if command == 'cleanup':
        return cleanup(rest[0])
    if command == 'session':
        log = Log('I')
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
