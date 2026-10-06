"""Retain an approved external Main in the existing Runner host lifetime."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from graphtraj.execution.runner_connection import connection_operation, worker_connection
from graphtraj.execution.runner_heartbeat import execution_start_lock, write_heartbeat
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    read_alias_mapping, require_execution_allowed, require_host_adoption,
    retained_session_directories,
)
from graphtraj.interfaces.local_tool import bind
from graphtraj.runtimes.runtime_adapter import current_recovery_reviewer, select_runtime_adapter
from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory


def execution_associations(runner: Path) -> Iterator[tuple[dict, dict]]:
    """Read existing registered execution associations without inferring purpose."""
    directory = runner / 'sessions'
    paths = list(directory.iterdir()) if directory.exists() else []
    seen = set()
    for path in [*paths, *retained_session_directories(runner)]:
        alias = path.name if path.parent == directory else path.parent.name
        if alias in seen or not path.is_dir():
            continue
        seen.add(alias)
        mapping, path = read_alias_mapping(runner, alias)
        native_path = path / 'native.yml'
        native = yaml.safe_load(native_path.read_text()) if native_path.exists() else {}
        if not isinstance(native, dict):
            raise RunnerError('operation-failed', 'Invalid registered execution association.')
        session = native.get('session') or mapping.get('session')
        if session:
            yield mapping, {**native, 'runtime': mapping['runtime'], 'session': session}


def require_unclaimed_execution(runner: Path, connection: dict, resume: str | None) -> None:
    """Prevent duplicate adoption and promotion of retained checker/member records."""
    matched = []
    for mapping, native in execution_associations(runner):
        if (native['runtime'], native['session']) == (connection['runtime'], connection['session']):
            if resume == mapping['alias'] and native.get('codex_home') != connection.get('codex_home'):
                raise RunnerError('authority-denied', 'Restoration cannot change the owning native connection.')
            matched.append(mapping)
    if matched and (len(matched) != 1 or matched[0]['alias'] != resume
                    or matched[0].get('purpose') != 'main'):
        raise RunnerError('authority-denied', 'This execution already belongs to a registered Agent.')
    if resume and not matched:
        raise RunnerError('authority-denied', 'Restoration must retain the registered execution association.')


@contextmanager
def external_main(cwd: Path, resume: str | None = None) -> Iterator[dict]:
    """Adopt the actual external Codex caller and retain its narrow hook attachment.

    The public foreground command owns this context until stopped. Native
    review allocates GraphTraj purpose; native handles only locate the already
    owning conversation. The protected hook attachment accepts lifecycle events
    only, never arbitrary Runner operations or caller-supplied aliases.
    """
    root = discover_project_root(cwd)
    runner = discover_runner_directory(root)
    require_host_adoption(runner)
    adapter = select_runtime_adapter('codex')
    connection = adapter.current_host_connection()
    if not connection:
        raise RunnerError('unsupported-operation', 'No existing owning Codex connection is available.')
    connection = dict(connection)
    adapter.verify_finalize_main(connection)
    require_unclaimed_execution(runner, connection, resume)
    selected_reviewer = current_recovery_reviewer()

    def review(proposal: dict) -> dict:
        """Review the exact host association through the selected existing route."""
        exact = {**proposal, 'execution_connection': connection}
        if selected_reviewer is not None:
            return selected_reviewer(exact)
        return adapter.native_recovery_approval(exact, root)

    def receive(event: dict) -> None:
        """Return notices through the same native connection, without a new Main."""
        adapter.send_host_event(connection, event)

    with bind(root, event_receiver=receive, recovery_reviewer=review) as host:
        alias = host.adopt_main('codex', resume=resume)
        mapping, directory = read_alias_mapping(runner, alias)
        # Serialize association publication with concurrent adoption and stopping.
        with execution_start_lock(runner):
            require_unclaimed_execution(runner, connection, resume)
            require_execution_allowed(runner, alias, mapping)
            write_yaml_durably(directory / 'native.yml', connection)
        credential = secrets.token_hex(32)
        checking = threading.Lock()
        binding_path = directory / 'finish-hook.json'
        if resume:
            # Restored ownership revokes an abandoned ephemeral attachment.
            binding_path.unlink(missing_ok=True)

        def lifecycle(document: dict) -> dict:
            """Authenticate fixed host code, then resolve registered execution purpose."""
            if (set(document) != {'credential', 'event'}
                    or not isinstance(document['credential'], str)
                    or not hmac.compare_digest(document['credential'], credential)):
                raise RunnerError('authority-denied', 'The trusted hook attachment is not authenticated.')
            if host.closed:
                raise RunnerError('operation-unavailable', 'The owning host attachment is closed.')
            require_execution_allowed(runner, alias, mapping)
            event = document['event']
            matches = []
            for registered, native in execution_associations(runner):
                if native['runtime'] != 'codex':
                    continue
                if registered['alias'] != alias and registered.get('parent') != alias:
                    continue
                transport = {**connection, 'session': native['session']}
                adapter.verify_finalize_main(transport)
                context = adapter.finalize_event(
                    {'connection': transport, 'session': native['session']}, event,
                )
                if context is not None:
                    matches.append(registered)
            if len(matches) != 1:
                raise RunnerError('authority-denied', 'The lifecycle has no unique registered execution association.')
            purpose = matches[0].get('purpose', 'member')
            if purpose in ('member', 'checker'):
                return {'status': 'skip', 'reason': f'GraphTraj {purpose} does not run Main completion checks.'}
            if matches[0]['alias'] != alias or purpose != 'main':
                raise RunnerError('authority-denied', 'The lifecycle does not belong to this adopted Main.')
            if not checking.acquire(blocking=False):
                raise RunnerError('operation-running', 'This Main already has an active finish-check.')
            try:
                return host.finish_check(connection, event)
            finally:
                checking.release()

        # The checker must be able to receive its skip while Main waits for it.
        with worker_connection(directory, lifecycle, concurrent=True) as address:
            descriptor = os.open(binding_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'address': address, 'credential': credential}, stream)
            try:
                hook = adapter.finalize_hook(binding_path, {'cwd': str(root), 'trusted_host': True})
                yield {'adoption_status': 'ready', 'alias': alias, 'hook': hook}
            finally:
                host.close()
                binding_path.unlink(missing_ok=True)


def trusted_hook_event(binding: Path, event: dict) -> dict:
    """Forward a fixed user-trusted handler through its private host attachment.

    Ordinary Agent commands retain their native file restrictions and cannot
    read this Runner-private capability. Its location alone grants no access.
    The capability is never part of the hook definition or model output.
    """
    document = json.loads(binding.read_text())
    return connection_operation(document['address'], {
        'credential': document['credential'], 'event': event,
    }, timeout_seconds=600)


def heartbeat_external_main(root: Path, alias: str) -> None:
    """Keep the existing ownership observable and honor actual Runner stops."""
    runner = discover_runner_directory(root)
    mapping, directory = read_alias_mapping(runner, alias)
    require_execution_allowed(runner, alias, mapping)
    write_heartbeat(directory, {'alias': alias, 'worker_pid': os.getpid()})
