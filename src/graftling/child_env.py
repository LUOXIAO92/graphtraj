"""The one rule deciding which environment variables a child Agent's Runtime receives.

Every launch path, for all four Runtimes and for a consumer's own members, calls
:func:`child_environment`. This is not a review rule: it neither forbids nor detects
a model reading its environment. It only does not hand a child keys unrelated to its
connection. ``PUBLIC_API.md`` section 3 holds the contract and every known gap.
"""

from __future__ import annotations

from functools import cache
from importlib.metadata import entry_points
import re
from typing import Iterable, Mapping

# One `_`-separated part of a name ending in a marker: HF_TOKEN, PGPASSWORD, APIKEY.
_CREDENTIAL_PART = re.compile(r'(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$')

# Git's indexed configuration names, not keys: with GIT_CONFIG_COUNT set, dropping
# them makes every Git command fail with a missing-key error.
_NOT_CREDENTIAL = re.compile(r'GIT_CONFIG_KEY_[0-9]+')


# The same rule as far as Codex's exclude globs allow: `*` and `?` only, case-insensitive,
# no classes and no negation. A part ending in a marker is the last part or is followed by
# `_`. `*KEY_<digit>*` is left out because it would also match GIT_CONFIG_KEY_<n>, whose
# removal breaks Git; so a dotfile's `MY_KEY_2` is not excluded (PUBLIC_API section 3.1).
_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'SECRETS', 'PASSWORD', 'CREDENTIAL', 'CREDENTIALS')
CODEX_SHELL_EXCLUDE = (
    *('*' + marker for marker in _MARKERS),
    *('*' + marker + '_*' for marker in _MARKERS if marker != 'KEY'),
    *('*KEY_' + first + '*' for first in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_'),
)


@cache
def consumer_environment() -> tuple[frozenset[str], tuple[str, ...]]:
    """Return the variables installed consumers keep from every child they did not start.

    A package that starts Agents through graftling from its own processes declares
    its own variables in the entry point group ``graftling.environment``: each
    entry's name is a variable, and its attribute says what the name is.
    ``connection`` marks a variable that carries the package's own host channel;
    ``prefix`` marks a name prefix the package owns. No child Runtime, child MCP
    server or reviewer receives a channel variable; Claude and Pi children also
    receive no name under a prefix. Only the installed metadata is read: the
    declaring package is never imported, and graftling itself names no consumer.

    Returns
    -------
    tuple
        The channel variables, and the prefixes, of every installed entry.

    Examples
    --------
    A consumer's ``pyproject.toml``::

        [project.entry-points."graftling.environment"]
        EXAMPLE_CONNECTION = "example:connection"
        EXAMPLE_ = "example:prefix"
    """
    connections: set[str] = set()
    prefixes: list[str] = []
    for entry in entry_points(group='graftling.environment'):
        if entry.attr == 'connection':
            connections.add(entry.name)
        elif entry.attr == 'prefix':
            prefixes.append(entry.name)
    return frozenset(connections), tuple(prefixes)


def is_credential_name(name: str) -> bool:
    """Return whether an environment variable's name marks it as a credential.

    The comparison ignores case and looks only at the name, never the value.
    Whole parts are compared, so ``TOKENIZERS_PARALLELISM`` and
    ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` stay ordinary where a substring test would
    call them credentials.

    Examples
    --------
    >>> [is_credential_name(n) for n in ('HF_TOKEN', 'PGPASSWORD', 'GIT_CONFIG_KEY_0', 'SSH_AUTH_SOCK')]
    [True, True, False, False]
    """
    upper = name.upper()
    if _NOT_CREDENTIAL.fullmatch(upper):
        return False
    return any(_CREDENTIAL_PART.search(part) for part in upper.split('_'))


def child_environment(
    parent: Mapping[str, str],
    *,
    api_key_env: str | None = None,
    defaults: Iterable[str] = (),
    declared: Iterable[str] = (),
    review_key: str | None = None,
) -> dict[str, str]:
    """Return the environment one child's Runtime starts from.

    Parameters
    ----------
    parent
        The owning host's environment; it is not changed.
    api_key_env
        The variable the child's connection names as its key.
    defaults
        Variables the Runtime reads when its connection names no key.
    declared
        The names the user declared with ``pass_env``. A model cannot supply them.
    review_key
        The ``api_key_env`` of the reviewer judging this child.

    Returns
    -------
    dict
        In order: ``parent`` without credential-class names; the child's own keys;
        the declared names; then the reviewer's key is removed, unless the connection
        itself names it. Declaring the reviewer's key therefore does not hand it over.
        A name absent from ``parent`` stays absent.

    Examples
    --------
    >>> parent = {'PATH': '/bin', 'A_KEY': 'a', 'B_KEY': 'b', 'R_KEY': 'r'}
    >>> child_environment(parent, api_key_env='A_KEY', declared=['R_KEY'], review_key='R_KEY')
    {'PATH': '/bin', 'A_KEY': 'a'}
    """
    environment = {name: value for name, value in parent.items() if not is_credential_name(name)}

    for name in (*([api_key_env] if api_key_env else []), *defaults, *declared):
        if name in parent:
            environment[name] = parent[name]

    if review_key and review_key != api_key_env:
        # The reviewer's key stays with this host, away from the child it judges.
        environment.pop(review_key, None)
    return environment
