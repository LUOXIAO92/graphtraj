"""Task 644, VM side: a graftling Codex child's tools on real Windows: execute, stop, take over (and 629 sec. 6).

Run by steps.zsh over ``gcloud compute ssh`` as ``<venv python> C:\\v644\\drive644.py <command> ...``. Every case runs in
the VM user's interactive console session, as a scheduled task started from SSH (``schedule``; Task 643's
arrangement: Codex 0.172.0, ``[windows] sandbox = "unelevated"``):

  config [mode]          write %USERPROFILE%\\.codex\\config.toml from settings.json (no secret; ``env_key``).
  versions <step>        Windows build, Python, Node, npm, Codex, git, graftling, elevation into out/<step>/.
  r0                     versions, then one ``codex exec`` with a one-line prompt: RESULT R0 PASS|FAIL|STOP.
  session                the VM user's console session from ``query user`` (SESSION ACTIVE <id> console | NONE).
  schedule <case> <s>    run ``task <case>`` as a scheduled task (principal: the SID of this SSH token, LogonType
                         Interactive, RunLevel Highest), wait at most <s> s for its done file, print its console,
                         remove the task.
  task <case>            the scheduled task's body: ``case <case>``, output kept, then out/<case>/done.json.
  case <case>            one case (CASES below). Each item prints ``CASE <case> <item>: PASS|FAIL|OBSERVED <obs>``;
                         last ``RESULT <case> PASS | FAIL | NO-TOOL-CALL | STOP <reason>``.
  cleanup <case>         end what a case may have left (its sleep tools, owner and task processes, Codex services).
  probe <out.json>       a caller of graftling's channel (GRAFTLING_CONNECTION): asks ``status``; records the answer
                         and its own job (used inside Codex's sandbox by the parent host's tool, case caller).
  jobctx <out.json>      this process's own (innermost) job: flags, UI restrictions, active count, member pids (run
                         inside the child's tool, case stop).
  jobopen <name> <out> [pid...]  a separate later process: open graftling's job BY NAME; active count, members,
                         limit flags, and whether each pid is in it.
  scan <step>            before evidence leaves the VM: fail (exit 3) if the key or the autologon password is in
                         out/<step> (never printed); then replace every settings value and IP address; counts only.
  scrub <dir> <json>     the same replacement on any directory (the Mac's second pass), values from <json>.

CASES (definition 644): tool (1: a child's tool writes a marker), nonascii (5: the same in C:\\v644\\work\\<non-ASCII>),
stop (2: cmd start /b, Start-Process and a foreground sleep held by the tool, job nesting, the job opened by name by
a later process, then graftling's stop), takeover (3: the owner is killed during a tool, a new owner process takes
over), caller (4: the Codex parent host; its own tool probes graftling's pipe from inside Codex's sandbox, and it
creates a child through MCP).
Layout (``HOME``: C:\\v644 on Windows, V644_HOME elsewhere): settings.json, venv\\, graftling\\, work\\<case>\\,
out\\<step>\\. Everything printed passes through the scrub first. Rehearsal only: V644_STANDIN names graftling's tests
directory (its stand-in Codex peer replaces Codex); V644_STANDIN_ROLLOUT injects a rollout; off Windows ``schedule``
starts ``task`` as a plain subprocess and the Win32 facts read NOT-WINDOWS.
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
_HOME = os.environ.get('V644_HOME') or (r'C:\v644' if WINDOWS else '')
# Resolved: a bound cwd must equal the MCP server's real cwd (a /tmp symbolic link on macOS would not).
HOME = Path(_HOME).resolve() if _HOME else Path()
STANDIN = os.environ.get('V644_STANDIN')
MODE = 'unelevated'
MARKER = 'marker-644.txt'
MARKER_TEXT = 'tool-ran-644'
TOOL_COMMAND = f'Set-Content -Path {MARKER} -Value {MARKER_TEXT}'
NONASCII = '工作ü-644'  # 629 sec. 6: a non-ASCII work dir
CASES = ('tool', 'nonascii', 'stop', 'takeover', 'caller')
NUMBERS = {'stop': ('6441', '6442', '6443'), 'takeover': ('6444',)}
ALL_NUMBERS = ('6441', '6442', '6443', '6444')
SLEEP = 'Start-Sleep'
# Each holding sleep is its own process with a literal command line, so Win32_Process finds it by its unique length.
HOLD_STOP = ("cmd /c start /b powershell -NoProfile -Command Start-Sleep 6441; Start-Process powershell "
             "-ArgumentList '-NoProfile','-Command','Start-Sleep 6442'; "
             'powershell -NoProfile -Command "Start-Sleep 6443"')
HOLD_TAKEOVER = 'powershell -NoProfile -Command "Start-Sleep 6444"'
SAMPLED_S = 5  # let the owner's sampler record a new tool before stopping it (as 640)
CALLER = ('controlled-host', 'actual-parent', 'parent-session', 'codex')
OWNER_MARK = 'from graftling.codex.driver import CodexDriver'
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
    """The autologon password step I set (Winlogon DefaultPassword; never printed). Rehearsal: V644_PASSWORD."""
    if not WINDOWS:
        return os.environ.get('V644_PASSWORD') or None
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
        """One definition item: ``CASE <case> <name>: PASS|FAIL|OBSERVED <observable>`` (one line)."""
        self.items.append({'item': name, 'verdict': verdict, 'observable': observable, **facts})
        self.say(f'CASE {self.step} {name}: {verdict} {" ".join(str(observable).split())}')
        self.save('items.json', self.items)

    def save(self, name: str, document: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        return path


# --- the VM's tools ------------------------------------------------------------------------------------------

def tool_path() -> None:
    """Put the provisioned tools first on PATH (a session may predate the installers' PATH changes)."""
    if not WINDOWS:
        return
    extra = [r'C:\Program Files\nodejs', os.path.join(os.environ.get('APPDATA', ''), 'npm'),
             r'C:\Program Files\Git\cmd', r'C:\Program Files\Python313']
    os.environ['PATH'] = os.pathsep.join([*extra, os.environ.get('PATH', '')])
    name = settings()['provider']['key_env']
    if not os.environ.get(name) and key_value():
        os.environ[name] = key_value()  # the VM user's own variable, for the Codex service graftling starts


def codex_command() -> str:
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
    """pid -> {ppid, name, cmd} for every process (Windows: Win32_Process; POSIX: graftling's same-user listing)."""
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


def chain(table: dict, pid: int, depth: int = 7) -> list[dict]:
    """``pid`` and its recorded parents (a reused parent PID is possible on Windows; inference only)."""
    out, seen = [], set()
    while pid in table and pid not in seen and len(out) < depth:
        seen.add(pid)
        row = table[pid]
        out.append({'pid': pid, 'name': row['name'], 'cmd': row['cmd'][:300]})
        pid = row['ppid']
    return out


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


# --- jobs (Win32; helper-local ctypes for what graftling._win32 does not offer) -----------------------------

LIMIT_FLAGS = {0x1: 'WORKINGSET', 0x2: 'PROCESS_TIME', 0x4: 'JOB_TIME', 0x8: 'ACTIVE_PROCESS', 0x10: 'AFFINITY',
               0x20: 'PRIORITY_CLASS', 0x40: 'PRESERVE_JOB_TIME', 0x80: 'SCHEDULING_CLASS', 0x100: 'PROCESS_MEMORY',
               0x200: 'JOB_MEMORY', 0x400: 'DIE_ON_UNHANDLED_EXCEPTION', 0x800: 'BREAKAWAY_OK',
               0x1000: 'SILENT_BREAKAWAY_OK', 0x2000: 'KILL_ON_JOB_CLOSE', 0x4000: 'SUBSET_AFFINITY'}
UI_FLAGS = {0x1: 'HANDLES', 0x2: 'READCLIPBOARD', 0x4: 'WRITECLIPBOARD', 0x8: 'SYSTEMPARAMETERS',
            0x10: 'DISPLAYSETTINGS', 0x20: 'GLOBALATOMS', 0x40: 'DESKTOP', 0x80: 'EXITWINDOWS'}


def flags(value: int, table: dict) -> str:
    names = [name for bit, name in table.items() if value & bit]
    return f'{value:#x} ({", ".join(names) if names else "none"})'


def job_facts(handle) -> dict:
    """Limit flags, UI restrictions, active count and member pids of ``handle`` (None: this process's own,
    innermost job)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    query = k32.QueryInformationJobObject
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    last = lambda: f'error {ctypes.get_last_error()}'

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
    basic, ui, accounting = BASIC(), wintypes.DWORD(), ACCOUNTING()
    facts: dict = {}
    facts['limit_flags'] = (flags(basic.LimitFlags, LIMIT_FLAGS)
                            if query(handle, 2, ctypes.byref(basic), ctypes.sizeof(basic), None) else last())
    facts['ui_restrictions'] = flags(ui.value, UI_FLAGS) if query(handle, 4, ctypes.byref(ui), 4, None) else last()
    facts['active_processes'] = (accounting.ActiveProcesses if query(handle, 1, ctypes.byref(accounting),
                                                                      ctypes.sizeof(accounting), None) else last())
    buffer = (ctypes.c_size_t * (1 + 256))()  # {DWORD assigned; DWORD listed; ULONG_PTR ids[]}, ids at byte 8
    if query(handle, 3, buffer, ctypes.sizeof(buffer), None):
        counts = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))
        facts['member_pids'] = [int(buffer[1 + index]) for index in range(counts[1])]
    else:
        facts['member_pids'] = last()
    return facts


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


def jobctx(target: str) -> int:
    """Inside a tool: this process's own innermost job (Codex's sandbox job, or graftling's when Codex adds none)."""
    document: dict = {'pid': os.getpid(), 'in_any_job': in_any_job()}
    if WINDOWS and document['in_any_job']:
        try:
            document['innermost_job'] = job_facts(None)
        except Exception as error:  # what the tool met is the finding
            document['innermost_job'] = {'error': repr(error)}
    Path(target).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    print('jobctx:', json.dumps(document)[:300], flush=True)
    return 0


def jobopen(name: str, target: str, pids: list[int]) -> int:
    """A separate, later process: open graftling's job BY NAME and read it."""
    document: dict = {'pid': os.getpid(), 'job': name}
    if not WINDOWS:
        document['opened'] = 'NOT-WINDOWS (rehearsal)'
    else:
        from graftling import _win32
        try:
            job = _win32.open_job(name)
        except OSError as error:
            document['opened'] = False
            document['error'] = f'winerror {getattr(error, "winerror", None)}: {error}'
        else:
            try:
                document['opened'] = True
                document.update(job_facts(job))
                document['pids_in_job'] = {}
                for pid in pids:
                    try:
                        document['pids_in_job'][str(pid)] = _win32.process_in_job(pid, job)
                    except OSError as error:
                        document['pids_in_job'][str(pid)] = f'not readable: winerror {getattr(error, "winerror", None)}'
            finally:
                _win32.close_handle(job)
    Path(target).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    print('jobopen:', json.dumps(document)[:300], flush=True)
    return 0


def open_later(log: Log, name: str | None, label: str, pids: list[int]) -> dict:
    """Run ``jobopen`` as its own new process (not this one, not the owner) and read its record."""
    target = log.dir / f'jobopen-{label}.json'
    if not name:
        return {'opened': 'no job name recorded by graftling'}
    run([sys.executable, str(Path(__file__).resolve()), 'jobopen', name, str(target), *map(str, pids)], 60)
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'opened': 'the jobopen process left no record'}


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
    if WINDOWS:
        import platform
        facts['windows'] = platform.platform()
        facts['windows_build'] = run(['cmd', '/c', 'ver'])['stdout'].strip()
        facts['code_page'] = run(['cmd', '/c', 'chcp'])['stdout'].strip()
        groups = run(['whoami', '/groups'])['stdout']
        facts['integrity'] = 'high (elevated)' if 'S-1-16-12288' in groups else 'medium or other'
        facts['node'] = run(['node', '--version']).get('stdout', '').strip()
        facts['npm'] = run(['cmd', '/c', 'npm', '--version']).get('stdout', '').strip()
    try:
        command = codex_command()
        facts['codex_version'] = run([command, '--version']).get('stdout', '').strip()
    except SystemExit as error:
        facts['codex_version'] = str(error)
    facts['git'] = run(['git', '--version']).get('stdout', '').strip()
    facts['graftling_head'] = run(['git', '-C', str(HOME / 'graftling'), 'rev-parse', 'HEAD']).get('stdout', '').strip()
    facts['graftling_expected'] = settings().get('candidate')
    try:
        from graftling.links import symbolic_links_available
        facts['symbolic_links'] = symbolic_links_available()
    except Exception as error:  # an import failure is itself the finding
        facts['symbolic_links'] = repr(error)
    log.save('versions.json', facts)
    for name in ('windows', 'windows_build', 'code_page', 'python', 'node', 'npm', 'codex_version', 'git',
                 'graftling_head', 'symbolic_links', 'integrity', 'filesystem_encoding'):
        if name in facts:
            log.say(f'  {name}: {str(facts[name]).splitlines()[0] if str(facts[name]) else ""}')
    return facts


def walk(document: object, where: str = ''):
    if isinstance(document, dict):
        for key, value in document.items():
            yield where + '/' + key, key, value
            yield from walk(value, where + '/' + key)
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from walk(value, f'{where}[{index}]')


def r0() -> int:
    log = Log('R0')
    log.say('[R0] versions, then one codex exec call with a one-line prompt (no tool)')
    facts = versions(log)
    provider = settings()['provider']
    same = facts.get('graftling_head') == facts.get('graftling_expected')
    log.say(f'ITEM R0.candidate {"PASS" if same else "FAIL"} graftling HEAD on the VM '
            f'{"is" if same else "is not"} the candidate')
    if not key_value():
        log.say('STOP: the key variable is not set for this user; run step K first')
        log.say('RESULT R0 STOP')
        return 2
    config = write_config(MODE)
    shutil.copyfile(config, log.dir / 'config.toml')
    work = HOME / 'work' / 'r0'
    work.mkdir(parents=True, exist_ok=True)
    started = time.time()
    token = 'PONG644'
    out = run([codex_command(), 'exec', '--json', '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(work),
               '-'], 300, input=f'Reply with exactly the word {token} and nothing else. Do not run any command.\n')
    (log.dir / 'exec-stdout.jsonl').write_text(out.get('stdout') or '', encoding='utf-8')
    (log.dir / 'exec-stderr.txt').write_text((out.get('stderr') or '') + (out.get('error') or ''), encoding='utf-8')
    log.say(f'codex exec exit: {out.get("exit")}')
    events = []
    for line in (out.get('stdout') or '').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    rollout = newest_rollout(started)
    records = read_records(rollout)
    if rollout:
        shutil.copyfile(rollout, log.dir / 'rollout.jsonl')
    answer = ' '.join(str(value) for document in events for _, key, value in walk(document)
                      if key == 'text' and isinstance(value, str))
    configured_provider = [value for record in records if record.get('type') == 'session_meta'
                           for _, key, value in walk(record) if key == 'model_provider']
    configured_model = [value for record in records if record.get('type') == 'turn_context'
                        for _, key, value in walk(record) if key == 'model']
    log.save('r0.json', {'exit': out.get('exit'), 'answer': answer, 'provider_in_rollout': configured_provider,
                         'model_in_turn_context': configured_model, 'events': len(events)})
    if out.get('exit') != 0 or token not in answer:
        log.say('STOP: the provider call did not answer; raw error follows (scrubbed), no fallback model is tried:')
        for line in ((out.get('stderr') or '') + (out.get('error') or '')).splitlines()[-40:]:
            log.say('  | ' + line)
        log.say(f'ITEM R0.answer FAIL codex exec exit {out.get("exit")}; answer token absent')
        log.say('RESULT R0 STOP')
        return 2
    ok_provider = bool(configured_provider) and set(configured_provider) == {provider['id']}
    ok_model = bool(configured_model) and set(configured_model) == {provider['model']}
    log.say(f'ITEM R0.answer PASS codex exec answered with {token}')
    log.say(f'ITEM R0.provider {"PASS" if ok_provider else "FAIL"} rollout session_meta model_provider '
            f'{"is" if ok_provider else "is not"} the configured one')
    log.say(f'ITEM R0.model {"PASS" if ok_model else "FAIL"} rollout turn_context model '
            f'{"is" if ok_model else "is not"} the configured one')
    bad = not (same and ok_provider and ok_model)
    log.say(f'RESULT R0 {"FAIL" if bad else "PASS"}')
    return 1 if bad else 0


# --- rollouts --------------------------------------------------------------------------------------------------

SHELL_FAILED = re.compile(r'(?i)(failed to create unified exec process[^\n]*|failed to start the process[^\n]*|'
                          r'unsupportedoperation[^\n]*|connecting [a-z]* ?pipe[^\n]*)')
SHELL_TOOLS = {'shell', 'shell_command', 'exec_command', 'local_shell', 'container.exec', 'unified_exec'}


def injected_rollout() -> Path | None:
    """Rehearsal only: V644_STANDIN_ROLLOUT names a rollout used for every turn (labelled as injected)."""
    value = os.environ.get('V644_STANDIN_ROLLOUT') if STANDIN else None
    return Path(value) if value else None


def read_records(path: Path | None) -> list[dict]:
    records = []
    if path is not None and path.exists():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    return records


def rollout_records(session: str | None) -> tuple[Path | None, list[dict]]:
    """The Codex rollout of ``session`` (sessions/**/rollout-*<session>*.jsonl, newest), parsed line by line."""
    path = injected_rollout()
    if path is None and session:
        sessions = codex_home() / 'sessions'
        found = sorted(sessions.rglob(f'rollout-*{session}*.jsonl'), key=lambda item: item.stat().st_mtime) \
            if sessions.is_dir() else []
        path = found[-1] if found else None
    return path, read_records(path)


def newest_rollout(since: float) -> Path | None:
    found = rollouts_since(since)
    return found[-1] if found else None


def rollouts_since(since: float) -> list[Path]:
    sessions = codex_home() / 'sessions'
    return sorted((path for path in sessions.rglob('rollout-*.jsonl') if path.stat().st_mtime >= since - 5),
                  key=lambda path: path.stat().st_mtime) if sessions.is_dir() else []


def tool_calls(records: list[dict]) -> list[dict]:
    """Shell/exec tool calls in Codex rollout records, with their command, exit code and error text.

    ``type: response_item`` with ``payload.type`` function_call / custom_tool_call / local_shell_call (``name``,
    ``arguments`` or ``input`` or ``action`` -> ``command``/``cmd``, ``call_id``); function_call_output /
    custom_tool_call_output (``call_id``, ``output``); ``type: event_msg`` exec_command_end (``exit_code``).
    The exit code comes from exec_command_end, else from the output text: Codex 0.172 writes 'Process exited with
    code N' (Task 643's reading; 640's driver matched only 'exit code' and reported None).
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
            calls[ident] = {'tool': name, 'command': str(command)[:300]}
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
            match = (re.search(r'(?i)\bexit(?:ed with)? code:?\s*(-?\d+)', output)
                     or re.search(r'"exit_code"\s*:\s*(-?\d+)', output))
            code = int(match.group(1)) if match else None
        failed = SHELL_FAILED.search(output) or re.search(r'(?im)^(error|failed)\b[^\n]*', output)
        error = failed.group(0).strip()[:200] if failed else (
            f'exit code {code}: {str(end.get("stderr") or output).strip()[:160]}' if code not in (None, 0) else None)
        found.append({**calls[ident], 'exit_code': code, 'error': error, 'answered': ident in outputs,
                      'output': output.strip()[:200]})
    return found


def reported_cwd(records: list[dict]) -> list[str]:
    """The work dir Codex records: ``cwd`` of turn_context and session_meta (distinct, in order)."""
    found: list[str] = []
    for record in records:
        if record.get('type') in ('turn_context', 'session_meta'):
            value = (record.get('payload') or {}).get('cwd')
            if isinstance(value, str) and value not in found:
                found.append(value)
    return found


def same_dir(one: str, other: str) -> bool:
    norm = lambda text: re.sub(r'^\\\\\?\\', '', text).rstrip('\\/').replace('/', '\\').casefold()
    return norm(one) == norm(other)


def show_calls(calls: list[dict]) -> str:
    if not calls:
        return '0 shell calls'
    return f'{len(calls)} shell call(s): ' + '; '.join(
        f"{call['tool']} {call['command'][:70]!r} -> exit {call['exit_code']}" for call in calls[:4])


def keep_rollout(log: Log, path: Path | None) -> None:
    if path is not None and path.exists():
        target = log.dir / 'rollouts'
        target.mkdir(exist_ok=True)
        shutil.copyfile(path, target / (('injected-' if injected_rollout() else '') + path.name))


# --- the owner, the child, the cases ------------------------------------------------------------------------

def child_settings(work: Path, codex: list[str], host: bool = False) -> dict:
    """Run.settings for a child (approvalPolicy never) or the parent host (on-request; Codex's reviewer decides)."""
    parameters = {'cwd': str(work), 'developerInstructions': '',
                  'config': {'default_permissions': 'chosen', 'permissions': {
                      'chosen': {'extends': ':workspace', 'filesystem': {str(work): 'write'}}}}}
    if STANDIN:
        parameters['model'] = 'chosen-model'
    else:
        parameters.update(model=settings()['provider']['model'], approvalPolicy='on-request' if host else 'never')
    return {'adapter_request': {'arguments': codex, 'worktree_path': str(work), 'session_parameters': parameters}}


def standin(work: Path, tool: str) -> list[str]:
    """Rehearsal: graftling's controlled peer as ``codex`` (tests/codex_stdio_peer.py), POSIX only."""
    peer = work.parent / f'codex-{work.name}'
    peer.write_text('#!' + sys.executable + '\n' + (Path(STANDIN) / 'codex_stdio_peer.py').read_text(encoding='utf-8'))
    peer.chmod(0o755)
    os.environ['PEER_TOOL_COMMAND'] = tool
    return [str(peer)]


def say_shell(command: str, reply: str) -> str:
    return (f'Use your shell tool to run exactly this PowerShell command and wait for it to finish. Run nothing '
            f'else. Then reply with exactly {reply}.\n\n{command}')


class Owner:
    """An owner process (AgentControl + CodexDriver) in this session; requests on stdin, documents on stdout."""

    def __init__(self, root: Path, native: dict) -> None:
        self.process = subprocess.Popen([sys.executable, '-c', OWNER, str(root), json.dumps(native),
                                         json.dumps(CALLER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding='utf-8')
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
            self.process.wait(30)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(30)


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


def sleeps(numbers: tuple[str, ...]) -> dict[str, list[int]]:
    """The holding tools found anywhere by their unique sleep lengths; a process naming several (a shell running
    the whole command) is filed under ``shell``."""
    found: dict[str, list[int]] = {}
    for pid, row in processes().items():
        if pid == os.getpid() or 'drive644' in row['cmd'] or 'Use your shell' in row['cmd']:
            continue
        named = [number for number in numbers if f'{SLEEP} {number}' in row['cmd'] or f'sleep {number}' in row['cmd']]
        if named:
            found.setdefault(named[0] if len(named) == 1 else 'shell', []).append(pid)
    return found


def kill_leftovers(log: Log, numbers: tuple[str, ...]) -> list[int]:
    """Cleanup only: end this case's own sleep tools (matched by their unique lengths) that outlived the checks."""
    left = [pid for pids in sleeps(numbers).values() for pid in pids]
    for pid in left:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    log.say(f'cleanup: {len(left)} leftover tool process(es) of this case ended{": " + str(left) if left else ""}')
    return left


class NoToolCall(Exception):
    """The model made no tool call (the step offers one rerun)."""


def created_child(log: Log, owner: Owner, instruction: str) -> tuple[str, str]:
    created = owner.ask({'action': 'create', 'runtime': 'codex', 'instruction': instruction})
    log.save('create.json', created)
    if 'error' in created:
        raise RuntimeError(f'graftling create refused: {json.dumps(created["error"], ensure_ascii=False)[:400]}')
    return created['agent'], created['session']


def case_marker(log: Log, work: Path, codex: list[str]) -> None:
    """Cases tool and nonascii: one tool call writes the marker in ``work``."""
    root = work.parent / f'agents-{log.step}'
    shutil.rmtree(root, ignore_errors=True)
    native = child_settings(work, codex)
    log.save('child-settings.json', native)
    owner = Owner(root, native)
    try:
        log.say(f'owner pid {owner.pid}; work dir {work}')
        agent, session = created_child(log, owner, 'tool-end' if STANDIN else say_shell(TOOL_COMMAND, 'CASE-DONE'))
        done = owner.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 600})
        log.save('wait.json', done)
        last = (done.get('result') or {}).get('last_result') or {}
        process = record(root, agent).get('process', {})
        path, records = rollout_records(session)
        keep_rollout(log, path)
        calls = tool_calls(records)
        marker = work / MARKER
        content = marker.read_text(encoding='utf-8', errors='replace').strip() if marker.exists() else None
        if content is None and path is not None and not calls:
            raise NoToolCall(f'rollout {path.name}: the model made no shell call')
        ran = [call for call in calls if call['exit_code'] == 0]
        log.item('tool call exit', 'PASS' if ran else 'FAIL',
                 f'{show_calls(calls)} (function_call_output of rollout {path.name if path else "none found"}'
                 f'{", injected" if injected_rollout() else ""})')
        log.item('marker', 'PASS' if content == MARKER_TEXT else 'FAIL',
                 f'{MARKER} in {work}: ' + (f'present, content {content!r}' if content is not None else 'absent'))
        log.item('turn completed', 'PASS' if last.get('outcome') == 'completed' else 'FAIL',
                 f'outcome {last.get("outcome")}; last message {str(last.get("last_message"))[:60]!r}')
        log.item('runtime job', 'PASS' if process.get('runtime_job') or not WINDOWS else 'FAIL',
                 f'runtime_job {process.get("runtime_job") or "absent"}; runtime pid {process.get("runtime_pid")}; '
                 f'worker pid {process.get("worker_pid")}{"" if WINDOWS else " (POSIX: graftling records no job)"}')
        if log.step == 'nonascii':
            cwd = reported_cwd(records)
            log.item('cwd Codex reports', 'PASS' if cwd and all(same_dir(one, str(work)) for one in cwd) else 'FAIL',
                     f'rollout turn_context/session_meta cwd {cwd or "absent"}; the work dir is {work}')
        try:
            owner.ask({'action': 'retire', 'agent': agent})
        except (OSError, ValueError, RuntimeError):
            pass
    finally:
        owner.close()
        collect(root, log.dir / 'agents')


def case_stop(log: Log, work: Path, codex: list[str]) -> None:
    """Case stop: the child's tool holds three sleeps; nesting and the job by name are read; graftling stops it."""
    numbers = NUMBERS['stop']
    root = work.parent / 'agents-stop'
    shutil.rmtree(root, ignore_errors=True)
    native = child_settings(work, codex)
    log.save('child-settings.json', native)
    python, me = sys.executable, str(Path(__file__).resolve())
    command = f"& '{python}' '{me}' jobctx jobctx-tool.json; {HOLD_STOP}"
    owner = Owner(root, native)
    try:
        log.say(f"owner pid {owner.pid}; the tool: & '<venv python>' '<drive644.py>' jobctx jobctx-tool.json; {HOLD_STOP}")
        agent, session = created_child(log, owner, 'tool-hold' if STANDIN else say_shell(command, 'STOP-DONE'))
        seen = wait_for(lambda: (lambda found: found if all(n in found for n in numbers) else None)(sleeps(numbers)),
                        240, 3) or sleeps(numbers)
        execution = record(root, agent)
        job = execution.get('process', {}).get('runtime_job')
        table = processes()
        shape = {number: [{'pid': pid, 'in_graftling_job': in_job(pid, job), 'in_any_job': in_any_job(pid),
                           'chain': chain(table, pid)} for pid in pids] for number, pids in seen.items()}
        pids = sorted({pid for found in seen.values() for pid in found})
        before = open_later(log, job, 'before-stop', pids)
        inside = None
        if (work / 'jobctx-tool.json').exists():
            inside = json.loads((work / 'jobctx-tool.json').read_text(encoding='utf-8'))
        log.save('stop-tools.json', {'runtime_job': job, 'tools': shape, 'job_by_name_before': before,
                                     'jobctx_in_tool': inside, 'process': execution.get('process')})
        if not any(number in seen for number in numbers):
            path, records = rollout_records(session)
            keep_rollout(log, path)
            calls = tool_calls(records)
            if path is not None and not calls:
                owner.ask({'action': 'interrupt', 'agent': agent})
                raise NoToolCall(f'rollout {path.name}: the model made no shell call')
            log.item('holding tool', 'FAIL', f'no sleep {"/".join(numbers)} appeared within 240 s; {show_calls(calls)}')
        time.sleep(SAMPLED_S)
        stop = owner.ask({'action': 'interrupt', 'agent': agent})
        stopped = owner.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 120})
        log.save('stop.json', {'interrupt': stop, 'wait': stopped})
        last = (stopped.get('result') or {}).get('last_result') or {}
        wait_for(lambda: not [pid for pid in pids if alive(pid)], 30)
        survivors = [pid for pid in pids if alive(pid)]
        listed = before.get('member_pids') if isinstance(before.get('member_pids'), list) else []
        after = open_later(log, job, 'after-stop', listed)
        members_left = [pid for pid in listed if alive(pid)]
        log.save('stop-after.json', {'survivors': survivors, 'job_by_name_after': after,
                                     'job_members_before_alive_after': members_left})
        path, records = rollout_records(session)
        keep_rollout(log, path)
        log.say(f'rollout: {show_calls(tool_calls(records))}')
        log.item('graftling stop result', 'PASS' if last.get('outcome') == 'interrupted' else 'FAIL',
                 f'interrupt {(stop.get("result") or {}).get("interrupt") or json.dumps(stop.get("error"))[:160]}; '
                 f'outcome {last.get("outcome")}; state {(stopped.get("result") or {}).get("state")}')
        for number, label in zip(numbers, ('cmd start /b', 'Start-Process', 'foreground')):
            rows = shape.get(number, [])
            if STANDIN and not WINDOWS:
                member = 'not readable off Windows'
                ok = bool(rows) and not [row['pid'] for row in rows if row['pid'] in survivors]
            else:
                member = [row['in_graftling_job'] for row in rows]
                ok = bool(rows) and all(value is True for value in member) and \
                    not [row['pid'] for row in rows if row['pid'] in survivors]
            log.item(f'sleep {number} ({label})', 'PASS' if ok else 'FAIL',
                     f'{len(rows)} process(es) {[row["pid"] for row in rows]}; in graftling\'s job: {member}; '
                     f'alive 30 s after the stop: {[row["pid"] for row in rows if row["pid"] in survivors]}')
        if not WINDOWS:
            log.item('job after stop', 'OBSERVED', 'not Windows (rehearsal): no job to open')
        else:
            gone = after.get('opened') is False and 'winerror 2' in str(after.get('error'))
            zero = after.get('opened') is True and after.get('active_processes') == 0
            log.item('job after stop', 'PASS' if gone or zero else 'FAIL',
                     f'a later process opened {job} by name: ' +
                     (f'active processes {after.get("active_processes")}, members {after.get("member_pids")}'
                      if after.get('opened') is True else f'not opened ({after.get("error") or after.get("opened")}): '
                                                          'the job no longer exists, so no process is left in it'
                      if gone else f'not opened ({after.get("error") or after.get("opened")})'))
        ended = not survivors and not members_left
        log.item('every job process ended', 'PASS' if ended and (pids or STANDIN) else 'FAIL',
                 f'{len(pids)} sleep process(es) seen, alive after the stop {survivors}; of the {len(listed)} job '
                 f'member(s) listed before the stop, alive after {members_left}')
        log.item('job by name (later process)', 'PASS' if before.get('opened') is True and pids and
                 all(value is True for value in (before.get('pids_in_job') or {}).values()) else
                 ('OBSERVED' if not WINDOWS else 'FAIL'),
                 f'a separate later process opened {job} by name: opened {before.get("opened")}; active processes '
                 f'{before.get("active_processes")}; members {before.get("member_pids")}; sleep pids in it '
                 f'{before.get("pids_in_job")}; limit flags {before.get("limit_flags")}')
        nest = {number: [(row['pid'], row['in_graftling_job'], row['in_any_job']) for row in rows]
                for number, rows in shape.items()}
        inner = (inside or {}).get('innermost_job') or {}
        relation = 'unknown (the in-tool probe left no record)'
        if inner and isinstance(inner.get('member_pids'), list) and listed:
            relation = ('the same job as graftling\'s (equal member lists)' if sorted(inner['member_pids']) == sorted(listed)
                        else 'a different job (Codex\'s own nested job, or another)')
        log.item('job nesting', 'OBSERVED',
                 f'per sleep (pid, in graftling job, in any job): {nest}; inside the tool (jobctx): in a job '
                 f'{(inside or {}).get("in_any_job")}, innermost job flags {inner.get("limit_flags")}, UI '
                 f'{inner.get("ui_restrictions")}, active {inner.get("active_processes")}, members '
                 f'{inner.get("member_pids")} -> {relation}; graftling job flags {before.get("limit_flags")}; '
                 'the launcher\'s (Task Scheduler\'s) job: see the launcher line')
        try:
            owner.ask({'action': 'retire', 'agent': agent})
        except (OSError, ValueError, RuntimeError):
            pass
    finally:
        owner.close()
        kill_leftovers(log, numbers)
        collect(root, log.dir / 'agents')


def case_takeover(log: Log, work: Path, codex: list[str]) -> None:
    """Case takeover: the owner is killed hard during a tool; a NEW owner process takes over the same Session."""
    numbers = NUMBERS['takeover']
    root = work.parent / 'agents-takeover'
    shutil.rmtree(root, ignore_errors=True)
    native = child_settings(work, codex)
    log.save('child-settings.json', native)
    first = Owner(root, native)
    second = None
    try:
        log.say(f'first owner pid {first.pid}; the tool: {HOLD_TAKEOVER}')
        agent, session = created_child(log, first, 'tool-hold' if STANDIN else say_shell(HOLD_TAKEOVER, 'HOLD-DONE'))
        seen = wait_for(lambda: sleeps(numbers) or None, 240, 3) or {}
        pids = sorted({pid for found in seen.values() for pid in found})
        if not pids:
            path, records = rollout_records(session)
            keep_rollout(log, path)
            calls = tool_calls(records)
            if path is not None and not calls:
                raise NoToolCall(f'rollout {path.name}: the model made no shell call')
            log.item('holding tool', 'FAIL', f'no sleep {numbers[0]} appeared within 240 s; {show_calls(calls)}')
        job = record(root, agent).get('process', {}).get('runtime_job')
        log.save('takeover-before.json', {'tool_pids': pids, 'process': record(root, agent).get('process'),
                                          'in_graftling_job': {pid: in_job(pid, job) for pid in pids}})
        time.sleep(SAMPLED_S)
        first.process.kill()  # hard: TerminateProcess on Windows, SIGKILL elsewhere
        first.process.wait(30)
        log.say(f'first owner {first.pid} killed hard (exit {first.process.returncode})')
        second = Owner(root, native)
        log.say(f'new owner process pid {second.pid} (also in this session) takes over')

        def reconciled():
            second.ask({'action': 'status', 'agent': agent})
            execution = record(root, agent)
            return execution if execution.get('state') == 'ended' else None
        execution = wait_for(reconciled, 120, 2) or record(root, agent)
        escaped = execution.get('escaped_processes') or {}
        stopped = {item.get('pid') for item in escaped.get('stopped', [])} if isinstance(escaped, dict) else set()
        wait_for(lambda: not [pid for pid in pids if alive(pid)], 30)
        still = [pid for pid in pids if alive(pid)]
        code = (execution.get('error') or {}).get('code')
        log.save('takeover-reclaim.json', {'state': execution.get('state'), 'error': execution.get('error'),
                                           'escaped_processes': escaped, 'tool_pids': pids, 'alive': still})
        log.item('reclaim of the dead owner\'s tool', 'PASS' if execution.get('state') == 'ended' and pids and not still
                 else 'FAIL',
                 f'execution {execution.get("state")} with {code or "no error code"}; graftling recorded '
                 f'escaped_processes {json.dumps(escaped, ensure_ascii=False, default=str)[:240]}; tool pid(s) {pids}, '
                 f'listed stopped {sorted(pid for pid in pids if pid in stopped)}, alive {still}')
        log.item('tool process ended', 'PASS' if pids and not still else 'FAIL',
                 f'tool pid(s) {pids}; alive 30 s after the takeover: {still}')
        confirmed = second.ask({'action': 'interrupt', 'agent': agent})
        resumed = second.ask({'action': 'resume', 'agent': agent,
                              'message': 'after takeover' if STANDIN else
                              'Reply with exactly TAKEOVER-DONE and run no command.'})
        done = second.ask({'action': 'wait', 'agent': agent, 'timeout_seconds': 300})
        log.save('takeover-after.json', {'confirm': confirmed, 'resume': resumed, 'wait': done})
        last = (done.get('result') or {}).get('last_result') or {}
        same = resumed.get('session') == session
        ok = 'error' not in resumed and same and last.get('outcome') == 'completed'
        log.item('same Session resumes', 'PASS' if ok else 'FAIL',
                 f'confirm {(confirmed.get("result") or {}).get("termination_confirmed", confirmed.get("error"))}; '
                 f'resumed in the same Session: {same}; outcome {last.get("outcome")}; last message '
                 f'{str(last.get("last_message"))[:60]!r}')
        try:
            second.ask({'action': 'retire', 'agent': agent})
        except (OSError, ValueError, RuntimeError):
            pass
        path, records = rollout_records(session)
        keep_rollout(log, path)
        log.say(f'rollout: {show_calls(tool_calls(records))}')
    finally:
        if first.process.poll() is None:
            first.process.kill()
            first.process.wait(30)
        if second is not None:
            second.close()
        kill_leftovers(log, numbers)
        collect(root, log.dir / 'agents')


def _guard(function):
    try:
        return function()
    except BaseException as error:  # the host's own error is the finding
        return {'error': {'type': type(error).__name__, 'message': str(error)}}


def case_caller(log: Log, work: Path, codex: list[str]) -> None:
    """Case caller: the Codex parent host with graftling's MCP server; its own tool, inside Codex's sandbox, runs
    the probe against graftling's pipe; then it creates a child through MCP."""
    from graftling.codex.host import CodexHost
    directory = work.parent / 'host-caller'
    shutil.rmtree(directory, ignore_errors=True)
    python, me = sys.executable, str(Path(__file__).resolve())
    began = time.time()
    if STANDIN:
        os.environ['PEER_MCP_CALLS'] = json.dumps([
            {'action': 'execute', 'feature': 'create', 'arguments': {'runtime': 'codex', 'instruction': 'hold'}},
            {'action': 'execute', 'feature': 'status', 'arguments': {}}])
        text = 'mcp-in-turn'
    else:
        text = ('Do these two things in order.\n'
                f"1. Run this exact PowerShell command and wait for it: & '{python}' '{me}' probe probe-sandbox.json\n"
                '2. Use the subagents tool to create one codex child with the instruction "Reply with exactly '
                'CHILD-OK and run no command.", wait for its result, then reply with its answer.')
    host_settings = child_settings(work, codex, host=True)
    log.save('host-settings.json', host_settings)
    host = CodexHost(host_settings, directory, text)
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(result=_guard(host.run)), daemon=True)
    thread.start()
    thread.join(780)  # inside the schedule's 900 s bound, so the case still reports
    result = box.get('result') or {'error': 'the host did not return within 780 s'}
    log.save('host-result.json', result)
    collect(directory, log.dir / 'host')
    sandbox = None
    if (work / 'probe-sandbox.json').exists():
        sandbox = json.loads((work / 'probe-sandbox.json').read_text(encoding='utf-8'))
        log.save('probe-sandbox.json', sandbox)
    calls = []
    for path in rollouts_since(began) + ([injected_rollout()] if injected_rollout() else []):
        keep_rollout(log, path)
        calls += tool_calls(read_records(path))
    probing = [call for call in calls if 'probe' in call['command']]
    log.say(f'rollouts since the case began: {show_calls(calls)}')
    if not STANDIN and sandbox is None and not probing:
        raise NoToolCall('the parent made no shell call running the probe')
    if STANDIN:
        log.item('probe inside the sandbox', 'OBSERVED', 'not run: the stand-in has no tool sandbox (real VM only)')
    elif sandbox is None:
        log.item('probe inside the sandbox', 'OBSERVED',
                 f'the probe left no record; its call: {show_calls(probing)}; last message '
                 f'{str(result.get("last_agent_message"))[:100]!r}')
    else:
        answer = sandbox.get('result', {})
        if not answer.get('failed'):
            outcome = f'accepted; status answer {json.dumps(answer.get("document"), ensure_ascii=False)[:200]}'
        else:
            outcome = 'refused: ' + json.dumps(answer.get('error') or (answer.get('document') or {}).get('error')
                                               or answer.get('exception'), ensure_ascii=False)[:240]
        inner = sandbox.get('innermost_job') or {}
        log.item('probe inside the sandbox', 'OBSERVED',
                 f'{outcome}; probe pid {sandbox.get("pid")}, connection variable present '
                 f'{sandbox.get("connection_present")}, in a job {sandbox.get("in_any_job")} (flags '
                 f'{inner.get("limit_flags")}, UI {inner.get("ui_restrictions")}); its call: {show_calls(probing)}')
    if isinstance(result, dict) and 'outcome' in result:
        creates = [item for item in result.get('operations', []) if item.get('action') == 'create'
                   and not item.get('failed')]
        child = None
        if creates:
            agent = (creates[0].get('result') or {}).get('agent')
            child = (directory / 'control/agents' / f'{agent}.json').exists()
        ok = result['outcome'] == 'completed' and creates and child
        log.item('create through MCP', 'PASS' if ok else 'FAIL',
                 f'outcome {result["outcome"]}; creates through MCP {len(creates)}; child record '
                 f'{"present" if child else "absent"}; authenticated callers '
                 f'{[item.get("caller_pid") for item in result.get("authenticated_callers") or []]}; '
                 f'stop_unconfirmed {result.get("stop_unconfirmed")}; last message '
                 f'{str(result.get("last_agent_message"))[:60]!r}')
    else:
        log.item('create through MCP', 'FAIL', f'host error: {json.dumps(result, ensure_ascii=False, default=str)[:400]}')


def probe(target: str) -> int:
    from graftling.connection import CONNECTION_ENV, call_owner
    from graftling.tool import AgentsError

    document: dict = {'pid': os.getpid(), 'connection_present': CONNECTION_ENV in os.environ,
                      'in_any_job': in_any_job(), 'cwd': os.getcwd()}
    if WINDOWS and document['in_any_job']:
        try:
            document['innermost_job'] = job_facts(None)
        except Exception as error:
            document['innermost_job'] = {'error': repr(error)}
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


# --- the launching process's context (Win32; recorded, never assumed) -----------------------------------------

LOGON_TYPES = {2: 'Interactive', 3: 'Network', 4: 'Batch', 5: 'Service', 10: 'RemoteInteractive'}


def context() -> dict:
    """This process's session, window station, desktop, elevation and job (Task Scheduler's, for a case)."""
    facts: dict = {'pid': os.getpid()}
    try:
        facts['parent_chain'] = ' <- '.join(f"{row['name']}({row['pid']})" for row in chain(processes(), os.getpid()))
    except Exception as error:
        facts['parent_chain'] = f'unknown: {error!r}'
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
    if facts['in_job']:
        try:
            facts['job'] = job_facts(None)
        except Exception as error:
            facts['job'] = {'error': repr(error)}
    return facts


# --- cases, the interactive session and the scheduled task ---------------------------------------------------

def run_case(case: str, fresh: bool = True) -> int:
    if fresh:
        shutil.rmtree(HOME / 'out' / case, ignore_errors=True)
    log = Log(case)
    log.say(f'[{case}] a graftling Codex child, [windows] sandbox = "{MODE}", in this session')
    verdict = 'STOP the driver ended early'
    try:
        tool_path()
        try:
            place = context()
        except Exception as error:  # never blocks the case
            place = {'pid': os.getpid(), 'windows': f'context not fully read: {type(error).__name__}: {error}'}
        log.save('context.json', place)
        job = place.get('job') or {}
        log.item('launcher', 'OBSERVED',
                 f'pid {place.get("pid")}; session {place.get("session_id")} (console session '
                 f'{place.get("active_console_session_id")}); elevated {place.get("elevated")}; INTERACTIVE SID '
                 f'{place.get("interactive_sid")}; in a job {place.get("in_job")} (Task Scheduler\'s: flags '
                 f'{job.get("limit_flags")}, active {job.get("active_processes")})'
                 f'{"; " + place["windows"] if place.get("windows") else ""}; chain '
                 f'{place.get("parent_chain")}')
        work = HOME / 'work' / (NONASCII if case == 'nonascii' else case)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        tools = {'stop': 'sleep 6441 & sleep 6442 & sleep 6443; wait', 'takeover': 'sleep 6444',
                 'caller': 'true'}
        if STANDIN:
            # V644_PEER_TOOL (rehearsal): another tool for the stand-in peer (e.g. one that does nothing).
            codex = standin(work, os.environ.get('V644_PEER_TOOL') or
                            tools.get(case, f'printf "{MARKER_TEXT}\\n" > {MARKER}'))
        elif not key_value():
            raise LookupError('the key variable is not set for this user; run step K first')
        else:
            config = write_config(MODE)
            shutil.copyfile(config, log.dir / 'config.toml')
            codex = [codex_command()]
        began = time.monotonic()
        {'tool': case_marker, 'nonascii': case_marker, 'stop': case_stop, 'takeover': case_takeover,
         'caller': case_caller}[case](log, work, codex)
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
    """End what a case may have left: sleep tools, owner and task processes, Codex services (Windows: any codex
    app-server on this disposable VM; elsewhere only processes naming this run's HOME). Never this process or its
    parents."""
    table = processes()
    mine, pid = set(), os.getpid()
    while pid in table and pid not in mine:
        mine.add(pid)
        pid = table[pid]['ppid']
    mine.add(os.getpid())
    ended = []
    for pid, row in table.items():
        cmd = row['cmd']
        if pid in mine or 'drive644.py cleanup' in cmd or 'drive644.py" cleanup' in cmd:
            continue
        number = any(f'{SLEEP} {n}' in cmd or f'sleep {n}' in cmd for n in ALL_NUMBERS)
        ours = OWNER_MARK in cmd or re.search(r'drive644\.py"? task ', cmd)
        service = (WINDOWS and 'app-server' in cmd and 'codex' in cmd.lower()) or (not WINDOWS and str(HOME) in cmd)
        if number or ours or service:
            try:
                os.kill(pid, 9)
                ended.append(f'{row["name"]}({pid})')
            except OSError:
                pass
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
        sample = os.environ.get('V644_QUSER_FILE')
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
             f"Get-ScheduledTaskInfo; 'state ' + $t.State + ', last result ' + $i.LastTaskResult + ', logon type ' + "
             f"$t.Principal.LogonType + ', run level ' + $t.Principal.RunLevel }} else {{ 'task absent' }}", 60)
    return (out.get('stdout') or out.get('error') or '').strip()


def task_script(case: str, name: str, script: Path | str, minutes: int) -> str:
    """Register and start the task. The principal is the SID of this process's own token (643 correction 1:
    USERDOMAIN\\USERNAME could not be mapped under the SSH network logon). Only booleans are printed."""
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
    name = f'v644-{case}'
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
        time.sleep(5 if WINDOWS else 1)
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
        raise SystemExit('V644_HOME is required off Windows')
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
    if command in ('case', 'schedule', 'task', 'cleanup') and (not rest or rest[0] not in CASES):
        print(f'usage: drive644.py {command} {"|".join(CASES)}')
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
    if command == 'probe':
        return probe(rest[0])
    if command == 'jobctx':
        return jobctx(rest[0])
    if command == 'jobopen':
        return jobopen(rest[0], rest[1], [int(pid) for pid in rest[2:]])
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
