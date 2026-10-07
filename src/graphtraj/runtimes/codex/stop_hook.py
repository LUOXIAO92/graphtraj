"""Codex command Stop hook; input comes from its owning native lifecycle."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

import click

from graphtraj.execution.main_finalize import check_main_finalize


@click.command()
@click.option('--binding', required=True, type=click.Path(path_type=Path))
@click.option('--hook-session', required=True)
def main(binding: Path, hook_session: str) -> None:
    """Receive native hook input and write only a valid Codex Stop response.

    Other hook events skip before opening Main's private binding. SIGTERM becomes
    KeyboardInterrupt so the async owner can cancel its checker; neither
    interrupt emits a continuation decision.
    """
    def interrupted(signum: int, frame: object) -> None:
        """Preserve a host cancellation instead of interpreting it as an error."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        event = json.load(sys.stdin)
        if (not isinstance(event, dict) or event.get('hook_event_name') != 'Stop'
                or event.get('session_id') != hook_session):
            result = {}
        else:
            result = check_main_finalize(binding, event)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        reason = f'Completion hook failed: {error}'
        result = {'continue': False, 'stopReason': reason, 'systemMessage': reason}
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
