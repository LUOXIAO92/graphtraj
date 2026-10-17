"""Codex Stop carrier and native context fork for one bound Main."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import ExitStack
import json
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from graphtraj.runtimes.codex.app_server import (
    CHECKER_PERMISSION_PROFILE, CodexAppServer, CodexServerRequest,
)
from graphtraj.runtimes.runtime_adapter import CheckUsage, RuntimeAdapterError
from graphtraj.workspace.runner_project import runtime_executable
from graphtraj.runtimes.codex.session_entry import session_source, event_record
from graphtraj.runtimes.codex.usage import CodexCheckUsage


def control_socket(codex_home: str) -> str:
    """Return the daemon control socket as its resolved target.

    The published socket may be a symlink. The checker's allowance and the
    proxy's connect then name the same path, since a sandbox rule matched on
    the literal symlink would not cover the resolved socket, or vice versa.
    """
    return os.path.realpath(Path(codex_home) / 'app-server-control' / 'app-server-control.sock')


def end_stale_check(binding: dict, child: str) -> dict | None:
    """Interrupt a stale checker's in-progress turn; return facts only if confirmed.

    Returns None when nothing was running or no confirmation arrived; failures raise.
    """
    async def run() -> dict | None:
        async with proxy(binding['connection']) as client:
            active = [turn for turn, status in await client.turn_states(child) if status == 'inProgress']
            if not active:
                return None
            requested_at = time.time()
            await client.interrupt_turn(child, active[0])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if dict(await client.turn_states(child)).get(active[0]) == 'interrupted':
                    return {'interrupted_turn': active[0], 'requested_at': requested_at,
                            'confirmed_at': time.time()}
                await asyncio.sleep(0.1)
            return None

    return asyncio.run(run())  # Read or interrupt failures reach the caller's record.


def proxy(
    connection: dict,
    on_request: Callable[[CodexServerRequest], Awaitable[dict]] | None = None,
) -> CodexAppServer:
    """Connect to the already owning daemon; never start a replacement service."""
    if any(not isinstance(connection.get(k), str) or not connection[k]
           for k in ('session', 'codex_home')):
        raise ValueError('Invalid owning Codex connection.')
    return CodexAppServer(
        cwd=Path.cwd(),
        command=(str(runtime_executable('codex')), 'app-server', 'proxy',
                 '--sock', control_socket(connection['codex_home'])),
        environment={'CODEX_HOME': connection['codex_home']}, experimental_api=True,
        on_request=on_request,
        request_handler_timeout=None,
    )


def verify_main(connection: dict) -> str:
    """Check native root metadata for the Session captured by the caller boundary."""
    async def read() -> str:
        """Read metadata through the existing host, without reading conversation turns."""
        async with proxy(connection) as client:
            thread = await client.read_thread(connection['session'])
            if session_source(thread) != 'main':
                raise RuntimeAdapterError('authority-denied', 'A child or unknown native source cannot bind Main Stop.')
            hook_session = thread.get('sessionId')
            if not isinstance(hook_session, str) or not hook_session:
                raise ValueError('The native hook Session identity is unavailable.')
            if 'hook_session' in connection and connection['hook_session'] != hook_session:
                raise ValueError('Codex lifecycle event belongs to a different native Session.')
            connection['hook_session'] = hook_session
            return thread['id']
    return asyncio.run(read())


def hook(path: Path, binding: dict) -> dict:
    """Return Session-scoped adoption material without installing or trusting it."""
    command = shlex.join([
        sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook',
    ])
    messages = {
        'SessionStart': 'GraphTraj: associating Main session',
        'Stop': 'GraphTraj: checking task completion',
        'SessionEnd': 'GraphTraj: retaining Main session',
    }
    return {'hooks': {
        event: [{'hooks': [{'type': 'command', 'command': command, 'statusMessage': message}]}]
        for event, message in messages.items()
    }}


def event_context(binding: dict, event: dict) -> dict | None:
    """Confirm Main's exact native turn, ignoring other lifecycle events."""
    if event.get('hook_event_name') != 'Stop' or event.get('session_id') != binding['connection']['hook_session']:
        return None
    if not isinstance(event.get('turn_id'), str) or not event['turn_id']:
        raise ValueError('Stop did not identify its native turn.')
    if type(event.get('stop_hook_active')) is not bool:
        raise ValueError('Stop did not identify continuation state.')
    if not isinstance(event.get('model'), str) or not event['model']:
        raise ValueError('Stop did not identify its actual native model.')

    async def belongs_to_main() -> bool:
        """A fork shares session_id; the exact native Main turn owns this Stop."""
        async with proxy(binding['connection']) as client:
            return await client.is_current_turn(binding['session'], event['turn_id'])

    if not asyncio.run(belongs_to_main()):
        return None
    context = {'turn': event['turn_id'], 'continued': event['stop_hook_active'],
               'model': event['model']}
    if event.get('transcript_path'):
        metadata, settings = event_record(event)
        if metadata['id'] != binding['session'] or session_source(metadata) != 'main':
            raise ValueError('The Stop transcript does not belong to the bound Main.')
        if settings.get('model') != event['model']:
            raise ValueError('The Stop model conflicts with its native turn settings.')
        context['settings'] = settings
        context['transcript_path'] = event['transcript_path']
    return context


def response(result: dict | None, continued: bool) -> dict:
    """Return one layered Stop message; repeated checker errors cannot self-continue forever.

    The message keeps an English title with its status token, the checker's own
    conclusion and reason, related Tasks, and this check's compact usage on
    separate lines without blank separators. A mechanical failure that never
    reached a checker conclusion falls back to fixed English, since the checker
    language is unknown; all four statuses still produce exactly one message.
    A normally cancelled execution has no task verdict and emits no chat entry.
    """
    if result is None:
        return {}
    if result.get('outcome') == 'cancelled':
        return {}
    status = result['status']
    conclusions = {
        'completed': 'Main may end this turn: the task is complete.',
        'waiting': 'Main may end this turn: the task is still pending.',
        'actionable': 'Main must continue this turn.',
        'error': 'Unable to determine whether Main may end this turn: check failure.',
    }
    conclusion = str(result.get('conclusion') or conclusions[status]).strip()
    lines = [f'Completion Check · {status}',
             f'Conclusion · {conclusion}',
             f'Reason · {result["reason"].strip()}']
    if result['nodes']:
        lines.append('Related · ' + ', '.join(dict.fromkeys(result['nodes'])))
    if result.get('usage_summary'):
        lines.append('Reviewer Usage · This Check · ' + result['usage_summary'])
    message = '\n'.join(lines)
    # Codex renders each of these fields as a separate hook entry. The block
    # reason is already both visible feedback and the same Main's continuation.
    if status in ('completed', 'waiting'):
        return {'systemMessage': message}
    if status == 'actionable':
        return {'decision': 'block', 'reason': message}
    return {'continue': False, 'stopReason': message}


async def _owned_request_result(binding: dict) -> dict | None:
    """Return an actionable result when Main's own direct child awaits Main.

    A pending native request needs Main's reply, and a latest-Round result of
    Main's own root Session needs Main's decision, so no checker is needed.
    Unreadable Runner or result evidence is not proof of neither; the full
    check decides. An empty mapping marks this unreadable case and forbids reuse.
    """
    from graphtraj.execution.runner_control import owned_root_requests, owned_root_undecided_results
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.workspace.runner_project import discover_runner_directory

    root = Path(binding['cwd'])
    try:
        owned = await asyncio.to_thread(owned_root_requests, discover_runner_directory(root), binding['connection'])
        if owned:
            pending = '; '.join(f"{mapping['alias']} awaits {request.get('method')} request {request.get('request_id')}"
                                for mapping, request in owned)
            reason = f"Main's direct child Session needs its native reply; no checker ran. {pending}."
        else:
            owned = await asyncio.to_thread(owned_root_undecided_results, root, binding['connection'])
            submitted = '; '.join(f"{mapping['alias']} submitted {submission['candidate']}"
                                  for mapping, submission in owned)
            reason = f'Main must decide this result; no checker ran. {submitted}.'
    except (RunnerError, OSError, ValueError, KeyError, TypeError):
        return {}
    if not owned:
        return None
    return {'outcome': 'completed', 'decided_before_fork': True,
            'usage': CheckUsage(0, 0, 0, 0, 0, 0), 'output': json.dumps({
        'status': 'actionable', 'conclusion': 'Main must continue this turn.', 'reason': reason,
        'nodes': sorted({mapping['task_id'] for mapping, _ in owned}),
    })}


def completion_boundary(binding: dict, context: dict) -> str | None:
    """Fingerprint native history, Task facts and actual execution activity.

    Hook/usage telemetry does not change model input. Native response items,
    compaction and turn settings do. Without a readable native history or Task
    projection, do a fresh check instead of treating missing evidence as equal.
    """
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.graph.task_index import read_index
    from graphtraj.execution.runner_status import NativeCaller, runtime_caller, status_tree
    from graphtraj.workspace.runner_project import discover_runner_directory

    transcript = context.get('transcript_path')
    if not transcript:
        return None
    try:
        digest = hashlib.sha256()
        with Path(transcript).open(encoding='utf-8') as stream:
            for line in stream:
                record = json.loads(line)
                if (record.get('type') in {'response_item', 'compacted', 'turn_context'}
                        or (record.get('type') == 'event_msg'
                            and record.get('payload', {}).get('type') == 'user_message')):
                    digest.update(line.encode())
        project = load_project_configuration(Path(binding['cwd']))
        index = read_index(project.state)
        with runtime_caller(discover_runner_directory(Path(binding['cwd'])),
                            NativeCaller(binding['session'], binding['connection'])):
            status = status_tree(Path(binding['cwd']))
        if not status.succeeded:
            return None
        agents = status.document['agents']
        if any(agent.get('activity') not in ('running', 'idle') for agent in agents):
            return None  # An unconfirmed execution cannot justify an old release.
        activities = [{key: agent[key] for key in (
            'alias', 'parent', 'children', 'session', 'execution_id',
            'activity', 'last_outcome', 'retire_status',
        ) if key in agent} for agent in agents]
        settings = {key: value for key, value in context.get('settings', {}).items()
                    if key != 'check_usage_baseline'}
        digest.update(json.dumps({
            'context': {**{key: value for key, value in context.items() if key != 'continued'},
                        'settings': settings},
            'summary_issue': binding['summary_issue'], 'tasks': index, 'agents': activities,
        }, sort_keys=True).encode())
        return digest.hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def previous_result(directory: Path, boundary: str | None) -> dict | None:
    """Reuse only a validated successful result for exactly this boundary."""
    import yaml
    from graphtraj.execution.main_finalize import parse_check_result

    if boundary is None:
        return None
    # ponytail: reuse existing execution evidence; index it only if this scan
    # becomes material for a long-lived Main with many retained checks.
    for path in directory.glob('checks/*/execution.yml'):
        native = yaml.safe_load(path.read_text(encoding='utf-8'))
        if native.get('completion_boundary') != boundary or native.get('outcome') != 'completed':
            continue
        try:
            result = parse_check_result(native['output'])
        except (ValueError, KeyError, TypeError):
            continue
        if result['status'] != 'error':
            return result
    return None


def check(
    binding: dict,
    context: dict,
    prompt: str,
    created: Callable[[str], None],
) -> dict[str, Any] | None:
    """Fork native context, bind the returned child and append only its check task."""
    async def run(resources: ExitStack) -> dict | None:
        """Keep the child owned until terminal; inherited hooks filter its distinct ID."""
        child_id: str | None = None
        approvals: dict = {}

        def resolve(notice: dict) -> None:
            """Mark a checker approval its native owner has resolved."""
            params = notice.get('params', {})
            if notice.get('method') == 'serverRequest/resolved' and params.get('requestId') in approvals:
                approvals[params['requestId']]['resolved'] = True

        async def handle(request: CodexServerRequest) -> dict:
            """Expose only read-only GraphTraj task summaries to this exact checker."""
            from graphtraj.interfaces.gateway import handle_request
            from graphtraj.execution.runner_status import runtime_caller
            from graphtraj.workspace.runner_project import discover_runner_directory

            if child_id is None or request.params.get('threadId') != child_id:
                # Subscribing to Main can replay its pending native requests.
                # Its UI owns the response; serverRequest/resolved or connection
                # shutdown cancels this observer without answering on its behalf.
                await asyncio.Future()
            if request.method.endswith('/requestApproval'):
                # The checker's request belongs to the same owner, or its
                # configured reviewer, as Main's. Resolution or shutdown
                # cancels this observer; the check limit still bounds it.
                approvals[request.request_id] = {'request_id': request.request_id,
                                                 'method': request.method, 'resolved': False}
                await asyncio.Future()
            if (request.method != 'item/tool/call'
                    or request.params.get('tool') != 'graphtraj'):
                raise RuntimeAdapterError('authority-denied', 'The checker cannot approve or control work.')

            def call() -> dict:
                """Keep the fork's caller identity separate from the root Main."""
                root = Path(binding['cwd'])
                with runtime_caller(discover_runner_directory(root), child_id):
                    result = handle_request(request.params.get('arguments', {}), cwd=root,
                                            allowed_features={'task_graph', 'alias_status'})
                return {'contentItems': [{'type': 'inputText', 'text': json.dumps(result.document)}],
                        'success': not result.failed}
            return await asyncio.to_thread(call)

        async with proxy(binding['connection'], handle) as client:
            parent = await client.read_thread(binding['session'])
            if not await client.is_current_turn(binding['session'], context['turn']):
                return None
            configuration = await client.subscribe_host(binding['session'])
            # Hook model is the active turn's slug; Thread.model is configuration,
            # and can differ from actual per-turn model selection.
            parent = {**parent, 'model': context['model'], 'configuration': configuration}
            parent['turn_settings'] = dict(context.get('settings', {}))
            # Main's own daemon socket, which the checker's CLI must reach.
            parent['control_socket'] = control_socket(binding['connection']['codex_home'])
            if 'effort' not in parent['turn_settings'] and 'reasoningEffort' in configuration:
                parent['turn_settings']['effort'] = configuration['reasoningEffort']
            # Register this attempt before requesting its fixed native fork:
            # new input during the request also invalidates the pending check.
            # Distinct addresses keep older sends away from later same-turn checks.
            from graphtraj.execution.main_finalize import session_binding

            directory = session_binding(Path(binding['cwd']), 'codex', binding['session']).parent
            pending = Path(resources.enter_context(tempfile.TemporaryDirectory(
                prefix='pending-', dir=directory,
            )))
            if os.name != 'nt':
                # Held for this attempt; the kernel releases it on any exit.
                from graphtraj import file_lock

                held = os.open(pending, os.O_RDONLY)
                resources.callback(os.close, held)
                file_lock.flock(held, file_lock.LOCK_EX)
            (pending / 'turn').write_text(context['turn'] + '\n', encoding='utf-8')

            def receipt() -> dict | None:
                """Read a send appended only after native acceptance of this turn."""
                lines = (pending / 'turn').read_text(encoding='utf-8').splitlines()
                if len(lines) < 2:
                    return None
                try:
                    return json.loads(lines[1])
                except json.JSONDecodeError:
                    # The sender appends to this file only after native success.
                    # A concurrent write need not delay cancellation for timing data.
                    return {'turn': context['turn'], 'submitted_at': None, 'accepted_at': None}

            gated = await _owned_request_result(binding)
            if gated:
                # A verdict for a superseded Main turn is never returned.
                if (not await client.is_current_turn(binding['session'], context['turn'])
                        or receipt() is not None):
                    return {'outcome': 'cancelled', 'decided_before_fork': True,
                            'usage': CheckUsage(0, 0, 0, 0, 0, 0)}
                return gated
            boundary = completion_boundary(binding, context) if gated is None else None
            reused = previous_result(directory, boundary)
            if reused is not None:
                if (not await client.is_current_turn(binding['session'], context['turn'])
                        or receipt() is not None
                        or completion_boundary(binding, context) != boundary):
                    return {'outcome': 'cancelled', 'decided_before_fork': True,
                            'usage': CheckUsage(0, 0, 0, 0, 0, 0)}
                if reused['status'] in ('completed', 'waiting'):
                    return None  # Already displayed; no second verdict or wakeup.
                return {'outcome': 'completed', 'decided_before_fork': True,
                        'usage': CheckUsage(0, 0, 0, 0, 0, 0), 'output': json.dumps(reused)}
            child = await client.fork_session(parent)
            child_id = child.thread_id
            created(child_id)
            from graphtraj.configuration.project_configuration import load_project_configuration
            from graphtraj.interfaces.agents import configured_archive
            from graphtraj.runtimes.codex.jsonl_archive import CodexJsonlArchive

            project = load_project_configuration(Path(binding['cwd']))
            archive = configured_archive(project.harness_root)
            if child.rollout_path is not None:
                trace = directory / 'checks' / hashlib.sha256(child_id.encode()).hexdigest() / 'events.jsonl'
                client.retain_native_trace(child, trace, archive=CodexJsonlArchive(
                    archive, 'checker:' + child_id, child_id, child.rollout_path, new_session=True,
                ))
            else:
                await client.retain_ordered_history(child, archive, 'checker:' + child_id)
            usage = CodexCheckUsage(child.rollout_path, child_id,
                                    parent['turn_settings'].get('check_usage_baseline'))
            evidence = {
                'session': child_id, 'parent': binding['session'], 'parent_turn': context['turn'],
                'model': parent['model'], 'provider': parent['modelProvider'],
                'configuration': child.configuration,
                'parent_configuration': {key: configuration[key] for key in child.configuration
                                         if key != 'thread' and key in configuration},
            }
            profile = child.configuration.get('activePermissionProfile') or {}
            if profile.get('id') == CHECKER_PERMISSION_PROFILE:
                # The checker's authorized difference from Main: managed network.
                evidence['authorized_difference'] = {
                    'permission_profile': profile, 'unix_socket': parent['control_socket'],
                    'network_access': {
                        'main': (configuration.get('sandbox') or {}).get('networkAccess'),
                        'checker': (child.configuration.get('sandbox') or {}).get('networkAccess'),
                    },
                }

            # Stop's turn is still in progress, so native lastTurnId is invalid.
            # The fork itself fixes its history boundary. Reject a superseding
            # Main turn before starting any model request against that snapshot.
            if not await client.is_current_turn(binding['session'], context['turn']):
                return {**evidence, 'outcome': 'cancelled', 'usage': usage.finish('')}
            if (accepted := receipt()) is not None:
                return {**evidence, 'outcome': 'cancelled', 'cancellation': accepted,
                        'usage': usage.finish('')}
            try:
                execution = await client.start_execution(child, prompt)
            except Exception as error:
                return {**evidence, 'outcome': 'error', 'error': str(error), 'usage': usage.finish('')}

            async def main_stopped() -> None:
                """Observe the owning turn's native stop without polling or waking it."""
                while True:
                    notice = await client.next_notification()
                    usage.observe(notice)
                    resolve(notice)
                    params = notice.get('params', {})
                    if params.get('threadId') != binding['session']:
                        continue
                    if notice.get('method') == 'thread/closed':
                        return
                    if notice.get('method') == 'turn/completed':
                        return
                    if notice.get('method') == 'turn/started' and params.get('turn', {}).get('id') != context['turn']:
                        return

            stopped = asyncio.create_task(main_stopped())
            checked = asyncio.create_task(client.wait(execution, timeout=540))

            async def input_received() -> dict:
                """Wait for an acknowledged send targeting this exact snapshot."""
                while True:
                    if (accepted := receipt()) is not None:
                        return accepted
                    await asyncio.sleep(0.05)

            received = asyncio.create_task(input_received())

            async def cancel_execution() -> None:
                """Confirm termination even if completion raced with cancellation."""
                try:
                    await client.interrupt(execution)
                except RuntimeAdapterError:
                    # A terminal result proves no execution remains to interrupt.
                    # A failed wait still exposes the cleanup failure to the caller.
                    await client.wait(execution, timeout=10)
                else:
                    await client.wait(execution, timeout=10)

            outcome = 'completed'
            failure = None
            result = {}
            try:
                # Leave time for native cancellation before the default 600s hook deadline.
                finished, _ = await asyncio.wait((stopped, checked, received), return_when=asyncio.FIRST_COMPLETED)
                accepted = receipt()
                if stopped in finished or received in finished or accepted is not None:
                    if received in finished:
                        evidence['cancellation'] = received.result()
                    elif accepted is not None:
                        evidence['cancellation'] = accepted
                    else:
                        stopped.result()
                    await cancel_execution()
                    if 'cancellation' in evidence:
                        evidence['cancellation']['confirmed_at'] = time.time()
                    outcome = 'cancelled'
                else:
                    result = checked.result()
            except BaseException as error:
                try:
                    await cancel_execution()
                except RuntimeAdapterError as cleanup_error:
                    error.add_note(f'Checker cancellation: {cleanup_error}')
                if not isinstance(error, Exception):
                    raise
                outcome = 'error'
                failure = str(error)
            finally:
                stopped.cancel()
                checked.cancel()
                received.cancel()
                await asyncio.gather(stopped, checked, received, return_exceptions=True)
                for notice in client.drain_notifications():
                    usage.observe(notice)
                    resolve(notice)
            try:
                if (not await client.is_current_turn(binding['session'], context['turn'])
                        and outcome != 'error'):
                    outcome = 'cancelled'
                if outcome != 'error' and (accepted := receipt()) is not None:
                    evidence.setdefault('cancellation', accepted)
                    outcome = 'cancelled'
            except Exception as error:
                outcome = 'error'
                failure = failure or str(error)
            if outcome == 'completed' and result.get('outcome') != 'completed':
                outcome = 'error'
                failure = 'Completion checker was interrupted.'
            current_boundary = completion_boundary(binding, context)
            if boundary is not None and current_boundary == boundary:
                evidence['completion_boundary'] = boundary
            elif boundary is not None and current_boundary is not None and outcome != 'error':
                outcome = 'cancelled'
                evidence.setdefault('cancellation', {
                    'reason': 'Native input or Task facts changed during the completion check.',
                })
            observed_usage = usage.finish(execution.turn_id)
            return {**evidence, 'output': result.get('last_agent_message'),
                    'approval_requests': list(approvals.values()),
                    'outcome': outcome, 'error': failure, 'turn': execution.turn_id,
                    'usage': observed_usage, 'response_usage': usage.response_evidence(execution.turn_id)}
    with ExitStack() as resources:
        return asyncio.run(run(resources))
