"""Make and read real Session archives with whichever agent_swarm this Python has (rehearse.zsh).

  create <sessions> <version> <name>...  a new archive through the installed code's own writer
  upgrade <sessions> <name>              let the installed code change one, as 0.2.4 at work does
  oldread <sessions>                     every read the old reader needs, including native_header
"""
import json
from pathlib import Path
import sys

from agent_swarm.sessions.archive import JsonlSessionStore
from agent_swarm.sessions.protocol import SESSION_FORMAT_VERSION


def header(name: str) -> dict:
    return {'version': SESSION_FORMAT_VERSION, 'id': f'{name}-{"0" * 8}', 'createdAt': 1, 'isSeeded': False}


def create(sessions: str, version: str, *names: str) -> None:
    if int(version) != SESSION_FORMAT_VERSION:
        sys.exit(f'this code writes version {SESSION_FORMAT_VERSION}, not {version}')
    for name in names:
        store = JsonlSessionStore.create(Path(sessions) / name / 'session.jsonl', header(name))
        print('created', name, 'version', store.header['version'])


def upgrade(sessions: str, name: str) -> None:
    path = Path(sessions) / name / 'session.jsonl'
    store = JsonlSessionStore(path)
    store.mark_boundary('after-install', 0)
    first = json.loads(path.read_text(encoding='utf-8').splitlines()[0])
    print('rewritten', name, 'file version now', first['header']['version'])


def oldread(sessions: str) -> None:
    from agent_swarm.sessions.archive import SessionArchive

    print('reader expects version', SESSION_FORMAT_VERSION)
    for path in sorted(Path(sessions).glob('*/session.jsonl')):
        store = JsonlSessionStore(path)
        print('read', path.parent.name, 'version', store.header['version'], 'events', len(store._events))
    # The lookup that globs every archive: one v5 file makes this raise.
    print('native_header lookup:', SessionArchive(Path(sessions).parent).native_header('claude', 'no-such-native'))


OPERATIONS = {'create': create, 'upgrade': upgrade, 'oldread': oldread}
OPERATIONS[sys.argv[1]](*sys.argv[2:])
