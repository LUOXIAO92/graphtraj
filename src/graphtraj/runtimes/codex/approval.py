"""Request-scoped model approval for Codex custom providers."""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def approval_route(
    settings: Mapping[str, Any] | None,
    *,
    custom: bool,
    defaults: Mapping[str, Any] | None = None,
) -> dict | None:
    """Select role then project approval settings, otherwise retain legal native review.

    A present route must validate; invalid settings never select another reviewer.
    Custom work providers require an explicit route. Hosted providers may retain
    their existing native approval configuration when neither route is set.
    """
    selected = settings if 'approval' in (settings or {}) else defaults
    if 'approval' not in (selected or {}) and not custom:
        return None
    route = (selected or {}).get('approval')
    if isinstance(route, dict) and 'connection' in route:
        from graphtraj.configuration.runtime_connections import read_catalog

        if set(route) != {'connection'} or not isinstance(route['connection'], str):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval requires one connection reference.')
        try:
            runtime_id, provider_id, model_id = route['connection'].split('/')
            catalog, _ = read_catalog()
            runtime = catalog['runtimes'][runtime_id]
            provider = runtime['providers'][provider_id]
            model = provider['models'][model_id]
        except (ValueError, KeyError):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval connection is unavailable.') from None
        if runtime['runtime'] == 'dsh' or provider.get('api') not in {None, 'openai-completions'}:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Codex approval requires a Chat Completions provider.')
        route = {'model': model['id'], 'base_url': provider.get('base_url'),
                 'api_key_env': provider.get('api_key_env')}
    for field in ('model', 'base_url', 'api_key_env'):
        if not isinstance(route, dict) or not isinstance(route.get(field), str) or not route[field].strip():
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', f'codex.approval.{field} is required for an approval route.')
    if set(route) != {'model', 'base_url', 'api_key_env'}:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Unsupported codex.approval field.')
    url = urlsplit(route['base_url'])
    if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval.base_url must be an HTTPS provider URL.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', route['api_key_env']):
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval.api_key_env must name an environment variable.')
    return dict(route)


class _NoRedirect(HTTPRedirectHandler):
    """Keep authorization and request context on the configured provider."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Reject redirects instead of forwarding credentials to another route."""
        return None


def default_approval_policy() -> str:
    """Compose the pinned official default policy with only transport instructions.

    Source and license: policy/SOURCE.md. Composition follows Codex 0.154.0
    core/src/guardian/prompt.rs; allow/deny rules are not authored here.
    """
    directory = Path(__file__).with_name('policy')
    template = (directory / 'policy_template.md').read_text(encoding='utf-8').rstrip()
    policy = (directory / 'policy.md').read_text(encoding='utf-8').strip()
    return template.replace('{{ tenant_policy_config }}', policy) + (
        '\n\n# Response transport\n'
        'This API call has no attached tools. Assess the supplied context and exact native request. '
        'The context contains the current task, native turn context, retained role settings, '
        'user/developer messages, and native compaction/history records. '
        'Return only JSON with request_id copied exactly, decision, and a short rationale. '
        'Encode the policy outcome allow as decision accept and deny as decision decline. '
        'For a permissions request, the action being assessed is the exact requested profile.'
    )


def _http_error_detail(error: HTTPError, key: str, context: dict) -> str:
    """Read one bounded error object and expose only cleaned standard fields.

    Request echoes and uncertain values are omitted, never copied as fallback.
    This runs inside the existing HTTP worker and timeout, without another call.
    """
    omitted = '; error details omitted'
    try:
        with error:
            raw = error.read(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            return omitted
        document = json.loads(raw.decode('utf-8'))
        if not isinstance(document, dict) or not isinstance(document.get('error'), dict):
            return omitted

        # Use only the request already in memory. Exact values include short
        # proposals; longer fragments also identify partial request echoes.
        pending = [context]
        request_values = set()
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str):
                plain = ''.join(char for char in item if not unicodedata.category(char).startswith('C'))
                request_values.add(' '.join(plain.split()).casefold())
        request_text = '\n'.join(request_values)
        short_values = [value for value in request_values if 0 < len(value) < 16]
        details = {}
        for field in ('code', 'type', 'param', 'message'):
            value = document['error'].get(field)
            if field not in document['error']:
                continue
            if field != 'message' and value is None:
                details[field] = value
                continue
            original = value
            if field != 'message' and type(value) is int:
                value = str(value)
            if not isinstance(value, str):
                continue

            value = ''.join(char for char in value if not unicodedata.category(char).startswith('C'))
            value = value.replace(key, '[REDACTED]')
            # Reuse the native startup diagnostic patterns, on every field.
            value = re.sub(r'(?i)(bearer\s+)[^\s"\']+', r'\1[REDACTED]', value)
            value = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', value)
            value = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[REDACTED]', value)
            if ('\\' in value or re.search(
                r'''(?i)["'](?:messages|request|authorization|developer_instructions|history|permissions)["']\s*:''', value,
            ) or re.search(r'(?i)\b(?:authorization|api[_ -]?key|password|secret|token)\b\s*[:=]', value)):
                continue
            value = ' '.join(value.split())
            folded = value.casefold()
            if folded in request_values or any(
                re.search(r'(?<!\w)' + re.escape(item) + r'(?!\w)', folded) for item in short_values
            ) or any(
                folded[index:index + 16] in request_text for index in range(len(folded) - 15)
            ):
                continue

            # Omit overlong fields rather than risk publishing a partial echo.
            if len(value) > (512 if field == 'message' else 128):
                continue
            if field != 'message' and not re.fullmatch(r'[A-Za-z0-9_.\[\]-]*', value):
                continue
            details[field] = original if type(original) is int and str(original) == value else value

        encoded = '; error=' + json.dumps(details, ensure_ascii=False)
        return encoded if details and len(encoded) <= 1024 else omitted
    except Exception:
        # Bad encoding, malformed content and failed reads cannot expose raw text
        # or turn an unsuccessful review into a decision.
        return omitted


def _completion(route: dict, context: dict) -> dict:
    """Call the configured chat-completions endpoint once, without retries."""
    key = os.environ.get(route['api_key_env'])
    if not key:
        raise ValueError('Approval API key environment variable is not set')
    # JSON mode guarantees JSON syntax, not this request's response envelope.
    # Supply the exact envelope without deriving a decision or repairing a reply.
    schema = {
        'type': 'object', 'additionalProperties': False,
        'required': ['request_id', 'decision', 'rationale'],
        'properties': {
            'request_id': {
                'type': 'integer' if type(context['request_id']) is int else 'string',
                'const': context['request_id'],
            },
            'decision': {'type': 'string', 'enum': context['allowed_decisions']},
            'rationale': {'type': 'string', 'minLength': 1},
        },
    }
    transport = (
        '\n\nYour answer must be one JSON instance matching the following response schema. '
        'Return exactly the three required properties, no extras or markdown. '
        'Copy request_id with its exact JSON value and type, including integer zero. '
        'Do not output the schema itself or the API response_format setting: '
        'type and json_object are not answer properties. '
        'The policy determines the decision; this schema only defines its transport.\n'
        + json.dumps(schema)
    )
    body = {
        'model': route['model'],
        'messages': [
            {'role': 'system', 'content': default_approval_policy() + transport},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)},
        ],
        'response_format': {'type': 'json_object'},
        'stream': False,
    }
    request = Request(route['base_url'].rstrip('/') + '/chat/completions',
                      data=json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            result = json.loads(response.read(1024 * 1024))
    except HTTPError as error:
        detail = _http_error_detail(error, key, context)
        raise RuntimeAdapterError(
            'RUNTIME_REQUEST_FAILED', f'Approval call failed: HTTPError (HTTP {error.code})' + detail,
            terminal_confirmed=False,
        ) from error
    choice = result['choices'][0]
    if choice['finish_reason'] != 'stop':
        raise ValueError('Approval completion was not finished')
    return json.loads(choice['message']['content'])


async def review_request(route: dict, context: dict) -> dict:
    """Return a validated decision; call failures use the native RPC error path."""
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_completion, route, context), 30)
        if (not isinstance(result, dict)
                or set(result) != {'request_id', 'decision', 'rationale'}
                or type(result['request_id']) is not type(context['request_id'])
                or result['request_id'] != context['request_id']
                or result['decision'] not in context['allowed_decisions']
                or not isinstance(result['rationale'], str) or not result['rationale'].strip()):
            raise ValueError('Invalid approval decision')
        if context.get('method') == 'graphtraj/recoveryApproval' and result['decision'] == 'decline':
            return {'decision': 'decline', 'rationale': result['rationale']}
        return {'decision': result['decision']}
    except RuntimeAdapterError:
        # The HTTP worker has already bounded and sanitized this diagnostic.
        raise
    except Exception as error:
        # Do not expose credentials, endpoint response bodies or request contents in errors.
        status = f' (HTTP {error.code})' if isinstance(error, HTTPError) else ''
        raise RuntimeAdapterError(
            'RUNTIME_REQUEST_FAILED', 'Approval call failed: ' + type(error).__name__ + status,
            terminal_confirmed=False,
        ) from error


def review_recovery(proposal: dict, cwd: Path) -> dict:
    """Review a host recovery action without inventing a native Codex request.

    Managed and local hosts bind their selected reviewer. CLI callers reuse the
    configured role/project HTTP route. A missing route fails closed; it never
    silently substitutes human review for native automatic review.
    """
    import uuid

    import yaml

    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.execution.runner_batch import read_session_task
    from graphtraj.execution.runner_status import NativeCaller, caller_alias, read_alias_mapping
    from graphtraj.workspace.runner_project import discover_project

    project = discover_project(cwd, require_clean_integration=False)
    defaults = load_project_configuration(project.harness_root).codex
    caller = caller_alias(project.runner_directory)
    settings = None
    context = {}
    custom = False
    if caller and not isinstance(caller, NativeCaller):
        mapping, directory = read_alias_mapping(project.runner_directory, caller)
        task = read_session_task(mapping, project.harness_root)
        role = task.inline_preset or load_project_roles(project.harness_root).preset(
            mapping.get('role_reference') or mapping['role'])
        settings = role.codex
        launch = yaml.safe_load((directory / 'launch.yml').read_text())
        params = launch['adapter_request']['session_parameters']
        custom = params.get('config', {}).get('model_provider', 'openai') != 'openai'
        context = {'task': task.task_content, 'instruction': task.instruction,
                   'developer_instructions': params.get('developerInstructions')}
    route = approval_route(settings, custom=custom, defaults=defaults)
    if route is None:
        raise RuntimeAdapterError('native-approval-unavailable',
                                  'Recovery requires the selected reviewer to be bound by the host.')
    return asyncio.run(review_request(route, {
        **context, 'request_id': uuid.uuid4().hex, 'method': 'graphtraj/recoveryApproval',
        'request': proposal, 'allowed_decisions': ['accept', 'decline'],
    }))
