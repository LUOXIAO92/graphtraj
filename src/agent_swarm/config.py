"""The ``agents`` tool's own ``config.yml`` in its data root.

The data root is chosen by the caller: any directory for standalone use, or
``<project>/.graphtraj/swarm`` under GraphTraj. Nothing here reads another
product's configuration or a Runtime's user-global settings. The file holds
the tool's own boolean choices, the Runtime connections children may use and
optional named presets::

    save_normalized_sessions: false
    backfill_history: false
    connections:
      work-claude:
        runtime: claude              # claude, codex, pi or dsh
        home: /abs/native/home       # optional native home
        base_url: https://host/v1    # optional, credential-free
        api_key_env: WORK_KEY        # optional: the variable's NAME, never a key
        provider: anthropic          # optional native provider
        models:                      # optional candidates; else discovery
          - claude-opus-5-5          # an id, or a mapping with id and optional
          - id: claude-sonnet-5-5    # alias, provider, supported_efforts
            supported_efforts: [low, high]
    presets:
      reviewer:
        connection: work-claude      # or runtime: <name>, never both
        model: claude-opus-5-5       # optional
        reasoning_effort: high       # optional
    reviewers:
      local-review:                  # a chat completions endpoint, or
        base_url: http://127.0.0.1:1234/v1
        model: reviewer-model
        api_key_env: REVIEW_KEY      # optional: the variable's NAME, never a key
        json_mode: false             # optional, default false
        timeout_seconds: 20          # optional, default 20
      own-script:                    # a local process
        command: [/abs/reviewer, --strict]

A connection names its reviewer with ``review: <reviewer name>``; this is how
the user declares that its native approval is missing or unusable. A connection
without it keeps native approval and no reviewer ever runs.

A field absent from the file has no explicit choice and takes its default;
without connections each Runtime uses its native default login. Consumers set
first-use defaults with :func:`default_config`, which never overrides a choice
already written. Reading is strict: an unknown or repeated field, a wrong type
or a reference to an undeclared connection fails with the file and line.

A write replaces only the boolean lines and keeps every other line, including
connections, presets and comments.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from agent_swarm.locks import exclusive

if TYPE_CHECKING:
    import yaml


CONFIG_FILE = "config.yml"

# Standalone defaults: archiving and history backfill are off.
CONFIG_DEFAULTS: dict[str, bool] = {
    "save_normalized_sessions": False,
    "backfill_history":         False,
}

# Runtimes a connection may name, and the keys of each declared entry.
RUNTIMES = ("claude", "codex", "pi", "dsh")
CONNECTION_FIELDS = frozenset({"runtime", "home", "provider", "base_url", "api_key_env", "models", "review"})
MODEL_FIELDS      = frozenset({"id", "alias", "provider", "supported_efforts"})
PRESET_FIELDS     = frozenset({"connection", "runtime", "model", "reasoning_effort"})
REVIEWER_HTTP_FIELDS = frozenset({"base_url", "model", "api_key_env", "json_mode"})
REVIEWER_FIELDS      = REVIEWER_HTTP_FIELDS | {"command", "timeout_seconds"}

_STR  = "tag:yaml.org,2002:str"
_BOOL = "tag:yaml.org,2002:bool"
_NUMBERS = ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float")


def explicit_choices(root: Path) -> dict[str, bool]:
    """Return only the boolean choices written in ``<root>/config.yml``.

    Blank lines and ``#`` comments are allowed. The whole file is checked:
    an unknown or repeated field, a non-boolean choice or an invalid
    connection or preset fails closed with ``ValueError`` naming the file and
    line instead of being guessed.
    """
    return _read(Path(root))[0]


def read_connections(root: Path) -> dict[str, dict[str, dict]]:
    """Return the declared ``connections`` and ``presets``, each keyed by name.

    Every entry is a copy of what the file says plus its ``name``; ``home`` is
    expanded to an absolute path. No credential is read: ``api_key_env`` stays
    the variable's name. ``reviewers`` is added when the file declares any.
    Raises ``ValueError`` like :func:`explicit_choices`.
    """
    _, connections, presets, reviewers = _read(Path(root))
    declared = {"connections": connections, "presets": presets}
    return {**declared, "reviewers": reviewers} if reviewers else declared


def is_loopback(host: str | None) -> bool:
    """Whether ``host`` names this machine, so traffic to it leaves no network."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _read(root: Path) -> tuple[dict[str, bool], dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Parse and check the whole file once."""
    path = root / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, {}, {}, {}

    def fail(node: yaml.Node | None, problem: str) -> ValueError:
        """Name the file and the 1-based line of ``node``."""
        line = node.start_mark.line + 1 if node is not None else 1
        return ValueError(f"{path}:{line}: {problem}")

    def fields(node: yaml.Node, what: str) -> list[tuple[str, yaml.Node, yaml.Node]]:
        """Return a mapping's (name, key, value) items; names are unique strings."""
        if not isinstance(node, yaml.MappingNode):
            raise fail(node, f"{what} must be a mapping of field: value lines")
        seen: set[str] = set()
        items = []
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode) or key.tag != _STR or not key.value:
                raise fail(key, f"{what}: expected a field name")
            if key.value in seen:
                raise fail(key, f"{key.value} is repeated")
            seen.add(key.value)
            items.append((key.value, key, value))
        return items

    def string(node: yaml.Node, name: str) -> str:
        """Return a non-empty string scalar."""
        if not isinstance(node, yaml.ScalarNode) or node.tag != _STR or not node.value.strip():
            raise fail(node, f"{name}: expected a non-empty string")
        return node.value

    def strings(node: yaml.Node, name: str) -> list[str]:
        """Return a non-empty list of non-empty strings."""
        if not isinstance(node, yaml.SequenceNode) or not node.value:
            raise fail(node, f"{name}: expected a non-empty list of strings")
        return [string(item, name) for item in node.value]

    def variable(node: yaml.Node, name: str) -> str:
        """Return the name of an environment variable, never a key."""
        value = string(node, name)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise fail(node, f"{name}: expected the name of an environment variable, never a key")
        return value

    def endpoint(node: yaml.Node, name: str) -> str:
        """Return a credential-free http(s) URL."""
        value = string(node, name)
        url = urlsplit(value)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise fail(node, f"{name}: expected a credential-free http(s) URL")
        return value

    def boolean(node: yaml.Node, name: str) -> bool:
        """Return exactly true or false."""
        if not isinstance(node, yaml.ScalarNode) or node.tag != _BOOL or node.value not in ("true", "false"):
            raise fail(node, f"{name}: expected true or false")
        return node.value == "true"

    def seconds(node: yaml.Node, name: str) -> int | float:
        """Return a finite number of seconds above zero."""
        if isinstance(node, yaml.ScalarNode) and node.tag in _NUMBERS:
            value = yaml.SafeLoader("").construct_object(node)
            if 0 < value < math.inf:
                return value
        raise fail(node, f"{name}: expected a finite number above 0")

    def model(node: yaml.Node, name: str) -> str | dict:
        """Return one candidate: an id, or a mapping with ``id`` and optional metadata."""
        if isinstance(node, yaml.ScalarNode):
            return string(node, name)
        entry = {}
        for field, key, value in fields(node, name):
            if field not in MODEL_FIELDS:
                raise fail(key, f"{name}.{field}: unknown field; expected " + ", ".join(sorted(MODEL_FIELDS)))
            entry[field] = (strings(value, f"{name}.{field}") if field == "supported_efforts"
                            else string(value, f"{name}.{field}"))
        if "id" not in entry:
            raise fail(node, f"{name}.id: required")
        return entry

    legacy = _legacy_choices(path, text)
    if legacy is not None:
        return legacy, {}, {}, {}
    # Only connections and presets need YAML; boolean-only files never import it.
    import yaml
    try:
        document = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        raise ValueError(f"{path}:{mark.line + 1 if mark else 1}: not valid YAML") from None
    if document is None:
        return {}, {}, {}, {}

    choices: dict[str, bool] = {}
    sections: dict[str, yaml.Node] = {}
    for name, key, value in fields(document, "config.yml"):
        if name in CONFIG_DEFAULTS:
            choices[name] = boolean(value, name)
        elif name in ("connections", "presets", "reviewers"):
            sections[name] = value
        else:
            raise fail(key, f"{name}: unknown field; expected {', '.join(CONFIG_DEFAULTS)}, "
                            "connections, presets or reviewers")

    reviewers: dict[str, dict] = {}
    if "reviewers" in sections:
        for name, key, value in fields(sections["reviewers"], "reviewers"):
            entry = {"name": name}
            for field, field_key, item in fields(value, f"reviewers.{name}"):
                label = f"reviewers.{name}.{field}"
                if field not in REVIEWER_FIELDS:
                    raise fail(field_key, f"{label}: unknown field; expected "
                                          + ", ".join(sorted(REVIEWER_FIELDS)))
                entry[field] = (strings(item, label) if field == "command"
                                else boolean(item, label) if field == "json_mode"
                                else seconds(item, label) if field == "timeout_seconds"
                                else endpoint(item, label) if field == "base_url"
                                else variable(item, label) if field == "api_key_env"
                                else string(item, label))
            if "command" in entry and REVIEWER_HTTP_FIELDS & entry.keys():
                raise fail(key, f"reviewers.{name}: give either command or the HTTP fields, never both")
            if "command" not in entry and not {"base_url", "model"} <= entry.keys():
                raise fail(key, f"reviewers.{name}: give either command, or base_url and model")
            url = urlsplit(entry.get("base_url", ""))
            if "api_key_env" in entry and url.scheme == "http" and not is_loopback(url.hostname):
                raise fail(key, f"reviewers.{name}.api_key_env: a key is never sent over plain http "
                                "to another host; use https")
            reviewers[name] = entry

    connections: dict[str, dict] = {}
    if "connections" in sections:
        for name, key, value in fields(sections["connections"], "connections"):
            entry: dict = {"name": name}
            for field, field_key, item in fields(value, f"connections.{name}"):
                label = f"connections.{name}.{field}"
                if field not in CONNECTION_FIELDS:
                    raise fail(field_key, f"{label}: unknown field; expected "
                                          + ", ".join(sorted(CONNECTION_FIELDS)))
                if field == "models":
                    if not isinstance(item, yaml.SequenceNode) or not item.value:
                        raise fail(item, f"{label}: expected a non-empty list of models")
                    entry[field] = [model(node, label) for node in item.value]
                    ids = [value if isinstance(value, str) else value["id"] for value in entry[field]]
                    if len(set(ids)) != len(ids):
                        raise fail(item, f"{label}: a model id is repeated")
                    continue
                entry[field] = string(item, label)
                if field == "runtime" and entry[field] not in RUNTIMES:
                    raise fail(item, f"{label}: expected one of {', '.join(RUNTIMES)}")
                if field == "home":
                    entry[field] = os.path.expanduser(entry[field])
                    if not os.path.isabs(entry[field]):
                        raise fail(item, f"{label}: expected an absolute path")
                if field == "api_key_env":
                    variable(item, label)
                if field == "base_url":
                    endpoint(item, label)
                if field == "review" and entry[field] not in reviewers:
                    raise fail(item, f"{label}: no reviewer {entry[field]!r} is declared")
            if "runtime" not in entry:
                raise fail(key, f"connections.{name}.runtime: required")
            connections[name] = entry

    presets: dict[str, dict] = {}
    if "presets" in sections:
        for name, key, value in fields(sections["presets"], "presets"):
            entry = {"name": name}
            for field, field_key, item in fields(value, f"presets.{name}"):
                label = f"presets.{name}.{field}"
                if field not in PRESET_FIELDS:
                    raise fail(field_key, f"{label}: unknown field; expected "
                                          + ", ".join(sorted(PRESET_FIELDS)))
                entry[field] = string(item, label)
                if field == "runtime" and entry[field] not in RUNTIMES:
                    raise fail(item, f"{label}: expected one of {', '.join(RUNTIMES)}")
                if field == "connection" and entry[field] not in connections:
                    raise fail(item, f"{label}: no connection {entry[field]!r} is declared")
            if ("connection" in entry) == ("runtime" in entry):
                raise fail(key, f"presets.{name}: give either connection or runtime")
            presets[name] = entry
    return choices, connections, presets, reviewers


def _legacy_choices(path: Path, text: str) -> dict[str, bool] | None:
    """Read a file of only boolean lines exactly as before 0.1.1, else return None.

    Every such file keeps its meaning and errors, including forms YAML reads
    differently (``backfill_history:true``, mixed indentation).
    """
    lines = [(number, line.split("#", 1)[0].strip()) for number, line in enumerate(text.splitlines(), start=1)]
    lines = [(number, content) for number, content in lines if content]
    if any(content.partition(":")[0].strip() not in CONFIG_DEFAULTS for _, content in lines):
        return None
    choices: dict[str, bool] = {}
    for number, content in lines:
        name, separator, value = (part.strip() for part in content.partition(":"))
        if not separator or value not in ("true", "false"):
            raise ValueError(f"{path}:{number}: expected a known field set to true or false")
        if name in choices:
            raise ValueError(f"{path}:{number}: {name} is repeated")
        choices[name] = value == "true"
    return choices


def read_config(root: Path) -> dict[str, bool]:
    """Return effective settings: explicit choices over standalone defaults."""
    return {**CONFIG_DEFAULTS, **explicit_choices(root)}


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
            ) + _other_lines(root / CONFIG_FILE)
            descriptor, temporary = tempfile.mkstemp(dir=root, prefix=".config-")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, root / CONFIG_FILE)
    return {**CONFIG_DEFAULTS, **merged}


def _other_lines(path: Path) -> str:
    """Return the file without its top-level boolean lines (already checked)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    if _legacy_choices(path, text) is not None:
        return "".join(line for line in text.splitlines(keepends=True)
                       if not line.split("#", 1)[0].strip())
    import yaml

    document = yaml.compose(text, Loader=yaml.SafeLoader)
    if document is None:
        return text
    choices = {number for key, value in document.value if key.value in CONFIG_DEFAULTS
               for number in range(key.start_mark.line, value.end_mark.line + 1)}
    return "".join(line for number, line in enumerate(text.splitlines(keepends=True))
                   if number not in choices)
