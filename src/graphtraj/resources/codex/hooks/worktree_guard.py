#!/usr/bin/env python3
"""Confine Codex tool calls to the hook process's Git worktree.

The process working directory is the immutable trust anchor.  Event fields are
untrusted requests.  Bash is accepted only through a deliberately small,
fail-closed grammar: shell expansion, stateful shell builtins, executable
payload options, and unknown command options are rejected instead of guessed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

import yaml


FLAG = "flag"
OPAQUE = "opaque"
PATH = "path"
INTEGER = "integer"
PACKAGE = "package"

PATHS = "paths"
OPAQUE_OPERANDS = "opaque"
NO_OPERANDS = "none"
PATTERN_PATHS = "pattern-paths"
OPTIONAL_PATHS = "optional-paths"

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
INTEGER_VALUE = re.compile(r"^[0-9]+$")
PACKAGE_VALUE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~].*)?$")
UNMODELLED_SHELL_CHARS = frozenset("$`{}*?[]~!\\")
ALLOWED_BOUNDARIES = frozenset({"\n", ";", "&&", "||", "|"})
DENIED_BOUNDARIES = frozenset({"&", "(", ")"})
REDIRECTS = frozenset({"<", ">", ">>"})
DENIED_REDIRECTS = frozenset({"<<", "<<<", "<>", ">&", "<&", "&>", ">|"})


@dataclass(frozen=True)
class Option:
    """One explicitly supported option and its value type, if any."""

    kind: str = FLAG
    attached: bool = False


@dataclass(frozen=True)
class Policy:
    """The complete accepted argument surface for one executable."""

    operands: str
    options: Mapping[str, Option]
    skip_operands: int = 0


def flags(*names: str) -> dict[str, Option]:
    return {name: Option() for name in names}


def values(kind: str, *names: str, attached: bool = False) -> dict[str, Option]:
    return {name: Option(kind=kind, attached=attached) for name in names}


def options(*groups: Mapping[str, Option]) -> dict[str, Option]:
    merged: dict[str, Option] = {}
    for group in groups:
        merged.update(group)
    return merged


FILE_POLICIES: Mapping[str, Policy] = {
    "cat": Policy(PATHS, flags("-b", "-E", "-n", "-s", "-T", "-v")),
    "cp": Policy(PATHS, flags("-a", "-f", "-i", "-n", "-p", "-r", "-R")),
    "diff": Policy(
        PATHS,
        options(
            flags("-b", "-B", "-q", "-r", "-u", "-w", "--brief", "--new-file", "--recursive"),
            values(INTEGER, "-U", "--unified", attached=True),
        ),
    ),
    "head": Policy(
        PATHS,
        options(flags("-q", "-v"), values(INTEGER, "-c", "-n", attached=True)),
    ),
    "ls": Policy(
        PATHS,
        flags("-1", "-a", "-A", "-d", "-F", "-h", "-l", "-n", "-r", "-R", "-S", "-t"),
    ),
    "mkdir": Policy(PATHS, flags("-p", "--parents")),
    "mv": Policy(PATHS, flags("-f", "-i", "-n")),
    "readlink": Policy(PATHS, flags("-e", "-f", "-n")),
    "rm": Policy(PATHS, flags("-d", "-f", "-i", "-r", "-R", "--force", "--recursive")),
    "rmdir": Policy(PATHS, flags("-p", "--parents")),
    "stat": Policy(PATHS, flags("-f", "-L", "-l", "-n", "-q", "-r", "-s", "-x")),
    "tail": Policy(
        PATHS,
        options(flags("-q", "-v"), values(INTEGER, "-c", "-n", attached=True)),
    ),
    "tee": Policy(PATHS, flags("-a", "--append")),
    "touch": Policy(PATHS, flags("-a", "-c", "-m", "--no-create")),
    "wc": Policy(PATHS, flags("-c", "-l", "-m", "-w")),
}

SIMPLE_POLICIES: Mapping[str, Policy] = {
    "date": Policy(NO_OPERANDS, {}),
    "echo": Policy(OPAQUE_OPERANDS, flags("-e", "-E", "-n")),
    "false": Policy(NO_OPERANDS, {}),
    "id": Policy(OPAQUE_OPERANDS, flags("-G", "-g", "-n", "-r", "-u")),
    "printf": Policy(OPAQUE_OPERANDS, {}),
    "pwd": Policy(NO_OPERANDS, flags("-L", "-P")),
    "true": Policy(NO_OPERANDS, {}),
    "uname": Policy(NO_OPERANDS, flags("-a", "-m", "-n", "-p", "-r", "-s", "-v")),
    "which": Policy(OPAQUE_OPERANDS, flags("-a", "-s")),
    "whoami": Policy(NO_OPERANDS, {}),
}

SEARCH_POLICIES: Mapping[str, Policy] = {
    "grep": Policy(
        PATTERN_PATHS,
        flags("-c", "-E", "-F", "-H", "-h", "-i", "-l", "-L", "-n", "-q", "-s", "-v", "-w", "-x"),
    ),
    "rg": Policy(
        PATTERN_PATHS,
        flags(
            "-c",
            "-F",
            "-H",
            "-h",
            "--hidden",
            "-i",
            "--json",
            "-l",
            "-n",
            "--no-ignore",
            "-q",
            "-s",
            "-S",
            "-v",
            "-w",
            "-x",
        ),
    ),
}

RG_FILES_POLICY = Policy(
    PATHS,
    flags("--files", "--hidden", "--no-ignore", "-q", "-s"),
)

PYTEST_POLICY = Policy(
    PATHS,
    options(
        flags(
            "-q",
            "--quiet",
            "-v",
            "--verbose",
            "-x",
            "--exitfirst",
            "--disable-warnings",
            "--no-header",
            "--no-summary",
        ),
        values(INTEGER, "--maxfail"),
        values(OPAQUE, "-k", "-m", "--tb", "--color", attached=True),
        values(PATH, "-c", "--rootdir", "--basetemp", attached=True),
    ),
)

RUFF_POLICY = Policy(
    PATHS,
    options(
        flags("--fix", "--diff", "--quiet", "--verbose", "--no-cache"),
        values(PATH, "--config", "--cache-dir", attached=True),
        values(OPAQUE, "--output-format", "--select", "--ignore", attached=True),
    ),
)

TYPECHECK_POLICY = Policy(
    PATHS,
    options(
        flags("--strict", "--pretty", "--no-pretty", "--verbose"),
        values(PATH, "--config-file", "--project", attached=True),
    ),
)

GIT_POLICIES: Mapping[str, Policy] = {
    "add": Policy(PATHS, flags("-A", "--all", "-u", "--update", "-N", "--intent-to-add", "--dry-run", "-n")),
    "apply": Policy(
        PATHS,
        options(
            flags("--check", "--index", "--cached", "--3way", "--reject", "--reverse", "-R"),
            values(PATH, "--directory", attached=True),
            values(OPAQUE, "--whitespace", attached=True),
        ),
    ),
    "branch": Policy(NO_OPERANDS, flags("--show-current", "--list", "-a", "-r", "-v")),
    "cat-file": Policy(OPAQUE_OPERANDS, flags("-e", "-p", "-s", "-t")),
    "check-ignore": Policy(PATHS, flags("-q", "-v", "--quiet", "--verbose", "--no-index")),
    "cherry-pick": Policy(
        OPAQUE_OPERANDS,
        options(
            flags("--abort", "--continue", "--quit", "--skip", "--no-commit", "-n", "--no-edit"),
            values(INTEGER, "-m", "--mainline", attached=True),
        ),
    ),
    "clean": Policy(PATHS, flags("-d", "-f", "-n", "-q", "-x", "-X")),
    "commit": Policy(
        OPTIONAL_PATHS,
        options(
            flags("-a", "--all", "--allow-empty", "--amend", "--dry-run", "--no-edit", "--no-verify", "-s", "--signoff", "-v", "--verbose"),
            values(OPAQUE, "-m", "--message", "--author", "--date", "--fixup", "--squash", "-C", "--reuse-message", "-c", "--reedit-message", attached=True),
            values(PATH, "-F", "--file", "--pathspec-from-file", attached=True),
        ),
    ),
    "diff": Policy(
        OPTIONAL_PATHS,
        options(
            flags("--cached", "--staged", "--check", "--stat", "--name-only", "--name-status", "--no-ext-diff", "--no-textconv", "--quiet", "--exit-code", "--summary", "--raw", "-w", "--word-diff"),
            values(INTEGER, "-U", "--unified", attached=True),
            values(OPAQUE, "--color", "--diff-filter", attached=True),
        ),
    ),
    "diff-index": Policy(OPTIONAL_PATHS, flags("--cached", "--quiet", "--name-only", "--name-status")),
    "diff-tree": Policy(OPTIONAL_PATHS, flags("-r", "--name-only", "--name-status", "--no-commit-id")),
    "log": Policy(
        OPAQUE_OPERANDS,
        options(
            flags("--all", "--decorate", "--graph", "--oneline", "--stat", "--name-only", "--name-status", "--no-merges"),
            values(INTEGER, "-n", "--max-count", attached=True),
            values(OPAQUE, "--format", "--pretty", "--since", "--until", attached=True),
        ),
    ),
    "merge": Policy(
        OPAQUE_OPERANDS,
        options(
            flags("--abort", "--continue", "--quit", "--ff", "--ff-only", "--no-ff", "--no-commit", "--no-edit", "--squash", "--stat", "--no-stat"),
            values(OPAQUE, "-m", "--message", attached=True),
        ),
    ),
    "merge-base": Policy(OPAQUE_OPERANDS, flags("--all", "--is-ancestor", "--fork-point")),
    "mv": Policy(PATHS, flags("-f", "-k", "-n", "--dry-run")),
    "rebase": Policy(
        OPAQUE_OPERANDS,
        options(
            flags("--abort", "--continue", "--quit", "--skip", "--rebase-merges", "--no-rebase-merges", "--autostash", "--no-autostash"),
            values(OPAQUE, "--onto", attached=True),
        ),
    ),
    "reflog": Policy(OPAQUE_OPERANDS, flags("show", "exists")),
    "reset": Policy(OPTIONAL_PATHS, flags("--soft", "--mixed", "--hard", "--merge", "--keep", "-q", "--quiet")),
    "restore": Policy(
        PATHS,
        options(
            flags("--staged", "--worktree", "--ours", "--theirs", "--ignore-unmerged"),
            values(OPAQUE, "--source", attached=True),
            values(PATH, "--pathspec-from-file", attached=True),
        ),
    ),
    "rev-parse": Policy(OPAQUE_OPERANDS, flags("--verify", "--quiet", "-q", "--show-toplevel", "--show-prefix", "--show-cdup", "--show-superproject-working-tree", "--git-common-dir", "--git-dir", "--is-inside-work-tree", "--is-bare-repository", "--is-shallow-repository", "--show-object-format", "--abbrev-ref", "--symbolic-full-name", "--short")),
    "rm": Policy(PATHS, flags("-f", "--force", "-n", "--dry-run", "-r", "--cached")),
    "show": Policy(
        OPAQUE_OPERANDS,
        options(
            flags("--stat", "--name-only", "--name-status", "--oneline", "--summary", "--no-ext-diff", "--no-textconv"),
            values(OPAQUE, "--format", "--pretty", "--color", attached=True),
        ),
    ),
    "show-ref": Policy(OPAQUE_OPERANDS, flags("--head", "--heads", "--tags", "--verify", "--quiet", "-q")),
    "status": Policy(
        PATHS,
        options(
            flags("-s", "--short", "-b", "--branch", "--porcelain", "--long", "--ignored", "--no-renames"),
            values(OPAQUE, "--untracked-files", attached=True),
        ),
    ),
    "tag": Policy(NO_OPERANDS, flags("--list", "-l")),
}


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def deny(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def git(cwd: Path, *arguments: str) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


def discover_worktrees(process_cwd: Path) -> Tuple[Path, list[Path]]:
    root = Path(git(process_cwd, "rev-parse", "--show-toplevel")).resolve()
    porcelain = git(root, "worktree", "list", "--porcelain")
    worktrees = [
        Path(line.removeprefix("worktree ")).resolve()
        for line in porcelain.splitlines()
        if line.startswith("worktree ")
    ]
    if root not in worktrees:
        raise RuntimeError("Git did not report the current worktree")
    return root, worktrees


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def contains_unmodelled_shell_syntax(value: str) -> bool:
    return any(character in value for character in UNMODELLED_SHELL_CHARS) or "\x00" in value


def path_from(raw: str, *, cwd: Path, required: bool = False) -> Optional[Path]:
    value = raw.strip().strip("'\"")
    if not value or contains_unmodelled_shell_syntax(value):
        return None
    if value.startswith(("http://", "https://", "ssh://", "git@")):
        return None
    looks_like_path = (
        required
        or os.path.isabs(value)
        or value.startswith(".")
        or "/" in value
        or "\\" in value
    )
    if not looks_like_path:
        return None
    try:
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def lexical_path_from(raw: str, *, cwd: Path) -> Optional[Path]:
    value = raw.strip().strip("'\"")
    if not value or contains_unmodelled_shell_syntax(value):
        return None
    try:
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        return Path(os.path.abspath(str(path)))
    except (OSError, RuntimeError, ValueError):
        return None


def configured_harness_paths(root: Path) -> Optional[Tuple[Path, Path, Path, Path]]:
    """Find the one GraphTraj configuration that owns this Worktree."""
    installed_root = Path(__file__).resolve().parents[2]
    candidates = (installed_root, root, *root.parents)
    seen: set[Path] = set()
    for harness_root in candidates:
        if harness_root in seen:
            continue
        seen.add(harness_root)
        config_file = harness_root / ".graphtraj" / "config.yml"
        try:
            if config_file.is_symlink() or not config_file.is_file():
                continue
            document = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or document.get("version") != 1
                or set(document) != {"version", "paths", "agent_runner"}
            ):
                continue
            paths = document["paths"]
            if not isinstance(paths, dict) or set(paths) != {
                "project_root",
                "docs",
                "agent_worktrees",
                "state",
            }:
                continue
            limits = document["agent_runner"]
            if not isinstance(limits, dict) or set(limits) != {
                "dispatch_depth",
                "max_concurrency",
            }:
                continue
            project_value = paths["project_root"]
            worktree_value = paths["agent_worktrees"]
            state_value = paths["state"]
            docs_value = paths["docs"]
            if not all(
                isinstance(value, str) and value
                for value in (
                    project_value,
                    worktree_value,
                    state_value,
                    docs_value,
                )
            ) or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in (limits["dispatch_depth"], limits["max_concurrency"])
            ):
                continue
            resolved_root = harness_root.resolve(strict=False)
            configured = {}
            for name, value in (
                ("project_root", project_value),
                ("agent_worktrees", worktree_value),
                ("state", state_value),
                ("docs", docs_value),
            ):
                path = Path(value)
                if path.is_absolute():
                    break
                path = (resolved_root / path).resolve(strict=False)
                if not is_inside(path, resolved_root):
                    break
                configured[name] = path
            else:
                configured_project_root = configured["project_root"]
                if (
                    configured_project_root != resolved_root
                    and configured_project_root.parent != resolved_root
                ):
                    continue
                worktree_root = configured["agent_worktrees"]
                state_root = configured["state"]
                documents_root = configured["docs"]
                if is_inside(root, worktree_root):
                    return harness_root, worktree_root, state_root, documents_root
        except (KeyError, OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError):
            continue
    return None


def ticket_evidence_scope(root: Path) -> Optional[Tuple[Path, Path]]:
    """Return the one state link and evidence directory implied by a ticket root."""
    configured = configured_harness_paths(root)
    if configured is None:
        return None
    _harness_root, worktree_directory, state_root, _documents_root = configured
    try:
        relative = root.relative_to(worktree_directory)
    except ValueError:
        return None
    if len(relative.parts) == 1 and "-" in relative.name:
        return root / ".state", state_root / "tickets" / relative.name
    return None


def readable_harness_document_view(
    lexical: Path,
    target: Path,
    *,
    root: Path,
) -> bool:
    """Return whether a Worktree view resolves to its root-owned document."""
    configured = configured_harness_paths(root)
    if configured is None:
        return False
    harness_root, worktree_directory, _state_root, documents_root = configured
    try:
        relative = root.relative_to(worktree_directory)
    except ValueError:
        return False
    if relative != Path("dev") and not (
        len(relative.parts) == 1
        or len(relative.parts) == 3 and relative.parts[0] == "runs"
    ):
        return False
    for name, directory, expected in (
        ("CONTEXT.md", False, harness_root / "CONTEXT.md"),
        ("docs", True, documents_root),
    ):
        view = root / name
        if not directory and lexical != view:
            continue
        if directory and not is_inside(lexical, view):
            continue
        try:
            if (
                not view.is_symlink()
                or expected.is_symlink()
                or view.resolve(strict=False) != expected
            ):
                return False
            if not directory:
                return target == expected
            relative_path = lexical.relative_to(view)
            cursor = view
            for part in relative_path.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    return False
            return target == expected / relative_path
        except (OSError, RuntimeError, ValueError):
            return False
    return False


def scoped_evidence_reason(
    lexical: Path,
    target: Path,
    *,
    root: Path,
    write: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Validate the sole external path exception for a Ticket Worktree."""
    scope = ticket_evidence_scope(root)
    if scope is None:
        return False, None
    scoped_state, expected_evidence = scope
    if not is_inside(lexical, scoped_state):
        return False, None

    relative = lexical.relative_to(scoped_state)
    if not relative.parts:
        return True, "Blocked direct operation on the scoped evidence link."
    try:
        if scoped_state.parent.resolve(strict=False) != scoped_state.parent:
            return True, "Cannot verify the scoped evidence link parent."
        if not scoped_state.is_symlink():
            return True, "Cannot verify the scoped evidence link."
        if expected_evidence.resolve(strict=False) != expected_evidence:
            return True, "Cannot verify the expected ticket evidence directory."
        if scoped_state.resolve(strict=False) != expected_evidence:
            return True, "Blocked mispointed scoped evidence link."
    except (OSError, RuntimeError, ValueError):
        return True, "Cannot resolve the scoped evidence link."

    if not is_inside(target, expected_evidence):
        return True, "target is outside the current ticket evidence directory"

    cursor = scoped_state
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True, "an inner ticket evidence path component is a symlink"
    if write and target not in writable_evidence_paths():
        return True, "the report target is not authorized for this role"
    return True, None


def lexically_targets_scoped_evidence(raw: str, *, cwd: Path, root: Path) -> bool:
    scope = ticket_evidence_scope(root)
    lexical = lexical_path_from(raw, cwd=cwd)
    return scope is not None and lexical is not None and is_inside(lexical, scope[0])


def target_reason(
    raw: str,
    *,
    cwd: Path,
    root: Path,
    required: bool = True,
    allow_harness_document_read: bool = False,
    write: bool = False,
) -> Optional[str]:
    target = path_from(raw, cwd=cwd, required=required)
    lexical = lexical_path_from(raw, cwd=cwd)
    if target is None or lexical is None:
        return "Cannot verify path target: {0}".format(raw)
    git_metadata = root / ".git"
    if is_inside(lexical, git_metadata) or is_inside(target, git_metadata):
        return _path_denial(raw, target, root, "target is Git metadata")
    scoped, reason = scoped_evidence_reason(lexical, target, root=root, write=write)
    if scoped:
        return _path_denial(raw, target, root, reason) if reason else None
    scope = ticket_evidence_scope(root)
    if scope is not None and is_inside(target, scope[1]):
        reason = direct_evidence_reason(target, scope[1], write=write)
        return _path_denial(raw, target, root, reason) if reason else None
    if not is_inside(target, root):
        if allow_harness_document_read and target in readable_skill_paths():
            return None
        if allow_harness_document_read and readable_harness_document_view(
            lexical,
            target,
            root=root,
        ):
            return None
        return _path_denial(raw, target, root, "target is outside the current Worktree")
    return None


def _path_denial(raw: str, target: Path, root: Path, condition: str) -> str:
    return (
        "Blocked path target: source=Worktree Guard; current_worktree={0}; "
        "requested={1}; resolved={2}; condition={3}"
    ).format(root, raw, target, condition)


def direct_evidence_reason(
    target: Path,
    expected_evidence: Path,
    *,
    write: bool,
) -> Optional[str]:
    if target == expected_evidence:
        return "direct operation on the ticket evidence directory is not allowed"
    try:
        if expected_evidence.resolve(strict=False) != expected_evidence:
            return "the expected ticket evidence directory cannot be verified"
    except (OSError, RuntimeError, ValueError):
        return "the expected ticket evidence directory cannot be resolved"
    relative = target.relative_to(expected_evidence)
    cursor = expected_evidence
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return "an inner ticket evidence path component is a symlink"
    if write and target not in writable_evidence_paths():
        return "the report target is not authorized for this role"
    return None


def readable_skill_paths() -> tuple[Path, ...]:
    """Exact enabled Skill files supplied by the immutable Adapter Hook command."""
    return tuple(
        Path(value)
        for index, value in enumerate(sys.argv[1:], start=1)
        if sys.argv[index - 1] == "--read-skill"
    )


def writable_evidence_paths() -> tuple[Path, ...]:
    """Return exact report targets supplied by the immutable Adapter Hook command."""
    paths = []
    for index, value in enumerate(sys.argv[1:], start=1):
        if sys.argv[index - 1] != "--write-path":
            continue
        try:
            paths.append(Path(value).resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            continue
    return tuple(paths)


def optional_target_reason(
    raw: str,
    *,
    cwd: Path,
    root: Path,
    write: bool = False,
) -> Optional[str]:
    target = path_from(raw, cwd=cwd)
    if target is None:
        return None
    return target_reason(raw, cwd=cwd, root=root, required=False, write=write)


def references_foreign_worktree(
    command: str,
    *,
    cwd: Path,
    root: Path,
    worktrees: Iterable[Path],
) -> Optional[Path]:
    normalized = command.replace("\\", "/")
    # A Harness Skill can be under the Primary Worktree in a same-root project.
    # target_reason still restricts these exact files to read commands.
    for skill in readable_skill_paths():
        normalized = normalized.replace(str(skill), "")
    for worktree in worktrees:
        if worktree == root:
            continue
        spellings = {str(worktree)}
        for base in (cwd, root):
            relative = os.path.relpath(worktree, base)
            if relative not in {"", "."}:
                spellings.add(relative)
        if any(spelling.replace("\\", "/") in normalized for spelling in spellings):
            return worktree
    return None


def tokenize(command: str) -> Optional[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def split_segments(tokens: Sequence[str]) -> Tuple[Optional[list[list[str]]], Optional[str]]:
    segments: list[list[str]] = []
    segment: list[str] = []
    for token in tokens:
        if token in DENIED_BOUNDARIES or (
            token and all(character in ";&|()" for character in token)
            and token not in ALLOWED_BOUNDARIES
        ):
            return None, "Cannot verify shell control operator: {0}".format(token)
        if token in ALLOWED_BOUNDARIES:
            if not segment:
                return None, "Cannot verify empty shell command segment."
            segments.append(segment)
            segment = []
            continue
        segment.append(token)
    if segment:
        segments.append(segment)
    if not segments:
        return None, "Cannot verify empty shell command."
    return segments, None


def strip_redirections(
    segment: Sequence[str],
    *,
    cwd: Path,
    root: Path,
) -> Tuple[Optional[list[str]], Optional[str]]:
    result: list[str] = []
    index = 0
    while index < len(segment):
        token = segment[index]
        descriptor = token.isdigit() and index + 1 < len(segment) and segment[index + 1] in REDIRECTS
        if descriptor:
            index += 1
            token = segment[index]
        if token in DENIED_REDIRECTS or token.startswith(("<<", ">&", "<&", "&>")):
            return None, "Cannot verify shell redirection: {0}".format(token)
        if token in REDIRECTS:
            if index + 1 >= len(segment):
                return None, "Cannot verify shell redirection target."
            reason = target_reason(
                segment[index + 1],
                cwd=cwd,
                root=root,
                write=token in {">", ">>"},
            )
            if reason:
                return None, reason
            index += 2
            continue
        if token and all(character in "<>" for character in token):
            return None, "Cannot verify shell redirection: {0}".format(token)
        result.append(token)
        index += 1
    return result, None


def executable_name(token: str) -> Optional[str]:
    if token.startswith((".", "/")) or "/" in token or "\\" in token:
        return None
    return token


def validate_option_value(
    kind: str,
    value: str,
    *,
    cwd: Path,
    root: Path,
    write: bool = False,
) -> Optional[str]:
    if kind == PATH:
        return target_reason(value, cwd=cwd, root=root, write=write)
    if kind == INTEGER and not INTEGER_VALUE.fullmatch(value):
        return "Cannot verify integer option value: {0}".format(value)
    if kind == PACKAGE and not PACKAGE_VALUE.fullmatch(value):
        return "Cannot verify package option value: {0}".format(value)
    return None


def option_match(token: str, policy: Policy) -> Tuple[Optional[str], Optional[Option], Optional[str]]:
    exact = policy.options.get(token)
    if exact is not None:
        return token, exact, None
    if token.startswith("--") and "=" in token:
        name, value = token.split("=", 1)
        spec = policy.options.get(name)
        if spec is not None and spec.kind != FLAG:
            return name, spec, value
    for name, spec in sorted(policy.options.items(), key=lambda item: len(item[0]), reverse=True):
        if spec.kind != FLAG and spec.attached and name.startswith("-") and not name.startswith("--"):
            if token.startswith(name) and token != name:
                return name, spec, token[len(name) :]
    if token.startswith("-") and not token.startswith("--") and len(token) > 2:
        members = ["-" + character for character in token[1:]]
        if all(policy.options.get(member) == Option() for member in members):
            return token, Option(), None
    return None, None, None


def validate_policy(
    arguments: Sequence[str],
    *,
    policy: Policy,
    cwd: Path,
    root: Path,
    allow_harness_document_read: bool = False,
    write: bool = False,
) -> Optional[str]:
    operands: list[str] = []
    index = 0
    options_ended = False
    while index < len(arguments):
        token = arguments[index]
        if token == "--" and not options_ended:
            options_ended = True
            index += 1
            continue
        if not options_ended and token.startswith("-") and token != "-":
            name, spec, inline_value = option_match(token, policy)
            if spec is None:
                return "Cannot verify option: {0}".format(token)
            if spec.kind == FLAG:
                index += 1
                continue
            value = inline_value
            if value is None:
                if index + 1 >= len(arguments):
                    return "Cannot verify option value: {0}".format(name)
                value = arguments[index + 1]
                index += 1
            reason = validate_option_value(
                spec.kind, value, cwd=cwd, root=root, write=write
            )
            if reason:
                return reason
            index += 1
            continue
        operands.append(token)
        index += 1

    if policy.operands == NO_OPERANDS and operands:
        return "Cannot verify command operands."
    if policy.operands == PATHS:
        for index, operand in enumerate(operands):
            if index < policy.skip_operands:
                continue
            reason = target_reason(
                operand,
                cwd=cwd,
                root=root,
                allow_harness_document_read=allow_harness_document_read,
                write=write,
            )
            if reason:
                return reason
    elif policy.operands == PATTERN_PATHS:
        for operand in operands[1:]:
            reason = target_reason(
                operand,
                cwd=cwd,
                root=root,
                allow_harness_document_read=allow_harness_document_read,
                write=write,
            )
            if reason:
                return reason
    elif policy.operands == OPTIONAL_PATHS:
        for operand in operands:
            reason = optional_target_reason(operand, cwd=cwd, root=root, write=write)
            if reason:
                return reason
    return None


def flag_only_operands(arguments: Sequence[str]) -> list[str]:
    """Collect operands after a flag-only policy has already been validated."""
    operands: list[str] = []
    options_ended = False
    for token in arguments:
        if token == "--" and not options_ended:
            options_ended = True
            continue
        if not options_ended and token.startswith("-") and token != "-":
            continue
        operands.append(token)
    return operands


def validate_git(arguments: Sequence[str], *, cwd: Path, root: Path) -> Optional[str]:
    index = 0
    git_cwd = cwd
    while index < len(arguments):
        token = arguments[index]
        if token == "--no-pager":
            index += 1
            continue
        if token == "-C" or token.startswith("-C"):
            if token == "-C":
                if index + 1 >= len(arguments):
                    return "Cannot verify Git working directory."
                value = arguments[index + 1]
                index += 2
            else:
                value = token[2:]
                if value.startswith("="):
                    value = value[1:]
                index += 1
            reason = target_reason(value, cwd=git_cwd, root=root)
            if reason:
                return reason
            requested_cwd = path_from(value, cwd=git_cwd, required=True)
            if requested_cwd is None:
                return "Cannot verify Git working directory."
            git_cwd = requested_cwd
            continue
        if token.startswith("--") and token.startswith("--no-pager="):
            return "Cannot verify Git global option: {0}".format(token)
        if token.startswith("-"):
            return "Cannot verify Git global option: {0}".format(token)
        policy = GIT_POLICIES.get(token)
        if policy is None:
            return "Cannot verify Git subcommand: {0}".format(token)
        return validate_policy(
            arguments[index + 1 :],
            policy=policy,
            cwd=git_cwd,
            root=root,
            write=token in {
                "add", "apply", "branch", "cherry-pick", "clean", "commit",
                "merge", "mv", "rebase", "reset", "restore", "rm", "tag",
            },
        )
    return "Cannot verify Git command."


def validate_python(arguments: Sequence[str], *, cwd: Path, root: Path) -> Optional[str]:
    if len(arguments) == 1 and arguments[0] in {"--version", "-V"}:
        return None
    if len(arguments) >= 2 and arguments[0] == "-m":
        module = arguments[1]
        module_arguments = arguments[2:]
        if module == "pytest":
            return validate_policy(module_arguments, policy=PYTEST_POLICY, cwd=cwd, root=root)
        if module == "compileall":
            reason = validate_policy(
                module_arguments,
                policy=Policy(PATHS, flags("-f", "-q")),
                cwd=cwd,
                root=root,
            )
            if reason:
                return reason
            if not flag_only_operands(module_arguments):
                return "Cannot verify compileall without an explicit path."
            return None
    return "Cannot verify Python payload."


def validate_uv(
    arguments: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    worktrees: Iterable[Path],
    depth: int,
) -> Optional[str]:
    if not arguments or arguments[0] != "run":
        return "Cannot verify uv wrapper."
    run_policy = Policy(
        NO_OPERANDS,
        options(
            flags("--active", "--exact", "--frozen", "--isolated", "--locked", "--no-project", "--no-sync", "--offline"),
            values(PACKAGE, "--with"),
        ),
    )
    index = 1
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            break
        name, spec, inline_value = option_match(token, run_policy)
        if spec is None:
            return "Cannot verify uv option: {0}".format(token)
        if spec.kind == FLAG:
            index += 1
            continue
        value = inline_value
        if value is None:
            if index + 1 >= len(arguments):
                return "Cannot verify uv option value: {0}".format(name)
            value = arguments[index + 1]
            index += 1
        reason = validate_option_value(spec.kind, value, cwd=cwd, root=root)
        if reason:
            return reason
        index += 1
    if index >= len(arguments):
        return "Cannot verify uv run payload."
    return validate_segment(
        arguments[index:],
        cwd=cwd,
        root=root,
        worktrees=worktrees,
        depth=depth + 1,
    )


def validate_segment(
    raw_segment: Sequence[str],
    *,
    cwd: Path,
    root: Path,
    worktrees: Iterable[Path],
    depth: int,
) -> Optional[str]:
    if depth > 4:
        return "Cannot verify nested command depth."
    segment, reason = strip_redirections(raw_segment, cwd=cwd, root=root)
    if reason:
        return reason
    assert segment is not None
    if not segment:
        return "Cannot verify empty command segment."
    if ASSIGNMENT.match(segment[0]):
        return "Cannot verify environment assignment."
    command = executable_name(segment[0])
    if command is None:
        return "Cannot verify executable path: {0}".format(segment[0])
    arguments = segment[1:]

    if command == "agent-runner" and "--team-leader" in sys.argv[1:]:
        return validate_policy(
            arguments,
            policy=Policy(NO_OPERANDS, options(
                flags("--help"), values(PATH, "--batch-input"),
            )),
            cwd=cwd,
            root=root,
        )

    if command in {"cd", "pushd", "popd", "bash", "sh", "env", "sed"}:
        return "Cannot verify stateful or executable command: {0}".format(command)
    if command == "git":
        return validate_git(arguments, cwd=cwd, root=root)
    if command == "uv":
        return validate_uv(arguments, cwd=cwd, root=root, worktrees=worktrees, depth=depth)
    if command in {"python", "python3"}:
        return validate_python(arguments, cwd=cwd, root=root)
    if command == "pytest":
        return validate_policy(arguments, policy=PYTEST_POLICY, cwd=cwd, root=root)
    if command == "ruff":
        return validate_policy(
            arguments, policy=RUFF_POLICY, cwd=cwd, root=root,
            write="--fix" in arguments,
        )
    if command in {"mypy", "pyright"}:
        return validate_policy(arguments, policy=TYPECHECK_POLICY, cwd=cwd, root=root)
    if command == "rg" and "--files" in arguments:
        return validate_policy(
            arguments,
            policy=RG_FILES_POLICY,
            cwd=cwd,
            root=root,
            allow_harness_document_read=True,
        )
    policy = (
        FILE_POLICIES.get(command)
        or SEARCH_POLICIES.get(command)
        or SIMPLE_POLICIES.get(command)
    )
    if policy is None:
        return "Cannot verify executable: {0}".format(command)
    reason = validate_policy(
        arguments,
        policy=policy,
        cwd=cwd,
        root=root,
        write=command in {"cp", "mkdir", "mv", "rm", "rmdir", "tee", "touch"},
        allow_harness_document_read=command
        in {
            "cat",
            "diff",
            "grep",
            "head",
            "ls",
            "readlink",
            "rg",
            "stat",
            "tail",
            "wc",
        },
    )
    if reason:
        return reason
    if command in {"cp", "mv"}:
        operands = flag_only_operands(arguments)
        if operands and lexically_targets_scoped_evidence(operands[-1], cwd=cwd, root=root):
            return "Cannot copy or move a target into scoped ticket evidence."
    return None


def validate_shell_command(
    command: str,
    *,
    cwd: Path,
    root: Path,
    worktrees: Iterable[Path],
) -> Optional[str]:
    if contains_unmodelled_shell_syntax(command):
        return "Cannot verify shell expansion or escape."
    foreign = references_foreign_worktree(command, cwd=cwd, root=root, worktrees=worktrees)
    if foreign is not None:
        return _path_denial(
            command, foreign, root, "command references another Git Worktree"
        )
    tokens = tokenize(command)
    if tokens is None:
        return "Cannot parse shell command safely."
    segments, reason = split_segments(tokens)
    if reason:
        return reason
    assert segments is not None
    for segment in segments:
        reason = validate_segment(
            segment,
            cwd=cwd,
            root=root,
            worktrees=worktrees,
            depth=0,
        )
        if reason:
            return reason
    return None


def patch_targets(patch: str, *, cwd: Path, root: Path) -> Optional[str]:
    seen = False
    for line in patch.splitlines():
        if line.startswith(("*** Add File:", "*** Update File:", "*** Delete File:", "*** Move to:")):
            seen = True
            reason = target_reason(
                line.split(":", 1)[1].strip(), cwd=cwd, root=root, write=True
            )
            if reason:
                return reason
    if not seen:
        return "Cannot verify apply_patch targets."
    return None


def resolve_requested_cwd(raw: Any, *, base: Path, root: Path) -> Tuple[Optional[Path], Optional[str]]:
    if raw is None:
        return base, None
    if not isinstance(raw, str):
        return None, "Cannot verify requested working directory."
    target = path_from(raw, cwd=base, required=True)
    if target is None:
        return None, "Cannot verify requested working directory."
    if not is_inside(target, root):
        return None, _path_denial(
            raw, target, root, "working directory is outside the current Worktree"
        )
    return target, None


def pre_tool_use(
    event: dict[str, Any],
    *,
    process_cwd: Path,
    root: Path,
    worktrees: Iterable[Path],
    read_only: bool = False,
) -> Optional[str]:
    event_cwd, reason = resolve_requested_cwd(event.get("cwd"), base=process_cwd, root=root)
    if reason:
        return reason
    assert event_cwd is not None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return "Cannot verify tool input."
    requested_cwds: list[Path] = []
    for field in ("cwd", "workdir"):
        if field not in tool_input:
            continue
        requested, reason = resolve_requested_cwd(tool_input[field], base=event_cwd, root=root)
        if reason:
            return reason
        assert requested is not None
        requested_cwds.append(requested)
    if len(set(requested_cwds)) > 1:
        return "Cannot verify conflicting tool working directories."
    tool_cwd = requested_cwds[0] if requested_cwds else event_cwd

    tool_name = event.get("tool_name")
    if tool_name not in {"Bash", "apply_patch"}:
        return "Cannot verify PreToolUse tool: {0}".format(tool_name)
    command = tool_input.get("command")
    if not isinstance(command, str):
        return "Cannot verify tool command."
    if read_only:
        if tool_name == "apply_patch":
            return "Native investigation helpers cannot edit files."
        segments, reason = split_segments(tokenize(command) or [])
        if reason:
            return reason
        for segment in segments or []:
            if any(token in REDIRECTS or token in DENIED_REDIRECTS for token in segment):
                return "Native investigation helpers cannot redirect shell output."
            executable = segment[0]
            if executable == "git":
                if len(segment) < 2 or segment[1] not in {
                    "diff", "log", "show", "status", "rev-parse", "ls-files",
                    "cat-file", "merge-base", "show-ref",
                }:
                    return "Native investigation helpers cannot change Git state."
            elif executable not in {
                "cat", "diff", "head", "ls", "readlink", "stat", "tail", "wc",
                "grep", "rg", "pwd", "date", "id", "uname", "which", "whoami",
            }:
                return "Native helpers may only run read-only investigation commands."
    if tool_name == "apply_patch":
        return patch_targets(command, cwd=tool_cwd, root=root)
    return validate_shell_command(command, cwd=tool_cwd, root=root, worktrees=worktrees)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError) as error:
        deny("Cannot parse Hook input: {0}".format(error))
        return 0
    if not isinstance(event, dict):
        deny("Cannot parse Hook input.")
        return 0

    event_name = event.get("hook_event_name")
    process_cwd = Path(os.getcwd()).resolve()
    try:
        root, worktrees = discover_worktrees(process_cwd)
    except Exception as error:
        if event_name == "PreToolUse":
            deny("Cannot verify the current Git worktree: {0}".format(error))
        return 0

    if event_name == "SubagentStart":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SubagentStart",
                    "additionalContext": (
                        "Worktree boundary: {0}. Stay inside this worktree. "
                        "Do not access any other Git worktree."
                        " You are a temporary read-only investigation helper. "
                        "Do not implement, Review, write files, own a Team seat, "
                        "invoke agent-runner, or directly start an Agent Runtime. "
                        "Return findings to your parent; GraphTraj does not retain "
                        "an independent Session Trace for native helpers."
                    ).format(root),
                }
            }
        )
        return 0
    if event_name != "PreToolUse":
        return 0

    try:
        read_only = False
        if "--team-leader" in sys.argv[1:]:
            # Native helpers inherit the Leader's Hooks. Only the Runner-mapped
            # historical Session may use the Leader's command/write authority.
            registration = Path(os.environ["GRAPHTRAJ_PARENT_REGISTRATION"])
            mapping = yaml.safe_load(
                (registration.parent / "mapping.yml").read_text(encoding="utf-8")
            )
            read_only = event.get("session_id") != mapping["session"]
        reason = pre_tool_use(
            event,
            process_cwd=process_cwd,
            root=root,
            worktrees=worktrees,
            read_only=read_only,
        )
    except Exception as error:
        reason = "Cannot verify tool action: {0}".format(error)
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
