"""The actual Pi extension's display-only callback and native context boundary."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_pi_display_preserves_tool_result_and_deduplicates_after_reload(tmp_path: Path) -> None:
    """Full bodies use native custom entries; a repeated reply is shown once."""
    if shutil.which('node') is None:
        pytest.skip('Node is required for the shipped Pi extension.')
    module = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
    module = Path(shutil.copy2(module, tmp_path / module.name))
    script = '''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { registerAgentDisplay } = await import(pathToFileURL(process.argv[1]));
const entries = [];
let handler, renderer;
const pi = {
  registerEntryRenderer(type, callback) { renderer = callback; },
  on(type, callback) { assert.equal(type, 'tool_result'); handler = callback; },
  appendEntry(customType, data) { entries.push({type: 'custom', customType, data}); },
};
const sdk = { CustomMessageComponent: class { constructor(message) { this.message = message; } } };
const ctx = {hasUI: true, sessionManager: {
  getSessionId: () => 'native-parent', getEntries: () => entries,
}};
const input = {action: 'create', instruction: 'full outbound\\nsecond line'};
const result = {agent: 'agent-child', session: 'native-child', execution: 'exec', result: {
  parent: 'agent-parent', name: 'Pi child', last_result: {id: 'exec', last_message: 'full reply\\nnext line'},
}};
const event = {details: {server: 'graphtraj', tool: 'agents'}, input: {action: 'execute', feature: input.action, arguments: {instruction: input.instruction}},
  toolCallId: 'call', structuredContent: {structuredContent: result},
};
const original = JSON.stringify(event);
registerAgentDisplay(pi, sdk);
assert.equal(handler(event, ctx), undefined);
assert.equal(entries.length, 2);
assert.equal(entries[0].data.body, input.instruction);
assert.equal(entries[1].data.body, result.result.last_result.last_message);
assert.equal(renderer(entries[1]).message.content, 'full reply\\nnext line');
assert.equal(JSON.stringify(event), original);
registerAgentDisplay(pi, sdk);
handler(event, ctx);
assert.equal(entries.length, 2);
handler({...event, toolCallId: 'second-call', input: {action: 'execute', feature: 'wait', arguments: {}}}, ctx);
assert.equal(entries.length, 2);
handler({...event, isError: true}, ctx);
assert.equal(entries.length, 2);
handler({...event, toolCallId: 'not-delivered', input: {action: 'execute', feature: 'resume', arguments: {message: 'not sent'}},
  structuredContent: {structuredContent: {...result, result: {...result.result, resumed: false}}}}, ctx);
assert.equal(entries.length, 2);
assert.equal(renderer(entries[0]).message.customType, 'agents · agent-parent → Pi child');
'''
    subprocess.run(['node', '--input-type=module', '-e', script, str(module)],
                   check=True, capture_output=True, text=True)
