const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { build } = require('esbuild');
let taskPaths, monitorGraph, taskFocus;
test.before(async () => {
  const result = await build({ entryPoints: [path.join(__dirname, '../src/monitor-graph.ts')],
    bundle: true, platform: 'node', format: 'cjs', write: false });
  const module = {exports:{}};
  vm.runInNewContext(result.outputFiles[0].text, {module,exports:module.exports,structuredClone});
  ({taskPaths,monitorGraph,taskFocus} = module.exports);
});
const node = (id,x,y,height=150) => ({id,x,y,width:320,height});
const edge = (source,target,kind='acceptance') => ({id:JSON.stringify([source,target,kind]),source,target,kind,
  kinds:[kind],relations:[{source,target,kind}],vertices:[],projected:false});
const fixture = () => ({nodes:[node('A',0,0),node('B',0,260),node('C',0,520),node('T',1200,0,500)],
  edges:[edge('A','T'),edge('B','T'),edge('C','T')]});
const pointKey = p => JSON.stringify(p);

test('multiple receipts truly converge once and every source has a path to the one arrow', () => {
  const {nodes,edges} = fixture(), before=JSON.stringify({nodes,edges});
  const drawing=taskPaths(nodes,edges), arrows=drawing.paths.filter(p=>p.arrow);
  assert.equal(arrows.length,1);
  assert.equal(arrows[0].target.cell,'T');
  assert.equal(drawing.ports.get('T').length,1);
  assert.equal(drawing.ports.size,nodes.length,'no synthetic task or junction node');
  assert.deepEqual(Array.from(arrows[0].data.relations,r=>r.source).sort(),['A','B','C']);
  for(const e of edges) {
    const branch=drawing.paths.find(p=>p.id===e.id);
    assert.equal(branch.arrow,false);
    assert.deepEqual(Array.from(branch.data.relations,r=>r.source),[e.source]);
    const seen=new Set(), queue=[branch.target]; let reached=false;
    while(queue.length) {
      const at=queue.shift(), key=pointKey(at); if(seen.has(key))continue; seen.add(key);
      for(const p of drawing.paths.filter(p=>pointKey(p.source)===key)) {
        assert.ok(p.data.relations.some(r=>r.source===e.source),'shared segment retains the entering source');
        if(p.arrow) reached=true; else queue.push(p.target);
      }
    }
    assert.ok(reached,'no discarded branch or second target arrow after convergence');
  }
  const shared=drawing.paths.filter(p=>p.direct);
  assert.equal(new Set(shared.map(p=>JSON.stringify([p.source,p.target]))).size,shared.length);
  assert.equal(JSON.stringify({nodes,edges}),before);
});

test('receiving structures isolate different targets, relation kinds and reverse approaches', () => {
  const {nodes,edges}=fixture();
  nodes.push(node('D',2200,0),node('E',2200,300),node('U',1200,800,400));
  edges.push(edge('A','T','dependency'),edge('B','T','dependency'),edge('D','T'),edge('E','T'),edge('A','U'),edge('B','U'));
  const drawing=taskPaths(nodes,edges), arrows=drawing.paths.filter(p=>p.arrow);
  assert.equal(arrows.length,4);
  for(const p of drawing.paths) {
    assert.equal(new Set(p.data.relations.map(r=>r.target)).size,1);
    assert.equal(new Set(p.data.relations.map(r=>r.kind)).size,1);
    const directions=new Set(p.data.relations.map(r=>Math.sign(nodes.find(n=>n.id===r.target).x-nodes.find(n=>n.id===r.source).x)));
    assert.equal(directions.size,1);
  }
  assert.equal(drawing.ports.get('T').length,3);
});

test('source selection follows its branch and shared receipt without selecting sibling branches', () => {
  const {nodes,edges}=fixture();
  const graph={tasks:[...['A','B','C'].map(task_id=>({task_id,parent_id:'T',dependencies:[],replaced_by:[],delivery:[{event:'task-completed',task_id:'T'}]})),
    {task_id:'T',parent_id:null,dependencies:[],replaced_by:[]}]};
  const focus=taskFocus(graph,'A');
  assert.deepEqual(Array.from(focus).sort(),['A','T']);
  const drawing=taskPaths(nodes,edges);
  const selected=drawing.paths.filter(p=>p.data.relations.some(r=>focus.has(r.source)&&focus.has(r.target)));
  assert.ok(selected.some(p=>p.arrow));
  assert.ok(selected.some(p=>p.id===edges[0].id));
  assert.ok(!selected.some(p=>p.id===edges[1].id||p.id===edges[2].id));
  for(const p of selected.filter(p=>p.direct))assert.ok(p.data.relations.some(r=>r.source==='A'));
});

test('collapsed visible pairs retain all relations before common-target drawing', () => {
  const task=(task_id,parent_id,dependencies=[])=>({task_id,parent_id,dependencies,title:task_id,status:'pending',active:true,replaced_by:[]});
  const graph={tasks:[task('S',null),task('A','S'),task('B','S'),task('T',null,['A','B'])]};
  for(const expanded of [[],['S']]) {
    const view=monitorGraph(graph,new Set(expanded)), drawing=taskPaths(view.nodes,view.edges);
    assert.equal(drawing.paths.filter(p=>p.arrow).length,1);
    const arrow=drawing.paths.find(p=>p.arrow);
    assert.deepEqual(Array.from(arrow.data.relations,r=>r.source).sort(),['A','B']);
    assert.equal(drawing.paths.filter(p=>'cell' in p.source).length,expanded.length?2:1);
  }
});
