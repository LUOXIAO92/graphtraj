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

/**
 * Attach a controlled, clearly labeled record set to one fixture Ticket.
 *
 * The records are a hand-written native Trace for this fixture only: no model
 * is invoked and no cost is incurred. Membership is created through the public
 * semantic-state entry, so the desktop reads the records through the same
 * desktop_activity boundary it uses in production.
 */
async function recordActivity(root, { ticketId, ticketName, alias, records, additionalMembers = [] }) {
  const members = [{ alias, records, historical: true }, ...additionalMembers];
  require('node:assert/strict').equal(await fs.readFile(path.join(root, 'seed.txt'), 'utf8'),
    'Desktop boundary test source.\n', 'Retained records belong only in disposable adoption fixtures');
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
    members: Object.fromEntries(members.map((member, index) =>
      [`member${index}`, { role: 'researcher', session_ref: member.alias }])),
  };
  operate(root, 'delivery_state_apply', { request, facts: request });

  for (const { alias, records, historical = true } of members) {
    const session = path.join(root, '.graphtraj', 'runner', 'sessions', alias);
    const trace = path.join(ticketDirectory, 'teams', '1', 'traces', alias, 'events.jsonl');
    await fs.mkdir(session, { recursive: true });
    await fs.mkdir(path.dirname(trace), { recursive: true });
    await fs.writeFile(trace, records.map(record => JSON.stringify(record)).join('\n') + '\n');

    // Controlled membership, never a launched Runtime or the caller's identity.
    // Current members have a completed execution; no process is presented as live.
    const mapping = {
      alias, runtime: 'codex', session: `native-${alias}`, ticket_id: ticketId,
      team_generation: 1, role: 'researcher', parent: null, retained_batch_file: 'batch.yml',
      worktree_path: path.join(root, 'worktrees', 'research'), trace_file: trace,
      worker_pid: 2147483647, runtime_pid: 2147483647,
    };
    // JSON is valid YAML; the public reader distinguishes retained retirement
    // from a current member whose recorded execution has already completed.
    if (historical) {
      await fs.writeFile(path.join(session, 'session.yml'),
        JSON.stringify({ retirement: { mapping } }, null, 2) + '\n');
    } else {
      await fs.writeFile(path.join(session, 'mapping.yml'), JSON.stringify(mapping, null, 2) + '\n');
      await fs.writeFile(path.join(session, 'execution.yml'), 'outcome: completed\n');
    }
    await fs.writeFile(path.join(session, 'launch.yml'), 'context_evidence:\n  model: recorded-model\n');
  }
  return path.join(ticketDirectory, 'teams', '1', 'traces', alias, 'events.jsonl');
}

module.exports = { operate, ticket, makeProject, recordActivity };
