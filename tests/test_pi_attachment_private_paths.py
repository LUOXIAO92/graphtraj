"""Which directories a Pi attachment is never copied from, and who declares them.

agents protects its data root and Codex's directories. GraphTraj declares its own
``.graphtraj`` through the public keyword and attribute. The standalone tests import
only ``agent_swarm``; the GraphTraj tests import it inside their bodies.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from agent_swarm import default_config
from agent_swarm.sessions import JsonlSessionStore, PiArchive, SessionArchive, archive_path


def bound_archive(root: Path) -> SessionArchive:
    """Open an archive with saving on, as the hosts do."""
    return SessionArchive(root, **default_config(root, save_normalized_sessions=True))


def write(path: Path, content: bytes = b'private bytes') -> Path:
    """Create one file with its parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def header(cwd: Path, session: str = 'attachments') -> dict:
    """Return a native Pi Session header."""
    return {'type': 'session', 'id': session, 'version': 3, 'timestamp': 0, 'cwd': str(cwd)}


def entry(*paths: Path) -> dict:
    """Return one native message that names each path as an attachment."""
    return {'type': 'message', 'id': 'm1', 'parentId': None, 'message': {
        'role': 'user', 'content': [{'type': 'file', 'path': str(path)} for path in paths]}}


def collected(collector: PiArchive, *paths: Path) -> list[dict]:
    """Publish one message after activation and return its attachment references."""
    collector.sync([entry(*paths)], 'm1', settled=True)
    return references(collector.archive, collector.key)


def references(archive: SessionArchive, key: str) -> list[dict]:
    """Read the attachment references of the archive's native message."""
    events = archive.store(key).page(limit=100)['events']
    return next(event for event in events if event['type'] == 'native')['attachments']


def standalone(tmp_path: Path, project: Path, *paths: Path, attachment_root: Path | None = None,
               data: Path | None = None, **options: object) -> tuple[list[dict], SessionArchive]:
    """Collect the paths through a directly built ``PiArchive``."""
    archive = bound_archive(data or tmp_path / 'data')
    collector = PiArchive(archive, header(project), project=str(project), entries=[], leaf_id=None,
                          attachment_root=attachment_root or project, **options)
    return collected(collector, *paths), archive


def assert_copied(reference: dict, archive: SessionArchive, content: bytes = b'private bytes') -> None:
    """The bytes were copied into the Session's archive and can be read back."""
    assert 'missing' not in reference
    assert archive.store(archive.native_id('pi', 'attachments')).attachment(reference['sha256']) == content


def assert_missing(reference: dict) -> None:
    """The attachment reads as missing and no bytes were copied."""
    assert 'sha256' not in reference
    assert reference['missing']['reason'] == 'Outside the host-authorized attachment directory.'


def test_standalone_copies_an_attachment_under_graphtraj(tmp_path: Path) -> None:
    """A ``.graphtraj`` directory means nothing to agents alone."""
    project = tmp_path / 'project'
    attachment = write(project / '.graphtraj/x')
    found, archive = standalone(tmp_path, project, attachment)
    assert_copied(found[0], archive)


def test_standalone_copies_it_with_no_graphtraj_package(tmp_path: Path) -> None:
    """An isolated Python that cannot import GraphTraj gives the same copy."""
    source = Path(__file__).resolve().parents[1] / 'src/agent_swarm'
    shutil.copytree(source, tmp_path / 'agent_swarm', ignore=shutil.ignore_patterns('__pycache__'))
    program = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agent_swarm import write_config
from agent_swarm.sessions.archive import ConfiguredSessionArchive
from agent_swarm.sessions.pi import PiArchive
base = Path(sys.argv[1])
project = base / 'project'
(project / '.graphtraj').mkdir(parents=True)
(project / '.graphtraj/x').write_bytes(b'bytes')
write_config(base / 'data', save_normalized_sessions=True)
archive = ConfiguredSessionArchive(base / 'data')
collector = PiArchive(archive, {'type': 'session', 'id': 's', 'version': 3, 'timestamp': 0, 'cwd': str(project)},
                      project=str(project), entries=[], leaf_id=None, attachment_root=project)
collector.sync([{'type': 'message', 'id': 'm1', 'parentId': None, 'message': {'role': 'user', 'content': [
    {'type': 'file', 'path': str(project / '.graphtraj/x')}]}}], 'm1', settled=True)
store = archive.store(collector.key)
reference = next(e for e in store.page(limit=10)['events'] if e['type'] == 'native')['attachments'][0]
assert store.attachment(reference['sha256']) == b'bytes', reference
assert not any(name == 'graphtraj' or name.startswith('graphtraj.') for name in sys.modules)
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', program, str(tmp_path)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_standalone_keeps_its_own_private_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The data root, ``<project>/.codex`` and ``~/.codex`` read as missing."""
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    project = home / 'project'
    data = home / 'data'
    ordinary = write(project / 'ordinary')
    found, archive = standalone(
        tmp_path, project, write(project / '.codex/x'), write(home / '.codex/x'), write(data / 'x'), ordinary,
        attachment_root=home, data=data)
    for reference in found[:3]:
        assert_missing(reference)
    assert_copied(found[3], archive)


def test_private_paths_keyword_reads_as_missing(tmp_path: Path) -> None:
    """A caller's further directory is protected; its sibling is not."""
    project = tmp_path / 'project'
    found, archive = standalone(
        tmp_path, project, write(project / 'kept/x'), write(project / 'other/x'),
        private_paths=iter([project / 'kept']))
    assert_missing(found[0])
    assert_copied(found[1], archive)


@pytest.mark.parametrize('target', ['.codex/x', '~/.codex/x', 'data/x', 'kept/x'])
def test_symlink_into_a_private_directory_reads_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    """A link inside the authorized directory does not reach private bytes."""
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    project = home / 'project'
    data = home / 'data'
    private = (home / target[2:]) if target.startswith('~') else (
        data / 'x' if target == 'data/x' else project / target)
    write(private)
    project.mkdir(exist_ok=True)
    link = project / 'link'
    link.symlink_to(private)
    options = {'private_paths': [project / 'kept']} if target == 'kept/x' else {}
    found, _ = standalone(tmp_path, project, link, attachment_root=home, data=data, **options)
    assert_missing(found[0])


@pytest.mark.parametrize('place', ['project', 'home', 'declared'])
def test_private_directory_that_is_itself_a_link_stays_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str,
) -> None:
    """The compared attachment path is resolved, so the private path must be too."""
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    project = home / 'project'
    linked = {'project': project / '.codex', 'home': home / '.codex', 'declared': project / 'kept'}[place]
    attachment = write(home / 'dotfiles' / place / 'auth.json')
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(attachment.parent, target_is_directory=True)
    options = {'private_paths': [linked]} if place == 'declared' else {}
    found, _ = standalone(tmp_path, project, linked / 'auth.json', attachment_root=home, **options)
    assert_missing(found[0])


def managed(tmp_path: Path, *, independent: bool, worktree: Path | None = None):
    """Build GraphTraj's real execution on the Runner or the agents driver path."""
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    turn = PiManagedExecution({'harness_root': str(tmp_path), 'worktree_path': str(worktree or tmp_path)}, 'go',
                              tmp_path / 'alias', None, None, tmp_path / 'trace.jsonl', None)
    turn.session = 'attachments'
    if independent:
        turn.independent = True
        turn.archive = bound_archive(tmp_path / 'agents-data')
        turn.extra_fields = None
    return turn


@pytest.mark.parametrize('independent', [False, True], ids=['runner', 'agents-driver'])
def test_graphtraj_execution_protects_its_directory_and_declares_it(tmp_path: Path, independent: bool) -> None:
    """Both GraphTraj paths keep ``.graphtraj`` out, by declaring it publicly."""
    secret = write(tmp_path / '.graphtraj/x')
    ordinary = write(tmp_path / 'ordinary')
    turn = managed(tmp_path, independent=independent)
    collector = turn.archive_collector(header(tmp_path), {'entries': [], 'leafId': None})
    found = collected(collector, secret, ordinary)
    assert_missing(found[0])
    assert_copied(found[1], turn.archive)
    assert list(turn.archive_private_paths) == [tmp_path / '.graphtraj']


def test_graphtraj_collection_entry_protects_its_directory_and_declares_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extension's collector entry runs the same rule, by declaring it publicly."""
    from click.testing import CliRunner
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.interfaces.agents import swarm_root
    from graphtraj.runtimes.native_entry import main

    tmp_path = tmp_path.resolve()
    write(tmp_path / '.graphtraj/config.yml', default_configuration_content(tmp_path, tmp_path).encode())
    secret = write(tmp_path / '.graphtraj/x')
    ordinary = write(tmp_path / 'ordinary')
    in_worktree = write(tmp_path / '.graphtraj/.agent-worktrees/member/x')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', 'attachments')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION_FILE', str(tmp_path / 'native.jsonl'))
    monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    declared = []
    construct = PiArchive.__init__

    def recording(self, *arguments, **options) -> None:
        """Keep what the entry passed, then build the real collector."""
        declared.append(options.get('private_paths', ()))
        construct(self, *arguments, **options)

    monkeypatch.setattr(PiArchive, '__init__', recording)
    pipe = [{'header': header(tmp_path), 'entries': [], 'leafId': None},
            {'type': 'agent_end', 'piNative': {'entries': [entry(secret, ordinary, in_worktree)], 'leafId': 'm1'}}]
    result = CliRunner().invoke(main, ['pi', '--collect'], input=''.join(json.dumps(line) + '\n' for line in pipe))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {'ready': True}
    archive = bound_archive(swarm_root(tmp_path))
    key = archive.native_id('pi', 'attachments')
    archive.map_session(JsonlSessionStore(archive_path(archive.root, key)).header)
    found = references(archive, key)
    assert_missing(found[0])
    assert_copied(found[1], archive)
    # The entry runs with cwd at the Harness Root, so the whole directory stays declared.
    assert_missing(found[2])
    assert [list(paths) for paths in declared] == [[tmp_path / '.graphtraj']]


# Where each project layout keeps the Worktree Directory; ``core_directory`` picks
# the layout from where config.yml sits, so the config is written beside its layout.
LAYOUTS = {'migrated': ('.graphtraj/core', '.graphtraj/core/worktrees'),
           'default': ('.graphtraj', '.graphtraj/.agent-worktrees')}
MEMBER = '425-member'
each_path = pytest.mark.parametrize('independent', [False, True], ids=['runner', 'agents-driver'])
each_layout = pytest.mark.parametrize('layout', list(LAYOUTS))


def configure(root: Path, layout: str = 'migrated', worktrees: str | None = None, state: str | None = None) -> Path:
    """Write a real config for one layout and return the configured Worktree Directory."""
    from graphtraj.configuration.project_configuration import default_configuration_content
    import yaml

    core, default = LAYOUTS[layout]
    document = yaml.safe_load(default_configuration_content(root, root))
    document['paths'].update(agent_worktrees=worktrees or default, state=state or core + '/state')
    write(root / core / 'config.yml', yaml.safe_dump(document).encode())
    return root / (worktrees or default)


def member_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str) -> tuple[Path, Path]:
    """Return a Harness Root in a private Home and the member's Worktree, built as Runner builds it."""
    home = (tmp_path / 'home').resolve()
    monkeypatch.setenv('HOME', str(home))
    root = home / 'project'
    worktree = configure(root, layout) / MEMBER
    worktree.mkdir(parents=True)
    return root, worktree


def member_collected(root: Path, cwd: Path, independent: bool, *paths: Path) -> tuple[list[dict], SessionArchive]:
    """Collect the paths through the real ``archive_collector`` of a member at ``cwd``."""
    turn = managed(root, independent=independent, worktree=cwd)
    collector = turn.archive_collector(header(cwd), {'entries': [], 'leafId': None})
    return collected(collector, *paths), turn.archive


@each_layout
@each_path
def test_member_reads_files_of_its_own_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, independent: bool,
) -> None:
    """Absolute, cwd-relative and nested files and an inner link are all copied."""
    root, worktree = member_project(tmp_path, monkeypatch, layout)
    write(worktree / 'plain', b'plain')
    write(worktree / 'a/b/nested', b'nested')
    (worktree / 'link').symlink_to('a/b/nested')
    cases = {worktree / 'plain': b'plain', Path('plain'): b'plain', worktree / 'a/b/nested': b'nested',
             Path('a/b/nested'): b'nested', worktree / 'link': b'nested'}
    found, archive = member_collected(root, worktree, independent, *cases)
    for reference, content in zip(found, cases.values(), strict=True):
        assert_copied(reference, archive, content)


@each_layout
@each_path
def test_member_working_in_a_subdirectory_reads_files_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, independent: bool,
) -> None:
    """A subdirectory is authorized for its own files, and only those."""
    root, worktree = member_project(tmp_path, monkeypatch, layout)
    inside = write(worktree / 'sub/x', b'inside')
    beside = write(worktree / 'beside/x')
    found, archive = member_collected(root, worktree / 'sub', independent, inside, Path('x'), beside)
    assert_copied(found[0], archive, b'inside')
    assert_copied(found[1], archive, b'inside')
    assert_missing(found[2])


def refused_paths(root: Path, worktree: Path) -> dict[str, Path]:
    """Create everything a member's attachment must not reach, under the name of each case."""
    from graphtraj.configuration.project_configuration import core_directory

    core = core_directory(root)
    other = worktree.parent / 'other'
    write(other / 'x')
    (worktree / 'other-link').symlink_to(os.path.relpath(other / 'x', worktree))
    state = write(core / 'state/tasks/425-member/x')
    (worktree / '.state').symlink_to(os.path.relpath(state.parent, worktree), target_is_directory=True)
    (worktree / 'docs').symlink_to(os.path.relpath(write(root / 'docs/x').parent, worktree), target_is_directory=True)
    (worktree / 'CONTEXT.md').symlink_to(os.path.relpath(write(root / 'CONTEXT.md'), worktree))
    write(worktree / '.graphtraj/x')
    (worktree / 'private-link').symlink_to('.graphtraj/x')
    write(worktree.parent / (MEMBER + '-more/x'))
    return {
        'own .graphtraj': worktree / '.graphtraj/x',
        'own .graphtraj, relative': Path('.graphtraj/x'),
        'own .graphtraj, by link': worktree / 'private-link',
        'own .codex': write(worktree / '.codex/x'),
        'own .codex, relative': Path('.codex/x'),
        'other Worktree': other / 'x',
        'other Worktree, relative': Path('../other/x'),
        'other Worktree, by link': worktree / 'other-link',
        'prefix sibling': worktree.parent / (MEMBER + '-more/x'),
        'prefix sibling, relative': Path('../' + MEMBER + '-more/x'),
        '.state link': worktree / '.state/x',
        'docs link': worktree / 'docs/x',
        'CONTEXT.md link': worktree / 'CONTEXT.md',
        'state': write(core / 'state/x'),
        'runner': write(core / 'runner/x'),
        'config': core / 'config.yml',
        'roles': write(core / 'roles.yml'),
        'swarm': write(root / '.graphtraj/swarm/x'),
        'project .codex': write(root / '.codex/x'),
        'home .codex': write(Path.home() / '.codex/x'),
    }


@each_layout
@each_path
def test_member_reads_nothing_outside_its_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str, independent: bool,
) -> None:
    """Every protected path reads as missing, while the member's own file beside them is copied."""
    root, worktree = member_project(tmp_path, monkeypatch, layout)
    refused = refused_paths(root, worktree)
    own = write(worktree / 'own', b'own bytes')
    found, archive = member_collected(root, worktree, independent, *refused.values(), own)
    copied = [name for name, reference in zip(refused, found, strict=False) if 'missing' not in reference]
    assert copied == []
    for reference in found[:-1]:
        assert_missing(reference)
    assert_copied(found[-1], archive, b'own bytes')
    stored = [path for path in (archive.root / 'sessions').rglob('*') if path.is_file()]
    assert not [path for path in stored if b'private bytes' in path.read_bytes()]


@pytest.mark.parametrize('private', ['.graphtraj', '.codex'])
def test_member_working_inside_its_private_directory_reads_nothing_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private: str,
) -> None:
    """The private directories are the Worktree's own, also for a subdirectory below them."""
    root, worktree = member_project(tmp_path, monkeypatch, 'migrated')
    found, _ = member_collected(root, worktree / private / 'sub', False, write(worktree / private / 'sub/x'))
    assert_missing(found[0])


@each_layout
def test_declaration_narrows_for_a_worktree_in_the_worktree_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str,
) -> None:
    """The top Worktree directory is named however the attachment directory is spelled."""
    from graphtraj.interfaces.agents import attachment_private_paths

    root, worktree = member_project(tmp_path, monkeypatch, layout)
    (worktree / 'sub/deep').mkdir(parents=True)
    (root / 'entry').symlink_to(worktree, target_is_directory=True)
    expected = [worktree / '.graphtraj', worktree / '.codex']
    for directory in (worktree, worktree / 'sub', worktree / 'sub/deep', str(worktree), root / 'entry',
                      worktree / '../' / MEMBER, worktree / '.graphtraj/sub'):
        assert attachment_private_paths(root, directory) == expected, directory


def whole_directory_cases() -> dict:
    """Name every attachment directory that keeps all of ``.graphtraj`` declared."""
    def layout_case(place: str) -> object:
        """Build the case for ``place`` under the migrated layout's core directory."""
        return lambda root: (configure(root), root / place)[1]

    def default_layout_case(place: str) -> object:
        """Build the case for ``place`` under the default layout."""
        return lambda root: (configure(root, 'default'), root / place)[1]

    def link_out(root: Path) -> Path:
        """A Worktree Directory entry that resolves out of it, to the state directory."""
        worktrees = configure(root)
        worktrees.mkdir(parents=True)
        (worktrees / 'link').symlink_to(root / '.graphtraj/core/state', target_is_directory=True)
        return worktrees / 'link'

    def link_to_root(root: Path) -> Path:
        """A Worktree Directory entry that resolves to the Harness Root."""
        worktrees = configure(root)
        worktrees.mkdir(parents=True)
        (worktrees / 'link').symlink_to(root, target_is_directory=True)
        return worktrees / 'link'

    def config_text(text: str) -> object:
        """Build a case whose config file holds ``text``."""
        return lambda root: (write(root / '.graphtraj/core/config.yml', text.encode()),
                             root / '.graphtraj/core/worktrees/member')[1]

    def linked_config(root: Path) -> Path:
        """A config file that is a link is refused by the loader."""
        configure(root)
        config = root / '.graphtraj/core/config.yml'
        config.rename(root / 'elsewhere.yml')
        config.symlink_to(root / 'elsewhere.yml')
        return root / '.graphtraj/core/worktrees/member'

    def outside(root: Path) -> Path:
        """A Worktree Directory configured outside ``.graphtraj``."""
        return configure(root, worktrees='worktrees', state='.graphtraj/core/state') / 'member'

    def data_directory_itself(root: Path) -> Path:
        """A Worktree Directory that is ``.graphtraj`` itself holds everything; nothing narrows."""
        configure(root, worktrees='.graphtraj', state='state')
        return root / '.graphtraj/core'

    return {
        'no argument': lambda root: (configure(root), None)[1],
        'harness root': layout_case('.'),
        '.graphtraj': layout_case('.graphtraj'),
        '.graphtraj/core': layout_case('.graphtraj/core'),
        'worktree directory': layout_case('.graphtraj/core/worktrees'),
        'prefix of worktree directory': layout_case('.graphtraj/core/worktrees-more/member'),
        'state': layout_case('.graphtraj/core/state'),
        'state task': layout_case('.graphtraj/core/state/tasks/425-member'),
        'runner': layout_case('.graphtraj/core/runner'),
        'swarm': layout_case('.graphtraj/swarm'),
        'other under .graphtraj': layout_case('.graphtraj/other/member'),
        'old layout worktree beside a migrated config': layout_case('.graphtraj/.agent-worktrees/member'),
        'default layout .graphtraj': default_layout_case('.graphtraj'),
        'default layout worktree directory': default_layout_case('.graphtraj/.agent-worktrees'),
        'default layout state': default_layout_case('.graphtraj/state'),
        'default layout runner': default_layout_case('.graphtraj/runner'),
        'link to state': link_out,
        'link to harness root': link_to_root,
        'worktree directory outside .graphtraj': outside,
        'worktree directory is .graphtraj': data_directory_itself,
        'missing config': lambda root: root / '.graphtraj/core/worktrees/member',
        'linked config': linked_config,
        'config not yaml': config_text('{'),
        'config wrong shape': config_text('version: 1\n'),
        'config raises ValueError': config_text('version: 2001-13-45\n'),
        'config raises RecursionError': config_text('[' * 20000),
        'directory with NUL': lambda root: (configure(root), str(root / '.graphtraj/core/worktrees/a\0b'))[1],
    }


@pytest.mark.parametrize('case', list(whole_directory_cases()))
def test_declaration_keeps_the_whole_directory_otherwise(tmp_path: Path, case: str) -> None:
    """Only a real Worktree narrows; everything else, and any bad config, stays as it was."""
    from graphtraj.interfaces.agents import attachment_private_paths

    root = tmp_path.resolve()
    directory = whole_directory_cases()[case](root)
    assert attachment_private_paths(root, directory) == [root / '.graphtraj']


def test_execution_without_a_worktree_keeps_the_whole_directory(tmp_path: Path) -> None:
    """A captured request that names no Worktree still builds, with everything declared."""
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    turn = PiManagedExecution({'harness_root': str(tmp_path)}, 'go', tmp_path / 'alias', None, None,
                              tmp_path / 'trace.jsonl', None)
    assert list(turn.archive_private_paths) == [tmp_path / '.graphtraj']


@pytest.mark.parametrize('owner', ['plugin-child', 'runner', 'agents-driver'])
def test_extension_in_a_worktree_never_spawns_the_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str,
) -> None:
    """``--collect`` exits 1 in a Worktree, and the real extension's session_start never reaches it.

    A characterisation of existing behaviour: it also passes on the code before the fix.
    """
    if shutil.which('node') is None:
        pytest.skip('node is not installed')
    root, worktree = member_project(tmp_path, monkeypatch, 'migrated')
    record = tmp_path / 'spawned.txt'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    command = bin_dir / 'graphtraj-session'
    command.write_text(f"""#!{sys.executable}
import sys
with open({str(record)!r}, 'a') as spawned:
    spawned.write(' '.join(sys.argv[1:]) + '\\n')
from graphtraj.runtimes.native_entry import main
main()
""")
    command.chmod(0o755)
    source = Path(__file__).resolve().parents[1] / 'src'
    for name in ('AGENT_SWARM_CONNECTION', 'AGENT_SWARM_PYTHON', 'GRAPHTRAJ_CLI_CONNECTION', 'PI_SUBAGENT_CHILD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('PYTHONPATH', str(source))
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_RUNTIME', 'pi')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION', 'attachments')
    monkeypatch.setenv('GRAPHTRAJ_NATIVE_SESSION_FILE', str(tmp_path / 'native.jsonl'))
    direct = subprocess.run([str(command), 'pi', '--collect'], cwd=worktree, input='', capture_output=True,
                            text=True, timeout=30, check=False)
    assert direct.returncode == 1
    assert 'GraphTraj Config was not found' in direct.stderr
    record.unlink()
    if owner == 'plugin-child':
        monkeypatch.setenv('PI_SUBAGENT_CHILD', '1')
    elif owner == 'runner':
        monkeypatch.setenv('GRAPHTRAJ_CLI_CONNECTION', 'unused')
    else:
        monkeypatch.setenv('AGENT_SWARM_CONNECTION', 'unused')
        monkeypatch.setenv('AGENT_SWARM_PYTHON', sys.executable)
    script = """
import { pathToFileURL } from 'node:url';
const { default: graphtraj } = await import(pathToFileURL(process.argv[1]).href);
const handlers = [], notices = [], servers = [];
graphtraj({registerFlag() {}, getFlag() {}, registerMcpServer(name) { servers.push(name); },
  on(name, handler) { if (name === 'session_start') handlers.push(handler); }});
const header = {type: 'session', version: 3, id: 'attachments', cwd: process.cwd(), timestamp: 0};
const sessionManager = {getSessionId: () => 'attachments', getSessionFile: () => '', getHeader: () => header,
  getEntries: () => [], getLeafId: () => null};
const ctx = {cwd: process.cwd(), hasUI: false, sessionManager,
  ui: {notify(message, level) { notices.push({message, level}); }}};
for (const handler of handlers) await handler({reason: 'startup'}, ctx);
console.log(JSON.stringify({notices, servers}));
"""
    # A rejected session_start exits node nonzero, so check=True pins that the handler resolved.
    result = subprocess.run(['node', '--input-type=module', '-e', script,
                             str(source / 'graphtraj/runtimes/pi/extension.mjs')],
                            cwd=worktree, check=True, timeout=30, capture_output=True, text=True)
    outcome = json.loads(result.stdout)
    spawned = record.read_text().splitlines() if record.exists() else []
    assert not [line for line in spawned if '--collect' in line]
    if owner == 'agents-driver':
        # extension.mjs returns before any native entry: an agents connection owns the Session.
        assert (spawned, outcome) == ([], {'notices': [], 'servers': ['agents']})
    else:
        assert spawned == ['pi']
        assert [notice['level'] for notice in outcome['notices']] == ['error']
        assert 'GraphTraj Config was not found' in outcome['notices'][0]['message']
        assert outcome['servers'] == ['graphtraj']
