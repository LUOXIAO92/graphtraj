const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { SettingsClient } = require('../dist-electron/settings.js');

for (const [kind, guidance] of [
  ['validation', 'Correct the reported setting'],
  ['conflict', 'Reload the current configuration'],
  ['write', 'Check that the destination is writable'],
]) test(`settings pipe gives ${kind}-specific recovery`, async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-298-errors-'));
  const executable = path.join(directory, 'settings-peer');
  await fs.writeFile(executable, `#!${process.execPath}\nprocess.stdin.once('data', () => console.log(JSON.stringify(${JSON.stringify({ failed: true, error: 'Controlled failure.', error_kind: kind })})));\n`, { mode: 0o755 });
  const client = new SettingsClient(executable);
  t.after(async () => { client.close(); await fs.rm(directory, { recursive: true, force: true }); });
  await assert.rejects(client.request(directory, { revision: 'r', edits: {}, renames: {}, add_edges: [], remove_edges: [] }), error => {
    assert.ok(error.message.includes(guidance));
    if (kind !== 'conflict') assert.doesNotMatch(error.message, /Reload/);
    return true;
  });
});
