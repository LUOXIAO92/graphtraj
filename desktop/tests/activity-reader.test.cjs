const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const childProcess = require('node:child_process');
const { syncBuiltinESMExports } = require('node:module');
const { ActivityReader } = require('../electron/activity.ts');

test('observer preserves safe rejection details, redacts credentials, and continues normal reads', async t => {
  const child = Object.assign(new EventEmitter(), {
    stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough(), kill() {},
  });
  t.mock.method(childProcess, 'spawn', () => child);
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
  const oldSecret = process.env.GRAPHTRAJ_TEST_SECRET;
  process.env.GRAPHTRAJ_TEST_SECRET = 'environment-value';
  t.after(() => {
    if (oldSecret === undefined) delete process.env.GRAPHTRAJ_TEST_SECRET;
    else process.env.GRAPHTRAJ_TEST_SECRET = oldSecret;
  });
  const reader = new ActivityReader('graphtraj-tool');
  t.after(() => reader.close());
  const exchange = async wire => {
    const result = reader.read('/controlled-project', { ticket_id: '299' });
    await new Promise(resolve => setImmediate(resolve));
    child.stderr.write('stderr-private-value');
    child.stdout.write(typeof wire === 'string' ? wire + '\n' : JSON.stringify(wire) + '\n');
    return result;
  };
  const message = 'Observer unavailable environment-value Bearer bearer-value password="two words" api_key=key-value sk-abcdefghijk https://name:pass@example.test /private/example/file';
  for (const wire of [
    { failed: true, result: { error: { code: 'activity-observer-unavailable', message, details: 'private-details' }, events: ['private-body'] } },
    { failed: true, error: { code: 'activity-observer-unavailable', message, token: 'private-field' } },
  ]) {
    await assert.rejects(exchange(wire), error => {
      assert.match(error.message, /\[activity-observer-unavailable\]: Observer unavailable/);
      assert.match(error.message, /\[redacted\]/);
      assert.doesNotMatch(error.message, /environment-value|bearer-value|two words|key-value|sk-abcdefghijk|name:pass|private-details|private-body|private-field|stderr-private-value|\/private/);
      return true;
    });
  }
  await assert.rejects(exchange({ failed: true, error: 'Native transport closed' }), /\[unknown\]: Native transport closed/);
  await assert.rejects(exchange({ failed: true, result: { events: ['private-body'] } }), /\[unknown\]: Reason unavailable/);
  await assert.rejects(exchange('not JSON private-body'), /\[unknown\]: Invalid response/);
  const success = { agents: [], events: [{ text: 'successful-body-unchanged' }] };
  assert.deepEqual(await exchange({ failed: false, result: success }), success);
});

test('queued polls retain FIFO replies without spending the active request timeout', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  let killed=0;
  const child=Object.assign(new EventEmitter(),{stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough(),kill(){killed++;this.emit('exit',0);}});
  t.mock.method(childProcess,'spawn',()=>child);syncBuiltinESMExports();
  t.after(()=>{t.mock.restoreAll();syncBuiltinESMExports();});
  const sent=[];child.stdin.on('data',data=>sent.push(JSON.parse(data.toString()).arguments.alias));
  const reader=new ActivityReader('graphtraj-tool');
  const replies=Array.from({length:7},(_,i)=>reader.read('/controlled-project',{ticket_id:'299',alias:String(i)}));
  // Attach rejection handlers immediately, including the pre-fix timeout case.
  const all=Promise.all(replies);
  await new Promise(resolve=>setImmediate(resolve));
  for(let i=0;i<7;i++){
    assert.equal(sent.length,i+1,'only the active request is written to the serial observer');
    t.mock.timers.tick(3000);
    child.stdout.write(JSON.stringify({failed:false,result:{agents:[],events:[],alias:String(i)}})+'\n');
  }
  assert.deepEqual((await all).map(r=>r.alias),['0','1','2','3','4','5','6']);
  assert.equal(killed,0,'21 seconds total queue service is not a 15 second per-request failure');
  reader.close();
});

test('a genuinely stalled active poll still times out and rejects queued callers', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  let killed=0;
  const child=Object.assign(new EventEmitter(),{stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough(),kill(){killed++;this.emit('exit',0);}});
  t.mock.method(childProcess,'spawn',()=>child);syncBuiltinESMExports();
  t.after(()=>{t.mock.restoreAll();syncBuiltinESMExports();});
  const reader=new ActivityReader('graphtraj-tool');
  const first=reader.read('/controlled-project',{ticket_id:'299'});
  const second=reader.read('/controlled-project',{ticket_id:'299',alias:'member'});
  const results=Promise.allSettled([first,second]);
  await new Promise(resolve=>setImmediate(resolve));
  t.mock.timers.tick(15000);
  const [active,queued]=await results;
  assert.match(active.reason.message,/timed out/);
  assert.match(queued.reason.message,/disconnected/);
  assert.equal(killed,1);
});
