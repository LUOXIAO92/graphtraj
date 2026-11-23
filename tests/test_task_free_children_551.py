"""Task-free agents children reach GraphTraj's general methods (551).

The ``tasks`` entry a child gets beside ``agents`` exposes only the general
method features, under the child's own Agent identity, and the installed
manuals that ``describe`` names are a read-only native resource for Claude
Task members and children alike. No native Runtime or model runs here.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import json
from pathlib import Path

import pytest

from graftling import AgentsResult
from graphtraj.interfaces import gateway
from graphtraj.interfaces.task_free import TASK_FREE_FEATURES, serve_task_free, task_free_tools
from graphtraj.interfaces.tools import METHOD_FEATURE_NAMES
from test_claude_runtime import claude_environment, execution  # noqa: F401 - pytest fixture
from test_result_submission import result_project

REPOSITORY = Path(__file__).resolve().parents[1]
CHILD = 'agent-' + '0' * 32


@pytest.fixture
def delivered(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Resolve manual references against this checkout's delivered ``manuals`` tree."""
    monkeypatch.setattr(gateway, 'delivered_manuals_root', lambda: REPOSITORY)
    return REPOSITORY / 'manuals'


def test_discover_lists_only_the_general_methods(tmp_path: Path, delivered: Path) -> None:
    """A child discovers the five method features and nothing it could execute."""
    result = serve_task_free(tmp_path, CHILD, {'action': 'discover'})
    assert not result.failed
    assert sorted(item['feature'] for item in result.document['features']) == sorted(METHOD_FEATURE_NAMES)
    assert TASK_FREE_FEATURES == frozenset(METHOD_FEATURE_NAMES)


def test_describe_names_the_installed_manual(tmp_path: Path, delivered: Path) -> None:
    """describe returns the readable installed guide by reference, not a copy."""
    result = serve_task_free(tmp_path, CHILD, {'action': 'describe', 'feature': 'concept-clarification'})
    assert not result.failed, result.document
    reference = Path(result.document['manual_ref'])
    assert reference == (delivered / 'concept-clarification/guide.md').resolve()
    assert 'name: concept-clarification' in reference.read_text(encoding='utf-8')


@pytest.mark.parametrize('feature', ['submit_result', 'decide_result', 'swarm', 'task_graph',
                                     'submit_report', 'session_reports'])
def test_execution_features_are_not_offered(tmp_path: Path, delivered: Path, feature: str) -> None:
    """Every execution feature answers Unknown feature through the existing gate."""
    for request in ({'action': 'execute', 'feature': feature, 'arguments': {}},
                    {'action': 'describe', 'feature': feature}):
        result = serve_task_free(tmp_path, CHILD, request)
        assert result.failed and result.document == {'error': f'Unknown feature: {feature}'}


def test_calls_run_as_the_child_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bound caller is the child's own Agent ID: never Main (None), never a member alias."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.interfaces.tools import ToolResult

    seen = []

    def observe(request: dict, *, cwd: Path, allowed_features: object) -> ToolResult:
        seen.append((caller_alias(runner_directory(tmp_path)), cwd, allowed_features))
        return ToolResult({})

    monkeypatch.setattr(gateway, 'handle_request', observe)
    assert not serve_task_free(tmp_path, CHILD, {'action': 'discover'}).failed
    assert seen == [(CHILD, tmp_path, TASK_FREE_FEATURES)]


def test_member_identities_and_agents_requests_are_refused(tmp_path: Path) -> None:
    """A Runner alias is never a Task-free child's identity, and agents keeps its own entry."""
    alias = '551-task_free-handover0-engineer@engineer_3'
    assert serve_task_free(tmp_path, alias, {'action': 'discover'}).document['error']['code'] == 'authority-denied'
    assert serve_task_free(tmp_path, '', {'action': 'discover'}).failed
    refused = serve_task_free(tmp_path, CHILD, {'action': 'describe', 'feature': 'agents'})
    assert refused.document['error']['code'] == 'invalid-input'
    assert serve_task_free(tmp_path, CHILD, ['not', 'an', 'object']).failed


def test_tool_pair_is_bound_to_its_child(tmp_path: Path, delivered: Path) -> None:
    """The hook pair names ``tasks`` and serves the child it was built for."""
    [(descriptor, callback)] = task_free_tools(tmp_path, CHILD)
    assert descriptor['name'] == 'tasks' and descriptor['inputSchema'] == gateway.INPUT_SCHEMA
    result = callback({'action': 'describe', 'feature': 'research'})
    assert isinstance(result, AgentsResult) and not result.failed


def test_agent_driver_gives_each_child_its_own_tasks_entry(tmp_path: Path) -> None:
    """The driver's factory, used for every Runtime, binds the run's own Agent."""
    from types import SimpleNamespace

    from graphtraj.execution.agent_driver import AdapterDriver

    driver = AdapterDriver(tmp_path, tmp_path)
    assert driver.codex.extra_tools == driver.child_tools
    [(descriptor, callback)] = driver.child_tools(SimpleNamespace(agent=CHILD))
    assert descriptor['name'] == 'tasks'


def _without_manuals(settings: dict, manuals: Path) -> dict:
    """Return ``settings`` minus exactly the read-only grant of ``manuals``, checking each is present."""
    settings = copy.deepcopy(settings)
    path = str(manuals)
    permissions, filesystem = settings['permissions'], settings['sandbox']['filesystem']
    for entries, values in ((permissions['allow'], (f'Read(/{path})', f'Read(/{path}/**)')),
                            (permissions['deny'], (f'Edit(/{path})', f'Edit(/{path}/**)')),
                            (permissions['additionalDirectories'], (path,)),
                            (filesystem['allowRead'], (path,)),
                            (filesystem['denyWrite'], (path,))):
        for value in values:
            entries.remove(value)
    assert path not in str(settings)
    return settings


def _without_add_dir(argv: list[str], manuals: Path) -> list[str]:
    """Return ``argv`` minus exactly ``--add-dir <manuals>`` and the grant inside ``--settings``."""
    index = next(i for i in range(len(argv) - 1) if argv[i:i + 2] == ['--add-dir', str(manuals)])
    argv = argv[:index] + argv[index + 2:]
    settings = argv.index('--settings') + 1
    argv[settings] = json.dumps(_without_manuals(json.loads(argv[settings]), manuals))
    assert str(manuals) not in ' '.join(argv)
    return argv


def _parsed_settings(argv: list[str]) -> list[str]:
    """Return ``argv`` with its ``--settings`` JSON re-serialized for comparison."""
    argv = list(argv)
    settings = argv.index('--settings') + 1
    argv[settings] = json.dumps(json.loads(argv[settings]))
    return argv


@pytest.mark.parametrize('independent', [False, True])
@pytest.mark.parametrize('access', ['read', 'write'])
def test_claude_manual_grant_is_the_only_difference(
    tmp_path: Path, claude_environment: None, monkeypatch: pytest.MonkeyPatch, independent: bool, access: str,
) -> None:
    """Members and children differ from before only by read access to the installed manuals.

    That access is a Read allow, an --add-dir and a sandbox read; Edit and
    sandbox writes stay denied there. Everything else is identical.
    """
    from graphtraj.runtimes.claude import execution as claude_execution

    result_project(tmp_path)
    manuals = (tmp_path / 'venv/share/graphtraj/manuals').resolve()
    manuals.mkdir(parents=True)
    address = str(tmp_path / 'connection.sock')
    observed = {}
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'unused', worktree_access=access)
        if independent:
            turn.configure_independent(archive=None, agents_callback=lambda request: AgentsResult({}))
        for name, granted in (('before', []), ('after', [manuals])):
            monkeypatch.setattr(claude_execution, 'installed_manuals', lambda granted=granted: granted)
            settings, mcp = turn.native_settings(address)
            argv, environment = turn._prepare(address)
            observed[name] = (settings, mcp, argv, environment, copy.deepcopy(turn.resource_settings))
    before, after = observed['before'], observed['after']
    assert _without_manuals(after[0], manuals) == before[0]
    assert after[1] == before[1]
    assert _without_add_dir(after[2], manuals) == _parsed_settings(before[2])
    assert after[3] == before[3]
    assert after[4] == before[4] is None
    assert f'Edit(/{manuals}/**)' in after[0]['permissions']['deny']
    assert str(manuals) not in after[0]['sandbox']['filesystem']['allowWrite']


def test_claude_manual_grant_uses_the_installed_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The one switch grants the installed manuals directory and nothing when it is absent."""
    from graphtraj.runtimes.claude.execution import installed_manuals

    monkeypatch.setattr(gateway, 'delivered_manuals_root', lambda: tmp_path)
    assert installed_manuals() == []
    (tmp_path / 'manuals').mkdir()
    assert installed_manuals() == [(tmp_path / 'manuals').resolve()]


@pytest.mark.parametrize('independent', [False, True])
def test_claude_member_tools_stay_fixed_and_children_inherit_the_host(
    tmp_path: Path, claude_environment: None, independent: bool,
) -> None:
    """A Task member keeps its fixed tool list; an agents child gets its Claude Code's probed default
    set unless it chose some (graftling 576: --tools is always passed, --restricted would drop Bash)."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(tmp_path, stack, 'unused')
        if independent:
            turn.configure_independent(archive=None, agents_callback=lambda request: AgentsResult({}))
        argv, _ = turn._prepare(str(tmp_path / 'connection.sock'))
        if independent:
            # The fixture's init answers graftling's probe with CLAUDE_FIXTURE_DEFAULT_TOOLS' default.
            assert argv[argv.index('--tools') + 1] == 'Bash,Read,Edit,Write'
            assert turn.diagnostics['default_tools'] == ['Bash', 'Read', 'Edit', 'Write']
            assert '--disallowedTools' not in argv
            turn.request.update(tools=['Read', 'WebFetch'], disallowed_tools=['Bash'])
            chosen, _ = turn._prepare(str(tmp_path / 'connection.sock'))
            assert chosen[chosen.index('--tools') + 1] == 'Read,WebFetch'
            assert chosen[chosen.index('--disallowedTools') + 1] == 'Bash'
        else:
            assert argv[argv.index('--tools') + 1] == 'Bash,Read,Write,Edit,Glob,Grep'
            assert '--disallowedTools' not in argv
            assert 'default_tools' not in turn.diagnostics   # a member's fixed tools start no probe
            turn.request.update(tools=['Read'], disallowed_tools=['Bash'])
            assert turn._prepare(str(tmp_path / 'connection.sock'))[0] == argv


def test_child_tool_choice_reaches_each_runtime_request() -> None:
    """Claude takes flags, Codex its expressible config, other Runtimes refuse for now."""
    from graftling import AgentsError

    from graphtraj.execution.agent_driver import apply_child_tools

    claude: dict = {}
    apply_child_tools('claude', claude, {'tools': None, 'disallowed_tools': ['WebFetch']})
    assert claude == {'tools': None, 'disallowed_tools': ['WebFetch']}
    codex = {'session_parameters': {'config': {}}}
    apply_child_tools('codex', codex, {'tools': None, 'disallowed_tools': ['web_search']})
    assert codex['session_parameters']['config']['web_search'] == 'disabled'
    with pytest.raises(AgentsError):
        apply_child_tools('codex', codex, {'tools': None, 'disallowed_tools': ['shell']})
