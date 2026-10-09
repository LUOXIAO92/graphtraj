"""Run Linux desktop adoption with public registration and controlled model work.

Run only on an unbound disposable CI host. Current caller identity is never
removed or replaced. All setup, Ticket and Session state uses public operations.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable

from graphtraj.interfaces.local_tool import bind


def operate(call: Callable[[dict], Any], feature: str, arguments: dict) -> dict:
    """Require a successful response from the bound public tool."""
    reply = call({'action': 'execute', 'feature': feature, 'arguments': arguments})
    assert not reply.failed, reply.document
    return reply.document


def main() -> None:
    """Retain one public host binding until the controlled execution completes."""
    assert sys.platform == 'linux', 'This fixture is for the target Linux CI host'
    root = Path(os.environ['ADOPTION_ROOT']).resolve()
    evidence = root / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    result = {'passed': False, 'controlledData': True, 'modelExecution': False, 'events': []}
    try:
        project = root / 'activity-project'
        source = project / 'source'
        source.mkdir(parents=True)
        for args in (['init', '--initial-branch=main'], ['config', 'user.name', 'Linux Adoption'],
                     ['config', 'user.email', 'adoption@example.invalid']):
            subprocess.run(['git', *args], cwd=source, check=True, capture_output=True)
        (source / 'fixture.txt').write_text('Controlled Linux desktop input; no real model execution.\n')
        subprocess.run(['git', 'add', 'fixture.txt'], cwd=source, check=True)
        subprocess.run(['git', 'commit', '-m', 'Controlled adoption source'], cwd=source, check=True)
        fixture_bin = root / 'fixture-bin'
        fixture_bin.mkdir()
        runtime = Path(__file__).with_name('linux_adoption_runtime.py').resolve()
        executable = fixture_bin / 'codex'
        executable.write_text(f'#!{sys.executable}\nimport runpy\nrunpy.run_path({str(runtime)!r}, run_name="__main__")\n')
        executable.chmod(0o755)
        os.environ['PATH'] = str(fixture_bin) + os.pathsep + os.environ['PATH']
        # Public Ticket operations resolve configuration from the host's cwd.
        os.chdir(project)
        call = bind(project)
        operate(call, 'project_setup', {'source_repository': str(source), 'apply': True, 'create_dev': True})
        (project / '.graphtraj/roles.yml').write_text(
            'roles:\n  observer:\n    runtime: codex\n    model: gpt-5.3-codex\nrole_tree:\n  observer: {}\n')
        registered = operate(call, 'ticket_register', {'ticket_id': '1', 'ticket_name': 'controlled-linux',
            'title': 'Controlled Linux desktop observation', 'source': 'local:controlled-linux-adoption',
            'body': 'Controlled message/tool/usage records, not real model execution.', 'dependencies': []})
        graph = operate(call, 'ticket_graph', {})
        assert len(graph['tickets']) == 1, graph
        ticket_id = graph['tickets'][0]['ticket_id']
        (project / 'controlled-input.txt').write_text('Disposable CI fixture authorized to emit known records.\n')
        operate(call, 'ticket_update', {'ticket_id': ticket_id, 'status': 'ready',
            'active_team_ordinal': None, 'worktree': None, 'branch': None, 'current_candidate': None,
            'caused_by_event_ids': [], 'evidence_refs': ['controlled-input.txt']})
        terminal = threading.Event()

        def receive(event: dict) -> None:
            """Receive completion on this same public host connection."""
            result['events'].append(event)
            terminal.set()

        with tempfile.TemporaryDirectory(prefix='graphtraj-linux-control-') as control:
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(Path(control) / 'fixture.sock'))
                listener.listen(1)
                listener.settimeout(30)
                os.environ['LINUX_ADOPTION_CONTROL'] = str(Path(control) / 'fixture.sock')
                with bind(project, event_receiver=receive) as host:
                    launched = operate(host, 'swarm', {'tasks': [{'ticket_id': ticket_id,
                        'role': 'observer', 'instruction': 'Emit the controlled desktop records and await test release.'}]})
                    task = launched['tasks'][0]
                    assert task['launch_status'] == 'launched', launched
                    result['registration'] = registered
                    result['task'] = task
                    try:
                        with listener.accept()[0] as connection:
                            connection.settimeout(30)
                            assert connection.recv(128) == b'controlled records ready\n'
                            environment = {**os.environ, 'ADOPTION_ACTIVITY_PROJECT': str(project),
                                'ADOPTION_AGENT_ALIAS': task['alias'], 'ADOPTION_TICKET_ID': ticket_id}
                            try:
                                desktop = Path(__file__).resolve().parents[1] / 'desktop'
                                completed = subprocess.run(['node', 'tests/adoption-linux.mjs'], cwd=desktop,
                                                           env=environment, timeout=240)
                                result['uiExitCode'] = completed.returncode
                                result['ui'] = json.loads((evidence / 'ui-result.json').read_text())
                            finally:
                                connection.sendall(b'finish')
                        assert terminal.wait(30), 'Runner did not deliver completion to the retained host'
                        assert result['events'][-1]['event'] == 'completed', result['events']
                        result['afterCompletion'] = operate(host, 'alias_status', {'aliases': [task['alias']]})
                        final = result['afterCompletion']['aliases'][0]
                        assert final['activity'] == 'idle' and final['last_outcome'] == 'completed', final
                        assert result['uiExitCode'] == 0 and result['ui']['uiPassed'], result['ui']
                        assert {key: final[key] for key in ('session', 'execution_id')} == result['ui']['controlledExecution']
                        result['passed'] = True
                    finally:
                        if not terminal.is_set():
                            result['cleanup'] = operate(host, 'interrupt', {'alias': task['alias']})
    except Exception as error:
        result['failure'] = str(error)
        raise
    finally:
        (evidence / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
