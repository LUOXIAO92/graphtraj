"""Claude native per-call identity shared by independent and project hosts."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import threading
import time
from typing import Callable
from uuid import UUID
from agent_swarm import AgentsError, AgentsResult

class NativeCalls:
    """Consume each current native association exactly once, never a startup ID.

    The mod prepares an association during Claude's permission check and ends
    it when that native call ends. Calls run concurrently, so several can be
    prepared, but only from one native Session at a time: an MCP request names
    no Session, so another Session's preparation is refused meanwhile.
    Preparing one exact call again keeps its one association. Two identical
    calls in flight therefore share it: the second is refused and can repeat.

    Claude can end a call it moved to the background before its request is
    read. Such an association is kept for that request only while a call of
    the same native Session executes; a preparation from another Session drops
    it, so it never crosses Sessions.
    """

    def __init__(
        self, make_call: Callable[[str, Path], Callable], cwd: Path, runner: Path | None = None,
    ) -> None:
        """Bind the backend factory, permitted native cwd and the notice queue's project."""
        self.make_call = make_call
        self.cwd = cwd.resolve()
        self.runner = runner
        self.prepared: list[dict] = []
        # Ended associations whose request may still arrive.
        self.queued: list[dict] = []
        self.running: list[dict] = []
        self.lock = threading.Lock()

    def context(self, document: dict) -> dict:
        """Accept only authenticated mod facts; this is not a model tool."""
        with self.lock:
            operation = document.get('operation')
            if operation == 'end':
                return self.end(document)
            if operation in {'notices', 'acknowledge', 'requeue'}:
                return self.notices(document)
            if operation != 'prepare' or set(document) != {'operation', 'tool', 'session', 'cwd', 'agent', 'request'}:
                raise AgentsError('invalid-input', 'Expected one native per-call context.')
            if document['tool'] not in {'agents', 'tasks'}:
                raise AgentsError('invalid-input', 'Expected the agents or tasks entry.')
            if document['agent'] is not None:
                raise AgentsError('authority-denied', 'A native subagent cannot adopt the Main association.')
            if (not isinstance(document['session'], str)
                    or str(UUID(document['session'])) != document['session']
                    or Path(document['cwd']).resolve() != self.cwd
                    or not isinstance(document['request'], dict)):
                raise AgentsError('authority-denied', 'Native Session/cwd/request is invalid.')
            if any(native['session'] != document['session'] for native in self.prepared):
                raise AgentsError('authority-denied', 'A different native call is already pending.')
            self.queued = [native for native in self.queued if native['session'] == document['session']]
            if document not in self.prepared:
                self.prepared.append(copy.deepcopy(document))
            return {'prepared': True}

    def end(self, document: dict) -> dict:
        """End this call's association, or with a bare ``end`` every prepared one.

        Hold the lock. A bare ``end`` comes from a Session ending or from a mod
        adopted earlier, which runs one call at a time.
        """
        if set(document) == {'operation'}:
            ending = self.prepared
        elif set(document) == {'operation', 'tool', 'session', 'request'}:
            ending = [native for native in self.prepared if self._same_call(native, document)]
        else:
            raise AgentsError('invalid-input', 'Expected one native per-call end.')
        for native in ending:
            if any(item['session'] == native['session'] for item in self.running):
                self.queued.append(native)
        self.prepared = [native for native in self.prepared if not any(native is item for item in ending)]
        print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'agents-call context-end', f'matched={len(ending)} prepared={len(self.prepared)} '
              f'queued={len(self.queued)} running={len(self.running)}', file=sys.stderr, flush=True)
        return {'ended': True}

    @staticmethod
    def _same_call(native: dict, document: dict) -> bool:
        """Whether both name one exact native call."""
        return all(native[key] == document[key] for key in ('tool', 'session', 'request'))

    def notices(self, document: dict) -> dict:
        """The consumer supplies its own pending-notice queue."""
        raise AgentsError('invalid-input', 'No notice receiver is configured.')

    def call(self, request: dict, tool: str = 'agents') -> AgentsResult:
        """Consume the association matching this MCP request; others stay untouched.

        Queued associations were prepared earlier than the prepared ones, so
        they are matched first, in order. All belong to one Session (see
        ``context``), so a match is never ambiguous between Sessions.
        """
        with self.lock:
            candidates = [item for item in self.queued + self.prepared
                          if item['request'] == request and item['tool'] == tool]
            if not candidates:
                raise AgentsError('authority-denied', 'No matching current native call association. '
                                  'A call whose native call ended before it was served, or that came '
                                  'from another Session, is not executed; call it again.')
            native = candidates[0]
            for associations in (self.queued, self.prepared):
                if any(native is item for item in associations):
                    associations[:] = [item for item in associations if item is not native]
            self.running.append(native)
        try:
            return self.make_call(native['session'], self.cwd)(tool, request)
        finally:
            with self.lock:
                self.running[:] = [item for item in self.running if item is not native]
