"""Parent consumption, explicit native replies and original Driver aggregation.

Controlled app-server peers replace model work only. Real installed Runner,
Adapter, process ownership and native request/reply transports remain in use.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_managed_sessions import managed_project
from test_session_alias_control import _register_ready_ticket


# The Leader's model work, executed as the scenario of its app-server peer.
LEADER_SCENARIO = '''
import json, os, subprocess, sys, time
from pathlib import Path

import yaml


def retain(record):
    """Keep one scenario step in the parent-side evidence log."""
    with Path(os.environ['PAIR_LOG']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record) + '\\n')


def call(*arguments):
    """Call one public Runner entry from this Session's own process tree."""
    completed = subprocess.run(
        [os.environ['GRAPHTRAJ_AGENT_RUNNER'], *arguments],
        cwd=os.environ['GRAPHTRAJ_HARNESS_ROOT'],
        capture_output=True, text=True,
    )
    retain({'call': list(arguments[:2]), 'returncode': completed.returncode,
            'document': completed.stdout})
    return completed


def notice_received():
    """Return whether this parent's peer already received the notice input."""
    protocol = Path(os.environ['PEER_PROTOCOL_LOG'])
    if not protocol.is_file():
        return False
    return any(
        json.loads(line).get('method') == 'turn/steer'
        for line in protocol.read_text(encoding='utf-8').splitlines()
    )


def consume(text: str) -> str:
    """Consume the received system message before deciding the native request."""
    notice = json.loads(text)
    assert set(notice) == {'source', 'alias', 'event', 'message'}
    assert all(isinstance(value, str) and value for value in notice.values())
    assert notice['source'] == 'graphtraj'
    assert notice['event'] == 'item/commandExecution/requestApproval'
    details = json.loads(notice['message'].split('\\n')[-1])
    assert details['params']['command'] == 'printf APPROVAL_121'
    retain({'consumed': notice})
    return notice['alias']


seen_budgets = set()


def consume_budgets() -> None:
    """Act on budget messages in the actual parent's running native scenario."""
    path = Path(os.environ['PEER_PROTOCOL_LOG'])
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        record = json.loads(line)
        text = record['params']['input'][0]['text']
        if not text.startswith('{'):
            continue
        notice = json.loads(text)
        if notice['event'] != 'execution-budget-exceeded' or text in seen_budgets:
            continue
        assert set(notice) == {'source', 'alias', 'event', 'message'}
        assert notice['source'] == 'graphtraj'
        seen_budgets.add(text)
        retain({'budget_action': notice})


prompt = sys.stdin.read()
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
elif prompt.startswith('{') and json.loads(prompt)['event'] in {'completed', 'runtime-error', 'interrupted'}:
    retain({'terminal_notice': json.loads(prompt)})
elif prompt.startswith('{'):
    child = consume(prompt)
    while not Path(os.environ['PAIR_RELEASE']).exists():
        consume_budgets()
        time.sleep(0.05)
    queried = call('requests', child)
    request = yaml.safe_load(queried.stdout)['requests'][0]
    Path(os.environ['PAIR_REQUEST_FILE']).write_text(json.dumps(request))
    call('reply', child, '--request-file', os.environ['PAIR_REQUEST_FILE'],
         '--response', '{"decision":"accept"}')
    # Stay active until aggregation arrives, exercising send rather than a
    # competing continuation when the original Driver collects child results.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        records = [json.loads(line) for line in Path(os.environ['PEER_PROTOCOL_LOG']).read_text().splitlines()]
        if any('Direct child execution results:' in r['params']['input'][0]['text'] for r in records):
            retain({'aggregated': True})
            break
        time.sleep(0.05)
    else:
        raise SystemExit('Original Driver did not return child results')
elif 'Direct child execution results:' in prompt:
    retain({'aggregated': True})
elif 'Run the pair probe' in prompt:
    child = os.environ['PAIR_CHILD']
    # Steer the running child while this parent keeps its own execution live.
    call('send', child, '--instruction', 'withdraw and reissue',
         '--caused-by-event-id', os.environ['PAIR_CAUSE'])
    deadline = time.monotonic() + 60
    waiting = received = False
    while time.monotonic() < deadline and not (waiting and received):
        if not waiting:
            status = call('status', child)
            if status.returncode == 0:
                waiting = yaml.safe_load(status.stdout)['aliases'][0].get(
                    'waiting_for') == 'runtime-request'
        received = received or notice_received()
        time.sleep(0.05)
    if not waiting or not received:
        raise SystemExit('The child never waited for its request in this parent.')
    records = [json.loads(line) for line in Path(os.environ['PEER_PROTOCOL_LOG']).read_text().splitlines()]
    consume(next(r['params']['input'][0]['text'] for r in records if r.get('method') == 'turn/steer' and r['params']['input'][0]['text'].startswith('{')))
    # The request stays unanswered until this parent's own reply entry runs.
    while not Path(os.environ['PAIR_RELEASE']).exists():
        consume_budgets()
        if time.monotonic() >= deadline:
            raise SystemExit('The pair probe was never released.')
        time.sleep(0.05)
    queried = call('requests', child)
    request = yaml.safe_load(queried.stdout)['requests'][0]
    Path(os.environ['PAIR_REQUEST_FILE']).write_text(
        json.dumps(request), encoding='utf-8')
    call('reply', child, '--request-file', os.environ['PAIR_REQUEST_FILE'],
         '--response', '{"decision":"accept"}')
else:
    call('--swarm-input', os.environ['PAIR_CHILD_BATCH'])
'''


def _controlled_peers(fake_codex: FakeCodex) -> None:
    """Serve the Leader and the Engineer with their own controlled peers.

    The Leader is the only Session that may register a direct child Batch, and
    its control calls must come from its own process tree, so its peer keeps
    the scenario subprocess. The Engineer runs the managed native peer that
    produces the native request. Every other role keeps the Team scenario, so
    the round still runs its remaining phases.
    """
    directory = fake_codex.executable.parent
    (directory / "team_peer.py").write_text(
        fake_codex.executable.read_text(encoding="utf-8"), encoding="utf-8")
    peer = Path(__file__).with_name("runner_codex_peer.py").read_text()
    anchor = "    elif method == 'turn/steer':\n"
    assert peer.count(anchor) == 1
    # The stdio peer already retains received client messages this way.
    (directory / "leader_peer.py").write_text(
        "#!" + sys.executable + "\n"
        "import sys, os\n"
        "if sys.argv[1:2] == ['app-server']:\n"
        "    import runpy\n"
        "    runpy.run_path(" + repr(str(directory / "runner_peer.py")) + ", "
        "init_globals={'scenario': __file__, 'session_name': "
        "os.environ.get('GRAPHTRAJ_PARENT_ALIAS', 'pair')})\n"
        "    raise SystemExit(0)\n" + LEADER_SCENARIO,
        encoding="utf-8",
    )
    (directory / "runner_peer.py").write_text(
        peer.replace(anchor, anchor + (
            "        text = params['input'][0]['text']\n"
            "        event = json.loads(text).get('event') if text.startswith('{') else None\n"
            "        marker = Path(os.environ['PAIR_EXECUTIONS']).with_suffix('.' + str(event).replace('/', '_'))\n"
            "        if event and os.environ.get('PAIR_FAIL_ONCE') and not marker.exists():\n"
            "            marker.touch()\n"
            "            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'temporary notice refusal'}})\n"
            "            continue\n"
            "        path = os.environ.get('PEER_PROTOCOL_LOG')\n"
            "        if path:\n"
            "            with open(path, 'a') as stream:\n"
            "                stream.write(json.dumps(request) + '\\n')\n"
        ), 1).replace(
            "    with output_lock:",
            "    if message.get('method') == 'turn/completed':\n"
            "        with open(os.environ['PAIR_EXECUTIONS'], 'a') as stream:\n"
            "            stream.write(json.dumps({'end': message['params']['turn']['id']}) + '\\n')\n"
            "    with output_lock:",
        ).replace(
            "        worker = threading.Thread(target=finish,",
            "        with open(os.environ['PAIR_EXECUTIONS'], 'a') as stream:\n"
            "            stream.write(json.dumps({'start': turn}) + '\\n')\n"
            "        worker = threading.Thread(target=finish,",
        ),
        encoding="utf-8",
    )
    (directory / "member_peer.py").write_text(
        Path(__file__).with_name("managed_codex_peer.py").read_text(
            encoding="utf-8"), encoding="utf-8")
    fake_codex.executable.write_text(
        "#!" + sys.executable + "\n"
        "import os, runpy, sys\n"
        "from pathlib import Path\n"
        "here = Path(__file__).resolve().parent\n"
        "role = os.environ.get('GRAPHTRAJ_ROLE')\n"
        "if role == 'team-leader':\n"
        "    runpy.run_path(str(here / 'leader_peer.py'))\n"
        "elif role == 'engineer':\n"
        "    runpy.run_path(str(here / 'member_peer.py'), run_name='__main__')\n"
        "else:\n"
        "    runpy.run_path(str(here / 'team_peer.py'))\n",
        encoding="utf-8",
    )
    fake_codex.executable.chmod(0o755)


def _last_worldline_event(root: Path) -> str:
    """Read the latest retained Project Worldline event identifier."""
    events = [
        json.loads(line)
        for shard in sorted((root / ".graphtraj/state/worldline").glob("*.jsonl"))
        for line in shard.read_text(encoding="utf-8").splitlines()
    ]
    return events[-1]["event_id"]


def _mapping_for_role(runner_directory: Path, role: str, timeout: float = 60.0) -> dict:
    """Wait for the Session the Runner recorded for one role."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in sorted((runner_directory / "sessions").glob("*/mapping.yml")):
            mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
            if mapping.get("role") == role and mapping.get("execution_id"):
                return mapping
        time.sleep(0.02)
    raise AssertionError("No {0} Session was launched".format(role))


def _records(path: Path) -> list[dict]:
    """Read the complete records of one evidence log; partial lines are ignored."""
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _await_records(path: Path, predicate, timeout: float = 60.0) -> list[dict]:
    """Wait for one evidence log to satisfy a predicate over its records."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = _records(path)
        if predicate(records):
            return records
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for records in {0}".format(path))


@pytest.mark.parametrize("idle,transient", [(False, False), (False, True), (True, False)])
def test_parent_consumes_notices_and_replies_while_driver_waits(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    idle: bool,
    transient: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running/idle parents consume notices, explicitly reply and retain aggregation."""
    from graphtraj.execution.runner_status import read_alias_mapping

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _controlled_peers(fake_codex)
    from test_task_budget_control import BODY
    _register_ready_ticket(installed_commands, root, body=BODY)
    child_batch = root / "child-batch.yml"
    child_batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "76", "ticket_name": "session-alias-control",
        "role": "coding-team.engineer",
        "instruction": "request:approval" if idle else "hold",
    }]}, sort_keys=False), encoding="utf-8")
    batch = root / "batch.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "76", "ticket_name": "session-alias-control",
        "role": "team-leader",
    }]}, sort_keys=False), encoding="utf-8")
    parent_log = tmp_path / "parent-calls.jsonl"
    protocol_log = tmp_path / "parent-received.jsonl"
    release = tmp_path / "pair-release"
    environment.pop("PYTHONPATH", None)
    environment.update({
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "MANAGED_NATIVE_ROOT": str(tmp_path / "native"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "PAIR_CHILD_BATCH": str(child_batch),
        "PAIR_LOG": str(parent_log),
        "PEER_PROTOCOL_LOG": str(protocol_log),
        "PAIR_FAIL_ONCE": "1" if transient else "",
        "PAIR_EXECUTIONS": str(tmp_path / "executions.jsonl"),
        "PAIR_CAUSE": _last_worldline_event(root),
        "PAIR_RELEASE": str(release),
        "PAIR_REQUEST_FILE": str(tmp_path / "child-request.json"),
    })
    runner_directory = root / ".graphtraj" / "runner"
    round_process = subprocess.Popen(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=root, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        # The Leader registers the child Batch through its own process tree and
        # the round starts that child Session under the recorded parent.
        leader = _mapping_for_role(runner_directory, "team-leader")
        child = _mapping_for_role(runner_directory, "engineer")
        assert child["parent"] == leader["alias"]
        child_alias = child["alias"]
        notices = runner_directory / "sessions" / child_alias / "parent-notices.jsonl"
        if not idle:
            assert not notices.exists()

        sessions_before = sorted(
            path.name for path in (runner_directory / "sessions").iterdir()
        )

        # The parent resumes and keeps running while it steers the child, so the
        # child's request appears while the parent owns a live execution.
        if not idle:
            with (tmp_path / 'send-stderr.log').open('w') as diagnostics:
                probe = subprocess.run(
                    [
                        str(installed_commands.runner), "send", leader["alias"],
                        "--instruction", "Run the pair probe now.",
                        "--caused-by-event-id", _last_worldline_event(root),
                    ],
                    cwd=root,
                    env={
                        **environment,
                        "PEER_PROTOCOL_LOG": str(protocol_log),
                        "PAIR_CHILD": child_alias,
                    },
                    timeout=60, stdout=subprocess.PIPE, stderr=diagnostics, text=True,
                )
            assert probe.returncode == 0, probe.stdout + (tmp_path / 'send-stderr.log').read_text()
            assert yaml.safe_load(probe.stdout)["send_status"] == "sent"

        received = _await_records(
            notices, lambda records: any(
                record["delivery"] == "received" for record in records
            ),
        )
        record, = [item for item in received if item["delivery"] == "received"]
        parent, parent_directory = read_alias_mapping(runner_directory, leader["alias"])
        consumed = _await_records(parent_log, lambda records: any('consumed' in r for r in records))
        notice = next(r['consumed'] for r in consumed if 'consumed' in r)
        assert notice == json.loads(record['notice'])
        assert notice['alias'] == child_alias
        assert parent['session'] == leader['session'] == record['parent_session']
        assert parent['execution_id'] == record['parent_execution_id']
        if idle:
            assert parent['execution_id'] != leader['execution_id']
        else:
            received_by_parent = _await_records(
                protocol_log, lambda records: any(record.get('method') == 'turn/steer' for record in records),
            )
            steer = next(item for item in received_by_parent if item['method'] == 'turn/steer')
            assert steer['params']['threadId'] == parent['session']
            assert steer['params']['expectedTurnId'] == parent['execution_id']
            assert steer['params']['input'][0]['text'] == record['notice']
        assert record["parent"] == leader["alias"]
        assert record["identity"]["method"] == "item/commandExecution/requestApproval"
        assert record["identity"]["session"] == child["session"]
        assert not (parent_directory / "execution.yml").exists()
        assert sorted(
            path.name for path in (runner_directory / "sessions").iterdir()
        ) == sessions_before

        # The parent read the child's state as a normal wait for the native
        # approval, and the request was still answerable through reply.
        def child_waiting(records: list[dict]) -> bool:
            """Return whether the parent already observed the child's native wait."""
            return any(
                item.get("call") == ["status", child_alias]
                and yaml.safe_load(item["document"])["aliases"][0].get("waiting_for")
                == "runtime-request"
                for item in records
            )

        if not idle:
            waiting = _await_records(parent_log, child_waiting)
            observed = [
                item for item in waiting if item.get("call") == ["status", child_alias]
                and yaml.safe_load(item["document"])["aliases"][0].get("waiting_for")
                == "runtime-request"
            ]
            assert yaml.safe_load(observed[-1]["document"])["aliases"][0]["execution_id"] == (
                record["identity"]["execution_id"]
            )
        assert not (runner_directory / "sessions" / child_alias / "execution.yml").exists()

        # Knowing the request is not the authority to answer it. This caller
        # stands outside the child's recorded direct relation, presents that
        # child's exact pending identity, and is refused before the request is
        # compared, so no carried value widens the relation.
        outside_request = tmp_path / "outside-request.yml"
        outside_request.write_text(
            yaml.safe_dump(
                {
                    "session": record["identity"]["session"],
                    "execution_id": record["identity"]["execution_id"],
                    "request_token": record["identity"]["request_token"],
                }
            ),
            encoding="utf-8",
        )
        refused = run_process(
            [
                str(installed_commands.runner), "reply", child_alias,
                "--request-file", str(outside_request),
                "--response", '{"decision":"accept"}',
            ],
            cwd=root, env=environment, timeout=30,
        )
        assert refused.returncode == 1, refused.stdout + refused.stderr
        refusal = yaml.safe_load(refused.stdout)
        assert refusal["alias"] == child_alias, refusal
        assert refusal["error"]["code"] == "authority-denied", refusal

        # The actual child monitor sees a retained threshold, retries a native
        # refusal if configured, and the same parent consumes the budget notice.
        from graphtraj.execution import execution_budget as budgets
        evidence = root / '.graphtraj/state/tickets/76-session-alias-control'
        monitor = budgets.execution_budget_monitor(evidence, '76', 'session-alias-control')
        usage = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        with (parent_directory / 'launch.yml').open('rb') as input_lock:
            fcntl.flock(input_lock, fcntl.LOCK_EX)
            with monkeypatch.context() as patch:
                patch.setattr(budgets.time, 'time', lambda: usage['started_at'] + 600)
                assert not monitor.check('engineer', 'engineer')
            blocked = _await_records(notices, lambda records: any(
                r.get('identity', {}).get('type') == 'execution-budget-exceeded'
                and r['delivery'] == 'not-delivered' for r in records
            ))
            assert any(r.get('error', {}).get('code') == 'operation-failed' for r in blocked)
            assert read_alias_mapping(runner_directory, leader['alias'])[0]['execution_id'] == parent['execution_id']
        budget_actions = _await_records(parent_log, lambda records: any('budget_action' in r for r in records))
        action = next(r['budget_action'] for r in budget_actions if 'budget_action' in r)
        assert action['alias'] == child_alias
        records = _records(notices)
        if transient:
            failures = [r for r in records if r['delivery'] == 'not-delivered']
            assert len(failures) >= 2
            native_failures = [r for r in failures if 'temporary notice refusal' in r['error']['message']]
            assert {json.loads(r['notice'])['event'] for r in native_failures} == {
                'item/commandExecution/requestApproval', 'execution-budget-exceeded',
            }
        release.touch()
        replied = _await_records(
            parent_log, lambda records: any(
                item.get("call") == ["reply", child_alias] for item in records
            ),
        )
        reply, = [item for item in replied if item.get("call") == ["reply", child_alias]]
        assert reply["returncode"] == 0, reply
        assert yaml.safe_load(reply["document"])["reply_status"] == "submitted"
        # The refused caller consumed nothing: the same native request, by the
        # notice's own token, stayed answerable by the recorded direct parent.
        answered_request = json.loads(
            (tmp_path / "child-request.json").read_text(encoding="utf-8")
        )
        assert answered_request["request_token"] == record["identity"]["request_token"]
        wait_for_file(runner_directory / "sessions" / child_alias / "execution.yml")
        native = tmp_path / "native" / ("rollout-" + child["session"] + ".jsonl")
        assert json.loads(native.read_text(encoding="utf-8").splitlines()[-1])[
            "payload"]["last_agent_message"] == "approval:accept"
        _await_records(parent_log, lambda records: any(r.get('aggregated') for r in records))
        wait_for_file(parent_directory / 'execution.yml')
        assert yaml.safe_load((parent_directory / 'execution.yml').read_text())['outcome'] == 'completed'
        active = None
        for execution in _records(tmp_path / 'executions.jsonl'):
            if 'start' in execution:
                assert active is None, 'Concurrent native executions for one parent Session'
                active = execution['start']
            else:
                assert execution['end'] == active
                active = None
        assert active is None
    finally:
        if 'leader' in locals():
            run_process([str(installed_commands.runner), 'interrupt', leader['alias']],
                        cwd=root, env=environment, timeout=30)
        round_process.kill()
        round_process.wait(timeout=30)


def _session_mapping(root: Path, alias: str) -> dict:
    """Read the identity a managed Worker retained in this isolated project."""
    return yaml.safe_load(
        (root / ".graphtraj/runner/sessions" / alias / "mapping.yml").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.skipif(
    os.environ.get('CODEX_MANAGED_REAL') != '1',
    reason='explicit real Codex boundary probe',
)
def test_real_native_parent_receives_the_child_request_notice(
    managed_project, tmp_path: Path,
) -> None:
    """A real parent execution takes the notice into its own native record.

    The parent runs the installed real Codex through the existing configured
    connection, so the notice has to be accepted by that Runtime in the
    execution it already owns. Only the child keeps the controlled peer that
    produces the synthetic approval request, which is the side this ticket does
    not have to prove.
    """
    import shutil
    import tomllib

    from test_managed_sessions import launch_document

    root, _, call, executable = managed_project
    real = shutil.which('codex')
    assert real
    controlled = tmp_path / 'controlled-peer.py'
    peer = Path(__file__).with_name('managed_codex_peer.py').read_text(encoding='utf-8')
    # The controlled producer raises its request once this Session has
    # published its own record, which a real first turn reaches later.
    trigger = "        ask('permissions' if 'request:permissions' in prompt else 'approval')"
    assert peer.count(trigger) == 1
    controlled.write_text(
        peer.replace(trigger, '        time.sleep(3)\n' + trigger, 1),
        encoding='utf-8',
    )
    # The parent alias is its own Session name; the child's alias ends with the
    # generation suffix this probe records, so one executable serves both sides.
    executable.write_text(
        '#!' + sys.executable + '\n'
        'import os, sys\n'
        "alias = os.environ.get('GRAPHTRAJ_PARENT_ALIAS', '')\n"
        "if alias.endswith('@e1'):\n"
        '    os.execv(sys.executable, [sys.executable, '
        + repr(str(controlled)) + ', *sys.argv[1:]])\n'
        'os.execv(' + repr(str(real)) + ', [' + repr(str(real)) + ', *sys.argv[1:]])\n',
        encoding='utf-8',
    )
    executable.chmod(0o755)
    # An isolated native store keeps the operator's connection settings intact.
    native_home = root / 'codex-home'
    native_home.mkdir(exist_ok=True)
    operator = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    for name in ('config.toml', 'auth.json'):
        if (operator / name).is_file():
            shutil.copy2(operator / name, native_home / name)
    config_file = native_home / 'config.toml'
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
    busy = (
        'Run this exact shell command with a long tool wait, and keep waiting '
        'until it ends. Do not run other commands or finish early: '
        + sys.executable + " -c 'import time; from pathlib import Path; "
        "p=Path(\"parent-busy\"); [(p.write_text(str(i)), time.sleep(0.1)) for i in range(150)]'"
    )
    document = launch_document(busy)
    preset = document['tasks'][0]['role']['managed-probe']
    preset['model'] = os.environ.get('CODEX_MANAGED_MODEL', config.get('model', preset['model']))
    parent = call('launch', document, timeout=30)['tasks'][0]['alias']
    parent_before = _session_mapping(root, parent)
    sessions = root / '.graphtraj/runner/sessions'

    # The child asks for a native decision while the parent still owns its turn.
    child = call('child', [parent, 'notice-child@e1', 'request:approval'], timeout=30)['alias']
    assert child.endswith('@e1')
    child_before = _session_mapping(root, child)
    sessions_before = sorted(path.name for path in sessions.iterdir())
    notices = sessions / child / 'parent-notices.jsonl'
    records = _await_records(
        notices,
        lambda items: any(item['delivery'] == 'received' for item in items),
        timeout=90,
    )
    record, = [item for item in records if item['delivery'] == 'received']

    # The real Runtime acknowledged a steer for exactly the execution it owned,
    # and no second execution, Session or copy appeared for either side.
    assert record['parent'] == parent
    assert record['parent_session'] == parent_before['session']
    assert record['parent_execution_id'] == parent_before['execution_id']
    assert record['identity']['session'] == child_before['session']
    assert _session_mapping(root, parent) == parent_before
    assert _session_mapping(root, child) == child_before
    assert not (sessions / child / 'execution.yml').exists()
    assert sorted(path.name for path in sessions.iterdir()) == sessions_before

    # The parent execution's own native record carries the input it received
    # once that real turn consumes it.
    from test_managed_sessions import observe

    observe(call, parent, 'idle', timeout=180)
    trace = Path(parent_before['trace_file'])
    encoded_notice = json.dumps(record['notice'], ensure_ascii=False)[1:-1]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and encoded_notice not in trace.read_text(errors='replace'):
        time.sleep(0.1)
    assert encoded_notice in trace.read_text(errors='replace')

    # The notice answered nothing: the child's request still has no native reply.
    assert not (tmp_path / 'native' / ('rollout-' + child_before['session'] + '.replies.jsonl')).exists()
