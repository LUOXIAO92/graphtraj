"""The Agent Runner command surface."""

import json
import asyncio
import signal
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NoReturn

import click
import yaml

from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.projection import OperationCommand, OperationGroup, invoke_tool


_MAIN_RECOVERY: "CodexMainRecovery | None" = None


@contextmanager
def _budget_notices() -> Iterator[None]:
    """Select CLI stderr only when no inherited caller channel is available.

    A Codex Main caller keeps its own recovery binding selected for the whole
    command, so the document this operation returns can carry an enforced stop
    to the turn that is waiting for it.
    """
    global _MAIN_RECOVERY
    descriptor, owned = caller_notice_fd()
    if descriptor is None:
        from graphtraj.runtimes.codex.app_server import CodexMainRecovery

        recovery = CodexMainRecovery.from_environment()
        if recovery is not None:
            with recovery:
                _MAIN_RECOVERY = recovery
                try:
                    with budget_notice_output(recovery.notice_fd):
                        yield
                finally:
                    _MAIN_RECOVERY = None
            return
        try:
            descriptor, owned = os.dup(sys.stderr.fileno()), True
        except OSError:
            yield
            return
    try:
        with budget_notice_output(descriptor):
            yield
    finally:
        if owned:
            os.close(descriptor)


@click.group(invoke_without_command=True, cls=OperationGroup)
@click.option(
    "--swarm-input",
    metavar="YAML_FILE",
    type=click.Path(path_type=Path),
)
@click.pass_context
def main(context: click.Context, swarm_input: Path | None) -> None:
    """Launch formal GraphTraj roles and control their Sessions; no compatibility commands."""
    if context.invoked_subcommand is None:
        context.with_resource(_budget_notices())
        if swarm_input is None:
            error = RunnerError(
                "BATCH_INPUT_REQUIRED", "Launch requires --swarm-input YAML_FILE."
            )
            _fail(error)
        try:
            cwd = Path.cwd().resolve()
            response = invoke_tool("swarm", {}, cwd=cwd, input_file=swarm_input)
        except RunnerError as error:
            _fail(error)
        _emit_result(response.document)
        if response.failed:
            for task in response.document["tasks"]:
                error = task.get("error")
                if error is not None:
                    click.echo(error["message"], err=True)
            raise click.exceptions.Exit(1)


def _emit_result(document: dict) -> None:
    """Render one Runner result document, including any delivered stop.

    A stop the caller channel delivered during this operation travels with the
    document, so the Main awaiting this call handles it without another input.
    Every other result keeps its existing schema.
    """
    if _MAIN_RECOVERY is not None and isinstance(document, dict):
        document = _MAIN_RECOVERY.attach_stop_deliveries(document)
    click.echo(yaml.safe_dump(document, sort_keys=False), nl=False)


def _fail(error: RunnerError, **identity: str) -> NoReturn:
    """Translate a domain failure into the established Runner CLI response."""
    _emit_result({**identity, "error": error.as_document()})
    click.echo(error.message, err=True)
    raise click.exceptions.Exit(1)


@main.command('main', cls=OperationCommand, feature="main")
@click.option('--instruction-file', type=click.Path(exists=True, path_type=Path))
@click.option('--resume')
def main_session(instruction_file: Path, resume: str | None) -> None:
    """Run an isolated Main turn using the user's native Runtime settings.

    Native user requests are printed unchanged to stderr. Reply on stdin with
    the native JSON-RPC id and result; this entry makes no approval decision.
    """
    from graphtraj.runtimes.codex.main_session import run_main
    from graphtraj.runtimes.codex.app_server import CodexServerRequest
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    async def execute(root: Path, instruction: str, record: str | None) -> dict:
        """Keep native request/response correlation while the turn is active."""
        replies = asyncio.Lock()

        async def native_request(request: CodexServerRequest) -> dict:
            """Forward the existing native request and await its exact response."""
            async with replies:
                click.echo(json.dumps({'id': request.request_id, 'method': request.method,
                                       'params': request.params}), err=True)
                line = await asyncio.to_thread(sys.stdin.readline)
                response = json.loads(line)
                if (
                    not isinstance(response, dict)
                    or response.get('id') != request.request_id
                    or not isinstance(response.get('result'), dict)
                ):
                    raise RunnerError('invalid-input', 'Reply with the native request id and result.')
                return response['result']

        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        previous = signal.getsignal(signal.SIGTERM)
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        try:
            return await run_main(root, instruction, record, native_request)
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            signal.signal(signal.SIGTERM, previous)

    def execute_main(root: Path, instruction: str, record: str | None) -> dict:
        """Bind the shared operation to the CLI native reply and signal transport."""
        return asyncio.run(execute(root, instruction, record))

    try:
        result = invoke_tool("main",
            {"instruction": instruction_file.read_text(), "resume": resume},
            cwd=Path.cwd().resolve(), execute=execute_main,
        )
        _emit_result(result.document)
    except (RunnerError, RuntimeAdapterError) as error:
        _fail(RunnerError(error.code, error.message))
    except (OSError, ValueError) as error:
        _fail(RunnerError('invalid-input', str(error)))


@main.command(cls=OperationCommand, feature="parent_status")
@click.option('--timeout-seconds', default=0.0, type=float)
def parent_status(timeout_seconds: float) -> None:
    """Observe the root caller's owning host without sending it input."""
    try:
        result = invoke_tool('parent_status', {'timeout_seconds': timeout_seconds}, cwd=Path.cwd().resolve())
    except (RunnerError, ValueError) as error:
        _fail(RunnerError(getattr(error, 'code', 'invalid-input'), str(error)))
    _emit_result(result.document)
    if result.failed:
        raise SystemExit(1)


@main.command(cls=OperationCommand, feature="alias_status")
@click.argument("aliases", nargs=-1, required=False)
@click.option(
    "--operation-total",
    is_flag=True
)
@click.option("--baseline")
@click.option("--candidate")
def status(
    aliases: tuple[str, ...],
    operation_total: bool,
    baseline: str | None,
    candidate: str | None,
) -> None:
    """Inspect the supplied Session aliases, or the visible Session tree."""
    try:
        arguments = {"operation_total": operation_total, "baseline": baseline, "candidate": candidate}
        if aliases:
            arguments["aliases"] = list(aliases)
        response = invoke_tool("alias_status", arguments, cwd=Path.cwd().resolve())
    except RunnerError as error:
        _fail(error)
    _emit_result(response.document)
    if response.failed:
        for entry in response.document.get("aliases", response.document.get("agents", [])):
            if "error" in entry:
                click.echo(entry["error"]["message"], err=True)
        raise click.exceptions.Exit(1)


@main.command(cls=OperationCommand, feature="pending_requests")
@click.argument("alias")
@click.option("--execution-id")
def requests(alias: str, execution_id: str | None) -> None:
    """Query pending native requests without consuming them."""
    try:
        response = invoke_tool("pending_requests",
            {"alias": alias, "execution_id": execution_id}, cwd=Path.cwd().resolve(),
        ).document
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command(cls=OperationCommand, feature="reply_to_request")
@click.argument("alias")
@click.option("--request-file", type=click.Path(path_type=Path))
@click.option("--response")
def reply(alias: str, request_file: Path, response: str) -> None:
    """Return an explicit reply to the original native request."""
    try:
        request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
        native_response = json.loads(response)
    except (OSError, ValueError, yaml.YAMLError) as error:
        _fail(RunnerError("invalid-input", str(error)), alias=alias)
    try:
        result = invoke_tool("reply_to_request",
            {"alias": alias, "request": request, "response": native_response},
            cwd=Path.cwd().resolve(),
        ).document
    except (RunnerError, ValueError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError("invalid-input", str(error)),
              alias=alias)
    _emit_result(result)


@main.command(cls=OperationCommand, feature="send_instruction")
@click.argument("alias")
@click.option("--instruction")
@click.option(
    "--caused-by-event-id",
    multiple=True,
)
@click.option(
    "--reports-only",
    is_flag=True
)
def send(
    alias: str,
    instruction: str,
    caused_by_event_id: tuple[str, ...],
    reports_only: bool,
) -> None:
    """Resume one Session using causal Project Worldline event IDs."""
    try:
        response = invoke_tool("send_instruction",
            {"alias": alias, "instruction": instruction,
             "caused_by_event_ids": list(caused_by_event_id), "reports_only": reports_only},
            cwd=Path.cwd().resolve(),
        ).document
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command(cls=OperationCommand, feature="interrupt")
@click.argument("alias")
def interrupt(alias: str) -> None:
    """Stop a descendant subtree and prevent further work, retaining Sessions."""
    try:
        response = invoke_tool("interrupt", {"alias": alias}, cwd=Path.cwd().resolve()).document
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command(cls=OperationCommand, feature="retire")
@click.argument("alias")
def retire(alias: str) -> None:
    """Retire a stopped member while preserving its Session and evidence."""
    try:
        response = invoke_tool("retire", {"alias": alias}, cwd=Path.cwd().resolve())
    except (RunnerError, OSError, ValueError, yaml.YAMLError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError("operation-failed", str(error)), alias=alias)
    _emit_result(response.document)


@main.command(cls=OperationCommand, feature="replace")
@click.argument("alias")
@click.option(
    "--actor",
    type=click.Choice(["main", "user"])
)
@click.option("--caused-by-event-id", multiple=True)
def replace(alias: str, actor: str | None, caused_by_event_id: tuple[str, ...]) -> None:
    """Replace one stopped actual member while preserving its Team and evidence.

    The recorded direct parent or native user approval authorizes replacement.
    The target and all descendants must already be stopped.
    """
    try:
        response = invoke_tool("replace",
            {"alias": alias, "actor": actor, "caused_by_event_ids": list(caused_by_event_id)},
            cwd=Path.cwd().resolve(),
        ).document
    except (RunnerError, OSError, ValueError, yaml.YAMLError) as error:
        if not isinstance(error, RunnerError):
            error = RunnerError("operation-failed", str(error))
        _fail(error, alias=alias)
    _emit_result(response)
    if "error" in response:
        raise click.exceptions.Exit(1)


@main.command("recover", cls=OperationCommand, feature="approved_recovery")
@click.argument("alias")
@click.option("--reason")
@click.option("--instruction")
@click.option("--allowed-scope")
@click.option("--forbidden-scope")
@click.option("--caused-by-event-id", multiple=True)
@click.option("--additional-minutes", type=float)
@click.option("--restore-active", is_flag=True, default=None)
@click.option("--resume/--no-resume", default=None)
@click.option("--retry-event-id")
def recover(
    alias: str,
    reason: str | None,
    instruction: str | None,
    allowed_scope: str | None,
    forbidden_scope: str | None,
    caused_by_event_id: tuple[str, ...],
    additional_minutes: float | None,
    restore_active: bool | None,
    resume: bool | None,
    retry_event_id: str | None,
) -> None:
    """Request concrete native-approved recovery, or retry an applied repair."""
    arguments = {key: value for key, value in {
        'alias': alias, 'reason': reason, 'instruction': instruction,
        'allowed_scope': allowed_scope, 'forbidden_scope': forbidden_scope,
        'additional_minutes': additional_minutes, 'restore_active': restore_active, 'resume': resume,
        'retry_event_id': retry_event_id,
    }.items() if value is not None}
    if caused_by_event_id:
        arguments['caused_by_event_ids'] = list(caused_by_event_id)
    try:
        result = invoke_tool('approved_recovery', arguments, cwd=Path.cwd().resolve())
    except (RunnerError, OSError, ValueError, yaml.YAMLError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError('operation-failed', str(error)))
    _emit_result(result.document)
    if result.failed:
        raise click.exceptions.Exit(1)


class RecoveryApplyCommand(click.Command):
    """Project recovery help without exposing its native executable as a tool."""

    feature = 'approved_recovery'
    get_short_help_str = OperationCommand.get_short_help_str
    format_help_text = OperationCommand.format_help_text


@main.command("recover-apply", cls=RecoveryApplyCommand)
@click.option("--proposal", required=True)
def recover_apply(proposal: str) -> None:
    """Execute the exact recovery proposal through the requested native reviewer."""
    from graphtraj.execution.approved_recovery import apply_approved_recovery

    try:
        value = json.loads(proposal)
        if not isinstance(value, dict) or set(value) != {'request', 'before', 'after', 'authority'}:
            raise ValueError('Expected the exact recovery proposal returned by recover.')
        result = apply_approved_recovery(value, Path.cwd().resolve())
    except (RunnerError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError('invalid-input', str(error)))
    # Native review needs the structured applied/stale/failure result, including
    # a repair that succeeded before continuation failed; do not discard stdout.
    _emit_result(result)


@main.command("continue", cls=OperationCommand, feature="continue")
@click.option("--ticket-id")
@click.option("--caused-by-event-id", multiple=True)
@click.option(
    "--budget-only", is_flag=True
)
def continue_ticket(
    ticket_id: str, caused_by_event_id: tuple[str, ...], budget_only: bool,
) -> None:
    """Restore an authorized task budget and, by default, resume original roots."""
    try:
        response = invoke_tool("continue",
            {"ticket_id": ticket_id, "caused_by_event_ids": list(caused_by_event_id),
             "budget_only": budget_only}, cwd=Path.cwd().resolve(),
        ).document
    except RunnerError as error:
        _fail(error, ticket_id=ticket_id)
    _emit_result(response)


@main.command(cls=OperationCommand, feature="cleanup")
@click.option("--ticket-id")
def cleanup(ticket_id: str | None) -> None:
    """Clean up one safely integrated ticket by stable identity."""
    if ticket_id is None:
        error = RunnerError(
            "invalid-input",
            "Cleanup requires --ticket-id.",
        )
        _fail(error)
    try:
        response = invoke_tool("cleanup", {"ticket_id": ticket_id}, cwd=Path.cwd().resolve())
    except RunnerError as error:
        _fail(error)
    _emit_result(response.document)
    if response.failed:
        error = response.document["error"]
        click.echo(error["message"], err=True)
        raise click.exceptions.Exit(1)


@main.command('reports', cls=OperationCommand, feature="session_reports")
@click.argument('alias')
def reports(alias: str) -> None:
    """Read a directly owned Session's reports and retained result submissions."""
    from graphtraj.workspace.runner_project import discover_project_root

    try:
        _emit_result(invoke_tool("session_reports",
            {"alias": alias}, cwd=discover_project_root(Path.cwd()),
        ).document)
    except (RunnerError, ValueError, OSError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError('RESULT_INVALID', str(error)))


@main.command('submit-result', cls=OperationCommand, feature="submit_result")
@click.option('--commit')
@click.option('--result-ref', 'result_refs', multiple=True)
@click.option('--evidence-ref', 'evidence_refs', multiple=True)
@click.option('--completion')
@click.option('--unresolved', multiple=True)
def submit_result(
    commit: str,
    result_refs: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    completion: str,
    unresolved: tuple[str, ...],
) -> None:
    """Submit the calling Session's committed files and retained evidence."""
    try:
        _emit_result(invoke_tool("submit_result",
            {"commit": commit, "result_refs": list(result_refs), "evidence_refs": list(evidence_refs),
             "completion": completion, "unresolved": list(unresolved)}, cwd=Path.cwd(),
        ).document)
    except (RunnerError, ValueError, OSError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError('RESULT_INVALID', str(error)))


@main.command('decide-result', cls=OperationCommand, feature="decide_result")
@click.option('--submission-id')
@click.option('--commit')
@click.option('--decision')
@click.option('--reason')
@click.option('--evidence-ref', 'evidence_refs', multiple=True)
def decide_result(
    submission_id: str,
    commit: str,
    decision: str,
    reason: str,
    evidence_refs: tuple[str, ...],
) -> None:
    """Accept or reject a submitted version using the caller's actual authority."""
    try:
        _emit_result(invoke_tool("decide_result",
            {"submission_id": submission_id, "commit": commit, "decision": decision,
             "reason": reason, "evidence_refs": list(evidence_refs)}, cwd=Path.cwd(),
        ).document)
    except (RunnerError, ValueError, OSError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError('RESULT_INVALID', str(error)))


@main.command("submit-report", cls=OperationCommand, feature="submit_report")
@click.option("--name")
@click.option("--text")
def submit_report(name: str, text: str) -> None:
    """Submit the calling Session's assigned report through the shared operation."""
    try:
        _emit_result(invoke_tool("submit_report", {"name": name, "text": text}, cwd=Path.cwd()).document)
    except (RunnerError, ValueError, OSError) as error:
        _fail(error if isinstance(error, RunnerError) else RunnerError("RESULT_INVALID", str(error)))
