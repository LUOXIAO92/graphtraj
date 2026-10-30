"""Bounded, metadata-only native queries with a nonsecret output projection."""

from __future__ import annotations


def discover_models(runtime: dict) -> dict:
    """Query native catalogs through agents without a turn or an account check.

    ``runtime`` is one entry of the user connections catalog; only its
    ``runtime`` and ``home`` select the native catalog, as before. The agents
    result is projected onto GraphTraj's existing document: models and the
    whole catalog are marked ``native`` and account access stays unknown.
    """
    from agent_swarm import discover_models as agents_discover_models

    # The catalog's provider/model entries are GraphTraj's manual records and
    # must not replace the native query, so no ``models`` key is passed.
    connection = {'runtime': runtime['runtime']}
    if runtime.get('home'):
        connection['home'] = runtime['home']
    found = agents_discover_models(connection)

    document = {'runtime': found['runtime'], 'source': 'native', 'account_access': 'unknown',
                'models': [{**model, 'source': 'native'} for model in found['models']],
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
    from agent_swarm.pi import pi_destination
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
