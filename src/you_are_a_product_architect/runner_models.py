"""Shared value objects for one Agent Runner launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .project_roles import RolePreset


ROLE_ALIAS_MARKERS = {
    "team-leader": "l",
    "delivery-state": "d",
    "engineer-junior": "j",
    "engineer-senior": "s",
    "engineer-expert": "e",
    "standards-reviewer": "r",
    "spec-reviewer": "r",
}
LOGICAL_ROLES = tuple(ROLE_ALIAS_MARKERS)


def role_alias_marker(role: str) -> str:
    """Return the stable alias marker for a configured or temporary role."""

    return ROLE_ALIAS_MARKERS.get(role, "x")


RUNTIME_TUNING_PATHS = frozenset(
    {
        ("model",),
        ("model_reasoning_effort",),
        ("model_context_window",),
        ("model_auto_compact_token_limit",),
        ("agents", "default_subagent_model"),
        ("agents", "default_subagent_reasoning_effort"),
    }
)


def managed_runtime_policy_matches(
    configured: Mapping[str, Any], packaged: Mapping[str, Any]
) -> bool:
    """Compare Runtime policy while preserving supported local tuning."""

    def managed(value: Any, path: Tuple[str, ...] = ()) -> Any:
        if isinstance(value, Mapping):
            return {
                key: managed(item, (*path, key))
                for key, item in value.items()
                if (*path, key) not in RUNTIME_TUNING_PATHS
            }
        if isinstance(value, list):
            return [managed(item, path) for item in value]
        return value

    return managed(configured) == managed(packaged)


def ticket_id_stem_prefix(ticket_id: str) -> str:
    """Return the unambiguous artifact prefix for one stable ticket ID."""

    encoded_id = ticket_id.replace(".", "%2E")
    return "{0}-{1}-".format(len(ticket_id), encoded_id)


def ticket_stem(ticket_id: str, ticket_name: str) -> str:
    """Return the injective, Git-safe visible ticket artifact stem."""

    return "{0}{1}".format(ticket_id_stem_prefix(ticket_id), ticket_name)


PUBLIC_ERROR_CODES = frozenset(
    {
        "invalid-input",
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
    "RUN_ID_INVALID": "invalid-input",
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
    "RUNTIME_START_FAILED": "launch-failed",
    "RUNTIME_SESSION_MISSING": "launch-failed",
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
        *,
        release_reservation: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.release_reservation = release_reservation

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
    review_round: Optional[int] = None
    inline_preset: RolePreset | None = None
    policy_role: str | None = None

    @property
    def stem(self) -> str:
        """Return the injective, Git-safe visible ticket artifact stem."""

        return ticket_stem(self.ticket_id, self.ticket_name)

    @property
    def id_stem_prefix(self) -> str:
        """Return the unambiguous branch prefix for this stable ticket ID."""

        return ticket_id_stem_prefix(self.ticket_id)


@dataclass(frozen=True)
class Batch:
    run_id: Optional[str]
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
    role_bindings: Mapping[str, RolePreset]
    repository_skill_allowlist: Tuple[str, ...] = ()

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
