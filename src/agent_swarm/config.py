"""The ``agents`` tool's own ``config.yml`` in its data root.

The data root is chosen by the caller: any directory for standalone use, or
``<project>/.graphtraj/swarm`` under GraphTraj. Nothing here reads another
product's configuration or a Runtime's user-global settings. The file holds
only the tool's own boolean choices::

    save_normalized_sessions: false
    backfill_history: false

A field absent from the file has no explicit choice and takes its default.
Consumers set first-use defaults with :func:`default_config`, which never
overrides a choice already written.

ponytail: a write rewrites the file with only the known fields, so comments a
user added are not preserved.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent_swarm.locks import exclusive
from agent_swarm.tool import AgentsError


CONFIG_FILE = "config.yml"

# Standalone defaults: archiving and history backfill are off.
CONFIG_DEFAULTS: dict[str, bool] = {
    "save_normalized_sessions": False,
    "backfill_history":         False,
}


def explicit_choices(root: Path) -> dict[str, bool]:
    """Return only the choices written in ``<root>/config.yml``.

    Blank lines and ``#`` comments are allowed. Any other content, an unknown
    field or a non-boolean value fails closed with ``ValueError`` instead of
    being guessed.
    """
    path = Path(root) / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    choices: dict[str, bool] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        content = line.split("#", 1)[0].strip()
        if not content:
            continue
        name, separator, value = (part.strip() for part in content.partition(":"))
        if not separator or name not in CONFIG_DEFAULTS or value not in ("true", "false"):
            raise ValueError(f"{path}:{number}: expected a known field set to true or false")
        if name in choices:
            raise ValueError(f"{path}:{number}: {name} is repeated")
        choices[name] = value == "true"
    return choices


def read_config(root: Path) -> dict[str, bool]:
    """Return effective settings: explicit choices over standalone defaults."""
    return {**CONFIG_DEFAULTS, **explicit_choices(root)}


def reject_archive_without_collector(root: Path) -> None:
    """Refuse ``save_normalized_sessions: true`` where no session collector exists.

    Independent hosts have no collector, so an enabled archive would fail every
    create. A consumer that binds a collector (GraphTraj) does not call this.
    """
    if read_config(root)["save_normalized_sessions"]:
        raise AgentsError(
            "archive-unavailable",
            f"{Path(root) / CONFIG_FILE}: save_normalized_sessions: true is not available here. "
            "Archiving needs a session collector, which GraphTraj provides and an independent "
            "host does not have. Set it to false (or delete the line) and start the host again.",
        )


def write_config(root: Path, **choices: bool) -> dict[str, bool]:
    """Record explicit choices and return the effective settings.

    Examples
    --------
    >>> write_config(root, save_normalized_sessions=True)  # doctest: +SKIP
    {'save_normalized_sessions': True, 'backfill_history': False}
    """
    return _update(root, choices, keep_existing=False)


def default_config(root: Path, **defaults: bool) -> dict[str, bool]:
    """Write ``defaults`` only for fields that have no explicit choice yet.

    A consumer such as GraphTraj calls this at first use to turn archiving on
    while preserving any choice the user already made.
    """
    return _update(root, defaults, keep_existing=True)


def _update(root: Path, values: dict[str, bool], *, keep_existing: bool) -> dict[str, bool]:
    """Merge ``values`` into the file under the config lock and replace it atomically."""
    for name, value in values.items():
        if name not in CONFIG_DEFAULTS or not isinstance(value, bool):
            raise ValueError(f"{name}: expected a known field with a boolean value")

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive(root / "live" / "config.lock"):
        choices = explicit_choices(root)
        merged  = {**values, **choices} if keep_existing else {**choices, **values}
        if merged != choices:
            text = "".join(
                f"{name}: {'true' if merged[name] else 'false'}\n"
                for name in CONFIG_DEFAULTS if name in merged
            )
            descriptor, temporary = tempfile.mkstemp(dir=root, prefix=".config-")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, root / CONFIG_FILE)
    return {**CONFIG_DEFAULTS, **merged}
