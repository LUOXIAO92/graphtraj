"""Execute replacement through Codex's native approval channel."""

from typing import Sequence

from graphtraj.runtimes.codex.native_approval import execute_native_operation


def execute_replacement(command: Sequence[str]) -> dict:
    """Request native execution of the exact remaining replacement."""
    return execute_native_operation(
        command, "replacement",
        "Allow this non-direct replacement after GraphTraj checked the recorded "
        "caller relationship? The target and all descendants must still be stopped.",
        "replacement_alias",
    )
