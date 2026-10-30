/** Exercise the delivered plugin in installed native scopes, without a model. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [nativePackage, pluginPath, python, server] = process.argv.slice(2);
// A standalone run supplies DSH_AGENT_PACKAGE and no GRAPHTRAJ_* variable (383).
if (!process.env.DSH_AGENT_PACKAGE) process.env.GRAPHTRAJ_DSH_PACKAGE = nativePackage;
const require = createRequire(nativePackage);
const load = name => import(pathToFileURL(require.resolve(name)));
const { Context } = await load('@deepseek-ai/cordis');
const { SessionStore } = await load('@deepseek-ai/dsh-session');
const { SessionQueryEngine } = await load('@deepseek-ai/dsh-session-query');
const { TypertRegistry } = await load('@deepseek-ai/dsh-typert-registry');
const { SystemPrompt } = await load('@deepseek-ai/dsh-system-prompt');
const { ToolRuntime } = await load('@deepseek-ai/dsh-tools');
const { createScope, scopeTarget } = await load('@deepseek-ai/dsh-scope');
const { Loader } = await load('@deepseek-ai/cordis-plugin-loader');
const { ClientModuleRegistry } = await load('@deepseek-ai/dsh-client-modules');
const { DeepSeekLlmApiExtensionRegistry } = await load('@deepseek-ai/dsh-deepseek-llm-api-extensions');
const inventory = await load('@deepseek-ai/dsh-plugin-package-inventory-deepseek');
const ctx = new Context();
await ctx.plugin(SessionStore).await();
await ctx.plugin(SessionQueryEngine).await();
await ctx.plugin(TypertRegistry).await();
await ctx.plugin(SystemPrompt).await();
await ctx.plugin(ToolRuntime).await();
ctx.provide('agents', { get: () => undefined });
ctx.provide('shellEnv', { register: () => () => {} });
const scopes = [];
try {
  await ctx.plugin(Loader, { baseUrl: pathToFileURL(process.cwd() + '/').href }).await();
  await ctx.loader.create({ name: pluginPath, config: { mcpCommand: python, mcpArgs: [server] } });
  await ctx.loader.await();
  await ctx.plugin(DeepSeekLlmApiExtensionRegistry).await();
  await ctx.plugin(inventory, {}).await();
  const extension = await ctx.deepseekLlmApiExtensions.prepare({ body: {}, signal: new AbortController().signal });
  // The manifest repeats agent_swarm.__version__ (test_mcp_server_version_is_the_single_package_version).
  const { version } = JSON.parse(readFileSync(new URL('package.json', pathToFileURL(pluginPath)), 'utf8'));
  assert.ok(extension.fields.dsh_plugin_packages.packages.some(item => item.name === 'agents-dsh' && item.version === version));
  await ctx.plugin(ClientModuleRegistry).await();
  const entry = ctx.clientModules.graph().entries.find(row => row.id === 'agents-dsh');
  assert.ok(entry);
  const bundle = await ctx.clientModules.fetchBundle(new Request(new URL(entry.url, 'http://fixture/')));
  assert.equal(bundle.status, 200);
  assert.match(await bundle.text(), /tool.call.toolview/);
  async function create(id, meta, parent) {
    const session = ctx.sessions.create(id, { meta: { cwd: process.cwd(), ...meta } });
    const agent = { id, session };
    const scope = createScope(ctx, agent, parent ? { parent } : undefined);
    scopes.push(scope);
    agent.ctx = scope.ctx;
    await ctx.serial(scopeTarget(agent, agent), 'agent/created', {
      agent, source: 'test', signal: new AbortController().signal,
    });
    return agent;
  }
  const parent = await create('native-parent', {});
  const child = await create('native-child', { origin: 'subagent', delegationDepth: 1 }, parent);
  for (const agent of [parent, child]) {
    assert.deepEqual(ctx.tools.schemas(agent).map(tool => tool.name), ['mcp__agents__agents']);
  }
  const args = { action: 'execute', feature: 'status', arguments: {} };
  const execution = { signal: new AbortController().signal };
  const result = await ctx.tools.get('mcp__agents__agents', parent).execute(args, execution);
  assert.equal(result.structuredContent.result.caller, 'native-parent');
  const childResult = await ctx.tools.get('mcp__agents__agents', child).execute(args, execution);
  assert.equal(childResult.structuredContent.result.caller, 'native-child');
  assert.equal(childResult.structuredContent.result.source, 'child');
  console.log(JSON.stringify({ tools: ctx.tools.schemas(parent).map(tool => tool.name),
    nativeSession: result.structuredContent.result.caller, childSourcePreserved: true,
    browserEntry: entry.id }));
} finally {
  for (const scope of scopes.reverse()) await scope.dispose();
  await ctx.fiber.dispose();
}
