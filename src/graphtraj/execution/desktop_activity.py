"""Human desktop observation of actual members and their existing native Traces."""
from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_connection import current_parent_connection
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.execution.runner_status import (
    caller_alias, read_alias_mapping, runtime_caller_is_bound, NativeCaller, _status_session,
)
from graphtraj.graph.delivery_state import read_team
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.runtimes.activity import TraceReader, redact
from graphtraj.workspace.runner_project import discover_runner_directory


human_observer: ContextVar[bool] = ContextVar("human_observer", default=False)


_READERS: OrderedDict[tuple[str, str, str], TraceReader] = OrderedDict()


def observe(
    cwd: Path,
    ticket_id: str,
    alias: str | None = None,
    cursor: str | None = None,
) -> dict:
    """Return human project activity or a verified formal Agent's own Session.

    A request can select only a recorded Ticket/member, never a filesystem path
    or caller identity. Existing OS/native identity checks precede any Trace read.
    """
    runner = discover_runner_directory(cwd)
    caller = caller_alias(runner)
    own = None
    if caller is not None and not isinstance(caller, NativeCaller):
        try:
            own = read_alias_mapping(runner, caller)
        except RunnerError as error:
            raise RunnerError('authority-denied', 'Only a verified registered Session may read itself.') from error
        if own[0]['ticket_id'] != ticket_id or alias not in {None, caller}:
            raise RunnerError('authority-denied', 'Agent activity access is limited to its own Session and Ticket.')
    else:
        # A bound Main/unknown native caller is never an unbound human observer.
        if (not human_observer.get() or runtime_caller_is_bound()
                or current_parent_connection() is not None or caller_runtime() is not None
                or caller is not None):
            raise RunnerError('authority-denied', 'Activity requires the human desktop host binding; human observation is unavailable to native Main/unknown callers.')

    configuration = load_project_configuration(cwd)
    if own is not None:
        # Do not enumerate other Teams, members, historical records or Traces.
        aliases = {caller}
        current = {caller}
    else:
        states = _load_states(configuration.state / 'tickets')
        if ticket_id not in states:
            raise ValueError('Choose a registered Ticket.')
        directory, ticket = states[ticket_id]
        aliases = set()
        current = set()
        for team_path in (directory / 'teams').glob('*/team.yml'):
            team = read_team(team_path)
            members = {member['session_ref'] for member in team['members'].values() if member['session_ref']}
            aliases.update(members)
            if team['team_ordinal'] == ticket['active_team_ordinal'] and team['status'] == 'active':
                current.update(members)
        aliases.update(path.name for path in (directory / 'teams').glob('*/traces/*')
                       if (path / 'runner/session.yml').is_file())
    agents = []
    mappings = {}
    for member in sorted(aliases):
        try:
            mapping, session_directory = own if own is not None else read_alias_mapping(runner, member)
            if mapping['ticket_id'] != ticket_id:
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
                           'team': mapping['team_generation']})
        except (RunnerError, OSError, ValueError):
            agents.append({'alias': member, 'historical': member not in current,
                           'state': 'unavailable', 'reason': 'Member evidence is missing or inaccessible.'})
    response = {'ticket_id': ticket_id, 'agents': redact(agents), 'scope': 'self' if own else 'human',
                'updated_at': datetime.now(timezone.utc).isoformat()}
    if alias is None:
        return response
    if alias not in aliases:
        raise ValueError('Choose an actual member of this Ticket.')
    if alias not in mappings:
        return {**response, 'events': [], 'availability': 'unavailable', 'cursor': cursor}
    mapping = mappings[alias]
    key = (str(configuration.harness_root), alias, mapping['session'])
    if key not in _READERS:
        _READERS[key] = TraceReader(Path(mapping['trace_file']), mapping['runtime'], mapping['session'])
    _READERS.move_to_end(key)
    while len(_READERS) > 64:
        _READERS.popitem(last=False)
    page = _READERS[key].page(cursor)
    for event in page['events']:
        event.update(ticket_id=ticket_id, agent=alias, session=mapping['session'])
        if 'usage' in event:
            usage = event['usage']
            usage.update(ticket_id=ticket_id, agent=alias, session=mapping['session'],
                         runtime=mapping['runtime'], model=event.get('model'), time=event.get('time'))
            identity = usage.get('call_id') or usage.get('observation_id')
            if identity:
                usage['identity'] = f"{mapping['runtime']}:{mapping['session']}:{identity}"
    return {**response, **page}
