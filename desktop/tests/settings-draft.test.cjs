const test = require('node:test');
const assert = require('node:assert/strict');

test('prototype-named roles keep serialized edits and literal or explicitly renamed labels', async () => {
  const { ownRole, roleName, roleChanges } = await import('../src/settings-draft.ts');
  const names = ['constructor', 'prototype', '__proto__', 'toString'];
  const saved = Object.fromEntries(names.map(role => [role, { model: 'original-model' }]));
  const roles = Object.fromEntries(names.map(role => [role, { model: 'edited-model' }]));
  const { edits, changes } = roleChanges(roles, saved);
  assert.deepEqual(JSON.parse(JSON.stringify({ edits })).edits, roles);
  assert.deepEqual(changes, names.map(role => ({
    label: `${role} · Model`, before: 'original-model', after: 'edited-model',
  })));
  assert.equal(ownRole({}, 'constructor'), undefined);
  for (const role of names) {
    assert.equal(roleName({}, role), role);
    const renames = { [role]: 'renamed-role' };
    assert.equal(roleName(renames, role), 'renamed-role');
    assert.equal(roleName({ ...renames, other: 'other-name' }, role), 'renamed-role');
    assert.equal(ownRole(roles, role).model, 'edited-model');
  }
});
