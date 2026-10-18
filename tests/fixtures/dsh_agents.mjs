/** Exercise the installed defineTool contract, without a model or UI claim. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [nativePackage, modulePath] = process.argv.slice(2);
const require = createRequire(nativePackage);
const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')));
const { agentsTool } = await import(pathToFileURL(modulePath));
const calls = [];
const payload = JSON.stringify({ failed: false, result: { action: 'wait', agent: 'child-1', result: {
  state: 'standby', last_result: { last_message: 'reply body' },
} } });
const execution = { agent: { session: { id: 'parent-1' } } };
const tool = defineTool(agentsTool(async (request, context) => {
  calls.push({ request, context });
  return payload;
}));
const args = { action: 'send', agent: 'child-1', message: 'outbound body' };
const value = await tool.execute(args, execution);
assert.deepEqual(calls, [{ request: { action: 'execute', feature: 'agents', arguments: args }, context: execution }]);
assert.equal(tool.name, 'agents');
assert.equal(tool.presentCall(args).content[0].text, 'outbound body');
assert.match(tool.presentCall(args).title, /current Agent → child-1/);
const content = tool.output.render(args, value);
const before = JSON.stringify(content);
const shown = tool.presentResult(args, { content, isError: false });
assert.equal(shown.content[0].text, 'reply body');
assert.match(shown.title, /child-1 → current Agent/);
assert.equal(JSON.stringify(content), before);
assert.equal(calls.length, 1); // Replaying the UI never calls or injects input again.
await assert.rejects(tool.execute({ action: 'invented' }, execution));
console.log('native defineTool and pure presentation passed');
