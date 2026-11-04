"""A real GraphTraj DSH member reaches its tools and commits on its own branch (428).

Real DSH cannot run in the team sandbox. Everything except the DSH service is
real here: the connection, the MCP entry the written patch names, the Runner
project and Git. A real member round is verified by Task 392's partial rerun.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
from typing import Iterator

import pytest
import yaml

from graftling.claude.host import IndependentCalls
from graftling.dsh import execution as native_execution
from dsh_standalone_peer import FakeDshService, install_dsh
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.runtimes.dsh import execution
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter
from test_dsh_standalone_child import claude_main, dsh, stop_owned  # noqa: F401 - dsh is a pytest fixture
from test_hosted_cli import own_process
from test_result_submission import result_project

ROOT = Path(__file__).resolve().parents[1]
GIT = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1', 'PATH': os.environ['PATH']}
FORWARDED = ('GRAFTLING_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION', 'PYTHONPATH')


def run_git(directory: Path, *arguments: str, prefix: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Run real Git with no inherited GIT_* or user configuration."""
    return subprocess.run([*prefix, 'git', '-C', str(directory), *arguments], env=GIT,
                          capture_output=True, text=True, timeout=60)


def checked_git(directory: Path, *arguments: str) -> str:
    """Run one setup step of real Git, which must succeed."""
    result = run_git(directory, *arguments)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> dict[str, Path]:
    """A repository with dev, a member's linked Worktree and a sibling's."""
    product = tmp_path / 'product'
    product.mkdir()
    checked_git(product, 'init', '-b', 'main')
    for name, value in (('user.name', 'Member'), ('user.email', 'member@example.com'),
                        ('gc.auto', '1'), ('gc.autoDetach', 'false')):
        checked_git(product, 'config', name, value)
    (product / 'base.txt').write_text('base\n')
    checked_git(product, 'add', '.')
    checked_git(product, 'commit', '-m', 'Base')
    checked_git(product, 'branch', 'dev')
    member, sibling = tmp_path / 'worktrees/member', tmp_path / 'worktrees/sibling'
    checked_git(product, 'worktree', 'add', '-b', 'agent/7-member', str(member), 'dev')
    checked_git(product, 'worktree', 'add', '-b', 'agent/8-sibling', str(sibling), 'dev')
    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))
    return {'product': product, 'common': product / '.git', 'member': member, 'sibling': sibling}


def written_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worktree: Path,
    common: Path | None,
    access: str = 'write',
) -> tuple[dict, list[dict]]:
    """Run role to adapter to launch; return the sandbox row and all rows of the written patch."""
    package = tmp_path / 'dsh'
    (package / 'lib').mkdir(parents=True, exist_ok=True)
    (package / 'package.json').write_text('{"version":"0.2.2-alpha.2"}')
    monkeypatch.setattr(shutil, 'which', lambda name: str(package / 'lib' / 'bin.js')
                        if name == 'dsh' else '/installed/graphtraj-session')
    monkeypatch.setenv('DSH_TEST_KEY', 'controlled-peer-key')
    role = ResolvedChildRole('author', 'Task responsibility', RolePreset(
        runtime='dsh', model='deepseek-official/deepseek-flash', base_url=None,
        api_key_env='DSH_TEST_KEY', worktree_access=access,
    ))
    adapter = select_runtime_adapter('dsh')
    launch = adapter.preflight_runtime_context(
        harness_root=tmp_path, git_common_directory=common or tmp_path / 'unused', role=role,
        worktree=worktree, evidence=tmp_path / 'state', requested_skills=(),
    ).finalize().launch_document()['adapter_request']
    if common is None:
        del launch['git_common_directory']  # A launch record older than this field.
    directory = tmp_path / 'session'
    directory.mkdir(exist_ok=True)
    turn = adapter.managed_execution(launch, 'Instruction', directory, lambda *_: None, {},
                                     trace_file=tmp_path / 'trace.jsonl', session_created=lambda *_: None)
    home = turn.prepare_launch()['DSH_HOME']
    rows = yaml.safe_load((Path(home) / 'profiles/web/cordis.patch.yml').read_text())
    return next(row for row in rows if row.get('id') == 'sandbox-policy'), rows


def granted(row: dict) -> list[str]:
    """The extra writable directories a written sandbox row really carries."""
    return row['config'].get('additionalWritableRoots', [])


def expected_roots(project: dict[str, Path]) -> list[str]:
    """The least set a member needs: own admin directory, objects, own branch's directories."""
    common = project['common'].resolve()
    return [str(common / 'worktrees/member'), str(common / 'objects'),
            str(common / 'refs/heads/agent'), str(common / 'logs/refs/heads/agent')]


@contextmanager
def only_granted_writable(common: Path, roots: list[str]) -> Iterator[None]:
    """Make everything in the common directory non-writable except the grants, then restore it."""
    grants, changed = [Path(root) for root in roots], []
    for parent, _, files in os.walk(common):
        for entry in (Path(parent), *(Path(parent) / name for name in files)):
            if not any(entry.is_relative_to(grant) for grant in grants):
                mode = stat.S_IMODE(entry.stat().st_mode)
                changed.append((entry, mode))
                entry.chmod(mode & ~0o222)
    try:
        yield
    finally:
        for entry, mode in reversed(changed):
            entry.chmod(mode)


def commit_in(worktree: Path, name: str, prefix: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Stage one new file and commit it; return the first step that failed, else the commit."""
    (worktree / name).write_text('member work\n')
    added = run_git(worktree, 'add', name, prefix=prefix)
    return added if added.returncode else run_git(worktree, 'commit', '-m', 'Member work', prefix=prefix)


def refused_writes(project: dict[str, Path], prefix: tuple[str, ...] = ()) -> list[str]:
    """Attempt each write a member must not have; return the ones that succeeded."""
    common = project['common'].resolve()
    targets = [common / 'config', common / 'hooks/pre-commit', common / 'packed-refs', common / 'packed-refs.lock',
               common / 'refs/heads/dev', common / 'refs/heads/dev.lock', common / 'refs/heads/other',
               common / 'refs/tags/release', common / 'worktrees/sibling/HEAD', common / 'worktrees/sibling/probe']
    succeeded = [str(path) for path in targets
                 if subprocess.run([*prefix, '/bin/sh', '-c', ': >> "$0"', str(path)], capture_output=True).returncode == 0]
    moved = run_git(project['member'], 'update-ref', 'refs/heads/dev', 'HEAD~0', prefix=prefix)
    configured = run_git(project['member'], 'config', 'core.hooksPath', '/tmp/hooks', prefix=prefix)
    return succeeded + ['update-ref dev'] * (moved.returncode == 0) + ['git config'] * (configured.returncode == 0)


class MemberTurn(FakeDshService):
    """Stand in for DSH only: on the prompt, start the MCP command the written patch names.

    ``plugin.mjs`` forwards the variables in FORWARDED and the two Session facts;
    the server is this host's descendant, as DSH's MCP client is under its owner.
    """

    answers: list[dict] = []
    failure: list[str] = []
    calls_to_make: list[tuple[str, str, dict]] = []

    def rpc(self, method: str, body: dict | None = None) -> dict:
        """Run the member's tool calls off the owner's lock, then end the turn."""
        if method != 'session/prompt':
            return super().rpc(method, body)
        with self.lock:
            self.running = True
            self.frames.append(self._event('turn/start', {}))
        threading.Thread(target=self.member_turn, daemon=True).start()
        return {'accepted': True}

    def _event(self, kind: str, data: dict) -> dict:
        """Number events from zero: a GraphTraj member's archive checks the native prefix."""
        frame = super()._event(kind, data)
        frame['event']['seq'] -= 1
        return frame

    def member_turn(self) -> None:
        """Speak stdio JSON-RPC to the real server, then close the native turn."""
        try:
            self.answers.extend(self.tool_calls())
        except Exception as error:
            self.failure.append(f'{type(error).__name__}: {error}')
        finally:
            with self.lock:
                self.frames.append(self._event('turn/end', {'reason': {'kind': 'completed'}}))

    def tool_calls(self) -> list[dict]:
        """Start the server with exactly what the plugin forwards; answer every call in order."""
        config = next(row['insert'][0]['config'] for row in self.patches
                      if 'insert' in row and row['insert'][0]['id'] == 'agents-mcp')
        forwarded = {'DSH_SESSION_ID': self.session, 'DSH_AGENT_SOURCE': 'main',
                     **{name: self.environment[name] for name in FORWARDED if name in self.environment}}
        # conftest requires this interpreter to resolve this checkout under -I, so the real command runs.
        server = subprocess.Popen([config['mcpCommand'], *config['mcpArgs']], cwd=self.cwd, env=forwarded,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        answers = []
        try:
            for number, (tool, feature, arguments) in enumerate(self.calls_to_make):
                call = {'action': 'discover'} if feature == 'discover' else {
                    'action': 'execute', 'feature': feature, 'arguments': arguments}
                server.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': number, 'method': 'tools/call',
                                               'params': {'name': tool, 'arguments': call}}) + '\n')
                server.stdin.flush()
                answers.append({'tool': tool, 'feature': feature, **json.loads(server.stdout.readline())})
        finally:
            server.stdin.close()
            server.wait(timeout=30)
        return answers


def test_a_member_uses_both_tools_and_its_round_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real connection and MCP entry: status, a report and a result, then a completed turn."""
    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    worktree = tmp_path / 'worktrees/research'
    report = '.state/teams/1/rounds/1/researcher-x1.md'
    monkeypatch.setenv('DSH_TEST_KEY', 'controlled-peer-key')
    monkeypatch.delenv('PYTHONPATH', raising=False)
    monkeypatch.setattr(execution, 'DshService', MemberTurn)
    monkeypatch.setattr(MemberTurn, 'instances', [])
    monkeypatch.setattr(MemberTurn, 'answers', [])
    monkeypatch.setattr(MemberTurn, 'failure', [])
    monkeypatch.setattr(MemberTurn, 'calls_to_make', [
        ('agents', 'status', {}),
        ('tasks', 'discover', {}),
        ('tasks', 'submit_report', {'name': 'researcher-x1.md', 'text': 'Member evidence'}),
        ('tasks', 'submit_result', {'commit': commit, 'result_refs': ['result.md'], 'evidence_refs': [report],
                                    'completion': 'Complete'}),
        ('tasks', 'session_reports', {'alias': 'research@x1'}),
    ])
    settings = {
        'executable': str(install_dsh(tmp_path / 'dsh')), 'package': str(tmp_path / 'dsh/package.json'),
        'tool': 'graphtraj-session', 'worktree_path': str(worktree), 'harness_root': str(tmp_path),
        'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoning_effort': None,
        'api_key_env': 'DSH_TEST_KEY', 'sandbox': 'workspace-write', 'instructions': 'Member',
        'reports': [report], 'git_common_directory': str(worktree / '.git'),
    }
    turn = execution.DshExecution(settings, 'Work', directory, lambda *_: None, lambda *_: None,
                                  tmp_path / 'trace.jsonl', None)

    with hold_ownership(directory, os.getpid()):
        outcome = turn.run()

    assert MemberTurn.failure == []
    answers = {answer['feature']: answer for answer in MemberTurn.answers}

    def answered(feature: str) -> dict:
        """The document one call returned; a refusal fails with the text the member saw."""
        assert 'result' in answers[feature], answers[feature]
        result = answers[feature]['result']
        assert not result['isError'], result['content'][0]['text']
        return result['structuredContent']

    answered('status')
    # The features the member's prompt names are the ones this tool really lists.
    listed = {item['feature'] for item in answered('discover')['features']}
    assert {'submit_report', 'submit_result', 'decide_result', 'session_reports'} <= listed
    answered('submit_report')
    submission = answered('submit_result')
    assert (submission['alias'], submission['candidate']) == ('research@x1', commit)
    assert (tmp_path / submission['evidence_refs'][0]).read_text() == 'Member evidence'
    assert answered('session_reports')['submissions'] == [submission]
    assert outcome['outcome'] == 'completed'

    [service] = MemberTurn.instances
    config = next(row['insert'][0] for row in service.patches
                  if 'insert' in row and row['insert'][0]['id'] == 'agents-mcp')['config']
    assert config == {'mcpCommand': str(Path(sys.executable).absolute()),
                      'mcpArgs': ['-I', '-m', 'graphtraj.interfaces.mcp'],
                      'mcpEnv': ['GRAPHTRAJ_CLI_CONNECTION']}
    assert 'GRAPHTRAJ_CLI_CONNECTION' in service.environment and 'GRAFTLING_CONNECTION' not in service.environment


def test_a_write_member_commits_with_only_the_granted_directories(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The written grants are enough to commit with auto-gc on, and nothing else opens."""
    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])
    assert granted(row) == expected_roots(project)
    before = checked_git(project['product'], 'rev-parse', 'agent/7-member')
    dev = checked_git(project['product'], 'rev-parse', 'dev')

    with only_granted_writable(project['common'], granted(row)):
        committed = commit_in(project['member'], 'work.txt')
        assert committed.returncode == 0, committed.stderr
        assert refused_writes(project) == []

    assert checked_git(project['product'], 'rev-parse', 'agent/7-member') != before
    assert checked_git(project['product'], 'rev-parse', 'dev') == dev
    assert checked_git(project['product'], 'log', '-1', '--format=%s', 'agent/7-member') == 'Member work'


def test_without_a_grant_the_same_commit_fails(project: dict[str, Path]) -> None:
    """The fence really refuses what the grants open, so the test above proves them."""
    before = checked_git(project['product'], 'rev-parse', 'agent/7-member')
    with only_granted_writable(project['common'], []):
        assert commit_in(project['member'], 'work.txt').returncode != 0
    assert checked_git(project['product'], 'rev-parse', 'agent/7-member') == before


def test_packed_refs_leave_no_missing_grant(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packing removes refs/heads/agent; the launch restores it, as DSH refuses a missing root."""
    checked_git(project['product'], 'pack-refs', '--all', '--prune')
    assert not (project['common'] / 'refs/heads/agent').exists()

    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])

    assert granted(row) == expected_roots(project)
    assert all(Path(root).is_dir() for root in granted(row))
    with only_granted_writable(project['common'], granted(row)):
        committed = commit_in(project['member'], 'work.txt')
        assert committed.returncode == 0, committed.stderr
        assert refused_writes(project) == []


@pytest.mark.parametrize('tamper', ['gitdir-file', 'symlink'])
def test_a_rewritten_worktree_pointer_does_not_move_the_grants(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tamper: str,
) -> None:
    """A member can rewrite its own .git, so a later launch must not read it."""
    pointer = project['member'] / '.git'
    pointer.unlink()
    if tamper == 'symlink':
        pointer.symlink_to(project['sibling'] / '.git')
    else:
        pointer.write_text(f"gitdir: {project['common'].resolve() / 'worktrees/sibling'}\n")

    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])

    assert granted(row) == expected_roots(project)


@pytest.mark.parametrize('head', ['ref: refs/heads/dev', 'ref: refs/heads/release/one', 'ref: refs/heads/agent/a/b',
                                  'ref: refs/heads/agent/../../../hooks/x', 'ref: refs/tags/agent/x',
                                  '0123456789012345678901234567890123456789'])
def test_a_head_outside_runners_branch_shape_grants_nothing(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch, head: str,
) -> None:
    """The grant makes the admin HEAD writable, so a rewrite must not aim a later launch elsewhere."""
    (project['common'] / 'worktrees/member/HEAD').write_text(head + '\n')

    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])

    assert 'additionalWritableRoots' not in row['config']


def test_a_worktree_git_does_not_list_grants_nothing(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmatched, ambiguous and primary checkouts all launch with no extra directory."""
    common = project['common']
    primary, _ = written_patch(tmp_path, monkeypatch, project['product'], common)
    assert 'additionalWritableRoots' not in primary['config']

    # A member can point its own record at a sibling: it loses its grant, the sibling gains nothing.
    recorded = common / 'worktrees/member/gitdir'
    recorded.write_text(str(project['sibling'] / '.git') + '\n')
    moved, _ = written_patch(tmp_path, monkeypatch, project['member'], common)
    ambiguous, _ = written_patch(tmp_path, monkeypatch, project['sibling'], common)
    assert 'additionalWritableRoots' not in moved['config']
    assert 'additionalWritableRoots' not in ambiguous['config']


def test_a_launch_record_older_than_the_field_still_launches(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Session recorded before this change resumes with no extra directory."""
    row, _ = written_patch(tmp_path, monkeypatch, project['member'], None)
    assert row['config'] == {'mode': 'workspace-write', 'workspaceRoot': str(project['member'])}


def test_a_read_only_member_gets_no_grant_and_cannot_write_git(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read access, including reports-only continuations, adds no key and opens nothing."""
    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'], 'read')

    assert row['config'] == {'mode': 'read-only', 'workspaceRoot': str(project['member'])}
    with only_granted_writable(project['common'], granted(row)):
        assert commit_in(project['member'], 'work.txt').returncode != 0
        assert refused_writes(project) == []


def test_seatbelt_enforces_the_written_grants(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DSH's own Seatbelt profile shape, without its /tmp roots: this project lives under /tmp."""
    def profile(roots: list[str]) -> str:
        """The dsh-sandbox-local profile for the workspace and the given roots."""
        allowed = ' '.join(f'(subpath {json.dumps(str(root))})' for root in roots)
        return ('(version 1) (allow default) (deny file-write*) (allow file-write* (literal "/dev/null")) '
                f'(allow file-write* {allowed})')

    probe = subprocess.run(['sandbox-exec', '-p', '(version 1) (allow default)', '/usr/bin/true'],
                           capture_output=True, text=True) if shutil.which('sandbox-exec') else None
    if probe is None or probe.returncode != 0:
        pytest.skip('sandbox-exec cannot apply here: ' + (probe.stderr.strip() if probe else 'not installed'))

    worktree = str(project['member'].resolve())
    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])
    before = checked_git(project['product'], 'rev-parse', 'agent/7-member')

    bare = ('sandbox-exec', '-p', profile([worktree]))
    assert commit_in(project['member'], 'denied.txt', bare).returncode != 0
    assert checked_git(project['product'], 'rev-parse', 'agent/7-member') == before

    fenced = ('sandbox-exec', '-p', profile([worktree, *granted(row)]))
    committed = commit_in(project['member'], 'work.txt', fenced)
    assert committed.returncode == 0, committed.stderr
    assert checked_git(project['product'], 'rev-parse', 'agent/7-member') != before
    assert refused_writes(project, fenced) == []


def test_the_installed_dsh_accepts_the_written_grants(
    tmp_path: Path, project: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed DSH's own sandbox derives the same roots; no service and no network."""
    node, installed = shutil.which('node'), shutil.which('dsh')
    if node is None or installed is None:
        pytest.skip('Installed DSH and Node are required for native sandbox evidence.')
    package_root = Path(installed).resolve().parent.parent
    row, _ = written_patch(tmp_path, monkeypatch, project['member'], project['common'])
    assert granted(row) == expected_roots(project)

    def derived(roots: list[str]) -> subprocess.CompletedProcess:
        """Ask the installed dsh-sandbox for the writable roots of this row's policy."""
        policy = {**row['config'], 'additionalWritableRoots': roots}
        return subprocess.run([node, str(ROOT / 'tests/fixtures/dsh_writable_roots.mjs'), str(package_root),
                               json.dumps(policy)], capture_output=True, text=True, timeout=30)

    accepted = derived(granted(row))
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout) == [str(project['member'].resolve()), *granted(row)]
    # The check bites: DSH refuses what the launch's mkdir and physical paths prevent.
    assert derived([str(project['common'] / 'refs/heads/missing')]).returncode != 0


def test_a_standalone_child_keeps_its_own_entry_and_policy(tmp_path: Path, dsh: dict) -> None:  # noqa: F811
    """No GraphTraj entry, variable or grant reaches the independent DSH child."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'dsh': dsh})
    invoke, _, _ = claude_main(host, tmp_path)
    try:
        invoke('wait', agent=invoke('create', runtime='dsh', instruction='x')['agent'], timeout_seconds=10)
    finally:
        stop_owned(host.control)
    [service] = FakeDshService.instances
    assert not [name for name in service.environment if name.startswith('GRAPHTRAJ_')]
    assert 'GRAFTLING_CONNECTION' in service.environment
    [plugin] = [row['insert'][0] for row in service.patches
                if 'insert' in row and row['insert'][0]['id'] == 'agents-mcp']
    assert plugin['config'] == {'mcpCommand': str(Path(sys.executable).absolute()),
                                'mcpArgs': ['-I', '-m', 'graftling.mcp'],
                                'mcpEnv': ['GRAFTLING_CONNECTION']}
    assert Path(plugin['name']).is_relative_to(ROOT / 'src/graftling')
    # Byte-identical to the row before this change: no extra key at all.
    assert next(row for row in service.patches if row.get('id') == 'sandbox-policy') == {
        'id': 'sandbox-policy', 'config': {'mode': 'workspace-write', 'workspaceRoot': str(tmp_path)}}


def test_only_a_caller_that_names_roots_changes_the_generic_row(tmp_path: Path) -> None:
    """The generic owner has no Git logic: the key follows the request, empty means absent."""
    package = tmp_path / 'package.json'
    package.write_text('{"version":"0.2.2-alpha.2"}')

    def row(**extra: object) -> dict:
        """The sandbox row the generic owner writes for one request."""
        settings = {'package': str(package), 'worktree_path': str(tmp_path), 'sandbox': 'workspace-write',
                    'unauthenticated': True, 'reasoning_effort': None, 'instructions': 'x', **extra}
        turn = native_execution.DshExecution(settings, 'x', tmp_path, lambda *_: None, lambda *_: None,
                                             tmp_path / 'trace.jsonl', None)
        patch = Path(turn.prepare_launch()['DSH_HOME']) / 'profiles/web/cordis.patch.yml'
        return next(item for item in yaml.safe_load(patch.read_text()) if item.get('id') == 'sandbox-policy')

    plain = {'id': 'sandbox-policy', 'config': {'mode': 'workspace-write', 'workspaceRoot': str(tmp_path)}}
    assert row() == row(additional_writable_roots=[]) == plain
    assert row(additional_writable_roots=['/a'])['config']['additionalWritableRoots'] == ['/a']
