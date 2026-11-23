"""Rehearsal only (Task 581): what a real Main leaves behind, so steps.zsh's verdicts can be exercised. Not graftling.

The host's Python is found the way the candidate documents it, from the attachment: DSH from the realpath of
profiles/headless/node_modules/graftling-dsh (<prefix>/lib/pythonX.Y/site-packages/graftling/dsh), Pi from
.pi/settings.json's package, Claude Code from .mcp.json's command. A process '<python> -c ... graftling.<kind>.host'
runs while the stub answers (it inherits the Main's environment, as a host does), so the process-table verdicts see
it; the ps stand-in learns its environment NAMES from the registry ($STUB581_PSFILE).
STUB581_OTHER_PYTHON=1: run that process with the stub's own Python instead (the verdict must FAIL).
STUB581_NO_NOTICE=1: the record's notification stays 'pending' (the notice verdicts must FAIL).
STUB581_LEAK=NAME: that host process also holds NAME (a leaked credential; observable 2 must FAIL).
STUB581_CHILD_PROVIDER=<p>: the child's native Session names provider <p> (observable 3 must FAIL unless deepseek).
The child's provider files: <root>/native/<agent>/dsh-native/session.jsonl (provider, model) and the record's
executions[].process.resolved_model, the fields providers.py reads.
"""
import json, os, subprocess, sys, uuid
from pathlib import Path


def register(rows):
    registry = os.environ.get('STUB581_PSFILE')  # read by the ps stand-in (the sandbox has no ps)
    if registry:
        with open(registry, 'a') as sink:
            for pid, ppid, command, env in rows:
                sink.write(f'{pid}\t{ppid}\t{command}\t{" ".join(sorted(env))}\n')


def run_host(kind: str, python: str | None) -> None:
    exe = sys.executable if os.environ.get('STUB581_OTHER_PYTHON') or not python else python
    argv = [exe, '-c', 'import time; time.sleep(1.5)', f'graftling.{kind}.host']
    env = dict(os.environ)
    if os.environ.get('STUB581_LEAK'):
        env[os.environ['STUB581_LEAK']] = 'leak'
    child = subprocess.Popen(argv, env=env)
    register([(os.getpid(), os.getppid(), f'{kind} (stub Main)', os.environ),
              (child.pid, os.getpid(), ' '.join(argv), env)])
    child.wait()


def main_session(kind: str, model: str) -> None:
    """A provider trace of the Main itself: DSH under DSH_HOME, Pi in --session-dir (584's message fields)."""
    if kind == 'dsh':
        d = Path(os.environ['DSH_HOME'], 'sessions'); d.mkdir(parents=True, exist_ok=True)
        (d / 'stub-main.jsonl').write_text(json.dumps({'provider': 'deepseek', 'model': model}) + '\n')
    elif kind == 'pi' and os.environ.get('STUB581_PI_SESSION_DIR'):
        d = Path(os.environ['STUB581_PI_SESSION_DIR']); d.mkdir(parents=True, exist_ok=True)
        (d / 'stub-main.jsonl').write_text(json.dumps({'type': 'message', 'message': {
            'provider': 'deepseek', 'model': model, 'api': 'openai-completions'}}) + '\n')


def answer(prompt: str, kind: str, python: str | None, model: str = 'deepseek-v4-flash') -> str:
    """One line for a plain prompt; for a create prompt, one record under ./.agents-control and four lines."""
    if '"feature":"create"' not in prompt:
        return f'{kind}-stub-model (stub provider)'
    main_session(kind, model)
    run_host(kind, python)
    root = Path.cwd() / '.agents-control'
    agent = f'agent-{uuid.uuid4().hex}'
    note = 'pending' if os.environ.get('STUB581_NO_NOTICE') else 'delivered'
    (root / 'control' / 'agents').mkdir(parents=True, exist_ok=True)
    (root / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps({
        'agent': agent, 'runtime': 'dsh', 'session': str(uuid.uuid4()),
        'creator': {'host': f'{kind}-native', 'session': 'stub'},
        'executions': [{'state': 'ended', 'outcome': 'completed', 'last_message': 'ready', 'notification': note,
                        'process': {'resolved_model': 'deepseek-v4-flash'}}]}))
    native = root / 'native' / agent / 'dsh-native'
    native.mkdir(parents=True, exist_ok=True)
    (native / 'session.jsonl').write_text(json.dumps({
        'provider': os.environ.get('STUB581_CHILD_PROVIDER', 'deepseek'), 'model': 'deepseek-v4-flash'}) + '\n')
    return f'AGENT: {agent}\nANSWER: ready\nSTATUS: standby; last_result.notification: {note}\nLISTED: {agent}'


def prefix_python(package_dir: str) -> str | None:
    """<prefix>/bin/python for <prefix>/lib/pythonX.Y/site-packages/graftling/<kind>."""
    real = Path(package_dir).resolve()
    candidate = real.parents[4] / 'bin' / 'python'
    return str(candidate) if candidate.exists() else None
