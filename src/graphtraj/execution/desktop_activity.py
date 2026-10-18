"""Human desktop observation of actual members and their existing native Traces."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration, ProjectConfiguration
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_connection import current_parent_connection
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.execution.runner_status import (
    caller_alias, read_alias_mapping, runtime_caller_is_bound, NativeCaller, _status_session,
)
from graphtraj.graph.delivery_state import read_team
from graphtraj.graph.task_graph import _load_states
from graphtraj.runtimes.activity import TraceReader, redact
from graphtraj.workspace.runner_project import discover_runner_directory, discover_project_root


human_observer: ContextVar[bool] = ContextVar("human_observer", default=False)


# Readers keep source bindings only; portable checkpoints carry authenticated offsets.
_READERS: dict[tuple[str, ...], TraceReader] = {}


def observe(
    cwd: Path,
    task_id: str | None = None,
    alias: str | None = None,
    cursor: str | None = None,
) -> dict:
    """Return human project activity or a verified formal Agent's own Session.

    A request can select only a recorded Task/member, never a filesystem path
    or caller identity. Existing OS/native identity checks precede any Trace read.
    """
    runner = discover_runner_directory(cwd)
    from graphtraj.interfaces.desktop_host import owns_project

    window = human_observer.get() and owns_project(cwd)
    caller = None if window else caller_alias(runner)
    own = None
    if caller is not None and not isinstance(caller, NativeCaller):
        try:
            own = read_alias_mapping(runner, caller)
        except RunnerError as error:
            raise RunnerError('authority-denied', 'Only a verified registered Session may read itself.') from error
        if own[0]['task_id'] != task_id or alias not in {None, caller}:
            raise RunnerError('authority-denied', 'Agent activity access is limited to its own Session and Task.')
    else:
        # A bound Main/unknown native caller is never an unbound human observer.
        if not window and (not human_observer.get() or runtime_caller_is_bound()
                or current_parent_connection() is not None or caller_runtime() is not None
                or caller is not None):
            raise RunnerError('authority-denied', 'Activity requires the human desktop host binding; human observation is unavailable to native Main/unknown callers.')

    configuration = load_project_configuration(cwd)
    if task_id is None:
        return project_activity(cwd, runner, configuration, alias, cursor)
    if own is not None:
        # Do not enumerate other Teams, members, historical records or Traces.
        aliases = {caller}
        current = {caller}
    else:
        states = _load_states(configuration.state / 'tasks')
        if task_id not in states:
            raise ValueError('Choose a registered Task.')
        aliases, current = _task_aliases(*states[task_id])
    agents = []
    mappings = {}
    for member in sorted(aliases):
        try:
            mapping, session_directory = own if own is not None else read_alias_mapping(runner, member)
            if mapping['task_id'] != task_id:
                continue
            mappings[member] = mapping
            retired = not (session_directory / 'mapping.yml').is_file()
            historical = member not in current or retired
            model = None
            try:
                launch = yaml.safe_load((session_directory / 'launch.yml').read_text())
                model = launch.get('context_evidence', {}).get('model')
            except (OSError, ValueError, AttributeError, yaml.YAMLError):
                pass
            state = {'activity': 'retired'} if retired else _status_session(
                mapping, session_directory, member, respond_to_abnormal=False,
            )
            agents.append({'alias': member, 'parent': mapping['parent'], 'runtime': mapping['runtime'],
                           'model': model, 'session': mapping['session'], 'historical': historical,
                           'state': state.get('activity'), 'last_outcome': state.get('last_outcome'),
                           'team': mapping['team_generation'],
                           'source': str(Path(mapping['trace_file']).resolve())})
        except (RunnerError, OSError, ValueError):
            agents.append({'alias': member, 'historical': member not in current,
                           'state': 'unavailable', 'reason': 'Member evidence is missing or inaccessible.'})
    response = {'task_id': task_id, 'agents': redact(agents), 'scope': 'self' if own else 'human',
                'updated_at': datetime.now(timezone.utc).isoformat()}
    if alias is None:
        return response
    if alias not in aliases:
        raise ValueError('Choose an actual member of this Task.')
    if alias not in mappings:
        return {**response, 'events': [], 'availability': 'unavailable', 'cursor': cursor}
    mapping = mappings[alias]
    return {**response, **read_page(configuration.harness_root, mapping, alias, task_id, cursor)}


def _task_aliases(directory: Path, task: dict) -> tuple[set[str], set[str]]:
    """Return every recorded member alias of one Task and those of its active Team.

    Seats name members; retained Trace records add members that left a seat.
    """
    aliases = set()
    current = set()
    for team_path in (directory / 'teams').glob('*/team.yml'):
        team = read_team(team_path)
        members = {member['session_ref'] for member in team['members'].values() if member['session_ref']}
        aliases.update(members)
        if team['team_ordinal'] == task['active_team_ordinal'] and team['status'] == 'active':
            current.update(members)
    aliases.update(path.name for path in (directory / 'teams').glob('*/traces/*')
                   if (path / 'runner/session.yml').is_file())
    return aliases, current


def task_members(cwd: Path, summary_task_id: str | None = None) -> dict:
    """List the member Agents of current summary Tasks or of one chosen summary.

    By default the scope is every unfinished summary Task (an active Task with
    children, or a top-level one, that is not integrated) and its recursive
    child Tasks; retired members are omitted. ``summary_task_id`` selects one
    Task and its recursive children regardless of completion and also lists
    retired members as history. Reading changes no identity or state.

    Returns
    -------
    ``scope`` names the selected summary Task IDs. Each ``members`` entry has
    ``alias``, ``task_id``, ``team``, ``role``, ``runtime``, the actual Agent
    ``parent``, ``state`` (``active`` or ``standby``; ``None`` once retired),
    ``last_outcome``, ``historical`` and ``retired``. An activity other than
    running or idle is kept as the ``diagnostic`` of that two-state view.
    """
    from graphtraj.graph.task_index import read_index

    configuration = load_project_configuration(cwd)
    runner        = discover_runner_directory(cwd)
    records       = read_index(configuration.state)['tasks']
    children: dict[str, list[str]] = {key: [] for key in records}
    for key, record in records.items():
        if record['parent_id'] is not None:
            children[record['parent_id']].append(key)

    if summary_task_id is None:
        roots = [key for key, record in records.items()
                 if record['active'] and record['status'] != 'integrated'
                 and (children[key] or record['parent_id'] is None)]
    elif summary_task_id in records:
        roots = [summary_task_id]
    else:
        raise ValueError('Choose a registered Task.')

    # Recursive child Tasks share their summary's member view.
    scope   = set()
    pending = list(roots)
    while pending:
        key = pending.pop()
        if key not in scope:
            scope.add(key)
            pending.extend(children[key])

    states  = _load_states(configuration.state / 'tasks') if scope else {}
    members = []
    for task_id in sorted(scope, key=int):
        aliases, current = _task_aliases(*states[task_id])
        for member in sorted(aliases):
            try:
                mapping, session_directory = read_alias_mapping(runner, member)
            except RunnerError:
                continue
            if mapping['task_id'] != task_id:
                continue
            retired = not (session_directory / 'mapping.yml').is_file()
            if retired and summary_task_id is None:
                continue
            entry = {'alias': member, 'task_id': task_id, 'team': mapping['team_generation'],
                     'role': mapping['role'], 'runtime': mapping['runtime'],
                     'parent': mapping['parent'], 'state': None, 'last_outcome': None,
                     'historical': retired or member not in current, 'retired': retired}
            if not retired:
                status = _status_session(mapping, session_directory, member, respond_to_abnormal=False)
                activity = status.get('activity')
                # An owner holding its execution without answering is still active.
                entry['state'] = 'active' if activity in {'running', 'unreachable'} else 'standby'
                entry['last_outcome'] = status.get('last_outcome')
                if activity not in {'running', 'idle'}:
                    entry['diagnostic'] = activity
            members.append(entry)
    return {'scope': sorted(roots, key=int), 'explicit': summary_task_id is not None,
            'members': members}


# The project inventory is shared by bounded pages, not rediscovered per Agent.
_PROJECT_MEMBERS: dict[str, dict[str, str | None]] = {}


def project_activity(
    cwd: Path,
    runner: Path,
    configuration: ProjectConfiguration,
    alias: str | None,
    cursor: str | None,
) -> dict:
    """List associated Main and members or read one selected source for a human.

    Only project-owned bindings are enumerated. No Runtime Home discovery or
    credential access is involved. Missing historical associations stay unknown.
    """
    root = configuration.harness_root
    key = str(root)
    response = {'task_id': None, 'agents': [], 'scope': 'human',
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'notices': ['Main history without a verified source and recorded project is not covered.']}
    mains = {}
    for path in (runner / 'main-sessions').glob('*/session.yml'):
        try:
            binding = yaml.safe_load(path.read_text(encoding='utf-8'))
            if binding.get('cwd') != str(root):
                continue
            name = f"Main:{binding['runtime']}:{binding['session']}"
            mains[name] = binding
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            response['notices'].append('Some Main associations are unreadable.')
    if alias is None:
        members = {}
        tasks = configuration.state / 'tasks'
        for task in _load_states(tasks) if tasks.exists() else {}:
            page = observe(cwd, task)
            for agent in page['agents']:
                members[agent['alias']] = task
                response['agents'].append({**agent, 'task_id': task, 'kind': 'member'})
        member_sessions = {(agent.get('runtime'), agent.get('session')) for agent in response['agents']}
        for name, binding in mains.items():
            if (binding['runtime'], binding['session']) in member_sessions:
                continue
            members[name] = None
            response['agents'].append({
                'alias': name, 'kind': 'main', 'task_id': None,
                'runtime': binding['runtime'], 'session': binding['session'],
                'historical': False, 'state': 'associated',
                'source': binding.get('activity', {}).get('trace_file'),
            })
        _PROJECT_MEMBERS[key] = members
        return redact(response)
    if key not in _PROJECT_MEMBERS:
        project_activity(cwd, runner, configuration, None, None)
    if alias not in _PROJECT_MEMBERS[key]:
        raise ValueError('Choose an associated Main or actual project member.')
    if alias in mains:
        binding = mains[alias]
        source = binding.get('activity', {}).get('trace_file')
        if not source:
            return {**response, 'events': [], 'availability': 'unavailable',
                    'reason': 'Main has no readable native source association; history is not covered.'}
        mapping = {**binding, 'trace_file': source}
        page = read_page(root, mapping, alias, None, cursor, main=True)
    else:
        mapping, _ = read_alias_mapping(runner, alias)
        task = _PROJECT_MEMBERS[key][alias]
        if mapping['task_id'] != task:
            raise ValueError('Project membership changed; refresh the Agent list.')
        page = read_page(root, mapping, alias, task, cursor)
    return {**response, **page}


def read_page(
    root: Path,
    mapping: dict,
    alias: str,
    task_id: str | None,
    cursor: str | None,
    *,
    main: bool = False,
) -> dict:
    """Normalize a recorded source before applying Main's per-record project scope."""
    source = Path(mapping['trace_file']).resolve()
    key = (str(root), mapping['runtime'], mapping['session'], str(source))
    if key not in _READERS:
        _READERS[key] = TraceReader(source, mapping['runtime'], mapping['session'])
    page = _READERS[key].page(cursor)
    projects = {}
    events = []
    excluded = 0
    for event in page['events']:
        if main:
            cwd = event.get('cwd')
            if (not isinstance(cwd, str)
                    or event.get('native_session') != mapping['session']
                    or event.get('source_kind') != 'main'):
                excluded += 1
                continue
            if cwd not in projects:
                try:
                    projects[cwd] = discover_project_root(Path(cwd)) if Path(cwd).is_absolute() else None
                except (OSError, ValueError, RunnerError):
                    projects[cwd] = None
            if projects[cwd] != root:
                excluded += 1
                continue
        event.update(task_id=task_id, agent=alias, session=mapping['session'])
        if 'usage' in event:
            usage = event['usage']
            usage.update(task_id=task_id, agent=alias, session=mapping['session'],
                         runtime=mapping['runtime'], model=event.get('model'), time=event.get('time'))
            identity = usage.get('call_id') or usage.get('observation_id')
            if identity:
                usage['identity'] = f"{mapping['runtime']}:{mapping['session']}:{identity}"
        events.append(event)
    page['events'] = events
    if excluded:
        page['notices'] = ['Native records belonging elsewhere or without a recorded project were excluded.']
    return page
