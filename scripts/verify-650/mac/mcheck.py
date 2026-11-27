"""Task 650 step M (correction 3), Mac side: does Claude Code (2.1.314) in print mode load the plugin that graftling's
``configuration --write`` generates (<project>/.claude/skills/agents-claude-host)?

Run by steps.zsh M only, with an isolated environment it builds: HOME, CLAUDE_CONFIG_DIR and TMPDIR inside one
temporary directory; ANTHROPIC_BASE_URL an unreachable local address, a dummy ANTHROPIC_AUTH_TOKEN,
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, DISABLE_AUTOUPDATER=1; no credential variable. Arguments:
  <claude binary> <graftling python> <work dir> <evidence dir>
Variants, each a fresh configuration --write project: untrusted, trusted (projects[<path>].hasTrustDialogAccepted in
<CLAUDE_CONFIG_DIR>/.claude.json), plugin-dir (--plugin-dir <project>/.claude/skills/agents-claude-host), and only
when the first two miss it: interactive under a pseudo-terminal (trusted). Each run is bounded and its process group
is killed once the init event and the load lines are read. Last line: RECOMMEND CLAUDE_HOST_LOAD=<value>: <reason>.
"""
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import threading
import time

CLAUDE, PY, WORK, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
PLUGIN = 'agents-claude-host'
TRUST_KEY = 'hasTrustDialogAccepted'
CONFIG = Path(os.environ['CLAUDE_CONFIG_DIR'])
PROMPT = 'Reply with exactly M-650-OK.'
BOUND_S = 90


def say(text: str) -> None:
    print(text, flush=True)
    with open(OUT / 'console.txt', 'a', encoding='utf-8') as out:
        out.write(text + '\n')


_BINARY: bytes | None = None


def binary_count(needle: bytes) -> int:
    global _BINARY
    if _BINARY is None:
        _BINARY = Path(CLAUDE).read_bytes()
    return _BINARY.count(needle)


def project(name: str) -> Path:
    directory = WORK / name / 'project'
    directory.mkdir(parents=True)
    done = subprocess.run([PY, '-m', 'graftling.claude.host', 'configuration', '--project', str(directory),
                           '--claude', CLAUDE, '--write'], capture_output=True, text=True, timeout=120)
    (OUT / f'{name}-configuration-write.txt').write_text(done.stdout + done.stderr, encoding='utf-8')
    if done.returncode != 0:
        raise SystemExit(f'configuration --write failed for {name}: {done.stderr[-300:]}')
    local = directory / '.claude' / 'settings.local.json'
    document = json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    document['enabledMcpjsonServers'] = ['graftling']  # as the VM driver (what the approval prompt writes)
    local.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return directory


def trust(directory: Path) -> list[str]:
    path = CONFIG / '.claude.json'
    document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    keys = list(dict.fromkeys([str(directory), str(directory.resolve())]))
    for key in keys:
        document.setdefault('projects', {}).setdefault(key, {})[TRUST_KEY] = True
    path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    return keys


def debug_lines(stderr_text: str) -> list[str]:
    lines = stderr_text.splitlines()
    for path in sorted((CONFIG / 'debug').glob('*.txt')) if (CONFIG / 'debug').is_dir() else []:
        lines += path.read_text(encoding='utf-8', errors='replace').splitlines()
    keep = [line for line in lines if PLUGIN in line or ('plugin' in line.lower() and any(
        word in line.lower() for word in ('load', 'skip', 'error', 'fail', 'trust', 'hook', 'module')))]
    return keep[:40]


def stop(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    process.wait(30)


def print_run(name: str, directory: Path, extra: list[str]) -> dict:
    """claude -p ... --output-format stream-json --verbose --debug; killed (process group) once init has come and the
    load lines had 8 s; bound BOUND_S."""
    for path in (CONFIG / 'debug').glob('*.txt') if (CONFIG / 'debug').is_dir() else []:
        path.unlink()
    err = (OUT / f'{name}-stderr.txt').open('w', encoding='utf-8')
    process = subprocess.Popen([CLAUDE, '-p', PROMPT, '--output-format', 'stream-json', '--verbose', '--debug', *extra],
                               cwd=str(directory), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                               text=True, start_new_session=True)
    lines: list[str] = []
    init: dict = {}
    seen = threading.Event()

    def read() -> None:
        for line in process.stdout:
            lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('subtype') == 'init':
                init.update(event)
                seen.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    began = time.monotonic()
    seen.wait(BOUND_S)
    if seen.is_set():
        time.sleep(min(8, max(0, BOUND_S - (time.monotonic() - began))))
    code = process.poll()
    stop(process)
    err.close()
    (OUT / f'{name}-stdout.jsonl').write_text(''.join(lines), encoding='utf-8')
    plugins = [p.get('name') for p in init.get('plugins') or [] if isinstance(p, dict)]
    return {'variant': name, 'init_seen': bool(init), 'plugins': plugins, 'listed': PLUGIN in plugins,
            'mcp_servers': [f'{s.get("name")}={s.get("status")}' for s in init.get('mcp_servers') or []],
            'exit': code if code is not None else 'killed after init' if init else f'killed at the {BOUND_S} s bound',
            'debug': debug_lines((OUT / f'{name}-stderr.txt').read_text(encoding='utf-8', errors='replace'))}


def interactive_run(name: str, directory: Path) -> dict:
    """Claude Code under a pseudo-terminal (trusted), debug on; after 25 s /exit, then killed; bound BOUND_S."""
    for path in (CONFIG / 'debug').glob('*.txt') if (CONFIG / 'debug').is_dir() else []:
        path.unlink()
    try:
        pid, fd = pty.fork()
    except OSError as error:  # no pseudo-terminal available: reported, not guessed
        return {'variant': name, 'init_seen': False, 'plugins': [], 'listed': False, 'mcp_servers': [],
                'exit': f'not run: {error}', 'debug': []}
    if pid == 0:
        os.chdir(directory)
        os.execv(CLAUDE, [CLAUDE, '--debug'])
    screen, began, sent = b'', time.monotonic(), False
    while time.monotonic() - began < min(45, BOUND_S):
        ready, _, _ = select.select([fd], [], [], 1)
        if ready:
            try:
                screen += os.read(fd, 65536)
            except OSError:
                break
        if not sent and time.monotonic() - began > 25:
            os.write(fd, b'/exit\r')
            sent = True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
        except OSError:
            pass
        time.sleep(1)
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass
    (OUT / f'{name}-screen.txt').write_bytes(screen)
    debug = debug_lines(screen.decode('utf-8', 'replace'))
    return {'variant': name, 'init_seen': False, 'plugins': [], 'listed': any(PLUGIN in line for line in debug),
            'mcp_servers': [], 'exit': 'ended (/exit, then killed)', 'debug': debug}


def report(result: dict) -> None:
    say(f'M {result["variant"]}: plugins listed {result["plugins"] or "none"}; {PLUGIN} loaded {result["listed"]}; '
        f'mcp_servers {result["mcp_servers"] or "none"}; exit {result["exit"]}; debug lines naming plugins/{PLUGIN}: '
        f'{len(result["debug"])}')
    for line in result['debug'][:12]:
        say(f'  | {line[:220]}')


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([CLAUDE, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()
    say(f'M Claude Code {version}; the binary names {TRUST_KEY} {binary_count(TRUST_KEY.encode())} time(s) and '
        f'find-generic-password {binary_count(b"find-generic-password")} time(s) (source of the trust key; Keychain use)')
    results = []
    untrusted = project('untrusted')
    results.append(print_run('untrusted', untrusted, []))
    trusted = project('trusted')
    keys = trust(trusted)
    say(f'M trusted: wrote projects[<project>].{TRUST_KEY} = true for {len(keys)} key(s) (the path and its real path) '
        'into <CLAUDE_CONFIG_DIR>/.claude.json')
    results.append(print_run('trusted', trusted, []))
    viadir = project('plugin-dir')
    results.append(print_run('plugin-dir', viadir, ['--plugin-dir', str(viadir / '.claude' / 'skills' / PLUGIN)]))
    if not results[0]['listed'] and not results[1]['listed']:
        interactive = project('interactive')
        trust(interactive)
        results.append(interactive_run('interactive', interactive))
    for result in results:
        report(result)
    (OUT / 'm.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    found = {result['variant']: result['listed'] for result in results}
    if found['untrusted']:
        value, why = ('plugin-dir', 'print mode loads the generated plugin on the Mac even untrusted, so the VM miss is '
                      'Windows-specific; --plugin-dir is the one route seen loading a plugin on Windows (probe650). '
                      'Not the documented route')
    elif found['trusted']:
        value, why = 'trust', 'print mode loads it only in a trusted folder (the documented "approve folder trust")'
    elif found['plugin-dir']:
        value, why = ('plugin-dir', 'print mode does not load the project plugin even trusted; only --plugin-dir loads it '
                      f'(interactive: {found.get("interactive")}). Not the documented route: a graftling documentation finding')
    else:
        value, why = 'none', 'no variant loaded it on the Mac: no setting can make the Claude host work on the VM'
    say(f'RECOMMEND CLAUDE_HOST_LOAD={value}: {why}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
