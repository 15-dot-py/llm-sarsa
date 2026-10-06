const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ts=require('../frontend/node_modules/typescript');
const code=ts.transpileModule(fs.readFileSync('frontend/lib/api.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const sid='original-workspace',archive={version:1,session_id:sid,updated:'2026-10-06',payload:'signed-opaque',signature:'opaque'};
function client(fetch,backup=archive){
  const local=new Map([['shenmou-session-v1',sid]]),notices=[],saved=[];
  const exports={};vm.runInNewContext(code,{exports,require:()=>({readArchive:async()=>backup,writeArchive:async a=>saved.push(a),notifyRecovery:s=>notices.push(s)}),
    localStorage:{getItem:k=>local.get(k)||null,setItem:(k,v)=>local.set(k,v)},fetch,Headers,FormData,Map,Promise,Error});
  return {...exports,local,notices,saved};
}
const ok=x=>new Response(JSON.stringify(x),{status:200});
const expired=()=>new Response(JSON.stringify({detail:{code:'workspace_expired',message:'expired'}}),{status:401});
(async()=>{
  let restored=false,restores=0,creates=0,posts=0;
  const c=client(async(path,options)=>{
    assert.equal(new Headers(options?.headers).get('X-Session-Id')||sid,sid);
    if(path==='/api/session'){creates++;return ok({session_id:'wrong-empty'});}
    if(path==='/api/workspace/restore'){restores++;await new Promise(r=>setTimeout(r,5));restored=true;return ok({session_id:sid});}
    if(path==='/api/workspace/backup')return ok(archive);
    if(!restored)return expired();
    if(path.endsWith('/execute')){posts++;return ok({confirmed:true});}
    return ok({records:1});
  });
  await Promise.all([c.api('/decisions'),c.api('/dashboard')]);
  assert.equal(restores,1);assert.equal(creates,0);assert.equal(c.local.get('shenmou-session-v1'),sid);
  await c.post('/decisions/one/execute');assert.equal(posts,1);assert.equal(c.saved.length,2);
  let calls=[];
  const missing=client(async(path)=>{calls.push(path);return expired();},null);
  await assert.rejects(missing.post('/decisions/one/execute'),/没有可恢复备份/);
  assert.deepEqual(calls,['/api/decisions/one/execute']);assert.equal(missing.local.get('shenmou-session-v1'),sid);
  calls=[];
  const auth=client(async path=>{calls.push(path);return new Response(JSON.stringify({detail:'请先登录'}),{status:401});});
  await assert.rejects(auth.api('/dashboard'),/请先登录/);assert.deepEqual(calls,['/api/dashboard']);
  const failedBackup=client(async path=>path==='/api/workspace/backup'?new Response('{}',{status:503}):ok({confirmed:true}));
  assert.equal((await failedBackup.post('/decisions/one/execute')).confirmed,true);
  assert.equal(failedBackup.notices.at(-1).kind,'warning');
  console.log('API recovery contracts passed: shared restore, preserved SID, no silent empty workspace, auth separation, successful execution despite backup failure.');
})().catch(e=>{console.error(e);process.exitCode=1;});
