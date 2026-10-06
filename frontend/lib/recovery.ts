export interface Archive {version:number;session_id:string;updated:string;payload:string;signature:string;}
export interface RecoveryState {kind:'idle'|'saved'|'restored'|'warning'|'missing';message:string;}
let state:RecoveryState={kind:'idle',message:''};
export function recoveryState(){return state;}
export function notifyRecovery(next:RecoveryState){state=next;window.dispatchEvent(new Event('shenmou-recovery'));}
let database:Promise<IDBDatabase>|null=null;
function db():Promise<IDBDatabase>{
  if(!database)database=new Promise<IDBDatabase>((resolve,reject)=>{
    const request=indexedDB.open('shenmou-workspace-backups',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('workspaces',{keyPath:'session_id'});
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(new Error('浏览器不允许保存备份'));
    request.onblocked=()=>reject(new Error('备份数据库被其他标签页占用'));
  }).catch(e=>{database=null;throw e;});
  return database;
}
export async function readArchive(sid:string):Promise<Archive|undefined>{
  const database=await db();
  return new Promise((resolve,reject)=>{
    const request=database.transaction('workspaces','readonly').objectStore('workspaces').get(sid);
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
}
export async function listArchives():Promise<Archive[]>{
  const database=await db();
  return new Promise((resolve,reject)=>{
    const request=database.transaction('workspaces','readonly').objectStore('workspaces').getAll();
    request.onsuccess=()=>resolve(request.result.sort((a:Archive,b:Archive)=>b.updated.localeCompare(a.updated)));
    request.onerror=()=>reject(request.error);
  });
}
export async function writeArchive(archive:Archive){
  const database=await db();
  await new Promise<void>((resolve,reject)=>{
    const tx=database.transaction('workspaces','readwrite'),store=tx.objectStore('workspaces');
    const current=store.get(archive.session_id);
    current.onsuccess=()=>{if(!current.result||current.result.updated<=archive.updated)store.put(archive);};
    tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
  });
}
export async function clearDeviceArchives(){
  const database=await db();
  await new Promise<void>((resolve,reject)=>{
    const tx=database.transaction('workspaces','readwrite');tx.objectStore('workspaces').clear();
    tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);
  });
}
