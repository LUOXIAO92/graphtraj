"""Incremental finish-check facts from Codex's existing native rollout."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from graphtraj.runtimes.runtime_adapter import CheckUsage, RuntimeAdapterError

if TYPE_CHECKING:
    from graphtraj.runtimes.codex.app_server import CodexAppServer


async def latest_check_usage(client: CodexAppServer, association: dict) -> dict:
    """Project usage and bounded identity/settings facts from Main's latest check.

    This existing parent-status observation never returns conversation, tool
    arguments, checker output or raw native configuration. It can diagnose checks
    made before usage diagnostics were retained in their execution result.
    """
    if association.get('status') != 'matching':
        return {'status': 'association-unavailable'}
    try:
        binding = Path(association['binding_path'])
        completed = list(binding.parent.glob('checks/*/execution.yml'))
        if not completed:
            return {'status': 'no-completed-check'}
        latest = max(completed, key=lambda path: path.stat().st_mtime_ns)
        child = yaml.safe_load(latest.with_name('session.yml').read_text())
        owner = yaml.safe_load(binding.read_text())
        if child.get('runtime') != 'codex' or child.get('parent') != owner.get('session'):
            return {'status': 'association-mismatch'}
        execution = yaml.safe_load(latest.read_text())
        if execution.get('session') == child['session'] and 'response_usage' in execution:
            if execution.get('parent') != owner.get('session'):
                return {'status': 'association-mismatch'}
            configuration = execution.get('configuration', {})
            return {'status': 'observed', 'session': child['session'],
                    'parent': execution['parent'], 'parent_turn': execution.get('parent_turn'),
                    'turn': execution.get('turn'), 'usage': execution.get('usage'),
                    'response_usage': execution['response_usage'],
                    'configuration': configuration_facts(configuration),
                    'parent_configuration': configuration_facts(execution.get('parent_configuration', {})),
                    'native_identity': {key: configuration.get('thread', {})[key] for key in (
                        'id', 'sessionId', 'forkedFromId', 'ephemeral', 'historyMode', 'cliVersion',
                    ) if key in configuration.get('thread', {})},
                    'outcome': execution.get('outcome')}
        thread = await client.read_thread(child['session'])
        state = await client.read_host_status(child['session'])
        turn = state.get('turn') or {}
        path = thread.get('path')
        result = {'session': child['session'], 'turn': turn.get('id'),
                  'path_available': isinstance(path, str), 'status': 'usage-unavailable'}
        if not isinstance(path, str) or not turn.get('id'):
            return result
        phases = {name: {'token_count_events': 0, 'info_fields': [], 'totals': {},
                         'usage_event_types': {}, 'payload_fields': []}
                  for name in ('before_turn', 'in_turn', 'after_completion')}
        phase = 'before_turn'
        identity = None
        matched = False
        with Path(path).open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    break
                record = json.loads(line)
                payload = record.get('payload', {})
                kind = record.get('type')
                if kind == 'session_meta':
                    identity = payload.get('id')
                if (kind == 'turn_context' or (kind == 'event_msg' and payload.get('type') == 'task_started')):
                    if payload.get('turn_id') == turn['id']:
                        phase = 'in_turn'
                        matched = True
                    elif matched:
                        break
                event = payload.get('type', '')
                if kind == 'event_msg' and ('token' in event.lower() or 'usage' in event.lower()):
                    facts = phases[phase]
                    facts['usage_event_types'][event] = facts['usage_event_types'].get(event, 0) + 1
                    facts['payload_fields'] = sorted(payload)
                if kind == 'event_msg' and event == 'token_count':
                    facts = phases[phase]
                    facts['token_count_events'] += 1
                    info = payload.get('info')
                    if isinstance(info, dict):
                        facts['info_fields'] = sorted(info)
                    total = _total(record)
                    if total is not None:
                        facts['totals'] = {key: value for key, value in total.items()
                                           if type(value) is int}
                if (kind == 'event_msg' and payload.get('type') == 'task_complete'
                        and payload.get('turn_id') == turn['id']):
                    phase = 'after_completion'
        return {**result, 'status': 'observed', 'session_matches': identity == child['session'],
                'turn_found': matched, 'completion_found': phase == 'after_completion',
                'phases': phases}
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, RuntimeAdapterError) as error:
        return {'status': 'unavailable', 'error_type': type(error).__name__}


def configuration_facts(configuration: dict) -> dict:
    """Allowlist settings and fingerprint paths/permission details without disclosure.

    Fingerprints compare recorded values; they do not prove instruction contents
    or reconstruct missing settings. Absent fields remain absent, null stays null.
    """
    facts = {key: configuration[key] for key in (
        'model', 'modelProvider', 'serviceTier', 'reasoningEffort',
        'approvalPolicy', 'approvalsReviewer',
    ) if key in configuration}
    for key in ('cwd', 'runtimeWorkspaceRoots', 'instructionSources', 'sandbox',
                'activePermissionProfile', 'disabledPluginIds'):
        if key in configuration:
            value = configuration[key]
            facts[key + '_sha256'] = None if value is None else hashlib.sha256(
                json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')
            ).hexdigest()
    return facts


def tool_call_id(payload: dict) -> str | None:
    """Identify native requests, sharing the Session operation counter's rules."""
    kind = payload.get('type')
    if kind in {'function_call', 'custom_tool_call'}:
        value = payload.get('call_id')
    elif kind in {'local_shell_call', 'tool_search_call'}:
        value = payload.get('call_id') or payload.get('id')
    elif kind in {'web_search_call', 'image_generation_call'}:
        value = payload.get('id')
    else:
        return None
    return value if isinstance(value, str) and value else None


def _total(record: dict) -> dict | None:
    """Read only an explicit native lifetime token snapshot."""
    payload = record.get('payload', {})
    if record.get('type') != 'event_msg' or payload.get('type') != 'token_count':
        return None
    info = payload.get('info')
    total = info.get('total_token_usage') if isinstance(info, dict) else None
    return total if isinstance(total, dict) else None


class CodexCheckUsage:
    """Collect current-check usage from live notifications or appended records.

    Codex total_token_usage is cumulative across inherited history; last usage
    can be replayed with rate-limit updates and has no independent request ID.
    Subtract observed baseline fields. When a fork omits that baseline, sum
    native last_token_usage only after new model output in this turn, deduping
    cumulative snapshots. A pre-output replay is not a current request.
    output_tokens already includes reasoning_output_tokens: expose reasoning
    separately without adding it to output. Exact response notifications or
    token_usage_record IDs take precedence over cumulative representations.
    Missing/unreadable telemetry does not change the completion decision.
    """

    def __init__(self, path: Path | None, session: str) -> None:
        """Remember the exact native file boundary before the checker starts."""
        self.path = path
        self.session = session
        self.responses: dict[str, dict[str, dict]] = {}
        self.native_calls: dict[str, set[str]] = {}
        self.terminal: dict[str, str] = {}
        self.updates: dict[str, dict] = {}
        self.offset = 0
        self.baseline: dict = {}
        self.calls: set[str] = set()
        self.ready = False
        if path is None:
            return
        try:
            identity = None
            with path.open('rb') as stream:
                # Read the inherited history once; keep only counters and IDs.
                for line in stream:
                    if not line.endswith(b'\n'):
                        return
                    record = json.loads(line)
                    if record.get('type') == 'session_meta':
                        identity = record['payload'].get('id')
                    total = _total(record)
                    if total is not None:
                        self.baseline = total
                    if record.get('type') == 'response_item':
                        call = tool_call_id(record.get('payload', {}))
                        if call is not None:
                            self.calls.add(call)
                self.offset = stream.tell()
            self.ready = identity == session
        except (OSError, ValueError, TypeError, KeyError):
            return

    def observe(self, notice: dict) -> None:
        """Keep only this child's native response facts, tool IDs and outcomes.

        Fork listeners suppress raw response events in Codex0.162. Use public
        tokenUsage updates following new canonical model output when raw facts
        are unavailable. Lifetime totals only deduplicate these updates.
        """
        if not isinstance(notice, dict):
            return
        params = notice.get('params', {})
        if params.get('threadId') != self.session:
            return
        method = notice.get('method')
        turn = params.get('turnId')
        if method == 'turn/completed':
            completed = params.get('turn', {})
            self.terminal[completed['id']] = completed['status']
        elif isinstance(turn, str):
            update = self.updates.setdefault(turn, {
                'items': set(), 'snapshots': set(), 'pending': False, 'usage': [],
            })
            if method in {'item/started', 'item/completed'}:
                item = params.get('item', {})
                kind = item.get('type')
                identifier = item.get('id')
                tools = {'commandExecution', 'fileChange', 'mcpToolCall', 'dynamicToolCall',
                         'collabAgentToolCall', 'webSearch', 'imageGeneration', 'imageView', 'sleep'}
                if isinstance(identifier, str) and kind in tools | {'agentMessage', 'reasoning', 'plan'}:
                    if identifier not in update['items']:
                        update['items'].add(identifier)
                        update['pending'] = True
                    if kind in tools:
                        self.native_calls.setdefault(turn, set()).add(identifier)
            elif method == 'thread/tokenUsage/updated':
                usage = params.get('tokenUsage', {})
                total = usage.get('total', {})
                snapshot = tuple(sorted((key, value) for key, value in total.items()
                                        if type(value) is int))
                if snapshot and snapshot not in update['snapshots']:
                    update['snapshots'].add(snapshot)
                    if update['pending']:
                        last = usage.get('last') or {}
                        update['usage'].append({field: last.get(native) for field, native in (
                            ('input_tokens', 'inputTokens'),
                            ('cached_input_tokens', 'cachedInputTokens'),
                            ('output_tokens', 'outputTokens'),
                            ('reasoning_tokens', 'reasoningOutputTokens'),
                        )})
                        update['pending'] = False
            if method == 'rawResponse/completed':
                response = params.get('responseId')
                if isinstance(response, str) and response:
                    usage = params.get('usage') or {}
                    self.responses.setdefault(turn, {}).setdefault(response, {
                        field: usage.get(native) for field, native in (
                            ('input_tokens', 'inputTokens'),
                            ('cached_input_tokens', 'cachedInputTokens'),
                            ('output_tokens', 'outputTokens'),
                            ('reasoning_tokens', 'reasoningOutputTokens'),
                        )
                    })
            elif method == 'rawResponseItem/completed':
                call = tool_call_id(params.get('item', {}))
                if call is not None:
                    self.native_calls.setdefault(turn, set()).add(call)

    def response_evidence(self, turn: str) -> dict:
        """Expose ordered independent response facts, including first-response reuse."""
        responses = [dict(response_id=key, **value)
                     for key, value in self.responses.get(turn, {}).items()]
        updates = self.updates.get(turn, {}).get('usage', [])
        return {'responses': responses, 'first_response': responses[0] if responses else None,
                'usage_updates': updates, 'first_usage_update': updates[0] if updates else None,
                'terminal_status': self.terminal.get(turn)}

    def _response_totals(self, turn: str) -> CheckUsage:
        """Aggregate unique current-turn responses only after native completion."""
        responses = list(self.responses.get(turn, {}).values())
        if self.terminal.get(turn) != 'completed' or not responses:
            return CheckUsage()
        values = {}
        for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'):
            parts = [response.get(field) for response in responses]
            if all(type(value) is int and value >= 0 for value in parts):
                values[field] = sum(parts)
        return CheckUsage(**values, model_requests=len(responses),
                          tool_calls=len(self.native_calls.get(turn, set())))

    def finish(self, turn: str) -> CheckUsage:
        """Count only complete appended records associated with this native turn."""
        if self.responses.get(turn):
            return self._response_totals(turn)
        update = self.updates.get(turn, {})
        if self.path is None and update.get('usage') and self.terminal.get(turn) == 'completed':
            increments = update['usage'] + ([{}] if update['pending'] else [])
            values = {}
            for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'):
                parts = [increment.get(field) for increment in increments]
                if all(type(value) is int and value >= 0 for value in parts):
                    values[field] = sum(parts)
            # A cumulative snapshot is not a response ID or independent request.
            return CheckUsage(**values, tool_calls=len(self.native_calls.get(turn, set())))
        if not self.ready or self.path is None:
            return CheckUsage()
        try:
            with self.path.open('rb') as stream:
                stream.seek(self.offset)
                data = stream.read()
            lines = data.splitlines()
            if data and not data.endswith(b'\n'):
                lines = lines[:-1]
            current = None
            total = None
            calls = set()
            completed = False
            snapshots = set()
            increments = []
            model_output = False
            for line in lines:
                record = json.loads(line)
                payload = record.get('payload', {})
                if record.get('type') == 'turn_context':
                    current = payload.get('turn_id')
                elif record.get('type') == 'event_msg' and payload.get('type') == 'task_started':
                    current = payload.get('turn_id')
                if current != turn:
                    continue
                if (record.get('type') == 'token_usage_record'
                        and payload.get('thread_id') == self.session
                        and payload.get('turn_id') == turn
                        and isinstance(payload.get('response_id'), str)
                        and payload['response_id']):
                    usage = payload.get('usage') or {}
                    self.responses.setdefault(turn, {}).setdefault(payload['response_id'], {
                        'input_tokens': usage.get('input_tokens'),
                        'cached_input_tokens': usage.get('cached_input_tokens'),
                        'output_tokens': usage.get('output_tokens'),
                        'reasoning_tokens': usage.get('reasoning_output_tokens'),
                    })
                snapshot = _total(record)
                if snapshot is not None:
                    total = snapshot
                    identity = tuple(sorted((key, value) for key, value in snapshot.items()
                                            if type(value) is int))
                    if identity and identity not in snapshots:
                        snapshots.add(identity)
                        if model_output:
                            last = payload['info'].get('last_token_usage')
                            increments.append(last if isinstance(last, dict) else {})
                            model_output = False
                if record.get('type') == 'response_item':
                    call = tool_call_id(payload)
                    if call is not None and call not in self.calls:
                        calls.add(call)
                        model_output = True
                    if (payload.get('type') == 'reasoning'
                            or (payload.get('type') == 'message' and payload.get('role') == 'assistant')):
                        model_output = True
                if record.get('type') == 'event_msg' and payload.get('type') == 'task_complete':
                    completed = payload.get('turn_id') == turn
                    current = None
            # A partial native flush cannot establish a whole-check aggregate.
            if not completed:
                return CheckUsage()
            if self.responses.get(turn):
                self.terminal[turn] = 'completed'
                self.native_calls[turn] = calls
                return self._response_totals(turn)
            if model_output:
                increments.append({})  # The final response has no usable usage update.
            values = {}
            for field, native in (
                ('input_tokens', 'input_tokens'),
                ('cached_input_tokens', 'cached_input_tokens'),
                ('output_tokens', 'output_tokens'),
                ('reasoning_tokens', 'reasoning_output_tokens'),
            ):
                before = self.baseline.get(native)
                after = total.get(native) if total is not None else None
                if type(before) is int and type(after) is int and 0 <= before <= after:
                    values[field] = after - before
                elif before is None and increments:
                    parts = [increment.get(native) for increment in increments]
                    if all(type(value) is int and value >= 0 for value in parts):
                        values[field] = sum(parts)
            return CheckUsage(**values, tool_calls=len(calls))
        except (OSError, ValueError, TypeError, KeyError):
            return CheckUsage()
