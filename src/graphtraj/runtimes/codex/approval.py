"""Request-scoped model approval for Codex custom providers."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


# The provider a hosted role's Session runs on when the role configures no
# provider of its own, so the same connection that serves the Session reviews.
HOSTED_BASE_URL = "https://api.openai.com/v1"


def approval_route(settings: Mapping[str, Any] | None, *, custom: bool) -> dict | None:
    """Validate the adapter-only route; hosted Sessions keep native Guardian."""
    if not custom:
        return None
    route = (settings or {}).get('approval')
    for field in ('model', 'base_url', 'api_key_env'):
        if not isinstance(route, dict) or not isinstance(route.get(field), str) or not route[field].strip():
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', f'codex.approval.{field} is required for a custom provider.')
    if set(route) != {'model', 'base_url', 'api_key_env'}:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Unsupported codex.approval field.')
    url = urlsplit(route['base_url'])
    if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval.base_url must be an HTTPS provider URL.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', route['api_key_env']):
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'codex.approval.api_key_env must name an environment variable.')
    return dict(route)


def harness_approvals_reviewer(runtime_store: Path) -> Any | None:
    """Return the approvals reviewer the Harness Runtime Store selects.

    One Session runs with its Ticket Worktree as the native project root, so
    the Runtime Store configuration sits outside the native lookup. Only this
    selected value is forwarded; a missing, unreadable or unparsable file adds
    no override and keeps the native default.
    """
    config = runtime_store / 'config.toml'
    try:
        document = tomllib.loads(config.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    return document.get('approvals_reviewer')


def role_approval_route(settings: RolePreset, runtime_store: Path) -> dict | None:
    """Return the route one role's own Runtime reviews this request on.

    A role with its own provider reviews on the adapter-only ``codex.approval``
    route its Sessions already use. A hosted role is reviewed on the connection
    its Session runs on, which is where the host's default ``auto_review``
    decides. ``None`` means the host hands its approvals to the user instead of
    a model review, which is the one decision this route cannot produce.
    """
    if settings.base_url is not None:
        return approval_route(settings.codex, custom=True)
    if harness_approvals_reviewer(runtime_store) != 'auto_review':
        return None
    hosted = {
        'model': settings.model,
        'base_url': os.environ.get('OPENAI_BASE_URL') or HOSTED_BASE_URL,
        'api_key_env': settings.api_key_env or 'OPENAI_API_KEY',
    }
    # Validate the derived route through the same adapter rule a role route passes.
    return approval_route({'approval': hosted}, custom=True)


def review_role_request(settings: RolePreset, runtime_store: Path, context: Mapping[str, Any]) -> dict:
    """Return the reviewed decision for this exact request.

    Only a validated model decision comes back. A host that reviews with the
    user raises ``RUNTIME_REQUEST_UNHANDLED``: that window is not reachable
    from the Runner, so this entry never stands in for the user's answer.
    """
    route = role_approval_route(settings, runtime_store)
    if route is None:
        raise RuntimeAdapterError(
            'RUNTIME_REQUEST_UNHANDLED',
            'The host reviews approvals with the user, and the Runner has no channel '
            'to open that window for this request.',
        )
    return asyncio.run(review_request(route, dict(context)))


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
    with build_opener(_NoRedirect()).open(request, timeout=30) as response:
        result = json.loads(response.read(1024 * 1024))
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
        return {'decision': result['decision']}
    except Exception as error:
        # Do not expose credentials, endpoint response bodies or request contents in errors.
        raise RuntimeAdapterError(
            'RUNTIME_REQUEST_FAILED', 'Approval call failed: ' + type(error).__name__,
            terminal_confirmed=False,
        ) from error
