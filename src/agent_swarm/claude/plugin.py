"""The Claude Code plugin files of a host, with the MCP tools it associates."""
from __future__ import annotations
import json
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
