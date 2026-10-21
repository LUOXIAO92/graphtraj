"""Bind a Main completion check to its existing host and native Session."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterator

import yaml

from graphtraj import file_lock
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.runtimes.runtime_adapter import current_host_connection, select_runtime_adapter
from graphtraj.workspace.runner_project import discover_runner_directory, discover_project_root


def bind_main_finalize(summary_issue: str, cwd: Path, paused: bool | None = None) -> dict[str, Any]:
    """Capture the actual root caller; return hook material for host adoption.

    No identity, model or connection is accepted from operation arguments.
    This records Session ownership, not a second task-completion state.
    """
    runner = discover_runner_directory(cwd)
    if caller_alias(runner) is not None:
        raise RunnerError('authority-denied', 'Only the owning Main can bind its completion check.')
    if not summary_issue.strip():
        raise ValueError('A summary Issue reference is required.')
    connection = current_host_connection()
    if connection is None:
        raise RunnerError('unsupported-operation', 'The current native Main host is unavailable.')
    if paused is not None and connection['runtime'] != 'codex':
        raise RunnerError('unsupported-operation', 'Explicit user pause is supported by the Codex Stop hook.')
    return bind_session(connection, cwd, summary_issue, paused=paused)


def bind_session(
    connection: dict,
    cwd: Path,
    summary_issue: str = '',
    activity_source: str | None = None,
    paused: bool | None = None,
    entry: str | None = None,
) -> dict[str, Any]:
    """Associate an Adapter-observed external Session using existing Main storage.

    Callers of this internal boundary obtain connection facts from their Runtime,
    never from model operation arguments. A task hint does not define identity.
    ``entry`` names a real native start/resume boundary; that verified Main
    then continues the project's Main working state (``main_continuity``).
    """
    cwd = discover_project_root(cwd)
    runner = discover_runner_directory(cwd)
    adapter = select_runtime_adapter(connection['runtime'])
    session = adapter.verify_finalize_main(connection)
    # Forks need not have a native child marker. Their Runner creation binding
    # still prevents a checker from registering itself as another Main.
    if connection['runtime'] == 'codex':
        from graphtraj.runtimes.codex.session_entry import is_bound_checker

        checker = is_bound_checker(runner, connection)
    else:
        checker = False
        for path in (runner / 'main-sessions').glob('*/checks/*/session.yml'):
            child = yaml.safe_load(path.read_text(encoding='utf-8'))
            if child['runtime'] == connection['runtime'] and child['session'] == session:
                checker = True
                break
    if checker:
        raise RunnerError('authority-denied', 'A bound checker cannot register Main completion.')
    configuration = load_project_configuration(cwd)
    key = hashlib.sha256((connection['runtime'] + ':' + session).encode()).hexdigest()
    directory = runner / 'main-sessions' / ('finalize_' + key)
    binding = {
        'runtime': connection['runtime'], 'session': session,
        'connection': connection, 'summary_issue': summary_issue,
        'cwd': str(configuration.harness_root),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'session.yml'
    with (directory / 'binding.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        if path.exists():
            previous = yaml.safe_load(path.read_text())
            if any(previous.get(key) != binding[key]
                   for key in ('runtime', 'session', 'cwd')):
                raise RunnerError('authority-denied', 'This Main already has a different Session binding.')
        else:
            previous = {}
        if not summary_issue:
            binding['summary_issue'] = previous.get('summary_issue', '')
        # Native rebinding and notifications retain the user's explicit pause.
        pause = dict(previous.get('user_pause', {'paused': False, 'revision': 0}))
        if paused is not None:
            if type(paused) is not bool:
                raise ValueError('The user pause must be a boolean.')
            if pause['paused'] != paused:
                pause = {'paused': paused, 'revision': pause['revision'] + 1}
        binding['user_pause'] = pause
        # Retain the source supplied by native entry without changing caller identity.
        source = activity_source or connection.get('session_file')
        activity = dict(previous.get('activity', {}))
        if source:
            activity['trace_file'] = str(Path(source).resolve())
        if activity:
            binding['activity'] = activity
        write_yaml_durably(path, binding)
    if entry is not None:
        from graphtraj.execution.main_continuity import claim_main

        claim_main(runner, connection, entry)
    return {'binding': str(path), 'session': session, 'user_pause': pause,
            'hook': adapter.finalize_hook(path, binding)}


def session_binding(cwd: Path, runtime: str, session: str) -> Path:
    """Locate the existing per-Session association without a caller-supplied path."""
    key = hashlib.sha256((runtime + ':' + session).encode()).hexdigest()
    return discover_runner_directory(cwd) / 'main-sessions' / ('finalize_' + key) / 'session.yml'


def parse_check_result(text: str) -> dict[str, Any]:
    """Validate the checker result without interpreting or persisting task truth."""
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {'status', 'reason', 'nodes', 'conclusion'}:
        raise ValueError('The completion checker must return status, conclusion, reason and nodes.')
    if result['status'] not in ('completed', 'waiting', 'actionable', 'error'):
        raise ValueError('The completion checker returned an unknown status.')
    if not isinstance(result['conclusion'], str) or not result['conclusion'].strip():
        raise ValueError('The completion checker returned no conclusion.')
    if not isinstance(result['reason'], str) or not result['reason'].strip():
        raise ValueError('The completion checker returned no reason.')
    nodes = result['nodes']
    if not isinstance(nodes, list) or any(not isinstance(n, str) or not n.strip() for n in nodes):
        raise ValueError('Completion nodes must be nonempty Task identifiers or URLs.')
    if result['status'] == 'actionable' and not nodes:
        raise ValueError('Actionable work must identify concrete unfinished nodes.')
    return result


def check_prompt(binding: dict) -> str:
    """Supply current authoritative graph access and a non-authoritative task hint."""
    prompt = files('graphtraj').joinpath('prompts/main_finalize_check.md').read_text(encoding='utf-8')
    return prompt + '\n\n' + json.dumps({
        'summary_issue_hint': binding['summary_issue'],
    }, ensure_ascii=False)


def bind_checker(binding_file: Path, binding: dict, child: str) -> Path:
    """Retain a native child returned to its owning Adapter before execution."""
    if not isinstance(child, str) or not child or child == binding['session']:
        raise ValueError('The checker did not create a distinct native Session.')
    key = hashlib.sha256(child.encode()).hexdigest()
    directory = binding_file.parent / 'checks' / key
    directory.mkdir(parents=True, exist_ok=False)
    # Held until this check is recorded; the kernel releases it on any exit.
    hold_liveness(directory)
    write_yaml_durably(directory / 'session.yml', {
        'runtime': binding['runtime'], 'session': child,
        'parent': binding['session'], 'parent_connection': binding['connection'],
        'summary_issue': binding['summary_issue'],
    })
    return directory


STALE_CHECK_ERROR = ('A previous completion check ended before it was recorded; '
                     'its termination cause is unknown.')
_LIVENESS: dict[Path, int] = {}


def hold_liveness(directory: Path) -> None:
    """Mark a check record as owned by this live process (POSIX only)."""
    if os.name == 'nt':
        return
    descriptor = os.open(directory, os.O_RDONLY)
    file_lock.flock(descriptor, file_lock.LOCK_EX)
    _LIVENESS[directory] = descriptor


def release_liveness(directory: Path) -> None:
    """Release ownership once the check record is written."""
    descriptor = _LIVENESS.pop(directory, None)
    if descriptor is not None:
        os.close(descriptor)


@contextmanager
def _unowned(directory: Path) -> Iterator[bool]:
    """Yield True only while no live process holds this entry's lock."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        yield False
        return
    try:
        try:
            file_lock.flock(descriptor, file_lock.LOCK_EX | file_lock.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True
    finally:
        os.close(descriptor)


def _recover_stale_checks(adapter: Any, binding: dict, binding_file: Path) -> None:
    """Record checks whose hook ended before recording them, never inferring why.

    Only entries no live process owns are touched. A cancellation is recorded
    only when this recovery interrupted the checker and the host confirmed it.
    """
    if os.name == 'nt':
        return
    for directory in sorted((binding_file.parent / 'checks').glob('*')):
        session_file = directory / 'session.yml'
        if not session_file.is_file() or (directory / 'execution.yml').exists():
            continue
        with _unowned(directory) as owned:
            if not owned:
                continue
            child = yaml.safe_load(session_file.read_text(encoding='utf-8'))['session']
            end = getattr(adapter, 'end_stale_check', None)
            error = STALE_CHECK_ERROR
            try:
                confirmed = end(binding, child) if end is not None else None
            except Exception as failure:  # Kept visible; never makes the check look ended.
                confirmed = None
                error += f' Recovery could not read or interrupt it: {type(failure).__name__}: {failure}'
            write_yaml_durably(directory / 'execution.yml', (
                {'session': child, 'outcome': 'cancelled', 'cancellation': confirmed} if confirmed
                else {'session': child, 'outcome': 'error', 'error': error}))
    for pending in sorted(binding_file.parent.glob('pending-*')):
        if not (pending / 'turn').is_file():
            continue
        with _unowned(pending) as owned:
            if owned:
                shutil.rmtree(pending)


def check_main_finalize(binding_file: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Handle one trusted host event through its Adapter and existing Task Graph.

    The host, not the model tool gateway, supplies the lifecycle event. The
    Adapter filters other Sessions and interruptions before any checker starts.
    Every actual child Session is retained with its creation-time parent binding.
    """
    # A second Stop waits for the first result to be durably recorded before
    # the Adapter decides whether this is still the same completion boundary.
    with (binding_file.parent / 'check.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        return _check_main_finalize(binding_file, event)


def _check_main_finalize(binding_file: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Check and record one host event while holding its Main's execution lock."""
    binding = yaml.safe_load(binding_file.read_text(encoding='utf-8'))
    adapter = select_runtime_adapter(binding['runtime'])
    context = adapter.finalize_event(binding, event)
    if context is None:
        return adapter.finalize_response(None, False)
    usage = adapter.finalize_usage()
    recovery_failure = None
    try:
        _recover_stale_checks(adapter, binding, binding_file)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as failure:
        # Left for a later Stop and reported; it never blocks this check.
        recovery_failure = f'{type(failure).__name__}: {failure}'
    try:
        prompt = check_prompt(binding)
        child_binding: tuple[str, Path] | None = None

        def created(child: str) -> None:
            """Bind only a fresh native handle returned to this Main's Adapter."""
            nonlocal child_binding
            if child_binding is not None:
                raise ValueError('One Stop cannot bind multiple completion checkers.')
            directory = bind_checker(binding_file, binding, child)
            child_binding = (child, directory)

        native = adapter.check_main_finalize(binding, context, prompt, created)
        if native is None:  # The host stopped, or an earlier release was already consumed.
            return adapter.finalize_response(None, False)
        usage = adapter.finalize_usage(native)
        # Only the Adapter's explicit pre-fork decision has no child; every
        # other result must belong to the one bound child.
        if not (child_binding is None and native.get('decided_before_fork') is True
                and 'session' not in native):
            if child_binding is None or native.get('session') != child_binding[0]:
                raise ValueError('The completion result does not belong to the bound child.')
            write_yaml_durably(child_binding[1] / 'execution.yml', {**native, 'usage': usage.document()})
            release_liveness(child_binding[1])
        if native.get('outcome') == 'cancelled':
            return adapter.finalize_response({'outcome': 'cancelled'}, False)
        if native.get('outcome') == 'error':
            raise ValueError(native['error'])
        result = parse_check_result(native['output'])
    except Exception as error:
        result = {'status': 'error', 'reason': f'Completion check failed: {error}', 'nodes': []}
    result['usage_summary'] = usage.summary()
    if recovery_failure is not None:
        result['reason'] = (str(result.get('reason') or '')
                            + f' Recovering an earlier unrecorded check failed: {recovery_failure}').strip()
    return adapter.finalize_response(result, context['continued'])
