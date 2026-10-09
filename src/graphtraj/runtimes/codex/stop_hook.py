"""Codex command Stop hook; input comes from its owning native lifecycle."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import click

from graphtraj.execution.main_finalize import bind_session, check_main_finalize, session_binding
from graphtraj.runtimes.codex.session_entry import (
    event_record, session_source, is_bound_checker, owns_native_root,
)


def native_event(event: dict) -> dict:
    """Associate native start/resume and handle Stop without Main relay calls."""
    from graphtraj.execution.runner_status import process_caller_alias
    from graphtraj.workspace.runner_project import discover_runner_directory

    name = event.get('hook_event_name')
    if name not in {'SessionStart', 'Stop'}:
        return {}
    root = Path(event['cwd'])
    runner = discover_runner_directory(root)

    def skipped(reason: str) -> dict:
        """Expose Stop routing without continuing a child or changing ownership."""
        return {'systemMessage': f'Completion check skipped: {reason}'} if name == 'Stop' else {}

    # Existing managed ownership always wins over an inherited Main environment.
    managed = process_caller_alias(runner, os.getpid())
    if managed is not None:
        return skipped(f'process ownership resolved to managed Agent {managed}.')
    if not event.get('transcript_path'):
        # Ephemeral root forks have no transcript. Their hook session ID is the
        # root thread ID; verify it natively and require our creation binding
        # before skipping, rather than stopping the child at SessionStart.
        session = event.get('session_id')
        connection = {'runtime': 'codex', 'session': session,
                      'hook_session': session,
                      'codex_home': os.path.abspath(os.environ.get('CODEX_HOME', Path.home() / '.codex'))}
        if isinstance(session, str) and session and is_bound_checker(runner, connection):
            from graphtraj.runtimes.codex.finalize import verify_main

            verify_main(connection)
            return skipped(f'Session {session} is a recorded completion checker.')
    metadata, _ = event_record(event)
    source = session_source(metadata)
    if source == 'child':
        return skipped(f'native source identifies child Session {metadata["id"]}.')
    if source != 'main':
        raise ValueError('Unknown Codex Session source; Main was not associated.')
    session = metadata['id']
    connection = {'runtime': 'codex', 'session': session,
                  'hook_session': event.get('session_id'),
                  'codex_home': os.path.abspath(os.environ.get('CODEX_HOME', Path.home() / '.codex'))}
    if is_bound_checker(runner, connection):
        return skipped(f'Session {session} is a recorded completion checker.')
    binding = session_binding(root, 'codex', session)
    if name == 'SessionStart':
        bind_session(connection, root)
        return {'systemMessage': 'GraphTraj Main Session associated.'}
    if not binding.is_file():
        if not owns_native_root(runner, connection):
            raise ValueError('Main Session association is unavailable; no established native root ownership.')
        # A hook can be adopted after this host's startup event was consumed.
        # Use the real Stop context and existing owner proof, not a fake start.
        bind_session(connection, root)
    result = check_main_finalize(binding, event)
    if not result:
        return skipped('the bound native Session/turn did not match, or its owning turn stopped. '
                       'No task completion result is available.')
    return result


@click.command()
@click.option('--binding', type=click.Path(path_type=Path))
@click.option('--hook-session')
@click.option('--configuration', is_flag=True, help='Print adoption material without enabling the hook.')
def main(binding: Path | None, hook_session: str | None, configuration: bool) -> None:
    """Receive native hook input and write only a valid Codex Stop response.

    Other hook events skip before opening Main's private binding. SIGTERM becomes
    KeyboardInterrupt so the async owner can cancel its checker; neither
    interrupt emits a continuation decision.
    """
    def interrupted(signum: int, frame: object) -> None:
        """Preserve a host cancellation instead of interpreting it as an error."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    if configuration:
        from graphtraj.runtimes.codex.finalize import hook

        click.echo(json.dumps(hook(Path(), {}), ensure_ascii=False))
        return
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError('Invalid native lifecycle event.')
        if binding is None:
            result = native_event(event)
        elif (event.get('hook_event_name') != 'Stop'
                or event.get('session_id') != hook_session):
            result = {}
        else:
            result = check_main_finalize(binding, event)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        reason = f'Completion hook failed: {error}'
        result = {'continue': False, 'stopReason': reason, 'systemMessage': reason}
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
