"""Diagnose Harness Project configuration and reusable roles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from graphtraj.configuration.project_configuration import (
    ProjectConfigurationError,
    configuration_exists,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import ProjectRolesError, load_project_roles, roles_exist


def _doctor_harness_root(cwd: Path) -> Path:
    """Return the project root, rejecting a known Harness child worktree."""

    if configuration_exists(cwd):
        return cwd
    for ancestor in cwd.parents:
        if configuration_exists(ancestor):
            raise DoctorError("Run doctor from the Harness Project Root.")
    return cwd


class DoctorError(ValueError):
    """The requested directory is not a supported diagnostic context."""


@dataclass(frozen=True)
class ProjectDiagnosis:
    """Reusable-role diagnostics without terminal output."""

    roles_checked: bool
    role_diagnostics: Tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        """Return whether the checked roles are valid."""
        return not self.role_diagnostics


def diagnose_project(cwd: Path) -> ProjectDiagnosis:
    """Check configuration and roles without mutation or Skill discovery.

    Invalid roles are returned as diagnostics. A wrong Harness context or
    invalid project configuration raises DoctorError.
    """
    harness_root = _doctor_harness_root(cwd.resolve())
    if configuration_exists(harness_root):
        try:
            load_project_configuration(harness_root)
        except ProjectConfigurationError as error:
            raise DoctorError(str(error)) from error
    roles_checked = configuration_exists(harness_root) or roles_exist(harness_root)
    diagnostics = ()
    if roles_checked:
        try:
            load_project_roles(harness_root)
        except ProjectRolesError as error:
            diagnostics = error.diagnostics
    return ProjectDiagnosis(roles_checked, diagnostics)
