"""Independent control owner launched by Pi's trusted native extension.

The extension supplies its native Session association on the owned stdio
launch boundary. Model requests supply neither identity nor launch settings.
The explicit host configuration contains ``root`` and a preflighted
``adapter_request``; it is not GraphTraj project or Task configuration.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Callable

from agent_swarm import AgentControl, AgentsError, Caller, bind
from agent_swarm.connection import agents_connection
from agent_swarm.process import process_ancestors
from graphtraj.runtimes.pi.driver import PiDriver
from graphtraj.runtimes.pi.session_entry import current_connection, session_record, verify_main


def verify_native_parent(executable: Path) -> None:
    """Require the actual MCP parent to be the selected native Pi process.

    Native environment facts only constrain this OS-observed launch boundary;
    they do not establish it. Reuse the existing kernel process readers and
    reject shell-launched or unrelated clients even with copied Session env.
    """
    from graphtraj.execution.runner_process import process_executable, _process_arguments

    parent = os.getppid()
    actual = process_executable(parent)
    arguments = _process_arguments(parent)
    expected = executable.resolve()
    selected_node = os.environ.get('AGENT_SWARM_PI_NODE')
    direct = actual is not None and actual.resolve() == expected
    node_script = (actual is not None and selected_node
                   and actual.resolve() == Path(selected_node).resolve()
                   and len(arguments) > 1 and Path(arguments[1]).resolve() == expected)
    if parent <= 1 or parent != os.getppid() or not (direct or node_script):
        raise ValueError('The MCP pipe is not owned by the selected native Pi process.')


def bind_native_main(control: AgentControl, connection: dict, cwd: Path) -> Callable:
    """Bind the extension's existing native root without writing an identity record.

    This is a trusted host API, not a model-callable adoption operation. Like
    nativeEntry, the caller obtains the association from Pi session_start.
    Never pass model arguments as ``connection``. Always read the selected
    native file rather than accepting a request-supplied header or entries.
    """
    if connection.get('runtime') != 'pi':
        raise ValueError('The owning native Runtime must be Pi.')
    selected = {key: connection[key] for key in ('runtime', 'session', 'session_file')}
    session = verify_main(selected)
    header, _ = session_record(Path(selected['session_file']), session)
    if Path(header['cwd']).resolve() != cwd.resolve():
        raise ValueError('The Pi native Session cwd does not match this host.')
    return bind(control, Caller('pi-native', None, session=session, runtime='pi'))


def main() -> None:
    """Keep one control owner alive until the trusted extension closes its pipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    options = parser.parse_args()
    if 'AGENT_SWARM_CONNECTION' in os.environ or 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        raise ValueError('An already-bound child must use its existing connection, not adopt Main.')
    configuration = json.loads(options.config.read_text(encoding='utf-8'))
    if set(configuration) != {'root', 'adapter_request'}:
        raise ValueError('Pi host configuration requires root and adapter_request only.')
    root = Path(configuration['root'])
    request = configuration['adapter_request']
    if not root.is_absolute() or not isinstance(request, dict):
        raise ValueError('The data root must be absolute and adapter_request must be an object.')
    verify_native_parent(Path(request['executable']))
    if Path(request['worktree_path']).resolve() != Path.cwd().resolve():
        raise ValueError('The prepared child cwd must match this native host.')
    if (request.get('model') != os.environ.get('AGENT_SWARM_PI_MODEL')
            or request.get('provider') != os.environ.get('AGENT_SWARM_PI_PROVIDER')):
        raise ValueError('The prepared child model/provider must match the selected native host.')
    connection = current_connection()
    if connection is None:
        raise ValueError('Pi native Session association is unavailable.')
    control = AgentControl(root, {'pi': PiDriver(request)})
    call = bind_native_main(control, connection, Path.cwd())
    parent = os.getppid()

    def authenticate(caller_pid: int) -> None:
        """Accept only direct clients of the verified native parent, not child Runtimes."""
        chain = process_ancestors(caller_pid)
        if os.getppid() != parent or len(chain) < 2 or chain[1] != parent:
            raise AgentsError('authority-denied', 'The client is not owned by this native Pi host.')

    try:
        with agents_connection(root / 'live' / 'pi-host', call, authenticate) as address:
            print(json.dumps({'connection': address}), flush=True)
            # Only lifecycle EOF travels over this private extension pipe.
            # Model requests use the shared authenticated CLI/MCP bridge.
            if sys.stdin.read():
                raise ValueError('The native host pipe only accepts lifecycle close.')
    finally:
        # Closing the extension pipe ends this owner's execution lifetime.
        # Preserve identities and Sessions; use the same public stop path.
        status = call({'action': 'status'})
        if not status.failed:
            pending = list(status.document['result']['agents'])
            owned = []
            while pending:
                agent = pending.pop()
                owned.append(agent)
                pending.extend(agent['children'])
            # Stop descendants before their parents so no nested execution
            # outlives the single control owner when its MCP pipe closes.
            for agent in reversed(owned):
                if agent['state'] == 'active':
                    call({'action': 'interrupt', 'agent': agent['agent']})
                    result = call({'action': 'wait', 'agent': agent['agent'], 'timeout_seconds': 10})
                    if result.failed or result.document['result']['state'] == 'active':
                        raise RuntimeError('Native child stop was not confirmed before host shutdown.')


if __name__ == '__main__':
    main()
