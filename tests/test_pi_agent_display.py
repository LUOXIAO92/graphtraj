"""The actual Pi extension's display-only callback and native context boundary."""
from pathlib import Path
import shutil
import subprocess
import sys

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


def test_independent_pi_extension_uses_only_builtin_mcp_client(tmp_path: Path) -> None:
    """Independent startup registers progressive MCP without Task entry or native tools."""
    if shutil.which('node') is None:
        pytest.skip('Node is required for the shipped Pi extension.')
    module = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
    module = Path(shutil.copy2(module, tmp_path / module.name))
    script = '''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const {default: extension} = await import(pathToFileURL(process.argv[1]));
const handlers = new Map();
const servers = [];
const pi = {
  registerFlag() {},
  on(name, handler) { handlers.set(name, handler); },
  registerMcpServer(name, configuration) { servers.push({name, configuration}); },
};
process.env.AGENT_SWARM_CONNECTION = '/owned/channel';
process.env.AGENT_SWARM_PYTHON = '/owned/python';
extension(pi);
const ctx = {hasUI:false,cwd:'/owned/work',sessionManager:{}};
await handlers.get('session_start')({reason:'startup'}, ctx);
assert.deepEqual(servers, [{name:'agents',configuration:{command:'/owned/python',
  args:['-I','-m','agent_swarm.mcp'], cwd:'/owned/work',
  env:{AGENT_SWARM_CONNECTION:'/owned/channel'},exposure:'direct'}}]);
const bash = {toolName:'bash',input:{command:'pwd'}};
assert.equal(await handlers.get('tool_call')(bash,ctx),undefined);
assert.equal(bash.input.command,'pwd');
'''
    subprocess.run(['node', '--input-type=module', '-e', script, str(module)],
                   check=True, capture_output=True, text=True)


def test_native_main_extension_registers_independent_host(tmp_path: Path) -> None:
    """Explicit host settings use native facts and preserve built-in tool behavior."""
    if shutil.which('node') is None:
        pytest.skip('Node is required for the shipped Pi extension.')
    source = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
    module = Path(shutil.copy2(source, tmp_path / source.name))
    peer = tmp_path / 'controlled-host'
    peer.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
assert os.environ['GRAPHTRAJ_NATIVE_SESSION'] == 'native-main'
assert os.environ['AGENT_SWARM_PI_MODEL'] == 'deepseek-flash'
assert sys.argv[1:] == ['-I', '-m', 'graphtraj.runtimes.pi.host', '--config', '/explicit/config.json']
print(json.dumps({'connection':'/controlled/native-main'}), flush=True)
sys.stdin.read()
''')
    peer.chmod(0o755)
    script = '''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const {default: extension} = await import(pathToFileURL(process.argv[1]));
const handlers = new Map(), servers = [];
delete process.env.AGENT_SWARM_CONNECTION;
process.env.AGENT_SWARM_PYTHON = process.argv[2];
const pi = {registerFlag(){},getFlag(name){return name==='agents-config'?'/explicit/config.json':false;},
 on(name,handler){handlers.set(name,handler);},registerMcpServer(name,config){servers.push({name,config});}};
extension(pi);
const ctx = {hasUI:false,cwd:process.argv[3],model:{id:'deepseek-flash',provider:'deepseek'},
 sessionManager:{getSessionId:()=> 'native-main',getSessionFile:()=> '/selected/session.jsonl',
 getHeader:()=>({id:'native-main'}),getEntries:()=>[]}};
await handlers.get('session_start')({reason:'startup'},ctx);
assert.equal(servers.length,1);
assert.equal(servers[0].name,'agents');
assert.deepEqual(servers[0].config.args,['-I','-m','agent_swarm.mcp']);
assert.equal(servers[0].config.command,process.argv[2]);
assert.equal(servers[0].config.env.AGENT_SWARM_CONNECTION,'/controlled/native-main');
const bash = {toolName:'bash',input:{command:'pwd'}};
assert.equal(await handlers.get('tool_call')(bash,ctx),undefined);
assert.equal(bash.input.command,'pwd');
ctx.sessionManager.getEntries = ()=>[];
ctx.sessionManager.getLeafId = ()=>null;
await handlers.get('session_shutdown')({},ctx);
'''
    subprocess.run(['node', '--input-type=module', '-e', script, str(module), str(peer), str(tmp_path)],
                   check=True, capture_output=True, text=True, timeout=10)
