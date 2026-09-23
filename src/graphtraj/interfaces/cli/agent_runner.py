"""The Agent Runner command surface."""

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NoReturn

import click
import yaml

from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_cleanup import cleanup_ticket
from graphtraj.execution.runner_control import (
    interrupt_session,
    pending_requests,
    reply_to_request,
    send_instruction,
)
from graphtraj.execution.runner_launch import launch_swarm_file
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import status_aliases, status_tree


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

        recovery = CodexMainRecovery.from_environment(Path.cwd().resolve())
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


@click.group(invoke_without_command=True)
@click.option(
    "--swarm-input",
    metavar="YAML_FILE",
    type=click.Path(path_type=Path),
    help="Activate the roles selected by Main or a Team Leader.",
)
@click.pass_context
def main(context: click.Context, swarm_input: Path | None) -> None:
    """Launch formal GraphTraj roles and control their Sessions; no compatibility commands."""
    context.with_resource(_budget_notices())
    if context.invoked_subcommand is None:
        if swarm_input is None:
            error = RunnerError(
                "BATCH_INPUT_REQUIRED", "Launch requires --swarm-input YAML_FILE."
            )
            _fail(error)
        try:
            cwd = Path.cwd().resolve()
            response = launch_swarm_file(swarm_input, cwd)
        except RunnerError as error:
            _fail(error)
        _emit_result(response.document)
        if not response.succeeded:
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


@main.command()
@click.argument("aliases", nargs=-1, required=False)
@click.option(
    "--operation-total",
    is_flag=True,
    help="Report native tool requests once by native identifier.",
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
        if aliases:
            response = status_aliases(
                aliases,
                Path.cwd().resolve(),
                operation_total=operation_total,
                baseline=baseline,
                candidate=candidate,
            )
        else:
            response = status_tree(
                Path.cwd().resolve(),
                operation_total=operation_total,
                baseline=baseline,
                candidate=candidate,
            )
    except RunnerError as error:
        _fail(error)
    _emit_result(response.document)
    if not response.succeeded:
        for error in response.errors:
            click.echo(error.message, err=True)
        raise click.exceptions.Exit(1)


@main.command()
@click.argument("alias")
@click.option("--execution-id", help="Reject a mapping that has moved to another execution.")
def requests(alias: str, execution_id: str | None) -> None:
    """Query pending native requests without consuming them."""
    try:
        response = pending_requests(alias, Path.cwd().resolve(), execution_id=execution_id)
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command()
@click.argument("alias")
@click.option("--request-file", required=True, type=click.Path(path_type=Path),
              help="YAML/JSON file containing one request returned by requests.")
@click.option("--response", required=True, help="Explicit native response as a JSON object.")
def reply(alias: str, request_file: Path, response: str) -> None:
    """Return an explicit reply to the original native request."""
    try:
        request = yaml.safe_load(request_file.read_text(encoding="utf-8"))
        native_response = json.loads(response)
    except (OSError, ValueError, yaml.YAMLError) as error:
        _fail(RunnerError("invalid-input", str(error)), alias=alias)
    try:
        result = reply_to_request(alias, request, native_response, Path.cwd().resolve())
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(result)


@main.command()
@click.argument("alias")
@click.option("--instruction", required=True)
@click.option(
    "--caused-by-event-id",
    multiple=True,
)
@click.option(
    "--reports-only",
    is_flag=True,
    help="Collect existing reports without sampling the Ticket budget.",
)
def send(
    alias: str,
    instruction: str,
    caused_by_event_id: tuple[str, ...],
    reports_only: bool,
) -> None:
    """Resume one Session using causal Project Worldline event IDs."""
    try:
        response = send_instruction(
            alias, instruction, Path.cwd().resolve(), caused_by_event_id,
            reports_only=reports_only,
        )
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command()
@click.argument("alias")
def interrupt(alias: str) -> None:
    """Stop a descendant subtree and prevent further work, retaining Sessions."""
    try:
        response = interrupt_session(alias, Path.cwd().resolve())
    except RunnerError as error:
        _fail(error, alias=alias)
    _emit_result(response)


@main.command()
@click.argument("alias")
@click.option("--actor", type=click.Choice(["main", "user"]), required=True)
@click.option("--caused-by-event-id", multiple=True, required=True)
def replace(alias: str, actor: str, caused_by_event_id: tuple[str, ...]) -> None:
    """Replace a seat; replacing the Leader retires the whole Team."""
    from graphtraj.teams.coding.team_replacement import replace_session

    try:
        response = replace_session(alias, actor, caused_by_event_id, Path.cwd().resolve())
    except (RunnerError, OSError, ValueError, yaml.YAMLError) as error:
        if not isinstance(error, RunnerError):
            error = RunnerError("operation-failed", str(error))
        _fail(error, alias=alias)
    _emit_result(response)


@main.command("continue")
@click.option("--ticket-id", required=True)
@click.option("--caused-by-event-id", multiple=True, required=True)
def continue_ticket(ticket_id: str, caused_by_event_id: tuple[str, ...]) -> None:
    """Continue a stopped Team after Main records a causal decision."""
    from graphtraj.teams.coding.team_round import continue_stopped_ticket

    try:
        response = continue_stopped_ticket(
            ticket_id, caused_by_event_id, Path.cwd().resolve()
        )
    except RunnerError as error:
        _fail(error, ticket_id=ticket_id)
    _emit_result(response)


@main.command()
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
        response = cleanup_ticket(Path.cwd().resolve(), ticket_id)
    except RunnerError as error:
        _fail(error)
    _emit_result(response.document)
    if not response.succeeded:
        error = response.document["error"]
        click.echo(error["message"], err=True)
        raise click.exceptions.Exit(1)
