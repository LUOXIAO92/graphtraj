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
    active_turn_directory,
    release_active_turn,
    write_yaml_durably,
)
from .runtime_adapter import RuntimeAdapter, RuntimeAdapterError, RuntimeTurn


ADAPTERS: Mapping[str, RuntimeAdapter] = {"codex": create_codex_turn}


def run(launch_file: Path) -> int:
    session_directory = launch_file.parent
    runner_directory = session_directory.parent.parent
    active_turn_key = ""
    turn_handle: RuntimeTurn | None = None
    mapping_recorded = False
    terminal_turn: dict[str, object] | None = None
    terminal_persisted = False
    runtime_terminal = False
    interruption_confirmed = False
    previous_sigterm = None

    def request_termination(signum: int, frame: object) -> None:
        nonlocal interruption_confirmed
        if turn_handle is not None and turn_handle.terminate():
            interruption_confirmed = True

    try:
        try:
            launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
            if not isinstance(launch, dict):
                raise ValueError("launch document is not a mapping")
            active_turn_key = launch["active_turn_key"]
            runtime = launch["runtime"]
            adapter = ADAPTERS[runtime]
            request = launch["adapter_request"]
            base_mapping = launch["mapping"]
            if not isinstance(base_mapping, dict):
                raise ValueError("mapping is not a mapping")
            prompt = sys.stdin.read()

            def record_session(session: str, runtime_pid: int) -> None:
                nonlocal mapping_recorded
                mapping = dict(base_mapping)
                mapping.update(
                    {
                        "session": session,
                        "worker_pid": os.getpid(),
                        "runtime_pid": runtime_pid,
                    }
                )
                reservation = active_turn_directory(
                    runner_directory, active_turn_key
                )
                write_yaml_durably(
                    reservation / "reservation.yml",
                    {"activity": "running", **mapping},
                )
                write_yaml_durably(session_directory / "mapping.yml", mapping)
                mapping_recorded = True

            turn_handle = adapter(
                request, prompt, session_directory, record_session
            )
            previous_sigterm = signal.signal(signal.SIGTERM, request_termination)
            turn = turn_handle.run()
            runtime_terminal = True
            terminal_turn = _terminal_turn(turn, interruption_confirmed)
        except RuntimeAdapterError as error:
            runtime_terminal = error.terminal_confirmed
            if not runtime_terminal and turn_handle is not None:
                turn_handle.terminate_until_terminal()
                runtime_terminal = True
            if mapping_recorded and runtime_terminal:
                terminal_turn = {
                    "outcome": (
                        "interrupted" if interruption_confirmed else "runtime-error"
                    )
                }
            else:
                _write_launch_error(session_directory, error.code, error.message)
        except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
            if mapping_recorded and runtime_terminal:
                terminal_turn = {"outcome": "runtime-error"}
            else:
                _write_launch_error(
                    session_directory,
                    "RUNTIME_WORKER_FAILED",
                    "The internal Runtime worker could not own the Engineer turn.",
                    str(error),
                )
        if terminal_turn is not None:
            try:
                write_yaml_durably(session_directory / "turn.yml", terminal_turn)
                terminal_persisted = True
            except (OSError, yaml.YAMLError) as error:
                _write_launch_error(
                    session_directory,
                    "RUNTIME_WORKER_FAILED",
                    "The internal Runtime worker could not persist its terminal outcome.",
                    str(error),
                )
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        if active_turn_key and terminal_persisted:
            release_active_turn(runner_directory, active_turn_key)
    return 0 if terminal_persisted else 1


def _terminal_turn(turn: object, interrupted: bool) -> dict[str, object]:
    if not isinstance(turn, dict):
        raise ValueError("Runtime turn result is not a mapping")
    outcome = turn.get("outcome")
    if outcome not in {"completed", "runtime-error"}:
        raise ValueError("Runtime turn result has an invalid outcome")
    terminal = {"outcome": "interrupted" if interrupted else outcome}
    exit_code = turn.get("runtime_exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        terminal["runtime_exit_code"] = exit_code
    return terminal


def _write_launch_error(
    session_directory: Path,
    code: str,
    message: str,
    diagnostic: str = "",
) -> None:
    failure = {"code": code, "message": message}
    if diagnostic:
        failure["diagnostic"] = diagnostic
    write_yaml_durably(session_directory / "launch-error.yml", failure)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
