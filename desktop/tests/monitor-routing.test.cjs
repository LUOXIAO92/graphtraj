const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let api;
test.before(async () => {
  const result = await build({ stdin: { contents: `
    export {routerPresets, Model, Shape, Point} from '@antv/x6';
    export {taskRouterOptions} from './src/monitor-graph';`, resolveDir: path.join(__dirname, '..') },
    mainFields: ['module', 'main'], bundle: true, platform: 'node', format: 'cjs', write: false });
  const module = { exports: {} };
  vm.runInNewContext(result.outputFiles[0].text, { module, exports: module.exports, console, setTimeout, clearTimeout });
  api = module.exports;
});

test('metro enters normal terminal segments without circling the last waypoint', () => {
  const { routerPresets, Model, Shape, Point, taskRouterOptions } = api;
  for (const dy of [-100, 100, 260]) {
    const model = new Model();
    const source = new Shape.Rect({ id: 'source', x: 0, y: 0, width: 320, height: 161 });
    const target = new Shape.Rect({ id: 'target', x: 460, y: dy, width: 320, height: 161 });
    const edge = new Shape.Edge({ source: { cell: 'source' }, target: { cell: 'target' } });
    model.addCells([source, target, edge]);
    const view = { cell: edge, graph: { model, grid: { getGridSize: () => 20 } },
      sourceAnchor: new Point(320, 81), targetAnchor: new Point(460, dy + 81),
      sourceBBox: source.getBBox(), targetBBox: target.getBBox() };
    const vertices = [{ x: 360, y: 81 }, { x: 420, y: dy + 81 }];
    const route = routerPresets.metro.call(view, vertices, {
      ...taskRouterOptions, startDirections: ['right'], endDirections: ['left'],
    }, view);
    const points = [view.sourceAnchor, ...route, view.targetAnchor];
    // A closed detour reverses x near the target even in this obstacle-free corridor.
    for (let i = 1; i < points.length; i++) assert.ok(points[i].x >= points[i - 1].x);
    assert.equal(route.at(-1).y, view.targetAnchor.y);
    assert.ok(view.targetAnchor.x - route.at(-1).x >= 40);
    assert.equal(route[0].y, view.sourceAnchor.y);
    assert.ok(route[0].x - view.sourceAnchor.x >= 40);
  }
});
