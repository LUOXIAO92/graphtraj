const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let api;
test.before(async () => {
  const result = await build({ stdin: { contents: `
    export {routerPresets, Model, Shape, Point, Rectangle} from '@antv/x6';
    export {taskRouterOptions, dependencyTerminals, monitorGraph, taskPaths} from './src/monitor-graph';`, resolveDir: path.join(__dirname, '..') },
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


test('distinct sources retain separate routed passages before entering one target', () => {
  const { routerPresets, Model, Shape, Point, taskRouterOptions, dependencyTerminals } = api;
  const nodes = [
    { id: 'upper', x: 0, y: 0, width: 320, height: 150 },
    { id: 'middle', x: 0, y: 260, width: 320, height: 150 },
    { id: 'lower', x: 0, y: 520, width: 320, height: 150 },
    { id: 'obstacle', x: 460, y: 50, width: 320, height: 280 },
    { id: 'target', x: 1200, y: 80, width: 320, height: 450 },
  ];
  const edges = ['upper', 'middle', 'lower'].map((source, index) => ({
    id: source, source, target: 'target', vertices: [{x: 900, y: 350}],
    kind: index === 1 ? 'dependency' : 'acceptance',
  }));
  const before = JSON.stringify({nodes, edges});
  const ends = dependencyTerminals(nodes, edges);
  const model = new Model();
  const cards = new Map(nodes.map(n => [n.id, new Shape.Rect(n)]));
  model.addCells([...cards.values()]);
  const paths = edges.map(e => {
    const terminals = ends.get(e.id), source = cards.get(e.source), target = cards.get(e.target);
    const edge = new Shape.Edge({source: {cell: e.source}, target: {cell: e.target}});
    model.addCell(edge);
    const view = {cell: edge, graph: {model, grid: {getGridSize: () => 20}},
      sourceAnchor: new Point(source.position().x + terminals.source.x, source.position().y + terminals.source.y),
      targetAnchor: new Point(target.position().x + terminals.target.x, target.position().y + terminals.target.y),
      sourceBBox: source.getBBox(), targetBBox: target.getBBox()};
    const route = routerPresets.metro.call(view, terminals.vertices, {
      ...taskRouterOptions, startDirections: ['right'], endDirections: ['left'],
    }, view);
    assert.equal(route[0].y, view.sourceAnchor.y);
    assert.equal(route.at(-1).y, view.targetAnchor.y);
    assert.ok(route[0].x - view.sourceAnchor.x >= 40);
    assert.ok(view.targetAnchor.x - route.at(-1).x >= 40);
    return [view.sourceAnchor, ...route, view.targetAnchor];
  });
  const horizontal = points => points.slice(1).flatMap((b,i) => {
    const a = points[i];
    return Math.abs(a.y-b.y) < .01 && Math.abs(a.x-b.x) > 1
      ? [{left: Math.min(a.x,b.x), right: Math.max(a.x,b.x), y:a.y}] : [];
  });
  for (let i=0;i<paths.length;i++) for(let j=i+1;j<paths.length;j++) {
    for(const a of horizontal(paths[i])) for(const b of horizontal(paths[j])) {
      assert.ok(Math.abs(a.y-b.y) >= 8 || Math.min(a.right,b.right)-Math.max(a.left,b.left) <= 1,
        'different visible pairs must not share a long horizontal segment then split');
    }
  }
  assert.equal(JSON.stringify({nodes,edges}), before);
});


test('X6 routes converging source branches and the sole entry without extra terminal arrows', () => {
  const {routerPresets,Model,Shape,Point,Rectangle,taskRouterOptions,taskPaths}=api;
  const nodes=[{id:'a',x:0,y:0,width:320,height:150},{id:'b',x:0,y:300,width:320,height:150},
    {id:'target',x:1200,y:100,width:320,height:300}];
  const edges=['a','b'].map(source=>({id:source,source,target:'target',vertices:[],kind:'acceptance',kinds:['acceptance'],
    relations:[{source,target:'target',kind:'acceptance'}],projected:false}));
  const drawing=taskPaths(nodes,edges),model=new Model(),cards=new Map(nodes.map(n=>[n.id,new Shape.Rect(n)]));
  model.addCells([...cards.values()]);
  const resolve=terminal=>{
    if(!('cell' in terminal))return {anchor:new Point(terminal.x,terminal.y),bbox:new Rectangle(terminal.x,terminal.y,0,0)};
    const card=cards.get(terminal.cell),port=drawing.ports.get(terminal.cell).find(p=>p.id===terminal.port);
    return {anchor:new Point(card.position().x+port.args.x,card.position().y+port.args.y),bbox:card.getBBox()};
  };
  const segments=[];
  for(const p of drawing.paths){
    const source=resolve(p.source),target=resolve(p.target),edge=new Shape.Edge({source:p.source,target:p.target});model.addCell(edge);
    const view={cell:edge,graph:{model,grid:{getGridSize:()=>20}},sourceAnchor:source.anchor,targetAnchor:target.anchor,sourceBBox:source.bbox,targetBBox:target.bbox};
    const route=routerPresets[p.direct?'normal':'metro'].call(view,p.vertices,{
      ...taskRouterOptions,startDirections:['right'],endDirections:'cell' in p.target?['left']:['left','right','top','bottom'],
    },view);
    const points=[source.anchor,...route,target.anchor];
    assert.ok(points.every(v=>Number.isFinite(v.x)&&Number.isFinite(v.y)));
    if(p.arrow){assert.equal(route.at(-1).y,target.anchor.y);assert.ok(target.anchor.x-route.at(-1).x>=40);}
    if('cell' in p.source){assert.equal(route[0].y,source.anchor.y);assert.ok(route[0].x-source.anchor.x>=40);}
    for(let i=1;i<points.length;i++)if(Math.abs(points[i].x-points[i-1].x)<.1&&Math.abs(points[i].y-points[i-1].y)>1)
      segments.push({id:p.id,x:points[i].x,top:Math.min(points[i].y,points[i-1].y),bottom:Math.max(points[i].y,points[i-1].y)});
  }
  for(let i=0;i<segments.length;i++)for(let j=i+1;j<segments.length;j++){
    const a=segments[i],b=segments[j];
    if(a.id!==b.id&&Math.abs(a.x-b.x)<.1)assert.ok(Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)<=.1,'shared receiving runs are drawn only once');
  }
  assert.equal(drawing.paths.filter(p=>p.arrow).length,1);
});
