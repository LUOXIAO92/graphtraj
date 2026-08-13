"""Runtime-neutral background owner for one Engineer turn."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Mapping

import yaml

from .codex_adapter import create_codex_turn
from .runner_io import (
    ActiveTurnReservation,
    release_active_turn,
    write_active_turn_owner,
    write_yaml_durably,
)
from .runtime_adapter import RuntimeAdapter, RuntimeAdapterError, RuntimeTurn
from .runner_transport import runtime_launch_failure


ADAPTERS: Mapping[str, RuntimeAdapter] = {"codex": create_codex_turn}


def run(launch_file: Path) -> int:
    session_directory = launch_file.parent
    runner_directory = session_directory.parent.parent
    active_turn: ActiveTurnReservation | None = None
    turn_handle: RuntimeTurn | None = None
    turn_terminal = False
    previous_sigterm = None

    def request_termination(signum: int, frame: object) -> None:
        nonlocal turn_terminal
        if turn_handle is not None:
            turn_terminal = turn_handle.terminate()

    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
        if not isinstance(launch, dict):
            raise ValueError("launch document is not a mapping")
        active_turn = ActiveTurnReservation(
            key=launch["active_turn_key"],
            device=launch["active_turn_device"],
            inode=launch["active_turn_inode"],
        )
        runtime = launch["runtime"]
        adapter = ADAPTERS[runtime]
        request = launch["adapter_request"]
        base_mapping = launch["mapping"]
        if not isinstance(base_mapping, dict):
            raise ValueError("mapping is not a mapping")
        prompt = sys.stdin.read()

        def record_session(session: str, runtime_pid: int) -> None:
            mapping = dict(base_mapping)
            mapping.update(
                {
                    "session": session,
                    "worker_pid": os.getpid(),
                    "runtime_pid": runtime_pid,
                }
            )
            assert active_turn is not None
            write_active_turn_owner(
                runner_directory,
                active_turn,
                {"activity": "running", **mapping},
            )
            write_yaml_durably(session_directory / "mapping.yml", mapping)

        turn_handle = adapter(
            request, prompt, session_directory, record_session
        )
        previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
        turn = turn_handle.run()
        turn_terminal = True
        write_yaml_durably(session_directory / "turn.yml", turn)
    except RuntimeAdapterError as error:
        turn_terminal = error.terminal_confirmed
        _write_launch_error(
            session_directory,
            error.code,
            error.message,
            terminal_confirmed=error.terminal_confirmed,
        )
        return 1
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        _write_launch_error(
            session_directory,
            "RUNTIME_WORKER_FAILED",
            "The internal Runtime worker could not own the Engineer turn.",
            str(error),
            terminal_confirmed=False,
        )
        return 1
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if active_turn is not None and turn_terminal:
            release_active_turn(runner_directory, active_turn)

    return 0


def _write_launch_error(
    session_directory: Path,
    code: str,
    message: str,
    diagnostic: str = "",
    *,
    terminal_confirmed: bool,
) -> None:
    failure = runtime_launch_failure(
        code,
        message,
        diagnostic,
        terminal_confirmed=terminal_confirmed,
    )
    write_yaml_durably(session_directory / "launch-error.yml", failure)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
