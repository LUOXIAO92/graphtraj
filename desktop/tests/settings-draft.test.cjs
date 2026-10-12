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

test('tree editing moves complete branches and explicitly reconnects or deletes children', async () => {
  const { moveNode, removeNodes, branchRoles } = await import('../src/settings-draft.ts');
  const tree = { 'team.root': { 'team.middle': { 'team.leaf': {} }, 'team.other': {} }, 'second.root': {} };
  const plain = value => JSON.parse(JSON.stringify(value));
  assert.deepEqual([...branchRoles(tree, 'team.middle')], ['team.middle', 'team.leaf']);
  assert.deepEqual(plain(moveNode(tree, 'team.middle', 'team.other')), {
    'team.root': { 'team.other': { 'team.middle': { 'team.leaf': {} } } }, 'second.root': {},
  });
  assert.throws(() => moveNode(tree, 'team.middle', 'team.leaf'), /outside this branch/);
  assert.deepEqual(plain(removeNodes(tree, new Set(['team.middle']), true)), {
    'team.root': { 'team.leaf': {}, 'team.other': {} }, 'second.root': {},
  });
  assert.deepEqual(plain(removeNodes(tree, branchRoles(tree, 'team.middle'), false)), {
    'team.root': { 'team.other': {} }, 'second.root': {},
  });
  assert.deepEqual(tree['team.root']['team.middle'], { 'team.leaf': {} });
});

test('team forest preserves individual native occurrences, cross-team edges and unattached roles', async () => {
  const { teamForest } = await import('../src/settings-draft.ts');
  const tree = { 'a.root': { 'a.worker': {} }, 'a.independent': {}, 'b.root': { 'a.worker': { 'b.child': {} } }, 'c.root': {} };
  assert.deepEqual(teamForest(tree, ['a.root', 'a.worker', 'a.independent', 'a.unattached']), {
    'a.root': { 'a.worker': {} }, 'a.independent': {}, 'b.root': { 'a.worker': { 'b.child': {} } }, 'a.unattached': {},
  });
  assert.deepEqual(teamForest(tree, ['c.root']), { 'c.root': {} });
});

test('connecting one occurrence preserves historical cross-team paths and refuses cycles', async () => {
  const { connectTeamNode } = await import('../src/settings-draft.ts');
  const tree = { 'a.root': { 'a.worker': { 'a.leaf': {} }, 'a.other': {} }, 'b.root': { 'a.worker': { 'b.child': {} } } };
  const next = connectTeamNode(tree, ['a.root', 'a.worker'], ['a.root', 'a.other']);
  assert.deepEqual(next, { 'a.root': { 'a.other': { 'a.worker': { 'a.leaf': {} } } }, 'b.root': tree['b.root'] });
  assert.deepEqual(tree['a.root']['a.worker'], { 'a.leaf': {} });
  assert.throws(() => connectTeamNode(tree, ['a.root','a.worker'], ['a.root','a.worker']), /itself/);
  assert.throws(() => connectTeamNode(tree, ['a.root','a.worker'], ['a.root','a.worker','a.leaf']), /descendants/);
  assert.throws(() => connectTeamNode(tree, ['a.root','a.worker'], ['b.root']), /current team/);
  assert.throws(() => connectTeamNode(tree, ['b.root','a.worker'], ['a.root']), /historical cross-team/);
  assert.deepEqual(connectTeamNode({}, ['a.worker'], ['a.root']), { 'a.root': { 'a.worker': {} } });
  const detached = connectTeamNode(tree, ['a.root', 'a.worker'], null);
  assert.deepEqual(detached['a.worker'], { 'a.leaf': {} });
  assert.deepEqual(detached['b.root'], tree['b.root']);
});

test('graph connections preserve literal prototype-named roles', async () => {
  const { connectTeamNode } = await import('../src/settings-draft.ts');
  const result = connectTeamNode({}, ['constructor'], ['__proto__']);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { ['__proto__']: { constructor: {} } });
  assert.equal(Object.hasOwn(result, '__proto__'), true);
});
