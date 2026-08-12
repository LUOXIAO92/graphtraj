"""Shared value objects for one Agent Runner launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


class RunnerError(Exception):
    """One stable failure crossing the Agent Runner process seam."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        release_reservation: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.release_reservation = release_reservation

    def as_document(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class Task:
    ticket_id: str
    ticket_name: str
    role: str
    ticket_file: Path
    ticket_content: str
    instruction: Optional[str]

    @property
    def stem(self) -> str:
        """Return the injective, Git-safe visible ticket artifact stem."""

        encoded_id = self.ticket_id.replace(".", "%2E")
        return "{0}-{1}-{2}".format(
            len(self.ticket_id), encoded_id, self.ticket_name
        )

    @property
    def id_stem_prefix(self) -> str:
        """Return the unambiguous branch prefix for this stable ticket ID."""

        encoded_id = self.ticket_id.replace(".", "%2E")
        return "{0}-{1}-".format(len(self.ticket_id), encoded_id)


@dataclass(frozen=True)
class Batch:
    run_id: str
    task: Task
    source_bytes: bytes


@dataclass(frozen=True)
class Project:
    repository: Path
    common_directory: Path
    worktree_root: Path
    state_directory: Path
    integration_branch: str
    integration_worktree: Path
    dev_commit: str
    runtime_executable: Path
    role_bindings: Mapping[str, str]


@dataclass(frozen=True)
class LaunchResponse:
    document: Dict[str, Any]
    succeeded: bool
