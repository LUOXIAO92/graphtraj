"""Native review dialogs are readable from the first lines a host actually shows."""

import io
import json
import re
import unicodedata

import pytest

from graphtraj.interfaces.mcp import elicit_review


ALIAS  = '364-readable_review_dialogs_and_single_notice_delivery-handover0-engineer@engineer'
PARENT = '364-readable_review_dialogs_and_single_notice_delivery-handover0-team_leader@leader'
MODELS = {f'vendor/model-{index}': {'id': f'vendor/model-{index}', 'source': 'discovered'} for index in range(399)}
CATALOG = {'version': 1, 'runtimes': {'pi': {'runtime': 'pi', 'providers': {'openrouter': {'models': MODELS}}}}}
SHRUNK  = {'version': 1, 'runtimes': {'pi': {'runtime': 'pi', 'providers': {'openrouter': {'models': {
    'vendor/model-0': MODELS['vendor/model-0'], 'probe364': {'id': 'probe364', 'source': 'manual'}}}}}}}
# Each kind: proposal, feature, a target marker for line 1, numbers line 2 must state.
PROPOSALS = {
    'retire': ({'request': {'operation': 'retire', 'alias': ALIAS},
                'before': {'mapping': {'parent': PARENT}, 'retired': False},
                'after': {'mapping': None, 'retired': True}, 'caller': None, 'parent': PARENT},
               'retire', 'engineer@engineer', []),
    'replace': ({'request': {'operation': 'replace', 'alias': ALIAS,
                             'registration': {'task_id': '364', 'team_ordinal': 2, 'role': 'engineer',
                                              'member': 'engineer', 'replaces': ALIAS}},
                 'before': {'mapping': {'parent': PARENT}, 'retired': False},
                 'after': {'mapping': None, 'retired': True}, 'caller': PARENT, 'parent': PARENT},
                'retire', 'engineer@engineer', ['364', '2']),
    'approved_recovery': ({'request': {'alias': ALIAS, 'additional_minutes': 7, 'resume': True},
                           'before': {'budget': {'approved_minutes': None}},
                           'after': {'budget': {'approved_minutes': 7}}, 'authority': []},
                          'approved_recovery', 'engineer@engineer', ['7']),
    'role_organization': ({'request': {'change': {'remove_presets': ['old']}},
                           'before': {'roles': {'old': {}, 'kept': {'a': 1}}}, 'after': {'roles': {'kept': {'a': 2}}}},
                          'role_organization', 'roles.yml', ['1']),
    'runtime_connections': ({'scope': 'user', 'path': '/home/u/.graphtraj/connections.yml',
                             'before': CATALOG, 'after': SHRUNK},
                            'runtime_connections', 'connections.yml', ['398', '1']),
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


def columns(line: str) -> int:
    """Return a line's terminal width, counting wide characters twice."""
    return sum(2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in line)


@pytest.mark.parametrize('kind', PROPOSALS)
@pytest.mark.parametrize('locale, chinese', [({'LANGUAGE': 'zh_CN:en', 'LANG': 'ja_JP.UTF-8'}, True),
                                              ({'LANG': 'zh_CN.UTF-8'}, True),
                                              ({'LANG': 'ja_JP.UTF-8'}, False),
                                              ({}, False)])
def test_first_three_lines_state_target_change_and_choices(
    monkeypatch: pytest.MonkeyPatch, kind: str, locale: dict, chinese: bool,
) -> None:
    """A host folding all but three lines still shows what Accept and Decline do."""
    for name in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        monkeypatch.delenv(name, raising=False)
    for name, value in locale.items():
        monkeypatch.setenv(name, value)
    proposal, feature, target, numbers = PROPOSALS[kind]

    params, decision = review(proposal, feature, 'decline')
    lines = params['message'].split('\n')
    assert decision['decision'] == 'decline'
    assert target in lines[0]
    assert all(number in re.findall(r'\d+', lines[1]) for number in numbers)
    assert 'Accept' in lines[2] and 'Decline' in lines[2]
    assert all(columns(line) <= 100 for line in lines[:3])
    assert bool(re.search(r'[一-鿿]', '\n'.join(lines[:3]))) is chinese
    # The full target and the authoritative request follow the folded lines.
    assert any(proposal.get('request', {}).get('alias', proposal.get('path', '')) in line for line in lines[3:])
    assert json.loads(lines[-1])['request'] == proposal.get('request', {'scope': 'user', 'path': proposal.get('path')})
    assert params['_meta']['tool_description'] == params['message']
    assert params['_meta']['tool_title'] == lines[0]
