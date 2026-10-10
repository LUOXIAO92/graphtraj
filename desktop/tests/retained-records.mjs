import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

export const controlledInput = { message: 'GraphTraj GUI controlled message', tool: 'controlled tool output',
  model: 'gpt-5.3-codex', input: 1000, cacheRead: 600, output: 80, reasoning: 20 };

/** Only seed the new disposable test project; these are retained controlled records, not live identities. */
export async function retainedRecords(project, ticketDirectory) {
  assert.equal(await fs.readFile(path.join(project, 'seed.txt'), 'utf8'),
    'Controlled Windows adoption project; no model execution.\n');
  const alias = 'controlled@x1';
  const session = 'controlled-retained-session';
  const team = path.join(ticketDirectory, 'teams/1');
  const record = path.join(project, '.graphtraj/runner/sessions', alias);
  await fs.mkdir(team, { recursive: true });
  await fs.mkdir(record, { recursive: true });
  const trace = path.join(team, 'controlled.jsonl');
  const time = '2026-10-10T00:00:00Z';
  const tokens = { input_tokens: 1000, cached_input_tokens: 600, output_tokens: 80, reasoning_output_tokens: 20 };
  // JSON is valid YAML. Shapes match the existing retained desktop_activity fixture.
  const write = (filename, value) => fs.writeFile(filename, JSON.stringify(value, null, 2), { flag: 'wx' });
  await write(path.join(team, 'team.yml'), { team_ordinal: 1, status: 'active', current_round: 1,
    started_at: time, members: { controlled: { role: 'controlled', session_ref: alias } } });
  await write(path.join(record, 'session.yml'), { retirement: { mapping: {
    alias, runtime: 'codex', session, ticket_id: '1', team_generation: 1,
    role: 'controlled', parent: null, retained_batch_file: 'controlled-test-input',
    worktree_path: project, trace_file: trace, worker_pid: 2147483647, runtime_pid: 2147483647,
  } } });
  await write(path.join(record, 'launch.yml'), { context_evidence: { model: 'gpt-5.3-codex' } });
  const records = [
    { type: 'turn_context', payload: { model: 'gpt-5.3-codex', turn_id: 'controlled-turn' } },
    { type: 'response_item', payload: { type: 'message', role: 'assistant',
      content: [{ type: 'output_text', text: controlledInput.message }] } },
    { type: 'response_item', payload: { type: 'function_call', call_id: 'controlled-echo', name: 'echo',
      arguments: JSON.stringify({ text: controlledInput.tool }) } },
    { type: 'response_item', payload: { type: 'function_call_output', call_id: 'controlled-echo', output: controlledInput.tool } },
    { type: 'event_msg', payload: { type: 'token_count', info: { last_token_usage: tokens, total_token_usage: tokens } } },
  ];
  await fs.writeFile(trace, records.map(value => JSON.stringify({ timestamp: time, ...value })).join('\n') + '\n', { flag: 'wx' });
  return alias;
}

