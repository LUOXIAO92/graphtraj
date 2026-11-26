"""Task 640, VM side: real Codex through graftling on Windows x64 (also rehearsed on macOS with the stand-in).

Run by steps.zsh over ``gcloud compute ssh`` as ``<venv python> C:\\v640\\drive640.py <command> ...``:

  config [mode]       write %USERPROFILE%\\.codex\\config.toml from settings.json (no secret; ``env_key`` names the
                      variable); ``mode`` adds ``[windows] sandbox = "<mode>"`` (Codex 0.172 WindowsSandboxModeToml:
                      elevated | unelevated | mxc).
  versions <step>     record Windows build, Python, Node, npm, Codex, git, graftling, Developer Mode, symbolic links,
                      elevation and code pages into out/<step>/versions.json.
  r0                  versions, then ``codex exec`` with a one-line prompt: answer, provider, configured model, and the
                      model the provider reported (if Codex exposes it). Prints ``RESULT R0 PASS|FAIL|STOP``.
  run <mode>          R1-R4 and the 629 section-6 Codex items (R5) with ``[windows] sandbox = "<mode>"``.
                      Prints ``ITEM <id> PASS|FAIL|OBSERVED <observable>`` lines and ``RESULT R-<mode> ...``.
  probe <out.json>    a caller of the channel named by GRAFTLING_CONNECTION: asks ``status``; records its pid, job
                      membership and the answer (used inside Codex's sandbox and by the forged callers).
  waitfile <p> <s>    wait until file ``p`` exists (at most ``s`` seconds); the parent's turn holds on it.
  scan <step>         before evidence leaves the VM: fail (exit 3) if the key's value is in out/<step> (never printed);
                      then replace every settings value and IP address with its placeholder; print counts only.
  scrub <dir> <json>  the same replacement on any directory (the Mac's second pass), values from <json>.

Layout (``HOME``: C:\\v640 on Windows, V640_HOME elsewhere): settings.json (from step V, no secret), venv\\,
graftling\\ (the candidate, from the bundle), work\\<non-ASCII>\\ (Codex's worktree), out\\<step>\\ (evidence).
Everything this prints passes through the scrub first, so the console carries placeholders, not settings values.
Stand-in mode (rehearsal only): V640_STANDIN names graftling's tests directory; the stand-in Codex peer replaces
Codex and the Windows-only items report NOT-RUN.
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
import threading
import time

WINDOWS = sys.platform == 'win32'
_HOME = os.environ.get('V640_HOME') or (r'C:\v640' if WINDOWS else '')
# Resolved: a bound cwd must equal the MCP server's real cwd (a /tmp symbolic link on macOS would not).
HOME = Path(_HOME).resolve() if _HOME else Path()
STANDIN = os.environ.get('V640_STANDIN')
WORK_NAME = '工作ü-640'  # 629 section 6 item 6: a non-ASCII worktree path
SLEEP = 'Start-Sleep'
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
        key = key_value() if HOME.parts else None
        if key:
            _PAIRS = [*_PAIRS, ['<KEY>', key]]
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

def _k32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    return ctypes, wintypes, k32


class Watched:
    """A handle held on a process from first sight, to read its exit code and exit time after it ends."""

    def __init__(self, pid: int) -> None:
        self.pid, self.handle = pid, None
        if WINDOWS:
            _, _, k32 = _k32()
            self.handle = k32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED | SYNCHRONIZE

    def end(self) -> dict:
        if not self.handle:
            return {'pid': self.pid, 'known': False}
        ctypes, wintypes, k32 = _k32()
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(self.handle, ctypes.byref(code))
        times = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes(self.handle, *[ctypes.byref(item) for item in times])
        ticks = lambda item: (item.dwHighDateTime << 32) | item.dwLowDateTime
        running = code.value == 259  # STILL_ACTIVE
        return {'pid': self.pid, 'known': True, 'running': running, 'exit_code': None if running else code.value,
                'exit_ticks': None if running else ticks(times[1])}


def in_any_job(pid: int | None = None) -> bool | None:
    if not WINDOWS:
        return None
    ctypes, wintypes, k32 = _k32()
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


def spawn_with_parent(parent: int, argv: list[str], environment: dict, seconds: float) -> dict:
    """Start ``argv`` naming ``parent`` through PROC_THREAD_ATTRIBUTE_PARENT_PROCESS (629 sec. 3.2's weaker case)."""
    ctypes, wintypes, k32 = _k32()

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR), ('lpDesktop', wintypes.LPWSTR),
                    ('lpTitle', wintypes.LPWSTR), ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                    ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD), ('dwXCountChars', wintypes.DWORD),
                    ('dwYCountChars', wintypes.DWORD), ('dwFillAttribute', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD), ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                    ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                    ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [('StartupInfo', STARTUPINFOW), ('lpAttributeList', ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                    ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]

    k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                                      ctypes.POINTER(ctypes.c_size_t)]
    k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                              ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                   wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.c_void_p, ctypes.c_void_p]
    k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x0080 | 0x1000, False, parent)  # PROCESS_CREATE_PROCESS | QUERY_LIMITED
    if not handle:
        return {'started': False, 'error': f'OpenProcess(parent) failed: {ctypes.get_last_error()}'}
    size = ctypes.c_size_t()
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    info = STARTUPINFOEXW()
    process = PROCESS_INFORMATION()
    try:
        if not k32.InitializeProcThreadAttributeList(buffer, 1, 0, ctypes.byref(size)):
            return {'started': False, 'error': f'InitializeProcThreadAttributeList: {ctypes.get_last_error()}'}
        value = wintypes.HANDLE(handle)
        if not k32.UpdateProcThreadAttribute(buffer, 0, 0x00020000, ctypes.byref(value), ctypes.sizeof(value),
                                             None, None):
            return {'started': False, 'error': f'UpdateProcThreadAttribute: {ctypes.get_last_error()}'}
        info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        info.lpAttributeList = ctypes.cast(buffer, ctypes.c_void_p)
        block = ''.join(f'{name}={text}\0' for name, text in environment.items()) + '\0'
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = 0x00080000 | 0x00000400 | 0x08000000  # EXTENDED_STARTUPINFO_PRESENT | UNICODE_ENVIRONMENT | NO_WINDOW
        if not k32.CreateProcessW(None, line, None, None, False, flags, ctypes.create_unicode_buffer(block), None,
                                  ctypes.byref(info), ctypes.byref(process)):
            return {'started': False, 'error': f'CreateProcessW: {ctypes.get_last_error()}'}
        waited = k32.WaitForSingleObject(process.hProcess, int(seconds * 1000))
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
        return {'started': True, 'pid': process.dwProcessId, 'timed_out': waited != 0, 'exit_code': code.value}
    finally:
        k32.DeleteProcThreadAttributeList(buffer)
        for item in (process.hProcess, process.hThread, handle):
            if item:
                k32.CloseHandle(item)


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
    work = HOME / 'work' / WORK_NAME
    work.mkdir(parents=True, exist_ok=True)
    sessions = codex_home() / 'sessions'
    started = time.time()
    token = 'PONG640'
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

SANDBOX_OFF = ('Codex\'s own sandbox is OFF in this run (permission profile extends ":danger-full-access", Codex '
               '0.172 PermissionProfile::Disabled), on a disposable VM, because no Windows sandbox mode could start a '
               'shell there')


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
    os.environ['PEER_TOOL_COMMAND'] = 'sleep 6403 & sleep 6404; wait'
    os.environ['PEER_TOOL_INHERIT'] = '1'
    return [str(peer)]


def say_shell(command: str, reply: str) -> str:
    return (f'Use your shell tool to run exactly this PowerShell command and wait for it to finish. Run nothing '
            f'else. Then reply with exactly {reply}.\n\n{command}')


INSTRUCTIONS = {
    'r1': ('tool-end', say_shell('Set-Content -Path r1-marker.txt -Value r1-640', 'R1-DONE')),
    # Each holding sleep is its own child process with a literal command line (Codex's own shell may encode its
    # script), so Win32_Process finds it by its unique length.
    'r2': ('tool-hold', say_shell("cmd /c start /b powershell -NoProfile -Command Start-Sleep 6401; Start-Process "
                                  "powershell -ArgumentList '-NoProfile','-Command','Start-Sleep 6402'; "
                                  'powershell -NoProfile -Command "Start-Sleep 6403"', 'R2-DONE')),
    'r3': ('tool-hold', say_shell('powershell -NoProfile -Command "Start-Sleep 6404"', 'R3-DONE')),
    'r3b': ('after takeover', 'Reply with exactly R3-AFTER and run no command.'),
}


def instruction(name: str) -> str:
    return INSTRUCTIONS[name][0 if STANDIN else 1]


def wait_for(predicate, seconds: float, step: float = 2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def sleeps(numbers: tuple[str, ...]) -> dict[str, list[int]]:
    """The tool processes of R2/R3, found anywhere by their unique sleep lengths (whatever started them).

    A process naming one length is filed under it; one naming several (a shell running the whole command) under
    ``shell``.
    """
    table = processes()
    found: dict[str, list[int]] = {}
    for pid, row in table.items():
        if pid == os.getpid() or 'drive640' in row['cmd'] or 'Use your shell' in row['cmd']:
            continue
        named = [number for number in numbers if f'{SLEEP} {number}' in row['cmd'] or f'sleep {number}' in row['cmd']]
        if named:
            found.setdefault(named[0] if len(named) == 1 else 'shell', []).append(pid)
    return found


SAMPLED_S = 5  # let the owner's sampler record a new tool before stopping it (462; the 639 test waits 1.5 s)


def alive(pid: int) -> bool:
    from graftling.tool_descendants import identity
    return identity(pid) is not None


def record(root: Path, agent: str) -> dict:
    return json.loads((root / 'control/agents' / f'{agent}.json').read_text(encoding='utf-8'))['executions'][-1]


def kill_leftovers(log: Log, numbers: tuple[str, ...]) -> list[int]:
    """Cleanup only: end this run's own sleep tools (matched by their unique lengths) that outlived the checks."""
    left = [pid for pids in sleeps(numbers).values() for pid in pids]
    for pid in left:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    if left:
        log.say(f'cleanup: ended {len(left)} leftover tool process(es) of this run: {left}')
    return left


def collect(root: Path, target: Path) -> None:
    """Copy the control records, termination reports and stderr logs (no symbolic link is followed)."""
    for path in root.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix in ('.json', '.yml', '.log') or path.name.startswith('codex-termination'):
            destination = target / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


NO_SHELL: dict[str, str] = {}
SHELL_FAILED = re.compile(r'(?i)(failed to create unified exec process[^\n]*|failed to start the process[^\n]*|'
                          r'unsupportedoperation[^\n]*|native mxc is unavailable[^\n]*|connecting runner pipe[^\n]*)')


def shell_failure(root: Path, last: dict) -> str | None:
    """Codex's own words when its shell tool could not start (stderr.log under the control root, the last message).

    Rehearsal: V640_STANDIN_NO_SHELL injects such a line (labelled as injected).
    """
    if STANDIN and os.environ.get('V640_STANDIN_NO_SHELL'):
        return 'UnsupportedOperation("native MXC is unavailable on this executor") (injected by the rehearsal)'
    texts = [str(last.get('last_message') or '')]
    for path in root.rglob('stderr.log'):
        texts.append(path.read_text(encoding='utf-8', errors='replace'))
    for text in texts:
        found = SHELL_FAILED.search(text)
        if found:
            return found.group(1).strip()[:240]
    return None


def r1_to_r3(log: Log, mode: str, work: Path, codex: list[str]) -> dict:
    from graftling import AgentControl, Caller, bind
    from graftling.codex.driver import CodexDriver

    root = work.parent / f'agents-{mode}'
    shutil.rmtree(root, ignore_errors=True)
    native = child_settings(work, codex, mode)
    log.save('child-settings.json', native)
    owner = subprocess.Popen([sys.executable, '-c', OWNER, str(root), json.dumps(native), json.dumps(CALLER)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
    facts: dict = {'root': str(root)}

    def ask(request: dict, seconds: float = 30) -> dict:
        owner.stdin.write(json.dumps(request) + '\n')
        owner.stdin.flush()
        return json.loads(owner.stdout.readline())

    try:
        facts['owner_pid'] = json.loads(owner.stdout.readline())['pid']
        # R1: create, one tool call, the turn ends.
        log.say('[R1] create a Codex child that runs one tool and ends its turn')
        created = ask({'action': 'create', 'runtime': 'codex', 'instruction': instruction('r1')})
        facts['r1_create'] = created
        if 'error' in created:
            log.item('R1', 'FAIL', f'create refused: {json.dumps(created["error"], ensure_ascii=False)}')
            return facts
        agent, session = created['agent'], created['session']
        done = ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 300})
        facts['r1_wait'] = done
        last = (done.get('result') or {}).get('last_result') or {}
        execution = record(root, agent)
        marker = work / 'r1-marker.txt'
        process = execution.get('process', {})
        cause = shell_failure(root, last) if not marker.exists() else None
        if cause:
            facts['no_shell'] = cause
            log.item('R1', 'NOT-RUN', f'Codex could not start its shell under {mode}: {cause}', process=process)
            for ident in ('R5.6-code-page', 'R2', 'R5.2-cmd-start-/b', 'R5.2-Start-Process', 'R5.2-nesting',
                          'R3.reconcile', 'R5.2-job-by-name', 'R3.takeover'):
                log.item(ident, 'NOT-RUN', 'needs a tool process; Codex could not start its shell (see R1)')
            NO_SHELL[mode] = cause
            kill_leftovers(log, ('6401', '6402', '6403', '6404'))
            return facts
        ok = last.get('outcome') == 'completed' and (STANDIN or marker.exists())
        log.item('R1', 'PASS' if ok else 'FAIL',
                 f'outcome {last.get("outcome")}; marker file {"present" if marker.exists() else "absent"}; '
                 f'runtime_job {"recorded" if process.get("runtime_job") else "absent"}; '
                 f'last message {str(last.get("last_message"))[:80]!r}', process=process)
        log.item('R5.6-code-page', 'PASS' if marker.exists() and execution.get('worktree_path', str(work)) else
                 ('NOT-RUN' if STANDIN else 'FAIL'),
                 'the tool wrote its marker inside the non-ASCII worktree; the record names it')

        # R2: stop, with start /b and Start-Process descendants (629 sec. 6.2).
        log.say('[R2] resume with a holding tool (cmd start /b, Start-Process, Start-Sleep), then interrupt')
        resumed = ask({'action': 'resume', 'agent': agent, 'message': instruction('r2')})
        facts['r2_resume'] = resumed
        numbers = ('6401', '6402', '6403') if not STANDIN else ('6403', '6404')
        seen = wait_for(lambda: (lambda found: found if all(n in found for n in numbers[-2:]) else None)(
            sleeps(numbers)), 240, 3)
        execution = record(root, agent)
        job = execution.get('process', {}).get('runtime_job')
        tool_marker = execution.get('process', {}).get('tool_marker')
        listed = {}
        if WINDOWS and tool_marker:
            from graftling.member_processes import find_marked_processes
            try:
                listed = find_marked_processes(tool_marker)
            except OSError as error:
                listed = {'error': str(error)}
        table = processes()
        shape = {number: [{'pid': pid, 'in_runtime_job': in_job(pid, job), 'in_any_job': in_any_job(pid),
                           'chain': chain(table, pid)} for pid in pids] for number, pids in (seen or {}).items()}
        facts['r2_tools'] = shape
        facts['r2_job_listing'] = {str(key): value for key, value in listed.items()} if isinstance(listed, dict) else listed
        log.save('r2-tools.json', {'runtime_job': job, 'tool_marker': tool_marker, 'tools': shape,
                                   'job_listing': facts['r2_job_listing']})
        if not seen:
            log.item('R2', 'FAIL', 'the holding tool never appeared within 240 s')
        time.sleep(SAMPLED_S)
        stop = ask({'action': 'interrupt', 'agent': agent})
        stopped = ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 120})
        facts['r2_stop'] = {'interrupt': stop, 'wait': stopped}
        last = (stopped.get('result') or {}).get('last_result') or {}
        pids = sorted({pid for pids in (seen or {}).values() for pid in pids})
        wait_for(lambda: not [pid for pid in pids if alive(pid)], 30)
        survivors = [pid for pid in pids if alive(pid)]
        if seen:
            log.item('R2', 'PASS' if last.get('outcome') == 'interrupted' and not survivors else 'FAIL',
                     f'outcome {last.get("outcome")}, state {(stopped.get("result") or {}).get("state")}; '
                     f'{len(pids)} tool process(es) seen, {len(survivors)} alive 30 s after the stop')
        if WINDOWS and not STANDIN:
            for number, label in (('6401', 'cmd start /b'), ('6402', 'Start-Process')):
                rows = shape.get(number, [])
                in_graft = rows and all(row['in_runtime_job'] is True for row in rows)
                gone = rows and not [row['pid'] for row in rows if row['pid'] in survivors]
                log.item(f'R5.2-{label.replace(" ", "-")}', 'PASS' if in_graft and gone else 'FAIL',
                         f'{label}: {len(rows)} process(es); in graftling\'s job: '
                         f'{[row["in_runtime_job"] for row in rows]}; ended by the stop: {bool(gone)}')
            nest = [row for rows in shape.values() for row in rows]
            log.item('R5.2-nesting', 'OBSERVED',
                     'per tool process (in graftling job, in any job): '
                     f'{[(row["in_runtime_job"], row["in_any_job"]) for row in nest]}; whether Codex adds its own '
                     'job is read from r2-tools.json chains (inference until a nested job is seen by name)')
        kill_leftovers(log, numbers)

        # R3: takeover after the owner dies during a tool.
        log.say('[R3] resume with a holding tool, kill the owner, take over from this process')
        ask({'action': 'resume', 'agent': agent, 'message': instruction('r3')})
        hold = ('6404',) if not STANDIN else ('6403', '6404')
        seen3 = wait_for(lambda: sleeps(hold) or None, 240, 3)
        time.sleep(SAMPLED_S)
        owner.kill()
        owner.wait(30)
        facts['r3_seen'] = seen3
        second = AgentControl(root, {'codex': CodexDriver(native)})
        call = bind(second, Caller(*CALLER))

        def reconciled():
            result = call({'action': 'status', 'agent': agent})
            execution = record(root, agent)
            return execution if execution.get('state') == 'ended' else None
        execution = wait_for(reconciled, 120, 2)
        facts['r3_reconciled'] = execution
        escaped = (execution or {}).get('escaped_processes') or {}
        pids3 = sorted({pid for pids in (seen3 or {}).values() for pid in pids})
        stopped_pids = {item.get('pid') for item in escaped.get('stopped', [])} if isinstance(escaped, dict) else set()
        still = [pid for pid in pids3 if alive(pid)]
        code = ((execution or {}).get('error') or {}).get('code')
        log.save('r3-escaped.json', {'escaped_processes': escaped, 'error': (execution or {}).get('error')})
        if execution and code == 'owner-exited' and pids3 and set(pids3) <= stopped_pids and not still:
            log.item('R3.reconcile', 'PASS', f'ended owner-exited; escaped_processes.stopped lists the {len(pids3)} '
                                             'leftover tool process(es); none alive (the job was opened by name)')
        elif execution and code == 'owner-exited':
            log.item('R3.reconcile', 'OBSERVED', f'ended owner-exited; tool pids seen {pids3}, stopped '
                     f'{sorted(stopped_pids)}, alive {still}; escaped_processes error: '
                     f'{escaped.get("error") if isinstance(escaped, dict) else escaped}')
        else:
            log.item('R3.reconcile', 'FAIL', f'the dead owner\'s execution did not end owner-exited: {code}')
        log.item('R5.2-job-by-name', 'PASS' if pids3 and set(pids3) <= stopped_pids else 'OBSERVED',
                 'a later process (this one) opened the job by name and stopped the tools' if pids3 and
                 set(pids3) <= stopped_pids else 'see R3.reconcile (No job open, or tools not in it)')
        kill_leftovers(log, hold)
        confirmed = call({'action': 'interrupt', 'agent': agent})
        resumed = call({'action': 'resume', 'agent': agent, 'message': instruction('r3b')})
        done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 300})
        facts['r3_after'] = {'confirm': confirmed.document, 'resume': resumed.document, 'wait': done.document}
        last = (done.document.get('result') or {}).get('last_result') or {}
        same = resumed.document.get('session') == session
        ok = (not confirmed.failed and confirmed.document.get('result', {}).get('termination_confirmed')
              and not resumed.failed and same and last.get('outcome') == 'completed')
        log.item('R3.takeover', 'PASS' if ok else 'FAIL',
                 f'confirm {confirmed.document.get("result", {}).get("termination_confirmed")}; resumed in the same '
                 f'Session: {same}; outcome {last.get("outcome")}; last message {str(last.get("last_message"))[:60]!r}')
        from graftling.shutdown import stop_owned
        facts['r3_stop_unconfirmed'] = stop_owned(second)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(30)
        collect(root, log.dir / 'agents')
        log.save('r1-r3.json', facts)
    return facts


def r4(log: Log, mode: str, work: Path, codex: list[str]) -> dict:
    from graftling.codex.host import CodexHost
    from graftling.connection import CONNECTION_ENV

    directory = work.parent / f'host-{mode}'
    shutil.rmtree(directory, ignore_errors=True)
    for name in ('probe-sandbox.json', 'forged-done.txt'):
        (work / name).unlink(missing_ok=True)
    python, me = sys.executable, str(Path(__file__).resolve())
    if STANDIN:
        # The stand-in parent holds its turn 15 s on a wait, so the forged caller runs while the channel is open.
        os.environ['PEER_MCP_CALLS'] = json.dumps([
            {'action': 'execute', 'feature': 'create', 'arguments': {'runtime': 'codex', 'instruction': 'hold'}},
            {'action': 'execute', 'feature': 'wait', 'arguments': {'agent': '<agent from 1>', 'timeout_seconds': 15}},
            {'action': 'execute', 'feature': 'status', 'arguments': {}}])
        text = 'mcp-in-turn'
    elif mode in NO_SHELL:
        text = ('Use the subagents tool to create one codex child with the instruction "Reply with exactly CHILD-OK '
                'and run no command.", wait for its result, then reply with its answer. Run no shell command.')
    else:
        text = ('Do these three things in order.\n'
                f"1. Run this exact PowerShell command and wait for it: & '{python}' '{me}' probe probe-sandbox.json\n"
                f"2. Run this exact PowerShell command and wait for it: & '{python}' '{me}' waitfile forged-done.txt 240\n"
                '3. Use the subagents tool to create one codex child with the instruction "Reply with exactly '
                'CHILD-OK and run no command.", wait for its result, then reply with its answer.')
    log.say('[R4] Codex parent host: one real MCP call (create a child), with the 629 sec. 6 probes beside it')
    host_settings = child_settings(work, codex, mode, host=True)
    log.save('host-settings.json', host_settings)
    host = CodexHost(host_settings, directory, text)
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(result=_guard(host.run)), daemon=True)
    thread.start()
    watched: dict[int, Watched] = {}
    shapes: dict = {}
    service = None
    forged: dict = {}
    deadline = time.monotonic() + 900
    while thread.is_alive() and time.monotonic() < deadline:
        adapter = getattr(host, 'adapter', None)
        try:  # the property raises once the connection is closed, not only AttributeError
            pid = adapter.service_pid if adapter is not None else None
        except Exception:
            pid = None
        if pid and service is None:
            service = Watched(pid)
        # The forged callers run as soon as the service is known, whatever the in-sandbox probe does.
        if not forged and pid:
            forged = forge(log, host, work, pid, python, me, CONNECTION_ENV)
            (work / 'forged-done.txt').write_text('done\n', encoding='utf-8')
        table = processes()
        for candidate, row in table.items():
            if 'graftling.mcp' in row['cmd'] and candidate not in watched:
                watched[candidate] = Watched(candidate)
                job = None
                try:
                    from graftling.process_tree import tree_facts
                    job = tree_facts(pid).get('runtime_job') if pid else None
                except Exception:
                    pass
                shapes[candidate] = {'chain': chain(table, candidate), 'in_service_job': in_job(candidate, job),
                                     'in_any_job': in_any_job(candidate), 'service_job': job}
        if pid and 'service' not in shapes:
            shapes['service'] = {'pid': pid, 'chain': chain(table, pid),
                                 'descendants': [{'pid': child, 'name': row['name'], 'cmd': row['cmd'][:300]}
                                                 for child, row in table.items() if row['ppid'] == pid]}
        time.sleep(0.3 if STANDIN else 2)
    thread.join(60)
    result = box.get('result') or {'error': 'the host did not return within the bound'}
    log.save('r4-result.json', result)
    ends = {str(pid): item.end() for pid, item in watched.items()}
    service_end = service.end() if service else None
    log.save('r4-processes.json', {'mcp_servers': shapes, 'ends': ends, 'service_end': service_end})
    sandbox = None
    if (work / 'probe-sandbox.json').exists():
        sandbox = json.loads((work / 'probe-sandbox.json').read_text(encoding='utf-8'))
        log.save('probe-sandbox.json', sandbox)
    collect(directory, log.dir / 'host')
    # R4 itself
    if isinstance(result, dict) and 'outcome' in result:
        creates = [item for item in result.get('operations', []) if item.get('action') == 'create'
                   and not item.get('failed') and item.get('parent_session')]
        child = None
        if creates:
            agent = creates[0]['result'].get('agent')
            child = (directory / 'control/agents' / f'{agent}.json').exists()
        ok = (result['outcome'] == 'completed' and creates and result.get('authenticated_callers')
              and result.get('stop_unconfirmed') == [] and child)
        log.item('R4', 'PASS' if ok else 'FAIL',
                 f'outcome {result["outcome"]}; creates through MCP {len(creates)}; authenticated callers '
                 f'{len(result.get("authenticated_callers") or [])}; stop_unconfirmed {result.get("stop_unconfirmed")}; '
                 f'child record {"present" if child else "absent"}; last message '
                 f'{str(result.get("last_agent_message"))[:80]!r}')
    else:
        log.item('R4', 'FAIL', f'host error: {json.dumps(result, ensure_ascii=False, default=str)[:400]}')
        result = {}
    callers = {item['caller_pid'] for item in result.get('authenticated_callers') or []}
    mcp = [pid for pid in watched]
    log.item('R5.1-mcp-caller', 'PASS' if callers and callers <= set(mcp) else 'OBSERVED',
             f'authenticated caller pid(s) {sorted(callers)}; MCP server pid(s) seen {mcp}; in the service job: '
             f'{[shapes[pid]["in_service_job"] for pid in mcp]}')
    if STANDIN:
        log.item('R5.1-sandbox-caller', 'NOT-RUN', 'the stand-in has no tool sandbox (real VM only)')
    elif sandbox is None:
        log.item('R5.1-sandbox-caller', 'OBSERVED', 'the in-sandbox probe left no file (it did not run, or could '
                                                    'not write); see r4-result.json last_agent_message')
    else:
        answer = sandbox.get('result', {})
        log.item('R5.1-sandbox-caller', 'OBSERVED',
                 f'inside Codex\'s {mode} sandbox: connection variable present {sandbox.get("connection_present")}; '
                 f'in a job {sandbox.get("in_any_job")}; answer: '
                 f'{"accepted" if not answer.get("failed") else json.dumps(answer.get("error") or answer.get("document", {}).get("error") or answer.get("exception"), ensure_ascii=False)[:300]}')
    plain = forged.get('plain') or {}
    code = (plain.get('result') or {}).get('error', {}).get('code') or \
        ((plain.get('result') or {}).get('document') or {}).get('error', {}).get('code')
    if not plain.get('result'):
        log.item('R5.1-forged-plain', 'NOT-RUN', 'the forged caller did not run (the service ended first, or no '
                                                 f'channel address was known): {json.dumps(plain)[:200]}')
    else:
        log.item('R5.1-forged-plain', 'PASS' if code == 'authority-denied' else 'FAIL',
                 f'a same-user process outside the job asked status: {code or json.dumps(plain)[:300]}')
    if WINDOWS:
        parented = forged.get('parented') or {}
        answer = parented.get('result') or {}
        log.item('R5.1-forged-parent-attribute', 'OBSERVED',
                 f'started naming the Codex service as parent (PROC_THREAD_ATTRIBUTE_PARENT_PROCESS): spawn '
                 f'{parented.get("spawn")}; in a job {parented.get("in_any_job")}; answer '
                 f'{"accepted" if answer and not answer.get("failed") else json.dumps(answer.get("error") or (answer.get("document") or {}).get("error"), ensure_ascii=False)[:300]} '
                 '(629 sec. 3.2: the known weaker case)')
        parents = sorted({shape['chain'][1]['name'] if len(shape['chain']) > 1 else '?'
                          for key, shape in shapes.items() if key != 'service'})
        log.item('R5.3-process-shape', 'OBSERVED',
                 f'MCP server parent(s): {parents}; Codex service: '
                 f'{(shapes.get("service") or {}).get("chain", [{}])[0].get("cmd", "?")[:200]!r}; descendants of the '
                 f'service: {[row["name"] for row in (shapes.get("service") or {}).get("descendants", [])]}')
    else:
        log.item('R5.1-forged-parent-attribute', 'NOT-RUN', 'Windows only')
        log.item('R5.3-process-shape', 'NOT-RUN', 'Win32_Process shape is real VM only')
    end_rows = [ends[str(pid)] for pid in mcp]
    exited = [row for row in end_rows if row.get('known') and not row.get('running')]
    if WINDOWS:
        before = service_end and service_end.get('exit_ticks') and all(
            row['exit_ticks'] <= service_end['exit_ticks'] for row in exited)
        zero = exited and all(row['exit_code'] == 0 for row in exited)
        log.item('R5.4-session-end', 'PASS' if exited and zero and before else 'FAIL',
                 f'MCP server exit codes {[row.get("exit_code") for row in exited]} (0: ended at stdin EOF); '
                 f'ended before the service: {bool(before)}; service exit code '
                 f'{(service_end or {}).get("exit_code")}')
    else:
        log.item('R5.4-session-end', 'NOT-RUN', 'exit codes of non-child processes are read on Windows only')
    stderr = [path for path in (log.dir).rglob('stderr.log')]
    errors = [line for path in stderr for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
              if re.search(r'(?i)\b(error|invalid|unknown field|unsupported)\b', line)]
    log.item('R5.5-app-server-profile', 'PASS' if not errors and result.get('outcome') == 'completed' else 'OBSERVED',
             f'app-server --listen stdio:// started under windows.sandbox={mode}; graftling\'s profile (no '
             f'unix_sockets, control directory write) accepted: {len(errors)} error line(s) in {len(stderr)} stderr.log '
             'file(s); the MCP server reached the pipe from outside the tool sandbox: '
             f'{bool(callers)}')
    return result


def _guard(function):
    try:
        return function()
    except BaseException as error:  # the host's own error is the finding
        return {'error': {'type': type(error).__name__, 'message': str(error)}}


def forge(log: Log, host, work: Path, service: int, python: str, me: str, variable: str) -> dict:
    """629 sec. 6.1 negative tests: same-user callers outside the service's job, while the host runs."""
    address = None
    probe_file = work / 'probe-sandbox.json'
    if probe_file.exists():
        address = json.loads(probe_file.read_text(encoding='utf-8')).get('address')
    if not address:
        try:
            config = host.context.launch_document()['adapter_request']['session_parameters']['config']
            address = config['mcp_servers'][host.mcp_server]['env'][variable]
        except Exception:
            address = None
    if not address:
        log.say('forged callers: no channel address known; not run')
        return {'plain': {'error': 'no address'}}
    base = {name: value for name, value in os.environ.items()
            if name.upper() not in {variable, settings()['provider']['key_env'].upper()}}
    environment = {**base, variable: address}
    out: dict = {}
    target = log.dir / 'forged-plain.json'
    done = run([python, me, 'probe', str(target)], 60, env=environment, cwd=str(work))
    out['plain'] = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'run': done}
    if WINDOWS:
        target = log.dir / 'forged-parented.json'
        spawn = spawn_with_parent(service, [python, me, 'probe', str(target)], environment, 60)
        out['parented'] = {**(json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}),
                           'spawn': spawn}
    log.save('forged.json', out)
    return out


def probe(target: str) -> int:
    from graftling.connection import CONNECTION_ENV, call_owner
    from graftling.tool import AgentsError

    document: dict = {'pid': os.getpid(), 'connection_present': CONNECTION_ENV in os.environ,
                      'address': os.environ.get(CONNECTION_ENV), 'in_any_job': in_any_job(),
                      'user': os.environ.get('USERNAME') or os.environ.get('USER'), 'cwd': os.getcwd()}
    try:
        result = call_owner({'action': 'execute', 'feature': 'status', 'arguments': {}})
        document['result'] = {'failed': result.failed, 'document': result.document}
    except AgentsError as error:
        document['result'] = {'failed': True, 'error': {'code': error.code, 'message': str(error)}}
    except Exception as error:  # what the caller met is the finding
        document['result'] = {'failed': True, 'exception': repr(error)}
    Path(target).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    print('probe:', 'accepted' if not document['result'].get('failed') else 'refused', flush=True)
    return 0


def run_mode(mode: str) -> int:
    step = f'R-{mode}'
    log = Log(step)
    if mode == 'none':
        log.say(f'[{step}] R1-R4 and the 629 sec. 6 Codex items with NO Codex sandbox')
        log.say(SANDBOX_OFF)
        (log.dir / 'SANDBOX-OFF.txt').write_text(SANDBOX_OFF + '\n', encoding='utf-8')
    else:
        log.say(f'[{step}] R1-R4 and the 629 sec. 6 Codex items with windows.sandbox = {mode}')
    tool_path()
    work = HOME / 'work' / WORK_NAME
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    if STANDIN:
        codex = standin(work)
    else:
        if not key_value():
            log.say('STOP: the key variable is not set for this user; run step K first')
            log.say(f'RESULT {step} STOP')
            return 2
        config = write_config(None if mode == 'none' else mode)
        shutil.copyfile(config, log.dir / 'config.toml')
        codex = [codex_command()]
    log.save('versions.json', {'codex': codex})
    try:
        r1_to_r3(log, mode, work, codex)
    except Exception as error:
        log.item('R1-R3', 'FAIL', f'driver error: {type(error).__name__}: {error}')
    try:
        r4(log, mode, work, codex)
    except Exception as error:
        log.item('R4', 'FAIL', f'driver error: {type(error).__name__}: {error}')
    counts: dict[str, int] = {}
    for item in log.items:
        counts[item['verdict']] = counts.get(item['verdict'], 0) + 1
    verdict = 'FAIL' if counts.get('FAIL') else ('NO-SHELL' if mode in NO_SHELL else 'PASS')
    why = f'; Codex could not start a shell under {mode}: {NO_SHELL[mode]}' if mode in NO_SHELL else ''
    log.say(f'RESULT {step} {verdict} ({", ".join(f"{key} {value}" for key, value in sorted(counts.items()))}{why})')
    return 0 if verdict == 'PASS' else 1


# --- evidence ------------------------------------------------------------------------------------------------

def scrub_tree(directory: Path, pair_list: list, key: str | None) -> tuple[dict, list[str]]:
    counts: dict[str, int] = {}
    hits: list[str] = []
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if key and any(key.encode(encoding) in data for encoding in ('utf-8', 'utf-16-le')):
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
    key = key_value()
    counts, hits = scrub_tree(directory, settings().get('scrub', []), key)
    if hits:
        print(f'SCAN FAIL the key value is in {len(hits)} file(s) (value not printed): {hits}')
        return 3
    files = sum(1 for path in directory.rglob('*') if path.is_file() and not path.is_symlink())
    print(f'SCAN PASS key {"checked" if key else "not set on this VM (nothing to find)"}; replacements: '
          f'{json.dumps(counts, sort_keys=True) if counts else "none"}; files {files}')
    return 0


def main() -> int:
    if not HOME.parts:
        raise SystemExit('V640_HOME is required off Windows')
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
    if command == 'run':
        return run_mode(rest[0])
    if command == 'probe':
        return probe(rest[0])
    if command == 'waitfile':
        found = wait_for(lambda: Path(rest[0]).exists(), float(rest[1]), 1)
        print('waitfile:', 'present' if found else 'timeout', flush=True)
        return 0
    if command == 'scan':
        return scan(rest[0])
    if command == 'scrub':
        counts, _ = scrub_tree(Path(rest[0]), json.loads(Path(rest[1]).read_text(encoding='utf-8')), None)
        print(f'SCRUB replacements: {json.dumps(counts, sort_keys=True) if counts else "none"}')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
