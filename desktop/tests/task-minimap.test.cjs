const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let TaskMiniMap;
test.before(async () => {
  const result = await build({ entryPoints: [path.join(__dirname, '../src/task-minimap.ts')],
    mainFields: ['module', 'main'], bundle: true, platform: 'node', format: 'cjs', write: false });
  const module = { exports: {} };
  vm.runInNewContext(result.outputFiles[0].text, { module, exports: module.exports, console, setTimeout, clearTimeout });
  ({ TaskMiniMap } = module.exports);
});

test('fitted minimap click and drag use the displayed coordinate scale', () => {
  // Exercise the adapter and inherited X6 drag handler without a browser host.
  const map = Object.create(TaskMiniMap.prototype);
  map.normalizeEvent = event => event;
  let centered, translated;
  map.sourceGraph = { centerPoint: (x, y) => { centered = { x, y }; },
    transform: { getScale: () => ({ sx: .8, sy: .8 }) },
    translate: (x, y) => { translated = { x, y }; } };
  map.graph = { getPlugin: () => undefined };
  map.ratio = .167; // Nominal paper ratio differs from the fitted graph scale.
  map.targetGraph = { transform: { getScale: () => ({ sx: .015, sy: .015 }) },
    clientToLocal: (x, y) => ({ x: (x - 1213 - 10) / .015, y: (y - 708 - 20) / .015 }) };
  map.scrollTo({ clientX: 1397, clientY: 764, offsetX: 4, offsetY: 5 });
  assert.deepEqual(centered, { x: 11600, y: 2400 });
  map.doAction({ clientX: 1397, clientY: 780, data: { action: 'panning',
    clientX: 1307, clientY: 760, translateX: 100, translateY: 200 } });
  assert.ok(Math.abs(translated.x - (100 - 90 * .8 / .015)) < 1e-8);
  assert.ok(Math.abs(translated.y - (200 - 20 * .8 / .015)) < 1e-8);
});
