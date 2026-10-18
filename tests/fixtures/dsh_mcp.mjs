/** Installed official MCP client, real stdio; controlled backend, no model/UI. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [nativePackage, python, server, pythonPath] = process.argv.slice(2);
const require = createRequire(nativePackage);
const { Context } = await import(pathToFileURL(require.resolve('@deepseek-ai/cordis')));
const client = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-mcp-client')));
const ctx = new Context();
const definitions = new Map();
ctx.provide('tools', { register(definition) {
  assert.equal(definitions.has(definition.name), false);
  definitions.set(definition.name, definition);
  return () => definitions.delete(definition.name);
} });
try {
  await ctx.plugin(client, {
    transport: 'stdio', serverName: 'agents', command: python, args: [server],
    cwd: process.cwd(), env: { PYTHONPATH: pythonPath },
    failOnStartupError: true, toolCallTimeoutMs: 10000,
  }).await();
  assert.deepEqual([...definitions.keys()], ['mcp__agents__agents']);
  const tool = definitions.get('mcp__agents__agents');
  assert.deepEqual(Object.keys(tool.parameters.properties), ['action', 'query', 'feature', 'arguments']);
  const invoke = args => tool.execute(args, { signal: new AbortController().signal });
  const discovered = (await invoke({ action: 'discover', query: 'status' })).structuredContent;
  assert.deepEqual(discovered.features.map(item => item.name), ['status']);
  assert.equal(discovered.features[0].input_schema, undefined);
  const described = (await invoke({ action: 'describe', feature: 'status' })).structuredContent;
  assert.deepEqual(Object.keys(described.input_schema.properties), ['agent']);
  const result = (await invoke({ action: 'execute', feature: 'status', arguments: {} })).structuredContent;
  assert.equal(result.result.operation, 'status');
  assert.equal(result.result.caller, 'native-parent');
  await assert.rejects(invoke({ action: 'execute', feature: 'send', arguments: { agent: 'child' } }));
  await assert.rejects(invoke({ action: 'execute', feature: 'status', arguments: { caller: 'fake' } }));
  console.log(JSON.stringify({ tools: [...definitions.keys()], discovery: discovered,
    selectedSchema: described, call: result }));
} finally {
  await ctx.fiber.dispose();
}
assert.equal(definitions.size, 0);
