"""Keep DSH's cursorless assistant frames separate from its Session log."""

from __future__ import annotations

from copy import deepcopy
from typing import Callable


def append_chunk(stream: list[dict], frame: dict) -> None:
    """Compact adjacent native deltas, retaining every original chunk time.

    This is DSH's text/reasoning/tool-call run representation. Unknown fields
    remain raw records instead of disappearing in a recognized run.
    """
    chunk, time = deepcopy(frame['chunk']), frame['time']
    kind = chunk['type']
    allowed = {'type', 'index', 'text'}
    if kind == 'tool-call-delta':
        allowed = {'type', 'index', 'id', 'name', 'argumentsDelta'}
    if (kind not in {'text-delta', 'reasoning-delta', 'tool-call-delta'}
            or set(chunk) - allowed
            or kind == 'tool-call-delta' and (not chunk['id'] or chunk.get('name') == '')):
        stream.append({'type': 'chunk', 'time': time, 'chunk': chunk})
        return

    member = 'args' if kind == 'tool-call-delta' else 'texts'
    value = chunk['argumentsDelta'] if member == 'args' else chunk['text']
    identity = {'type': kind.replace('-delta', '-chunks'), 'index': chunk['index']}
    if member == 'args':
        identity['id'] = chunk['id']
        if 'name' in chunk:
            identity['name'] = chunk['name']
    previous = stream[-1] if stream else None
    gap = (time - previous['time0'] - sum(previous['dt'])
           if previous is not None and 'time0' in previous else None)
    if (previous is not None and gap is not None and abs(gap) <= 2**53 - 1
        and all(previous.get(key) == value for key, value in identity.items())
        and (member != 'args' or ('name' in previous) == ('name' in identity))
    ):
        previous['dt'].append(gap)
        previous[member].append(value)
    else:
        stream.append({**identity, 'time0': time, 'dt': [], member: [value]})


class DshLiveFrames:
    """Checkpoint one live attempt; resolve only the native terminal seq link.

    Attempt IDs are Agent-lifecycle-local. The owning execution qualifies their
    archive locator, so restarting the same Session cannot collide with an old
    attempt. Neither a revision nor a chunk index is a Session event seq.
    """

    def __init__(
        self,
        session_id: str,
        execution_id: str,
        checkpoint: Callable[[dict, int], None],
        resolve: Callable[[tuple[str, str, str], tuple[str, str, str]], None],
    ) -> None:
        """Bind host-owned persistence callbacks without selecting event order."""
        self.session_id = session_id
        self.execution_id = execution_id
        self.checkpoint = checkpoint
        self.resolve = resolve
        self.attempt: dict | None = None
        self.revision = 0

    def baseline(self, baseline: dict) -> None:
        """Restore the native reconnect snapshot, whose chunks precede its cut."""
        self.revision = baseline['revision']
        active = baseline.get('activeAttempt')
        if active is not None:
            self.attempt = deepcopy(active)
            self._save()

    def accept(self, frame: dict) -> None:
        """Accept dense native frames, preserving interruption and terminal links."""
        revision = frame['revision']
        if revision <= self.revision:
            return
        if revision != self.revision + 1:
            raise ValueError('DSH assistant frames have a missing native revision.')
        self.revision = revision
        if frame['type'] == 'start':
            self.attempt = {**deepcopy(frame), 'nextIndex': 0, 'stream': []}
        else:
            if self.attempt is None or frame['attemptId'] != self.attempt['attemptId']:
                raise ValueError('DSH assistant frame does not belong to its active attempt.')
            if frame['index'] != self.attempt['nextIndex']:
                raise ValueError('DSH assistant frames have a missing native chunk index.')
            if frame['type'] == 'chunk':
                append_chunk(self.attempt['stream'], frame)
                self.attempt['nextIndex'] += 1
            elif frame['type'] == 'end':
                self.attempt['outcome'] = deepcopy(frame['outcome'])
            else:
                raise ValueError('Unknown DSH assistant frame type.')
        self._save()
        if frame['type'] == 'end':
            if frame['outcome']['kind'] == 'committed':
                self.resolve(self._key(), ('dsh', self.session_id, f"event/{frame['outcome']['seq']}"))
            self.attempt = None

    def _key(self) -> tuple[str, str, str]:
        """Return a live observation identity, never a canonical event position."""
        return ('dsh', self.session_id,
                f"live/{self.execution_id}/{self.attempt['attemptId']}")

    def _save(self) -> None:
        """Persist compact content before accepting the next cursorless frame."""
        attempt = self.attempt
        if attempt is None:
            return
        event = {
            'type': 'assistant/attempt', 'seq': 0, 'time': 0,
            'data': {'turn': attempt['turn'], 'step': attempt['step'],
                     'stream': deepcopy(attempt['stream'])},
            'native': {'runtime': 'dsh', 'sessionId': self.session_id,
                       'locator': self._key()[2], 'record': deepcopy(attempt)},
            'missing': [{'path': 'time', 'reason': 'Live frames do not have a Session event creation time.'}],
        }
        self.checkpoint(event, self.revision)
