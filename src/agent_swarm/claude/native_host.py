"""Claude native per-call identity shared by independent and project hosts."""
from __future__ import annotations
import copy
from pathlib import Path
import threading
from typing import Callable
from uuid import UUID
from agent_swarm import AgentsError, AgentsResult

class NativeCalls:
    """Consume one current native association exactly once, never a startup ID.

    The mod prepares an association during Claude's permission check and ends
    it when the native call ends. The MCP entry serves one request at a time,
    so a call Claude moves to the background while an earlier call still runs
    can end before its request is read. Such an association is kept for that
    queued request only while a call of the same native Session executes; a
    preparation from another Session drops it, so it never crosses Sessions.
    """

    def __init__(
        self, make_call: Callable[[str, Path], Callable], cwd: Path, runner: Path | None = None,
    ) -> None:
        """Bind the backend factory, permitted native cwd and the notice queue's project."""
        self.make_call = make_call
        self.cwd = cwd.resolve()
        self.runner = runner
        self.pending: dict | None = None
        # Ended associations whose request may wait behind the running call.
        self.queued: list[dict] = []
        self.running: dict | None = None
        self.lock = threading.Lock()

    def context(self, document: dict) -> dict:
        """Accept only authenticated mod facts; this is not a model tool."""
        with self.lock:
            operation = document.get('operation')
            if operation == 'end':
                if (self.pending is not None and self.running is not None
                        and self.pending['session'] == self.running['session']):
                    self.queued.append(self.pending)
                self.pending = None
                return {'ended': True}
            if operation in {'notices', 'acknowledge'}:
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
            if self.pending is not None and self.pending != document:
                raise AgentsError('authority-denied', 'A different native call is already pending.')
            self.queued  = [native for native in self.queued if native['session'] == document['session']]
            self.pending = copy.deepcopy(document)
            return {'prepared': True}

    def notices(self, document: dict) -> dict:
        """The consumer supplies its own pending-notice queue."""
        raise AgentsError('invalid-input', 'No notice receiver is configured.')

    def call(self, request: dict, tool: str = 'agents') -> AgentsResult:
        """Consume the association matching this MCP request; others stay untouched.

        Queued associations were prepared earlier than the current one, so
        they are matched first, in order.
        """
        with self.lock:
            candidates = self.queued + ([self.pending] if self.pending is not None else [])
            native = next((item for item in candidates
                           if item['request'] == request and item['tool'] == tool), None)
            if native is None:
                raise AgentsError('authority-denied', 'No matching current native call association. '
                                  'A call whose native call ended before it was served, or that came '
                                  'from another Session, is not executed; call it again.')
            if native is self.pending:
                self.pending = None
            else:
                self.queued.remove(native)
            self.running = native
        try:
            return self.make_call(native['session'], self.cwd)(tool, request)
        finally:
            with self.lock:
                self.running = None

