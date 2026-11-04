"""The Claude Code plugin files of a host, with the MCP tools it associates."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from typing import Iterable

# The one line of host_context.mjs naming its tools; the written copy replaces it.
TOOLS_LINE = 'const TOOLS = ["agents"];'


def claude_host_plugin(directory: Path, name: str, description: str, tools: Iterable[str] = ()) -> dict[str, object]:
    """Return a host plugin's files, keyed by absolute path; nothing is written.

    The plugin is the one module ``hooks/host_context.mjs``. It associates
    each native call of the ``agents`` tool with its Claude Session, and does
    the same for ``tools``, the names of tools a package serves beside
    ``agents`` on the same MCP server named ``agents``.

    Parameters
    ----------
    directory
        Plugin directory, normally ``<project>/.claude/skills/<name>``.
    name, description
        The plugin manifest's fields.
    tools
        A declared tool gets the association, notices and cleanup of
        ``agents`` but renders no agents exchange. The host's ``NativeCalls``
        must declare the same names.

    Returns
    -------
    A JSON value for each manifest and the module's text.

    Raises
    ------
    ValueError
        A tool name MCP cannot carry, ``agents`` itself, or a repeated name.
    """
    tools = list(tools)
    for tool in tools:
        if not isinstance(tool, str) or re.fullmatch(r'[A-Za-z0-9_-]+', tool) is None:
            raise ValueError(f'Not a tool name: {tool!r}.')
    if len({'agents', *tools}) != len(tools) + 1:
        raise ValueError('Declare each added tool once, and not agents itself.')
    module = Path(__file__).with_name('host_context.mjs').read_text(encoding='utf-8')
    if module.count(TOOLS_LINE) != 1:
        raise RuntimeError(f'host_context.mjs must hold exactly one line {TOOLS_LINE!r}.')
    directory = Path(directory)
    return {
        str(directory / '.claude-plugin/plugin.json'): {'name': name, 'version': '1', 'description': description},
        str(directory / 'hooks/hooks.json'): {'modules': ['./host_context.mjs']},
        str(directory / 'hooks/host_context.mjs'): module.replace(
            TOOLS_LINE, f"const TOOLS = {json.dumps(['agents', *tools])};"),
    }


def _existing_document(path: Path) -> dict | None:
    """Return the JSON object at ``path``, ``None`` without a file; refuse anything else, naming it."""
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise ValueError(f'{path}: not valid JSON, so it was left unchanged: {error}') from error
    if not isinstance(document, dict):
        raise ValueError(f'{path}: expected a JSON object, so it was left unchanged.')
    return document


def _merged(existing: object, update: object) -> object:
    """Merge dicts recursively, keeping what ``update`` does not name; anything else is replaced."""
    if not isinstance(existing, dict) or not isinstance(update, dict):
        return update
    return {**existing, **{key: _merged(existing.get(key), value) for key, value in update.items()}}


def write_adoption(material: dict[str, object]) -> None:
    """Write adoption material: text as it is, a JSON value merged into any existing file.

    The material holds only what the command owns, so a re-run updates those
    values and keeps every other key at any depth. A list or scalar in the
    material replaces the existing value.

    Parameters
    ----------
    material
        Absolute path to a file's text or JSON object, as ``adoption_material``
        and ``claude_host_plugin`` return it.

    Raises
    ------
    ValueError
        An existing JSON file does not parse or does not hold an object. The
        message names it. Every document is computed first, so nothing is written.
    """
    documents = {
        Path(path): content if isinstance(content, str)
        else json.dumps(_merged(_existing_document(Path(path)), content), indent=2) + '\n'
        for path, content in material.items()
    }
    for target, text in documents.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


def kept_host_paths(config: Path, project: Path, defaults: dict[str, str]) -> dict[str, str]:
    """Return the paths a re-run keeps from the host configuration at ``config``.

    A path the user declared stays, so a moved data root survives. The one
    exception is a project that moved: a value inside the configuration's
    recorded ``cwd``, when that differs from ``project``, goes to the same
    relative place under ``project``. Paths are compared as written, since the
    old location may no longer exist.

    Parameters
    ----------
    config
        The host configuration, which may not exist yet.
    project
        The project's absolute directory.
    defaults
        Each kept key and its value when the configuration has no string there.

    Returns
    -------
    A value for each key of ``defaults``.

    Raises
    ------
    ValueError
        An existing configuration does not parse or does not hold an object.
    """
    existing = _existing_document(Path(config)) or {}
    old = existing.get('cwd')
    moved = isinstance(old, str) and os.path.isabs(old) and Path(old).resolve() != Path(project).resolve()
    kept = {}
    for key, default in defaults.items():
        value = existing.get(key)
        if not isinstance(value, str):
            kept[key] = default
            continue
        # Normalized so that ``<old>/../elsewhere`` does not count as inside.
        location = Path(os.path.normpath(value))
        inside = moved and location.is_relative_to(os.path.normpath(old))
        kept[key] = str(Path(project) / location.relative_to(os.path.normpath(old))) if inside else value
    return kept
