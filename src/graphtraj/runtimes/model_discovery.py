"""Bounded, metadata-only native queries with a nonsecret output projection."""

from __future__ import annotations


def discover_models(runtime: dict, provider: str | None = None) -> dict:
    """Query native catalogs through agents without a turn or an account check.

    Parameters
    ----------
    runtime : dict
        One entry of the user connections catalog; its ``runtime`` and
        ``home`` select the native catalog.
    provider : str, optional
        A provider to list. When the entry declares it, its ``base_url`` and
        ``api_key_env`` (a variable name) go with it, as for a child of that
        connection; a DSH provider with ``base_url`` is a Messages endpoint
        behind DSH's DeepSeek route, so only those two are passed. Without
        ``provider`` the Runtime's own catalog is listed, as before.

    Returns
    -------
    dict
        GraphTraj's discovery document: models and the whole catalog are
        marked ``native``, account access stays unknown, and ``groups`` holds
        the models by provider, ``[{"provider", "models"}]``. No credential
        value is read or returned.

    Raises
    ------
    ValueError
        graftling refuses the connection, such as a DSH provider the installed
        DSH does not serve or one without ``api_key_env``.
    """
    from graftling import discover_models as agents_discover_models

    # The catalog's provider/model entries are GraphTraj's manual records and
    # must not replace the native query, so no ``models`` key is passed.
    connection = {'runtime': runtime['runtime']}
    if runtime.get('home'):
        connection['home'] = runtime['home']
    if provider is not None:
        declared = runtime['providers'].get(provider, {})
        connection.update({field: declared[field] for field in ('base_url', 'api_key_env') if field in declared})
        if not (runtime['runtime'] == 'dsh' and declared.get('base_url')):
            connection['provider'] = provider
    found = agents_discover_models(connection)

    def native(models: list[dict]) -> list[dict]:
        """Mark each listed model as coming from the native catalog."""
        return [{**model, 'source': 'native'} for model in models]

    document = {'runtime': found['runtime'], 'source': 'native', 'account_access': 'unknown',
                'models': native(found['models']),
                'groups': [{'provider': group['provider'], 'models': native(group['models'])}
                           for group in found['groups']],
                'supported_efforts': 'unknown', 'catalog_scope': 'runtime',
                'status': found['status']}
    if 'provider_status' in found:
        document['provider_status'] = found['provider_status']
    return {**document, 'message': found['message']}


def pi_model_domain(home: str, provider: str, model: str, api_key_env: str | None = None) -> str:
    """Resolve a selected native destination without exposing endpoint credentials.

    Extension-only or unavailable models are unsupported by this metadata seam;
    they must not be launched under an unrelated provider's network grants.
    The agents resolver reads the catalog of the Runtime this Runner selects.
    """
    from graftling.pi import pi_destination
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
    from graphtraj.workspace.runner_project import runtime_executable

    try:
        executable = str(runtime_executable('pi'))
    except Exception:
        raise RuntimeAdapterError(
            'ROLE_CONFIG_UNSUPPORTED',
            'Pi did not expose a supported native destination for the selected provider/model.',
        ) from None
    return pi_destination(executable, home, provider, model, api_key_env)
