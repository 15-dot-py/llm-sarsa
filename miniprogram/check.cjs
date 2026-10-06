// Offline client contract checks. These do not claim WeChat device acceptance.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=__dirname,manifest=JSON.parse(fs.readFileSync(path.join(root,'app.json'),'utf8'));
for(const p of manifest.pages)for(const suffix of ['.js','.json','.wxml'])assert(fs.existsSync(path.join(root,p+suffix)),p+suffix);
for(const file of ['project.config.json','sitemap.json'])JSON.parse(fs.readFileSync(path.join(root,file),'utf8'));
const calls=[],fakeApi={request:async(p,data,method)=>{calls.push({p,data,method});if(p==='/decisions')return record;return {};},ensureLogin:async()=>false,save(){},clear(){},upload:async()=>({})};
const record={id:'one',status:'draft',action_name:'a',action_label:'合法动作',q_values:[{name:'a',legal:true,label:'合法动作',q:.2}],explanation:{reasons:[]},actual_reward:null};
function page(name){let definition;vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{require(p){return p.includes('api')?fakeApi:{privacyVersion:'2026-10-06'};},Page(p){definition=p;},wx:{showToast(){},redirectTo(){},navigateTo(){}},setInterval(){return 1;},clearInterval(){},Date,Number,Promise,Error});
  const instance={...definition,data:JSON.parse(JSON.stringify(definition.data || {})),setData(v){for(const [key,value]of Object.entries(v)){const parts=key.split('.');let node=this.data;for(const part of parts.slice(0,-1)){node[part]??={};node=node[part];}node[parts.at(-1)]=value;}}};return instance;}
(async()=>{
  const login=page('login');await login.send();assert.equal(calls.length,0,'unconfigured login must never send SMS');
  login.phoneInput({detail:{value:'13800000000'}});assert(login.data.phoneValid);login.setData({challenge:'old',code:'123456',codeValid:true});login.phoneInput({detail:{value:'13900000000'}});assert.equal(login.data.challenge,'');assert.equal(login.data.code,'');
  const home=page('home');home.setRecord(record);assert.equal(calls.length,0,'displaying suggestion must not execute it');
  home.setData({activeId:'one'});await home.run(async()=>{await home.execute();});assert.equal(calls.length,0,'busy guards prevent duplicate operations');
  home.setData({busy:false});await home.run(async()=>{});assert.equal(calls.length,0);
  home.setData({feedback:{revenue:'1',profit:'1',roi:'1',cac:'1',inventory_level:'1'}});home.feedback();await new Promise(r=>setImmediate(r));assert.equal(calls.length,0,'incomplete feedback must not become zero');
  for(const p of manifest.pages){const source=fs.readFileSync(path.join(root,p+'.js'),'utf8');new vm.Script(source,{filename:p});const pageDef=page(path.basename(path.dirname(p)));const wxml=fs.readFileSync(path.join(root,p+'.wxml'),'utf8');for(const m of wxml.matchAll(/(?:bind\w+|catch\w+)="([A-Za-z][\w]*)"/g))assert.equal(typeof pageDef[m[1]],'function',p+' missing event '+m[1]);}
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'project.config.json'),'utf8')).setting.urlCheck,true);
  console.log('Mini-program manifest, JavaScript, event bindings and auth/decision contracts passed. Native WeChat build remains pending.');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
