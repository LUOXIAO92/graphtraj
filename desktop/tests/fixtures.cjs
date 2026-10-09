const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');

/** Exercise installed public operations, never write GraphTraj's private state. */
function operate(root, feature, args = {}) {
  const reply = JSON.parse(execFileSync(process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool', [], {
    cwd: root, encoding: 'utf8',
    input: JSON.stringify({ action: 'execute', feature, arguments: args }) + '\n',
  }));
  if (reply.failed) throw new Error(JSON.stringify(reply));
  return reply.result;
}

function ticket(id, name, dependencies = []) {
  return {
    ticket_id: id, ticket_name: name, title: name.replaceAll('-', ' '),
    source: `https://github.com/example/desktop-test/issues/${id}`,
    body: 'A controlled desktop read-boundary fixture. No model execution.', dependencies,
  };
}

async function makeProject(root, name) {
  await fs.mkdir(root);
  execFileSync('git', ['init', '--initial-branch=main', root]);
  await fs.writeFile(path.join(root, 'seed.txt'), 'Desktop boundary test source.\n');
  execFileSync('git', ['add', 'seed.txt'], { cwd: root });
  execFileSync('git', ['-c', 'user.name=Desktop Test', '-c', 'user.email=test@example.invalid',
    'commit', '-m', 'Test source'], { cwd: root });
  operate(root, 'project_setup', { source_repository: root, apply: true, create_dev: true });
  operate(root, 'ticket_register', ticket('1', name));
  operate(root, 'ticket_register', ticket('2', 'dependent', ['1']));
  return root;
}

/** Quote one YAML scalar so identifiers and paths survive parsing unchanged. */
function scalar(value) {
  return typeof value === 'number' ? String(value) : JSON.stringify(value);
}

/**
 * Attach a controlled, clearly labeled record set to one fixture Ticket.
 *
 * The records are a hand-written native Trace for this fixture only: no model
 * is invoked and no cost is incurred. Membership is created through the public
 * semantic-state entry, so the desktop reads the records through the same
 * desktop_activity boundary it uses in production.
 */
async function recordActivity(root, { ticketId, ticketName, alias, records }) {
  const ticketDirectory = path.join(root, '.graphtraj', 'state', 'tickets',
    `${ticketId}-${ticketName}`);
  await fs.writeFile(path.join(root, 'evidence.md'), 'Controlled adoption fixture. No model execution.\n');

  const ready = operate(root, 'ticket_update', {
    ticket_id: ticketId, status: 'ready', active_team_ordinal: null, worktree: null,
    branch: null, current_candidate: null, caused_by_event_ids: [], evidence_refs: ['evidence.md'],
  });
  const request = {
    phase: 'start', ticket_id: ticketId, caused_by_event_ids: [ready.event_id],
    evidence_refs: ['evidence.md'], worktree: 'worktrees/research',
    branch: `agent/${ticketId}-${ticketName}`,
    members: { first: { role: 'researcher', session_ref: alias } },
  };
  operate(root, 'delivery_state_apply', { request, facts: request });

  const session = path.join(root, '.graphtraj', 'runner', 'sessions', alias);
  const trace = path.join(ticketDirectory, 'teams', '1', 'traces', alias, 'events.jsonl');
  await fs.mkdir(session, { recursive: true });
  await fs.mkdir(path.dirname(trace), { recursive: true });
  await fs.writeFile(trace, records.map(record => JSON.stringify(record)).join('\n') + '\n');

  const mapping = {
    alias, runtime: 'codex', session: `native-${alias}`, ticket_id: ticketId,
    team_generation: 1, role: 'researcher', parent: null, retained_batch_file: 'batch.yml',
    worktree_path: path.join(root, 'worktrees', 'research'), trace_file: trace,
    worker_pid: 1, runtime_pid: 1,
  };
  const lines = Object.entries(mapping).map(([key, value]) => `${key}: ${scalar(value)}`);
  await fs.writeFile(path.join(session, 'mapping.yml'), lines.join('\n') + '\n');
  await fs.writeFile(path.join(session, 'launch.yml'), 'context_evidence:\n  model: recorded-model\n');
  await fs.writeFile(path.join(session, 'execution.yml'), 'outcome: completed\n');
  return trace;
}

module.exports = { operate, ticket, makeProject, recordActivity };
