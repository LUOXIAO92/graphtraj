"""Which ended rounds of a child Agent its direct parent must handle.

One rule for every host and every parent level. Every other end is kept in
the child's records (status, reports, Trace) without notifying the parent.
"""
from __future__ import annotations

# Notice events that announce the end of one execution.
END_EVENTS = frozenset({'completed', 'interrupted', 'failed', 'runtime-error'})


def needs_parent(
    outcome: str,
    *,
    submitted: bool = False,
    pending_requests: int = 0,
    budget: bool = False,
    active_members: int = 0,
) -> bool:
    """Whether the end of a child's round must notify its direct parent.

    ``submitted`` is a report or result asking for the parent, ``budget`` a
    budget shortage, timeout or budget stop, and ``active_members`` the
    members under the child still executing or registered to start. A round
    whose child keeps no such member is the stall guard: the parent is the
    only one left to continue, so a leaf child's end always notifies.
    """
    return (submitted or pending_requests > 0 or budget or outcome != 'completed'
            or active_members == 0)


def notice_id(execution: object, event: object, request: object = None) -> str | None:
    """Return the stable identity of one execution's notice, if it has one.

    A notice announcing a native request also names that request, so two
    requests of one execution are two notices.
    """
    if isinstance(execution, str) and execution and isinstance(event, str) and event:
        return f'{execution}:{event}' if request is None else f'{execution}:{event}:{request}'
    return None
