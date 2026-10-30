"""Progressive agent features over the existing action schema and handler."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from agent_swarm.schema import validate
from agent_swarm.tool import ACTION_FIELDS, INPUT_SCHEMA as ACTION_SCHEMA, AgentsResult


INPUT_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['discover', 'describe', 'execute']},
        'query': {'type': 'string'},
        'feature': {'type': 'string'},
        'schema': {'type': 'boolean', 'default': False,
                   'description': 'For describe only: return the selected input schema.'},
        'arguments': {'type': 'object'},
    },
    'required': ['action'],
    'additionalProperties': False,
}

DESCRIPTIONS = {
    'create': 'Create a child Agent on a Runtime; returns before its work finishes.',
    'send': 'Send a message to an Agent.',
    'status': 'Read Agent status, or the visible hierarchy when no Agent is supplied.',
    'wait': 'Wait a finite positive number of seconds for an Agent.',
    'interrupt': 'Stop active work while retaining the native Session for continuation.',
    'resume': 'Continue the same native Session, optionally with a message.',
    'requests': 'Read pending native approval or input requests.',
    'reply': 'Answer one native request explicitly.',
    'retire': 'Remove an Agent from the active list while retaining its history.',
    'ask_parent': 'Ask your direct parent for a decision or resources (more time, wider scope) '
                  'and wait a finite time for its answer.',
}

# Intent words a caller may use instead of the action name; discovery matches them too.
INTENTS = {
    'create': 'start launch spawn new run begin',
    'send': 'message tell',
    'status': 'list show',
    'interrupt': 'stop cancel',
    'requests': 'approvals pending',
    'reply': 'answer approve respond',
    'retire': 'remove delete archive',
    'ask_parent': 'request permission time budget scope extend',
}

# Words that carry no intent; they would otherwise match nearly every description.
FILLER = frozenset({'a', 'an', 'the', 'to', 'of', 'for', 'my', 'one', 'please'})


def validate_envelope(request: dict) -> str:
    """Validate the shared discover/describe/execute envelope, returning its action."""
    validate(request, INPUT_SCHEMA, 'request')
    action = request['action']
    fields = {'action', 'query'} if action == 'discover' else {'action', 'feature'}
    if action == 'execute':
        fields.add('arguments')
    if action == 'describe':
        fields.add('schema')
    for name in request.keys() - fields:
        raise ValueError(f'request.{name}: not valid for {action}')
    if action != 'discover' and 'feature' not in request:
        raise ValueError('request.feature: required')
    if action == 'execute' and 'arguments' not in request:
        raise ValueError('request.arguments: required')
    return action


def feature_schema(feature: str) -> dict:
    """Project one action's schema without exposing parameters of other actions."""
    required, optional = ACTION_FIELDS[feature]
    fields = required | optional
    return {
        'type': 'object',
        'properties': {name: deepcopy(schema) for name, schema in ACTION_SCHEMA['properties'].items()
                       if name in fields},
        'required': sorted(required),
        'additionalProperties': False,
    }


def handle_request(request: dict, execute: Callable[[dict], AgentsResult]) -> AgentsResult:
    """Discover one action or invoke the host's already-bound business callback.

    The callback is a host input, never a model argument. No identity, state,
    controller or Runtime is created by discovery or schema requests.
    """
    try:
        action = validate_envelope(request)
        if action == 'discover':
            terms = [term for term in request.get('query', '').casefold().split() if term not in FILLER]
            return AgentsResult({'features': [
                {'feature': name, 'description': description}
                for name, description in DESCRIPTIONS.items()
                if all(term in f'{name} {INTENTS.get(name, "")} {description}'.casefold() for term in terms)
            ], 'describe': {'action': 'describe', 'feature': '<feature>'}})
        feature = request['feature']
        if feature not in ACTION_FIELDS:
            raise ValueError(f'Unknown feature: {feature}')
        schema = feature_schema(feature)
        if action == 'describe':
            if request.get('schema', False):
                return AgentsResult({'input_schema': schema})
            return AgentsResult({'feature': feature, 'description': DESCRIPTIONS[feature],
                                 'input_schema': schema})
        validate(request['arguments'], schema, 'arguments')
        return execute({'action': feature, **request['arguments']})
    except ValueError as error:
        action = request.get('action') if isinstance(request, dict) else None
        return AgentsResult({'action': action, 'error': {'code': 'invalid-input', 'message': str(error)}},
                            failed=True)
