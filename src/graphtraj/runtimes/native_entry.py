"""Native extension carrier; Session facts are supplied by the owning Runtime."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys

import click
import yaml

from graphtraj.execution.main_finalize import (
    bind_session, bind_checker, check_prompt, parse_check_result, session_binding,
)
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_status import process_caller_alias
from graphtraj.workspace.runner_project import discover_runner_directory


def check_event(event: dict, cwd: Path, connection: dict) -> dict:
    """Keep Adapter-owned checking on the existing bound Session and check records."""
    path = session_binding(cwd, connection['runtime'], connection['session'])
    binding = yaml.safe_load(path.read_text(encoding='utf-8'))
    if binding['connection'] != connection:
        raise ValueError('Native Session association is stale.')
    if event.get('event') == 'check_context':
        return {'prompt': check_prompt(binding)}
    child = event.get('session')
    if not isinstance(child, str) or not child or child == binding['session']:
        raise ValueError('The checker must have a distinct native Session.')
    if event.get('event') == 'checker_created':
        bind_checker(path, binding, child)
        return {'session': child}
    if event.get('event') == 'check_result':
        directory = path.parent / 'checks' / hashlib.sha256(child.encode()).hexdigest()
        ownership = yaml.safe_load((directory / 'session.yml').read_text(encoding='utf-8'))
        if ownership['session'] != child or ownership['parent'] != binding['session']:
            raise ValueError('The checker result belongs to another native Session.')
        result = parse_check_result(event['output'])
        write_yaml_durably(directory / 'execution.yml', event)
        return result
    raise ValueError('Unknown native lifecycle event.')


def pi_event(event: dict, cwd: Path) -> dict:
    """Consume Pi's session_start callback without model-authored identity inputs."""
    from graphtraj.runtimes.pi.session_entry import current_connection, session_source, verify_main

    runner = discover_runner_directory(cwd)
    if process_caller_alias(runner, os.getpid()) is not None:
        return {'source': 'member'}
    connection = current_connection()
    if event.get('event') != 'session_start':
        if connection is None:
            raise ValueError('Pi native Session association is unavailable.')
        verify_main(connection)
        return check_event(event, cwd, connection)
    if event.get('event') != 'session_start' or event.get('reason') not in {
        'startup', 'reload', 'new', 'resume', 'fork',
    }:
        raise ValueError('Unknown Pi native Session entry.')
    header = event.get('header') or {}
    entries = event.get('entries') or []
    source = session_source(header, entries, os.environ)
    if source == 'child':
        return {'source': source}
    if source != 'main' or connection is None:
        raise ValueError('Unknown Pi Session source; Main was not associated.')
    connection.update(native_header=header, native_entries=entries)
    bind_session(connection, cwd)
    return {'source': 'main'}


def dsh_event(event: dict, cwd: Path) -> dict:
    """Consume DSH's native agent/created header without reading its private store."""
    from graphtraj.runtimes.dsh.session_entry import current_connection, session_source

    if process_caller_alias(discover_runner_directory(cwd), os.getpid()) is not None:
        return {'source': 'member'}
    connection = current_connection()
    if event.get('event') != 'agent/created':
        from graphtraj.runtimes.dsh.session_entry import caller_identity

        if connection is None or caller_identity(discover_runner_directory(cwd), connection) is not None:
            raise ValueError('Only the current DSH Main can run its completion check.')
        return check_event(event, cwd, connection)
    if event.get('event') != 'agent/created' or event.get('source') not in {
        'startup', 'resume', 'clear', 'compact',
    }:
        raise ValueError('Unknown DSH native Session entry.')
    header = event.get('header') or {}
    source = session_source(header)
    if source == 'child':
        return {'source': source}
    connection = current_connection()
    if source != 'main' or connection is None:
        raise ValueError('Unknown DSH Session source; Main was not associated.')
    connection['native_header'] = header
    bind_session(connection, cwd)
    return {'source': 'main'}


@click.command()
@click.argument('runtime', type=click.Choice(['pi', 'dsh']))
def main(runtime: str) -> None:
    """Handle one native extension event without exporting config in environment."""
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError('A native event object is required.')
        result = (pi_event if runtime == 'pi' else dsh_event)(event, Path.cwd())
    except Exception as error:
        result = {'error': str(error)}
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
