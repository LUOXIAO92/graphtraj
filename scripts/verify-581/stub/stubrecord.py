"""Rehearsal only (Task 581): what a real Main leaves behind, so steps.zsh's verdicts can be exercised. Not graftling.

The host's Python is found the way the candidate documents it, from the attachment: DSH from the realpath of
profiles/headless/node_modules/graftling-dsh (<prefix>/lib/pythonX.Y/site-packages/graftling/dsh), Pi from
.pi/settings.json's package, Claude Code from .mcp.json's command. A process '<python> -c ... graftling.<kind>.host'
runs while the stub answers, so the process-table verdict sees it.
STUB581_OTHER_PYTHON=1: run that process with the stub's own Python instead (the verdict must FAIL).
STUB581_NO_NOTICE=1: the record's notification stays 'pending' (the notice verdicts must FAIL).
"""
import json, os, subprocess, sys, uuid
from pathlib import Path


def run_host(kind: str, python: str | None) -> None:
    exe = sys.executable if os.environ.get('STUB581_OTHER_PYTHON') or not python else python
    argv = [exe, '-c', 'import time; time.sleep(1.5)', f'graftling.{kind}.host']
    child = subprocess.Popen(argv)
    registry = os.environ.get('STUB581_PSFILE')  # read by the ps stand-in (the sandbox has no ps)
    if registry:
        with open(registry, 'a') as sink:
            sink.write(f'{os.getpid()} {os.getppid()} {kind} (stub Main)\n{child.pid} {os.getpid()} {" ".join(argv)}\n')
    child.wait()


def answer(prompt: str, kind: str, python: str | None) -> str:
    """One line for a plain prompt; for a create prompt, one record under ./.agents-control and four lines."""
    if '"feature":"create"' not in prompt:
        return f'{kind}-stub-model (stub provider)'
    run_host(kind, python)
    root = Path.cwd() / '.agents-control'
    agent = f'agent-{uuid.uuid4().hex}'
    note = 'pending' if os.environ.get('STUB581_NO_NOTICE') else 'delivered'
    (root / 'control' / 'agents').mkdir(parents=True, exist_ok=True)
    (root / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps({
        'agent': agent, 'runtime': 'dsh', 'session': str(uuid.uuid4()),
        'creator': {'host': f'{kind}-native', 'session': 'stub'},
        'executions': [{'state': 'ended', 'outcome': 'completed', 'last_message': 'ready', 'notification': note}]}))
    return f'AGENT: {agent}\nANSWER: ready\nSTATUS: standby; last_result.notification: {note}\nLISTED: {agent}'


def prefix_python(package_dir: str) -> str | None:
    """<prefix>/bin/python for <prefix>/lib/pythonX.Y/site-packages/graftling/<kind>."""
    real = Path(package_dir).resolve()
    candidate = real.parents[4] / 'bin' / 'python'
    return str(candidate) if candidate.exists() else None
