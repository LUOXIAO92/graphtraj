"""The review plugin's core: approval layer 3, shared by every Runtime adapter.

A connection that names a reviewer in ``config.yml`` has its tool calls judged
here before they run. The reviewer is a chat completions endpoint or a local
process, whatever model it runs. :func:`review_call` asks it once and returns
one decision document (``PUBLIC_API.md`` section 6); only ``allow`` lets a call
run, and any problem is a failed review that goes to the direct parent.

The policy is the reviewer's prompt only: agents applies no rule of its own to
what a request contains.
"""

from __future__ import annotations

from functools import cache
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Mapping
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from agent_swarm.approval import parse_decision, review_failed
from agent_swarm.config import is_loopback
from agent_swarm.tool import AgentsError


REVIEW_TIMEOUT_DEFAULT = 20

REVIEW_FILE = "review.jsonl"
REQUEST_VERSION = 1
INSTRUCTION_LIMIT = 20_000
RESPONSE_LIMIT = 1024 * 1024
ERROR_BODY_LIMIT = 16 * 1024
REASON_LIMIT = 2000
DETAIL_LIMIT = 512
# A provider message sharing this many characters with the request echoes it.
ECHO_WINDOW = 16

_FAILED = review_failed("")["reason"]


class _Unavailable(Exception):
    """The reviewer gave no answer; the text is a diagnosis without credentials."""


class _NoRedirect(HTTPRedirectHandler):
    """Keep the key and the request on the configured reviewer."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        """Refuse a redirect instead of forwarding the call to another route."""
        return None


@cache
def review_policy() -> str:
    """Compose the shared policy with this plugin's response transport.

    Source and license: ``review_policy/SOURCE.md``. The template and policy
    are copied unchanged; only the transport section below is written here.
    """
    directory = Path(__file__).with_name("review_policy")
    template = (directory / "policy_template.md").read_text(encoding="utf-8").rstrip()
    policy = (directory / "policy.md").read_text(encoding="utf-8").strip()
    return template.replace("{{ tenant_policy_config }}", policy) + (
        "\n\n# Response transport\n"
        "This call has no attached tools. Assess only the review request you are given: `tool` and "
        "`input` are the exact planned action, `cwd` its working directory, `runtime` the coding "
        "agent, `native` that Runtime's own facts about the action, and `instruction` the task its "
        "direct parent gave; only `instruction` can establish user authorization.\n"
        'Return only one JSON object, exactly {"decision":"allow|deny|escalate","reason":"..."}, '
        "with no other field and no markdown. Encode the policy outcome allow as decision allow and "
        "deny as decision deny. If you are uncertain, or the evidence does not let you decide, the "
        "decision is escalate. `reason` is one short non-empty sentence for the direct parent; do "
        "not repeat credentials in it."
    )


def redact(value: object) -> object:
    """Redact credentials; loaded late so ``import agent_swarm`` starts no Runtime package."""
    from agent_swarm.codex.diagnostics import redact as redact_native

    return redact_native(value)



def build_request(
    runtime: str,
    tool: str,
    input: Any,
    *,
    cwd: str,
    instruction: str,
    native: Mapping[str, Any] | None = None,
) -> dict:
    """Return the review request an adapter sends for one planned tool call."""
    omitted = len(instruction) - INSTRUCTION_LIMIT
    if omitted > 0:
        instruction = f'{instruction[:INSTRUCTION_LIMIT]}\n<truncated omitted_chars="{omitted}" />'
    return {"version": REQUEST_VERSION, "runtime": runtime, "tool": tool, "input": input,
            "cwd": cwd, "instruction": instruction, "native": dict(native) if native is not None else None}


def review_call(reviewer: Mapping[str, Any], request: Mapping[str, Any]) -> dict:
    """Ask the reviewer once and return its decision, or the failed review.

    Blocks at most the reviewer's timeout. Reviewer problems never raise: they
    return :func:`agent_swarm.approval.review_failed`, which escalates to the
    direct parent. There is no retry and no repair of the answer.
    """
    try:
        document = parse_decision(_answer(reviewer, request))
    except _Unavailable as error:
        document = review_failed(str(error))
    return {**document, "reason": _clean(document["reason"], reviewer)[:REASON_LIMIT]}


def check_reviewer(reviewer: Mapping[str, Any]) -> None:
    """Raise ``review-unavailable`` unless the reviewer answers a real review call.

    It takes the same path and request shape as :func:`review_call`, so an
    endpoint that would reject every review fails here, at ``create``, instead
    of holding every later tool call. A well-formed decision of any value
    passes.
    """
    probe = build_request("agents", "agents/connectivity-check", {}, cwd="/", instruction=(
        "Connectivity check only: no tool call is planned and nothing will run. "
        "Answer with one valid decision document."))
    try:
        reason = parse_decision(_answer(reviewer, probe))["reason"]
    except _Unavailable as error:
        reason = _FAILED + str(error)
    if reason.startswith(_FAILED):
        why = _clean(reason.removeprefix(_FAILED), reviewer)[:REASON_LIMIT]
        raise AgentsError("review-unavailable", f"Reviewer {reviewer.get('name')!r} is unavailable: {why}")


def record_decision(
    directory: Path,
    runtime: str,
    tool: str,
    request_id: str | None,
    decision: Mapping[str, Any],
) -> None:
    """Append one decision to ``<directory>/review.jsonl``, without the tool input."""
    line = {"at": time.time(), "runtime": runtime, "tool": tool, "request_id": request_id,
            "decision": decision["decision"], "reason": redact(decision["reason"])}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / REVIEW_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")


def _answer(reviewer: Mapping[str, Any], request: Mapping[str, Any]) -> bytes | str:
    """Return the reviewer's raw answer; every problem raises :class:`_Unavailable`."""
    transport = _ask_process if "command" in reviewer else _ask_http
    try:
        return transport(reviewer, request)
    except _Unavailable:
        raise
    except Exception as error:
        # An unexpected error's text may hold request content; its type does not.
        raise _Unavailable(type(error).__name__) from None


def _timeout(reviewer: Mapping[str, Any]) -> int | float:
    """Return the reviewer's own bound on one call."""
    return reviewer.get("timeout_seconds", REVIEW_TIMEOUT_DEFAULT)


def _ask_http(reviewer: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    """POST once to the chat completions endpoint and return the message content."""
    timeout, key = _timeout(reviewer), None
    headers = {"Content-Type": "application/json"}
    variable = reviewer.get("api_key_env")
    if variable is not None:
        key = os.environ.get(variable)
        if not key:
            raise _Unavailable(f"the key variable {variable} is unset or empty")
        headers["Authorization"] = "Bearer " + key
    body = {"model": reviewer["model"], "stream": False, "messages": [
        {"role": "system", "content": review_policy()},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ]}
    # Local servers such as LM Studio reject response_format.
    if reviewer.get("json_mode") is True:
        body["response_format"] = {"type": "json_object"}
    url = reviewer["base_url"].rstrip("/") + "/chat/completions"
    # A proxy must not see a key sent in the clear to this machine.
    handlers = [_NoRedirect()] + ([ProxyHandler({})] if is_loopback(urlsplit(url).hostname) else [])
    opener = build_opener(*handlers)
    post = Request(url, data=json.dumps(body).encode(), headers=headers)

    def exchange() -> bytes:
        """Perform the one exchange, reading a bounded body."""
        try:
            with opener.open(post, timeout=timeout) as response:
                return response.read(RESPONSE_LIMIT + 1)
        except HTTPError as error:
            with error:
                raw = error.read(ERROR_BODY_LIMIT + 1)
            raise _Unavailable(f"HTTP {error.code}" + _error_detail(raw, reviewer, request)) from None
        except URLError as error:
            raise _Unavailable(f"cannot reach the reviewer: {error.reason}") from None
        except TimeoutError:
            raise _Unavailable(f"no answer within {timeout} seconds") from None

    raw = _within(timeout, exchange)
    if len(raw) > RESPONSE_LIMIT:
        raise _Unavailable("the response is larger than 1 MiB")
    try:
        document = json.loads(raw)
        choice = document["choices"][0]
        finish, content = choice["finish_reason"], choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise _Unavailable("the response is not a chat completion"
                           + _error_detail(raw, reviewer, request)) from None
    if finish != "stop":
        raise _Unavailable(f"finish_reason is {str(finish)[:DETAIL_LIMIT]}, not stop")
    if not isinstance(content, str):
        raise _Unavailable("the message content is not text")
    return content


def _within(timeout: int | float, call: Callable[[], bytes]) -> bytes:
    """Return ``call()``, giving up at ``timeout``.

    A socket timeout bounds neither name resolution nor a slow body, so the
    exchange runs on a daemon thread; an abandoned one's answer is dropped.
    """
    outcome: list[tuple[bytes | None, Exception | None]] = []

    def run() -> None:
        """Keep the one result or error for the waiting caller."""
        try:
            outcome.append((call(), None))
        except Exception as error:
            outcome.append((None, error))

    thread = threading.Thread(target=run, name="agents-review", daemon=True)
    thread.start()
    thread.join(timeout)
    if not outcome:
        raise _Unavailable(f"no answer within {timeout} seconds")
    result, error = outcome[0]
    if error is not None:
        raise error
    return result


def _ask_process(reviewer: Mapping[str, Any], request: Mapping[str, Any]) -> bytes:
    """Run the local reviewer once: ``{policy, request}`` on stdin, the decision on stdout."""
    timeout = _timeout(reviewer)
    document = json.dumps({"policy": review_policy(), "request": request}, ensure_ascii=False).encode()
    # A reviewer judges calls; it holds no way to control Agents.
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("AGENT_SWARM_CONNECTION", "GRAPHTRAJ_CLI_CONNECTION")}
    try:
        process = subprocess.Popen(reviewer["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, start_new_session=True)
    except OSError as error:
        raise _Unavailable(f"cannot start {reviewer['command'][0]}: "
                           f"{error.strerror or type(error).__name__}") from None
    try:
        answer, errors = process.communicate(document, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(process)
        raise _Unavailable(f"no answer within {timeout} seconds; the process was killed") from None
    if process.returncode != 0:
        text = _plain(errors.decode("utf-8", "replace")[-DETAIL_LIMIT:], reviewer)
        raise _Unavailable(f"the process exited with status {process.returncode}"
                           + (f": {text}" if text and not _echoes(text, request) else ""))
    return answer


def _kill(process: subprocess.Popen) -> None:
    """Kill the reviewer's whole session; a child that escaped it is abandoned."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _error_detail(raw: bytes, reviewer: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    """Return the provider's own code, type and message, cleaned and bounded.

    An echo of the request is omitted, never copied. A body that is not JSON
    is treated as the message, so a plain ``400`` text stays diagnosable.
    """
    if len(raw) > ERROR_BODY_LIMIT:
        return "; error details omitted"
    text = raw.decode("utf-8", "replace")
    try:
        document = json.loads(text)
    except ValueError:
        document = {"message": text}
    source = document.get("error", document) if isinstance(document, dict) else {}
    source = source if isinstance(source, dict) else {"message": source}
    details = {}
    for field in ("code", "type", "message", "detail"):
        value = source.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if isinstance(value, str):
            value = _plain(value, reviewer)[:DETAIL_LIMIT]
            if value and not _echoes(value, request):
                details[field] = value
    return "; error=" + json.dumps(details, ensure_ascii=False) if details else "; error details omitted"


def _plain(text: str, reviewer: Mapping[str, Any]) -> str:
    """Return ``text`` on one line, without control characters or credentials."""
    text = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return " ".join(_clean(text, reviewer).split())


def _clean(text: str, reviewer: Mapping[str, Any]) -> str:
    """Remove the reviewer's key and any recognizable credential from ``text``."""
    key = os.environ.get(reviewer.get("api_key_env") or "")
    return redact(text.replace(key, "[redacted]") if key else text)


def _echoes(text: str, request: Mapping[str, Any]) -> bool:
    """Whether ``text`` repeats a value or a long fragment of the request."""
    values, pending = set(), [request]
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        elif isinstance(item, str):
            values.add(" ".join(item.split()).casefold())
    folded, known = " ".join(text.split()).casefold(), "\n".join(values)
    return folded in values or any(folded[index:index + ECHO_WINDOW] in known
                                   for index in range(len(folded) - ECHO_WINDOW + 1))
