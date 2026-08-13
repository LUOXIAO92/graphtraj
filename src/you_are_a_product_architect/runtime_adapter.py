"""Runtime-neutral contracts for one background Engineer turn."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Protocol


SessionStarted = Callable[[str, int], None]


class RuntimeAdapterError(Exception):
    """A Runtime Adapter failed with a stable Runner-facing error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        terminal_confirmed: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.terminal_confirmed = terminal_confirmed


class RuntimeTurn(Protocol):
    """One Adapter-owned Runtime invocation."""

    def run(self) -> Dict[str, Any]:
        """Run the invocation until its Runtime reaches a terminal state."""

    def terminate(self) -> bool:
        """Request termination and confirm that it stopped a live Runtime."""

    def terminate_until_terminal(self) -> None:
        """Keep ownership until the Runtime process group is terminal."""


RuntimeAdapter = Callable[
    [Mapping[str, Any], str, Path, SessionStarted], RuntimeTurn
]
