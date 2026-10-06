"""Codex command Stop hook; input comes from its owning native lifecycle."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

import click

from graphtraj.execution.main_finalize import PREFIX


@click.command()
@click.option('--binding', required=True, type=click.Path(path_type=Path))
@click.option('--hook-session', required=True)
def main(binding: Path, hook_session: str) -> None:
    """Visibly refuse legacy static bindings without reading or changing them.

    This entry remains to report an actionable failure to old configurations.
    The adopted owning host must invoke its finish_check callback; a native
    Session argument cannot authenticate GraphTraj identity. SIGTERM still
    exits without requesting continuation.
    """
    def interrupted(signum: int, frame: object) -> None:
        """Preserve a host cancellation instead of interpreting it as an error."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    click.echo(f'{PREFIX} start: Resolving owning host.', err=True)
    try:
        json.load(sys.stdin)
        raise ValueError(
            'Legacy standalone hook cannot authenticate GraphTraj identity. '
            'Keep it disabled; adopt HostTool.finish_check through the owning host.'
        )
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        reason = f'{PREFIX} failure: {error}'
        result = {'continue': False, 'stopReason': reason, 'systemMessage': reason}
    click.echo(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
