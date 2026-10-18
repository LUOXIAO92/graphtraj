"""Opt-in real Claude control evidence, retained outside pytest temp rotation.

This checks the managed SDK/MCP path. It does not establish interactive Main
plugin trust, current-context binding, or native screen/keyboard acceptance.
Run only in the separately assigned real Runtime slot.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from agent_swarm import AgentControl, Caller, bind, write_config
from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.agent_driver import AdapterDriver
from graphtraj.interfaces.agents import configured_archive
from graphtraj.runtimes.claude.history import conversation, message_id
from graphtraj.sessions.archive import JsonlSessionStore, archive_path


@pytest.mark.skipif(not os.environ.get('CLAUDE_REAL_LIFECYCLE'), reason='Requires the assigned real Runtime slot')
def test_real_progressive_mcp_memory_stop_and_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use one related Session for progressive tools, active stop, recall and projection."""
    destination = Path(os.environ['CLAUDE_REAL_EVIDENCE_DIR'])
    assert destination.is_absolute() and not destination.exists(), 'Use a NEW fixed evidence directory.'
    binary = Path(os.environ['CLAUDE_REAL_TEST_BINARY'])
    sdk = Path(os.environ['CLAUDE_SDK_MODULE'])
    assert binary.is_file() and sdk.is_file()
    destination.mkdir(parents=True)
    project = destination / 'project'
    (project / '.graphtraj').mkdir(parents=True)
    (project / '.graphtraj/config.yml').write_text(default_configuration_content(project, project))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'claude': {'runtime': 'claude', 'model': 'claude-opus-5-5',
                            'reasoning_effort': 'high', 'claude': {'permission_mode': 'auto'}}},
        'role_tree': {'claude': {}},
    }))
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    # Preserve explicit SCRUB; this probe does not override a user's choice.
    root = project / '.graphtraj/swarm'
    write_config(root, save_normalized_sessions=True, backfill_history=True)
    archive = configured_archive(project)
    call = bind(AgentControl(root, {'claude': AdapterDriver(project, project)}),
                Caller('task332-managed-validation', None, 'task332-lifecycle'), archive=archive)
    facts: list[dict] = []
    agent = None
    session = None

    def operate(request: dict) -> dict:
        """Persist public results before assertions, including failed operations."""
        answer = call(request)
        facts.append({'request': request, 'document': answer.document, 'failed': answer.failed})
        (destination / 'operations.json').write_text(json.dumps(facts, indent=2))
        assert not answer.failed, answer.document
        return answer.document

    try:
        created = operate({'action': 'create', 'runtime': 'claude', 'instruction':
            'Remember TASK332-MEMORY-ORCHID for later. Use mcp__agents__agents three times: '
            'first action discover query status; then action describe feature status schema true; '
            'finally action execute feature status arguments {}. Do not use shell or other tools. '
            'After the status result, reply READY.'})
        agent, session = created['agent'], created['session']
        ready = operate({'action': 'wait', 'agent': agent, 'timeout_seconds': 60})
        assert ready['result']['state'] == 'standby', ready
        assert ready['result']['last_result']['outcome'] == 'completed', ready
        store = JsonlSessionStore(archive_path(root, 'claude:' + session))
        transcript = Path(store.header['graphtraj']['native']['locator'])
        (destination / 'native-locator.json').write_text(json.dumps({
            'session': session, 'agent': agent, 'transcript': str(transcript),
            'project': str(project), 'requested_model': 'claude-opus-5-5', 'requested_effort': 'high',
        }, indent=2))
        entries = [json.loads(line) for line in transcript.read_text().splitlines()]
        blocks = [block for entry in entries for block in entry.get('message', {}).get('content', [])
                  if isinstance(block, dict)]
        tools = [b for b in blocks if b.get('type') == 'tool_use' and b.get('name') == 'mcp__agents__agents']
        assert {b['input']['action'] for b in tools} >= {'discover', 'describe', 'execute'}, tools
        for tool in tools:
            result = next(b for b in blocks if b.get('type') == 'tool_result' and b.get('tool_use_id') == tool['id'])
            assert result.get('is_error') is not True, result
            contents = result['content']
            text = contents if isinstance(contents, str) else '\n'.join(
                b['text'] for b in contents if b.get('type') == 'text')
            decoded = json.loads(text)
            assert not decoded.get('error'), decoded
            if tool['input']['action'] == 'execute':
                assert decoded['result']['agents'] == [], decoded

        before = archive_path(root, 'claude:' + session).read_bytes()
        write_config(root, save_normalized_sessions=False, backfill_history=False)
        sent = operate({'action': 'send', 'agent': agent, 'message':
                        'Run Bash sleep 20 once, then say FINISHED. Do nothing else.'})
        assert sent['session'] == session, sent
        active = operate({'action': 'status', 'agent': agent})
        assert active['result']['state'] == 'active', 'Completed before interrupt: no active-stop evidence.'
        operate({'action': 'interrupt', 'agent': agent})
        stopped = operate({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
        assert stopped['result']['state'] == 'standby', stopped
        assert archive_path(root, 'claude:' + session).read_bytes() == before

        write_config(root, save_normalized_sessions=True, backfill_history=True)
        resumed = operate({'action': 'resume', 'agent': agent, 'message':
                           'What exact marker did I ask you to remember earlier? Reply only the marker, without tools.'})
        assert resumed['session'] == session, resumed
        done = operate({'action': 'wait', 'agent': agent, 'timeout_seconds': 60})
        assert done['result']['state'] == 'standby', done
        assert 'TASK332-MEMORY-ORCHID' in done['result']['last_result']['last_message'], done
        # Read only the exact locator already attested by this owned Session.
        raw = transcript.read_bytes()
        (destination / 'related-native.jsonl').write_bytes(raw)
        entries = [json.loads(line) for line in raw.splitlines()]
        program = """
            import {readFileSync} from 'node:fs';
            const {getSessionMessages} = await import(process.argv[1]);
            const entries = JSON.parse(readFileSync(0, 'utf8'));
            const result = await getSessionMessages(process.argv[2], {
                dir: process.argv[3], sessionStore: {load: async () => entries, append: async () => {}}});
            process.stdout.write(JSON.stringify(result));
        """
        projected = subprocess.run(['node', '--input-type=module', '-e', program, sdk.as_uri(), session, str(project)],
                                   input=json.dumps(entries), capture_output=True, text=True, timeout=20, check=True)
        native = json.loads(projected.stdout)
        (destination / 'official-messages.json').write_text(projected.stdout)
        actual = conversation(entries)
        assert [(message_id(r), r['message']) for r in actual] == [(r['uuid'], r['message']) for r in native]
        store = JsonlSessionStore(archive_path(root, 'claude:' + session))
        assert [m['id'] for m in store.messages()] == [r['uuid'] for r in native]
        (destination / 'projection.json').write_text(json.dumps({
            'native_sha256': hashlib.sha256(raw).hexdigest(), 'native_messages': len(native),
            'normalized_messages': len(store.messages()),
            'pending_count': len(store.pending()),
            'scope': 'Managed single Session; no real fork/compaction or interactive UI acceptance.',
        }, indent=2))
    finally:
        if agent is not None:
            status = operate({'action': 'status', 'agent': agent})
            if status['result']['state'] == 'active':
                operate({'action': 'interrupt', 'agent': agent})
                stopped = operate({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
                assert stopped['result']['state'] == 'standby', stopped
        # Evidence is intentionally retained, with no pytest tmp_path/retire/cleanup.
