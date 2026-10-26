"""Native review dialogs are readable from the message a host actually shows."""

import io
import json
import re

import pytest

from graphtraj.interfaces.mcp import elicit_review


ALIAS  = '338-task-handover0-engineer@engineer'
PARENT = '338-task-handover0-team_leader@leader'
PROPOSALS = {
    'retire': ({'request': {'operation': 'retire', 'alias': ALIAS},
                'before': {'mapping': {'parent': PARENT}, 'retired': False},
                'after': {'mapping': None, 'retired': True}, 'caller': None, 'parent': PARENT}, 'retire', ALIAS),
    'replace': ({'request': {'operation': 'replace', 'alias': ALIAS,
                             'registration': {'task_id': '338', 'team_ordinal': 2, 'role': 'engineer',
                                              'member': 'engineer', 'replaces': ALIAS}},
                 'before': {'mapping': {'parent': PARENT}, 'retired': False},
                 'after': {'mapping': None, 'retired': True}, 'caller': PARENT, 'parent': PARENT},
                'retire', PARENT),
    'approved_recovery': ({'request': {'alias': ALIAS, 'additional_minutes': 7, 'resume': True},
                           'before': {'budget': {'approved_minutes': None}},
                           'after': {'budget': {'approved_minutes': 7}}, 'authority': []},
                          'approved_recovery', ALIAS),
    'role_organization': ({'request': {'change': {'remove_presets': ['old']}},
                           'before': {'roles': {'old': {}}}, 'after': {'roles': {}}},
                          'role_organization', 'roles.old'),
    'runtime_connections': ({'scope': 'user', 'path': '/home/u/connections.yml',
                             'before': {'runtimes': {}}, 'after': {'runtimes': {'claude': {}}}},
                            'runtime_connections', '/home/u/connections.yml'),
}


def review(proposal: dict, feature: str, action: str) -> tuple[dict, dict]:
    """Return the elicitation sent for ``proposal`` and the decision for ``action``."""
    output = io.StringIO()

    class Client(io.StringIO):
        """Answer the dialog once it was written."""
        def readline(self, size: int = -1) -> str:
            request = json.loads(output.getvalue())
            return json.dumps({'jsonrpc': '2.0', 'id': request['id'],
                               'result': {'action': action, 'content': {}}}) + '\n'

    decision = elicit_review(Client(), output, proposal, 1, feature, lambda result: True)
    return json.loads(output.getvalue())['params'], decision


@pytest.mark.parametrize('kind', PROPOSALS)
@pytest.mark.parametrize('locale, chinese', [({'LANGUAGE': 'zh_CN:en', 'LANG': 'ja_JP.UTF-8'}, True),
                                              ({'LANG': 'zh_CN.UTF-8'}, True),
                                              ({'LANG': 'ja_JP.UTF-8'}, False),
                                              ({}, False)])
def test_review_message_names_request_target_and_choices_first(
    monkeypatch: pytest.MonkeyPatch, kind: str, locale: dict, chinese: bool,
) -> None:
    """The readable lines precede the full request, in the user's locale language."""
    for name in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        monkeypatch.delenv(name, raising=False)
    for name, value in locale.items():
        monkeypatch.setenv(name, value)
    proposal, feature, named = PROPOSALS[kind]

    params, decision = review(proposal, feature, 'decline')
    readable, full = params['message'].rsplit('\n', 1)
    assert decision['decision'] == 'decline'
    assert named in readable
    # Requester, operation, target, change, Accept, Decline, then the full-request label.
    assert len(readable.split('\n')) == 7
    assert bool(re.search(r'[一-鿿]', readable)) is chinese
    assert json.loads(full)['request'] == proposal.get('request', {'scope': 'user', 'path': proposal.get('path')})
    assert params['_meta']['tool_description'] == params['message']
    assert params['_meta']['tool_title'] == readable.split('\n')[0]
