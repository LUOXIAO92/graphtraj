"""Codex command Stop hook; input comes from its owning native lifecycle."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import click
import yaml

from graphtraj.execution.main_finalize import bind_session, check_main_finalize, session_binding
from graphtraj.runtimes.codex.session_entry import (
    NativeInputError, event_record, session_source, is_bound_checker, owns_native_root,
)


def native_event(event: dict, project_root: Path | None = None) -> dict:
    """Associate native events with the configured Harness, preserving host identity."""
    from graphtraj.execution.runner_status import process_caller_alias
    from graphtraj.workspace.runner_project import discover_runner_directory, discover_project_root

    name = event.get('hook_event_name')
    if name not in {'SessionStart', 'Stop', 'SessionEnd'}:
        return {}
    root = discover_project_root(project_root if project_root is not None else Path(event['cwd']))
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
    if name == 'SessionEnd':
        # The native SessionEnd hook flushes the terminal record before calling
        # us. It does not run a completion checker or establish new ownership.
        saved = yaml.safe_load(binding.read_text(encoding='utf-8'))
        if saved.get('connection') != connection:
            raise ValueError('Native SessionEnd association is stale.')
        _archive(root, session, event['transcript_path'])
        return {}
    if name == 'SessionStart':
        bind_session(connection, root, activity_source=event.get('transcript_path'))
        _archive(root, session, event['transcript_path'], new_session=event.get('source') == 'startup')
        return {'systemMessage': 'GraphTraj Main Session associated.'}
    if not binding.is_file():
        if not owns_native_root(runner, connection):
            raise ValueError('Main Session association is unavailable; no established native root ownership.')
        # A hook can be adopted after this host's startup event was consumed.
        # Use the real Stop context and existing owner proof, not a fake start.
        bind_session(connection, root, activity_source=event.get('transcript_path'))
    _archive(root, session, event['transcript_path'])
    result = check_main_finalize(binding, event)
    if not result:
        return {}  # Normal cancellation or an already-consumed completion result.
    # Only a matching Stop may update an older readable-source association.
    # Optional monitoring failures must not change the checker's decision.
    try:
        saved = yaml.safe_load(binding.read_text())
        source = str(Path(event['transcript_path']).resolve())
        if saved.get('activity', {}).get('trace_file') != source:
            bind_session(connection, root, activity_source=source)
    except Exception:
        field = next((key for key in ('systemMessage', 'reason', 'stopReason') if key in result), 'systemMessage')
        result[field] = result.get(field, '') + '\nMain activity source could not be retained.'
    return result


def _archive(root: Path, session: str, transcript: str, *, new_session: bool = False) -> None:
    """Collect a verified external Main, retaining policy boundaries across hooks.

    Hooks are separate processes. The binding owns only the native byte boundary
    and last observed saving choice; conversation bodies live solely in JSONL.
    Enabling saving takes effect when the next native hook observes the choice.
    Earlier bytes require explicit backfill, never a receipt-time approximation.
    """
    from graphtraj import file_lock
    from graphtraj.interfaces.agents import configured_archive
    from graphtraj.runtimes.codex.jsonl_archive import CodexJsonlArchive
    from graphtraj.execution.runner_io import write_yaml_durably

    directory = session_binding(root, 'codex', session).parent
    source = Path(transcript)
    archive = configured_archive(root)
    boundary = directory / 'archive.yml'
    with (directory / 'archive.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        saved = yaml.safe_load(boundary.read_text()) if boundary.exists() else None
        size = source.stat().st_size
        activation = 0 if new_session else size
        if saved is not None:
            if saved['session'] != session or saved['rollout'] != str(source):
                raise ValueError('Native archive boundary no longer matches the bound Session.')
            if saved['enabled'] and archive.save_normalized_sessions:
                activation = saved['activation']
        collector = CodexJsonlArchive(archive, 'main', session, source)
        collector.activation = activation
        collector.collect(source)
        write_yaml_durably(boundary, {
            'session': session, 'rollout': str(source), 'activation': activation,
            'enabled': archive.save_normalized_sessions,
        })


@click.command()
@click.option('--binding', type=click.Path(path_type=Path))
@click.option('--hook-session')
@click.option('--configuration', is_flag=True, help='Print adoption material without enabling the hook.')
@click.option('--project-root', type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Select the Harness for an external native Session; identity still comes from the host.')
def main(
    binding: Path | None,
    hook_session: str | None,
    configuration: bool,
    project_root: Path | None,
) -> None:
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
    event = None
    try:
        raw = sys.stdin.read()
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as error:
            raise NativeInputError(f'Codex hook stdin ({len(raw)} characters) is not a lifecycle event JSON: {error}') from None
        if not isinstance(event, dict):
            raise ValueError('Invalid native lifecycle event.')
        if binding is None:
            result = native_event(event, project_root)
        elif (event.get('hook_event_name') != 'Stop'
                or event.get('session_id') != hook_session):
            result = {}
        else:
            result = check_main_finalize(binding, event)
            if result and event.get('transcript_path'):
                saved = yaml.safe_load(binding.read_text(encoding='utf-8'))
                metadata, _ = event_record(event)
                if metadata['id'] != saved['session']:
                    raise ValueError('Main archive source does not match the bound native Session.')
                _archive(Path(saved['cwd']), saved['session'], event['transcript_path'])
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        from graphtraj.runtimes.codex.finalize import response

        name = event.get('hook_event_name') if isinstance(event, dict) else None
        if isinstance(error, NativeInputError) and name in {'SessionStart', 'SessionEnd'}:
            # Unreadable input is not a completion verdict. Codex stops the
            # pending user turn on continue=false, so report it without
            # consuming input. Identity refusals and an event whose kind is
            # unknown still stop; the next Stop checks or reports its own failure.
            label = f"{name} ({event.get('source') or 'unknown source'})"
            click.echo(json.dumps({'systemMessage': f'GraphTraj {label} input failed: {error}'},
                                  ensure_ascii=False))
            return
        from graphtraj.runtimes.runtime_adapter import CheckUsage

        result = response({'status': 'error', 'reason': f'Completion hook failed: {error}',
                           'nodes': [], 'usage_summary': CheckUsage().summary()}, False)
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
