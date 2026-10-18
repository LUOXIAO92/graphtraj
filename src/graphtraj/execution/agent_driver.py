"""Run existing Runtime Adapters' native executions for the ``agents`` core.

:class:`AdapterDriver` is GraphTraj's :class:`agent_swarm.RuntimeDriver`. It
resolves Runtime settings from the project's configured role presets, then
runs the Adapter's ``managed_execution`` owner (``RuntimeTurn``) on a thread
of the calling host process. No Task, Team, Round, role_tree, Worldline,
budget or report is read or required.

The thread is non-daemon, so a one-shot host such as the CLI stays alive
until its Agent's execution ends; a long-lived host (MCP server, Runtime
Worker) keeps serving other calls meanwhile.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Mapping

from agent_swarm import AgentsError, Caller, Run

from graphtraj.runtimes.runtime_adapter import (
    RuntimeAdapterError,
    RuntimeTurn,
    runtime_process_owner,
    select_runtime_adapter,
)


# Runtime owners with Task-free host bindings.
SUPPORTED_RUNTIMES = frozenset({"claude", "dsh"})

# Native owners of this process's running executions, by core execution ID.
_TURNS: dict[str, RuntimeTurn] = {}
_TURNS_LOCK = threading.Lock()


def _native_error(error: RuntimeAdapterError) -> AgentsError:
    """Keep the Adapter's own code and message for the caller."""
    return AgentsError(error.code, error.message)


def _git_common_directory(cwd: Path) -> Path:
    """Return the Git common directory of ``cwd``, or ``cwd/.git`` outside Git."""
    try:
        output = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd, capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return cwd / ".git"
    return Path(output)


class AdapterDriver:
    """Native execution through the selected Runtime's existing Adapter.

    Parameters
    ----------
    root
        Trusted Harness Project Root, used for role presets and the Adapter's
        existing project-level resources.
    cwd
        Working directory the host chose for new Agents; retained per Agent
        so continuations keep the native Runtime's location.
    """

    def __init__(self, root: Path, cwd: Path) -> None:
        """Bind the project and the host-chosen working directory."""
        self.root = Path(root)
        self.cwd  = Path(cwd)

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Resolve the Runtime's role preset and freeze its launch settings.

        A preset named after the Runtime wins; otherwise exactly one preset
        must use that Runtime.
        """
        from graphtraj.configuration.project_roles import load_project_roles
        from graphtraj.configuration.role_definitions import resolve_child_role

        if runtime not in SUPPORTED_RUNTIMES:
            raise AgentsError("unsupported-runtime", f"The Task-free driver does not run {runtime!r} yet.")
        presets = load_project_roles(self.root).presets
        matches = sorted(name for name, preset in presets.items() if preset.runtime == runtime)
        name    = runtime if runtime in matches else matches[0] if len(matches) == 1 else None
        if name is None:
            raise AgentsError("invalid-config", f"Configure one role named {runtime!r} or exactly one "
                                                f"role using it; found {matches or 'none'}.")

        try:
            role     = resolve_child_role(name, presets[name], self.root)
            adapter  = select_runtime_adapter(runtime)
            prepared = adapter.preflight_runtime_context(
                harness_root=self.root, git_common_directory=_git_common_directory(self.cwd),
                role=role, worktree=self.cwd, evidence=self.root, requested_skills=(),
            ).finalize()
        except RuntimeAdapterError as error:
            raise _native_error(error) from None
        return {
            "role":            name,
            "cwd":             str(self.cwd),
            "adapter_request": prepared.launch_document()["adapter_request"],
            "evidence":        prepared.evidence_document(),
        }

    def start(self, run: Run) -> None:
        """Start the native owner and return once the Runtime confirms its Session.

        A failure before that confirmation raises the Adapter's error; later
        failures are reported through ``run.events``.
        """
        adapter = select_runtime_adapter(run.runtime)
        ready   = threading.Event()
        failure: list[AgentsError] = []

        def created(session: str, pid: int) -> None:
            """Record the native Session and process before any model work."""
            run.events.session(session)
            run.events.process(runtime_pid=pid)

        try:
            turn = adapter.managed_execution(
                dict(run.settings["adapter_request"]), run.message, run.directory,
                lambda session, pid: ready.set(), dict(run.settings["evidence"]),
                trace_file=run.directory / "trace.jsonl", expected_session=run.session,
                session_created=created,
            )
        except RuntimeAdapterError as error:
            raise _native_error(error) from None
        if run.runtime == 'dsh':
            from graphtraj.runtimes.dsh.driver import bind_agents

            bind_agents(turn, run, self)
        turn.parent_notice = lambda message, details: (run.events.request(details),
                                                       {"delivery": "retained"})[1]
        with _TURNS_LOCK:
            _TURNS[run.execution] = turn

        thread = threading.Thread(target=self._own, args=(turn, run, failure),
                                  name=f"agents-{run.agent}")
        thread.start()
        while not ready.wait(0.05):
            if not thread.is_alive():
                thread.join()
                if failure:
                    raise failure[0]
                break

    @staticmethod
    def _own(turn: RuntimeTurn, run: Run, failure: list[AgentsError]) -> None:
        """Run the native owner to its end and report the native result."""
        def process(pid: int, outcome: dict | None = None) -> None:
            """Keep runtime process creation and exit facts."""
            if outcome is None:
                run.events.process(runtime_pid=pid)
            else:
                run.events.process(runtime_exit=outcome)

        try:
            with runtime_process_owner(process):
                result = turn.run()
            run.events.finished(
                result["outcome"], last_message=result.get("last_agent_message"),
                terminal_confirmed=result.get("terminal_confirmed", True),
            )
        except RuntimeAdapterError as error:
            failure.append(_native_error(error))
            run.events.finished("failed", error={"code": error.code, "message": error.message},
                                terminal_confirmed=error.terminal_confirmed)
        except Exception as error:
            failure.append(AgentsError("RUNTIME_WORKER_FAILED", str(error)))
            run.events.finished("failed", error={"code": "RUNTIME_WORKER_FAILED", "message": str(error)},
                                terminal_confirmed=False)
        finally:
            with _TURNS_LOCK:
                _TURNS.pop(run.execution, None)

    def deliver(self, run: Run, message: str) -> None:
        """Send input into the running native execution."""
        self._operate(run, operation="send", instruction=message)

    def interrupt(self, run: Run) -> bool:
        """Request the native stop; ``run()`` keeps ownership until it ends."""
        return self._turn(run).terminate()

    def requests(self, run: Run) -> list[dict]:
        """Return the native approval or input requests still pending."""
        return self._operate(run, operation="requests")["requests"]

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Submit one explicit native allow/deny reply."""
        return self._operate(run, operation="reply", request_token=request.get("request_token"),
                             response=dict(response))

    @staticmethod
    def _turn(run: Run) -> RuntimeTurn:
        """Return this process's native owner of ``run``."""
        with _TURNS_LOCK:
            turn = _TURNS.get(run.execution)
        if turn is None:
            raise AgentsError("not-owned", "This process does not own the native execution.")
        return turn

    def _operate(self, run: Run, **request: Any) -> dict:
        """Apply one Adapter operation to the exact Session and invocation."""
        turn = self._turn(run)
        try:
            return turn.operate({**request, "session": turn.session, "execution_id": turn.execution_id})
        except RuntimeAdapterError as error:
            raise _native_error(error) from None
