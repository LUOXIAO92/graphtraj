"""Read the one general configuration for a GraphTraj project."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIRECTORY = ".graphtraj"
CONFIG_FILE = "config.yml"
CONFIG_PATH = Path(CONFIG_DIRECTORY) / CONFIG_FILE
DEFAULT_CONFIG_CONTENT = """version: 1

paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state

agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
"""


class ProjectConfigurationError(Exception):
    """A GraphTraj project configuration is missing or invalid."""


@dataclass(frozen=True)
class ProjectConfiguration:
    """The configured project paths, resolved from the Harness Project Root."""

    harness_root: Path
    project_root: Path
    docs: Path
    agent_worktrees: Path
    state: Path
    dispatch_depth: int
    max_concurrency: int

    @property
    def integration_worktree(self) -> Path:
        """Return the fixed dev Integration Worktree path."""

        return self.agent_worktrees / "dev"


def configuration_file(harness_root: Path) -> Path:
    """Return the fixed configuration file location for one project root."""

    return harness_root / CONFIG_PATH


def default_configuration_content(harness_root: Path, project_root: Path) -> str:
    """Render the accepted defaults for one selected Source Repository."""

    root = harness_root.resolve()
    source = project_root.resolve()
    try:
        configured_project_root = source.relative_to(root).as_posix() or "."
    except ValueError as error:
        raise ProjectConfigurationError("GraphTraj Config is invalid.") from error
    if not _is_supported_project_root(root, source):
        raise ProjectConfigurationError("GraphTraj Config is invalid.")
    if configured_project_root == ".":
        return DEFAULT_CONFIG_CONTENT
    return yaml.safe_dump(
        {
            "version": 1,
            "paths": {
                "project_root": configured_project_root,
                "docs": "docs",
                "agent_worktrees": ".graphtraj/.agent-worktrees",
                "state": ".graphtraj/state",
            },
            "agent_runner": {"dispatch_depth": 2, "max_concurrency": 18},
        },
        sort_keys=False,
    )


def default_project_configuration(
    harness_root: Path,
    project_root: Path,
) -> ProjectConfiguration:
    """Return the accepted setup defaults for one selected Source Repository."""

    return _configuration_from_document(
        harness_root,
        yaml.safe_load(default_configuration_content(harness_root, project_root)),
    )


def load_project_configuration(harness_root: Path) -> ProjectConfiguration:
    """Load the fixed configuration without detecting a project layout."""

    path = configuration_file(harness_root)
    try:
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(path)
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ProjectConfigurationError(
            "GraphTraj Config was not found at {0}.".format(path)
        ) from error
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ProjectConfigurationError(
            "GraphTraj Config is not readable valid YAML."
        ) from error
    return _configuration_from_document(harness_root, document)


def configuration_exists(harness_root: Path) -> bool:
    """Return whether the fixed configuration target exists, including links."""

    return os.path.lexists(str(configuration_file(harness_root)))


def _configuration_from_document(
    harness_root: Path,
    document: Any,
) -> ProjectConfiguration:
    invalid = "GraphTraj Config is invalid."
    if not isinstance(document, dict) or set(document) != {
        "version",
        "paths",
        "agent_runner",
    }:
        raise ProjectConfigurationError(invalid)
    paths = document.get("paths")
    limits = document.get("agent_runner")
    if (
        document.get("version") != 1
        or not isinstance(paths, dict)
        or set(paths) != {"project_root", "docs", "agent_worktrees", "state"}
        or not isinstance(limits, dict)
        or set(limits) != {"dispatch_depth", "max_concurrency"}
    ):
        raise ProjectConfigurationError(invalid)

    try:
        project_root = _resolve_configured_path(
            harness_root, paths["project_root"]
        )
        docs = _resolve_configured_path(harness_root, paths["docs"])
        agent_worktrees = _resolve_configured_path(
            harness_root, paths["agent_worktrees"]
        )
        state = _resolve_configured_path(harness_root, paths["state"])
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ProjectConfigurationError(invalid) from error
    root = harness_root.resolve()
    if not _is_supported_project_root(root, project_root):
        raise ProjectConfigurationError(invalid)

    dispatch_depth = limits["dispatch_depth"]
    max_concurrency = limits["max_concurrency"]
    if (
        isinstance(dispatch_depth, bool)
        or not isinstance(dispatch_depth, int)
        or dispatch_depth < 1
        or isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or max_concurrency < 1
    ):
        raise ProjectConfigurationError(invalid)
    if _paths_overlap(agent_worktrees, state):
        raise ProjectConfigurationError(invalid)
    return ProjectConfiguration(
        harness_root=root,
        project_root=project_root,
        docs=docs,
        agent_worktrees=agent_worktrees,
        state=state,
        dispatch_depth=dispatch_depth,
        max_concurrency=max_concurrency,
    )


def _resolve_configured_path(harness_root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Configured paths must be non-empty strings.")
    root = harness_root.resolve()
    path = Path(value)
    if path.is_absolute():
        raise ValueError("Configured paths must be relative to the Harness Project Root.")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Configured path escapes the Harness Project Root.") from error
    return resolved


def _is_supported_project_root(harness_root: Path, project_root: Path) -> bool:
    return project_root == harness_root or project_root.parent == harness_root


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False
