import fixtures from './fixtures.cjs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
const root = process.argv[2];
const first = await fixtures.makeProject(path.join(root, 'first-project'), 'first-project');
await fixtures.recordActivity(first, { taskId: '1', taskName: 'first-project', alias: 'research@x1', records: [
  { type: 'turn_context', payload: { model: 'actual-model' } },
  { timestamp: new Date().toISOString(), type: 'event_msg', payload: { type: 'token_count', info: {
    last_token_usage: { input_tokens: 4321, cached_input_tokens: 1234, output_tokens: 567 },
    total_token_usage: { input_tokens: 4321, output_tokens: 567 } } } }] });
fixtures.operate(first, 'task_revise', { product_preserving: true, caused_by_event_ids: [], evidence_refs: ['evidence.md'], tasks: [
  { ...fixtures.task('2', 'dependent', ['1']), disposition: 'superseded', replaced_by: ['3'], retirement_reason: 'Replaced by successor.',
    current_definition: fixtures.operate(first, 'task_graph', { view: 'full' }).tasks.find(t => t.task_id === '2').current_definition },
  { ...fixtures.task('3', 'successor', ['1']), current_definition: null }] });
const reply = JSON.parse(execFileSync('graphtraj-tool', ['--desktop-observer', '--allowed-features', 'desktop_activity'], { cwd: first, encoding: 'utf8',
  input: JSON.stringify({ action: 'execute', feature: 'desktop_activity', arguments: { task_id: '1', alias: 'research@x1' } }) + '\n' }));
console.log('scope', reply.result?.scope, 'usage tokens', JSON.stringify(reply.result?.events?.find(e => e.kind === 'usage')?.usage?.tokens));
for (const t of fixtures.operate(first, 'task_graph').tasks) console.log('task', t.task_id, 'status', t.status, 'active', t.active, 'disposition', t.disposition);
