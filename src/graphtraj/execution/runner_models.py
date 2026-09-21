"""Shared value objects for one Agent Runner launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from graphtraj.configuration.project_roles import ProjectRoles, RolePreset


PUBLIC_ERROR_CODES = frozenset(
    {
        "invalid-input",
        "authority-denied",
        "team-not-active",
        "seat-replaced",
        "insufficient-capacity",
        "invalid-config",
        "unsupported-runtime",
        "integration-not-ready",
        "invalid-ticket",
        "ticket-already-live",
        "worktree-conflict",
        "worktree-busy",
        "launch-failed",
        "alias-not-found",
        "session-not-resumable",
        "turn-running",
        "live-input-unsupported",
        "operation-failed",
        "cleanup-not-integrated",
        "cleanup-not-merged",
        "cleanup-dirty",
        "cleanup-ownership-mismatch",
        "cleanup-failed",
    }
)
DETAIL_ERROR_CATEGORIES = {
    "BATCH_INPUT_REQUIRED": "invalid-input",
    "BATCH_FILE_INVALID": "invalid-input",
    "BATCH_YAML_INVALID": "invalid-input",
    "BATCH_SCHEMA_INVALID": "invalid-input",
    "TASK_COUNT_UNSUPPORTED": "invalid-input",
    "TASK_SCHEMA_INVALID": "invalid-input",
    "TICKET_ID_INVALID": "invalid-input",
    "TICKET_ID_DUPLICATE": "invalid-input",
    "TICKET_NAME_INVALID": "invalid-input",
    "ROLE_NOT_CONFIGURED": "invalid-input",
    "INSTRUCTION_INVALID": "invalid-input",
    "SKILL_SELECTION_INVALID": "invalid-input",
    "REPORT_FILE_INVALID": "invalid-input",
    "REPOSITORY_SKILL_NOT_FOUND": "invalid-input",
    "REPOSITORY_SKILL_AMBIGUOUS": "invalid-input",
    "HARNESS_SKILL_NOT_FOUND": "invalid-config",
    "PROJECT_NOT_FOUND": "invalid-config",
    "RUNTIME_EXECUTABLE_INVALID": "invalid-config",
    "ROLE_CONFIG_INVALID": "invalid-config",
    "ROLE_CONFIG_UNSUPPORTED": "invalid-config",
    "LEGACY_SANDBOX_CONFIG_CONFLICT": "invalid-config",
    "ROLE_HOOK_MISMATCH": "invalid-config",
    "ROLE_GUARD_MISMATCH": "invalid-config",
    "PROJECT_CONFIG_MISMATCH": "invalid-config",
    "PACKAGED_ROLE_INVALID": "invalid-config",
    "ROLE_NOT_SUPPORTED": "invalid-config",
    "RUNTIME_NOT_CONFIGURED": "unsupported-runtime",
    "RUNTIME_UNSUPPORTED": "unsupported-runtime",
    "INTEGRATION_WORKTREE_INVALID": "integration-not-ready",
    "INTEGRATION_WORKTREE_DIRTY": "integration-not-ready",
    "TICKET_FILE_INVALID": "invalid-ticket",
    "TICKET_ALREADY_ACTIVE": "ticket-already-live",
    "WORKTREE_CONFLICT": "worktree-conflict",
    "WORKTREE_TURN_ACTIVE": "worktree-busy",
    "ACTIVE_TURN_RESERVATION_FAILED": "launch-failed",
    "WORKTREE_PROVISION_FAILED": "launch-failed",
    "STATE_LINK_FAILED": "launch-failed",
    "RUNTIME_WORKER_START_FAILED": "launch-failed",
    "RUNTIME_MAPPING_INVALID": "launch-failed",
    "RUNTIME_LAUNCH_FAILED": "launch-failed",
    "RUNTIME_LAUNCH_TIMEOUT": "launch-failed",
    "RUNTIME_WORKER_FAILED": "launch-failed",
    "RUNTIME_PROVIDER_FAILED": "launch-failed",
    "RUNTIME_ACCESS_DENIED": "invalid-config",
    "RUNTIME_START_FAILED": "launch-failed",
    "RUNTIME_SESSION_MISSING": "launch-failed",
    "AGENT_BINDING_CONFLICT": "launch-failed",
    "RUNTIME_REQUEST_INVALID": "launch-failed",
    "ALIAS_ALLOCATION_FAILED": "launch-failed",
    "METADATA_WRITE_FAILED": "launch-failed",
    "BATCH_RETENTION_FAILED": "operation-failed",
    "STATE_DIRECTORY_INVALID": "operation-failed",
    "GIT_FAILED": "operation-failed",
}


class RunnerError(Exception):
    """One stable failure crossing the Agent Runner process seam."""

    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_document(self) -> Dict[str, str]:
        public_code = (
            self.code
            if self.code in PUBLIC_ERROR_CODES
            else DETAIL_ERROR_CATEGORIES.get(self.code, "operation-failed")
        )
        return {"code": public_code, "message": self.message}


@dataclass(frozen=True)
class Task:
    ticket_id: str
    ticket_name: str
    role: str
    ticket_file: Optional[Path]
    ticket_content: str
    instruction: Optional[str]
    requested_skills: Tuple[str, ...] = ()
    report_file: Optional[Path] = None
    inline_preset: RolePreset | None = None
    policy_role: str | None = None
    role_reference: str | None = None



@dataclass(frozen=True)
class Batch:
    tasks: Tuple[Task, ...]
    source_bytes: bytes


@dataclass(frozen=True)
class Project:
    harness_root: Path
    repository: Path
    common_directory: Path
    runner_directory: Path
    worktree_root: Path
    state_directory: Path
    documents_directory: Path
    integration_branch: str
    integration_worktree: Path
    dev_commit: str
    roles: ProjectRoles
    max_concurrency: int = 18

    @property
    def runtime_store(self) -> Path:
        """Return the Harness-owned Runtime Store for this project."""
        return self.harness_root / ".codex"


@dataclass(frozen=True)
class LaunchResponse:
    document: Dict[str, Any]
    succeeded: bool


@dataclass(frozen=True)
class CleanupResponse:
    document: Dict[str, Any]
    succeeded: bool


@dataclass(frozen=True)
class StatusResponse:
    document: Dict[str, Any]
    succeeded: bool
    errors: tuple[RunnerError, ...]
