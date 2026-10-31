"""Which directories a Pi attachment is never copied from, and who declares them.

agents protects its data root and Codex's directories. GraphTraj declares its own
``.graphtraj`` through the public keyword and attribute. The standalone tests import
only ``agent_swarm``; the GraphTraj tests import it inside their bodies.
"""
from __future__ import annotations

import json
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


def managed(tmp_path: Path, *, independent: bool):
    """Build GraphTraj's real execution on the Runner or the agents driver path."""
    from graphtraj.runtimes.pi.managed_session import PiManagedExecution

    turn = PiManagedExecution({'harness_root': str(tmp_path), 'worktree_path': str(tmp_path)}, 'go',
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
            {'type': 'agent_end', 'piNative': {'entries': [entry(secret, ordinary)], 'leafId': 'm1'}}]
    result = CliRunner().invoke(main, ['pi', '--collect'], input=''.join(json.dumps(line) + '\n' for line in pipe))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {'ready': True}
    archive = bound_archive(swarm_root(tmp_path))
    key = archive.native_id('pi', 'attachments')
    archive.map_session(JsonlSessionStore(archive_path(archive.root, key)).header)
    found = references(archive, key)
    assert_missing(found[0])
    assert_copied(found[1], archive)
    assert [list(paths) for paths in declared] == [[tmp_path / '.graphtraj']]
