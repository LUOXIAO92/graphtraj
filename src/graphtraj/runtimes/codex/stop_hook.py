"""Codex command Stop hook; input comes from its owning native lifecycle."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

import click

from graphtraj.execution.main_finalize import PREFIX


@click.command()
@click.option('--binding', type=click.Path(path_type=Path))
@click.option('--hook-session')
@click.option('--channel')
@click.option('--project', type=click.Path(path_type=Path))
def main(
    binding: Path | None,
    hook_session: str | None,
    channel: str | None,
    project: Path | None,
) -> None:
    """Carry native lifecycle input through the registered owner's CLI channel.

    Legacy static Session bindings remain refused without changing old records.
    Native user interruption exits without a continuation response.
    """
    def interrupted(signum: int, frame: object) -> None:
        """Preserve a host cancellation instead of interpreting it as an error."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    click.echo(f'{PREFIX} start: Resolving owning host.', err=True)
    try:
        from graphtraj.interfaces.hosted_cli import forward_lifecycle

        event = json.load(sys.stdin)
        if binding is not None or hook_session is not None:
            raise ValueError('Legacy standalone hook cannot authenticate GraphTraj identity; '
                             'prepare its authenticated channel with graphtraj bind-finalize.')
        result = forward_lifecycle(event, project or Path.cwd(), channel)
        # Excluded Agent purposes have no native check to translate.
        if result.get('status') == 'skip':
            result = {'systemMessage': f"{PREFIX} skip: {result['reason']}"}
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        reason = f'{PREFIX} failure: {error}'
        result = {'continue': False, 'stopReason': reason, 'systemMessage': reason}
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
