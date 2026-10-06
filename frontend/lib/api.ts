import {Archive,notifyRecovery,readArchive,writeArchive} from './recovery';
export class ApiError extends Error {
  constructor(message:string,public status:number,public code=''){super(message);}
}
let sessionPromise:Promise<string>|null=null;
const KEY='shenmou-session-v1';
const restorations=new Map<string,Promise<void>>();
async function failure(response:Response):Promise<ApiError>{
  try{const body=await response.json(),detail=body.detail;
    return new ApiError(typeof detail==='string'?detail:detail?.message||`请求失败 (${response.status})`,response.status,detail?.code||'');
  }catch{return new ApiError(`请求失败 (${response.status})`,response.status);}
}
export async function session():Promise<string>{
  const existing=localStorage.getItem(KEY);if(existing)return existing;
  if(!sessionPromise)sessionPromise=fetch('/api/session',{method:'POST'}).then(async response=>{
    if(!response.ok)throw await failure(response);
    const data=await response.json();localStorage.setItem(KEY,data.session_id);return data.session_id;
  }).finally(()=>{sessionPromise=null;});
  return sessionPromise;
}
async function preserve(sid:string){
  try{
    const response=await fetch('/api/workspace/backup',{headers:{'X-Session-Id':sid}});
    if(!response.ok)throw await failure(response);
    const archive:Archive=await response.json();await writeArchive(archive);
    notifyRecovery({kind:'saved',message:'数据、执行记录和模型已备份到本浏览器'});
  }catch(e){
    notifyRecovery({kind:'warning',message:`服务端操作已完成，但本浏览器备份未更新：${e instanceof Error?e.message:'保存失败'}。请导出记录。`});
  }
}
async function restore(sid:string){
  let pending=restorations.get(sid);
  if(!pending){
    pending=(async()=>{
      let archive:Archive|undefined;
      try{archive=await readArchive(sid);}catch{/* Leave the original workspace selected. */}
      if(!archive){
        const message='服务端原工作区已失效，本浏览器没有可恢复备份。更新前丢失的记录无法自动找回；可以明确选择创建新工作区。';
        notifyRecovery({kind:'missing',message});throw new ApiError(message,401,'workspace_expired');
      }
      const response=await fetch('/api/workspace/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(archive)});
      if(!response.ok)throw await failure(response);
      notifyRecovery({kind:'restored',message:'已从本浏览器恢复经营数据、执行记录和模型'});
    })().finally(()=>{restorations.delete(sid);});
    restorations.set(sid,pending);
  }
  await pending;
}
async function request(path:string,options:RequestInit={},retry=true):Promise<Response>{
  const sid=await session(),headers=new Headers(options.headers);headers.set('X-Session-Id',sid);
  if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');
  const response=await fetch(`/api${path}`,{...options,headers});
  if(!response.ok){
    const error=await failure(response);
    if(response.status===401&&error.code==='workspace_expired'&&retry){await restore(sid);return request(path,options,false);}
    throw error;
  }
  return response;
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  const response=await request(path,options),data:T=await response.json();
  // A failed backup must never turn a successful execution into a failed action.
  if(path==='/dashboard'||((options.method||'GET')!=='GET'&&path!=='/session'))await preserve(await session());
  return data;
}
export function post<T>(path:string,body:unknown={}){return api<T>(path,{method:'POST',body:JSON.stringify(body)});}
export async function startNewWorkspace(){
  const response=await fetch('/api/session',{method:'POST'});if(!response.ok)throw await failure(response);
  const data=await response.json();localStorage.setItem(KEY,data.session_id);
  await preserve(data.session_id);return data;
}
export async function downloadHistory(){
  const response=await request('/export/history.json');
  const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');
  a.href=url;a.download='营销决策历史.json';a.click();URL.revokeObjectURL(url);
}
export async function downloadRecovery(){
  const sid=await session();await preserve(sid);const archive=await readArchive(sid);
  if(!archive)throw new Error('本浏览器没有完整恢复备份');
  const url=URL.createObjectURL(new Blob([JSON.stringify(archive)],{type:'application/json'})),a=document.createElement('a');
  a.href=url;a.download='深谋远虑工作区恢复备份.json';a.click();URL.revokeObjectURL(url);
}
export async function importRecovery(file:File){
  if(file.size>2*1024*1024)throw new Error('恢复备份最大 2 MB');
  const archive:Archive=JSON.parse(await file.text());
  const response=await fetch('/api/workspace/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(archive)});
  if(!response.ok)throw await failure(response);
  const data=await response.json();localStorage.setItem(KEY,data.session_id);await preserve(data.session_id);
}
