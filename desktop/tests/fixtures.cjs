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

module.exports = { operate, ticket, makeProject };
