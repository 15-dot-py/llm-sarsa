'use client';
import {useEffect,useState} from 'react';
import {Phone,ArrowRight} from 'lucide-react';

interface Status {login_required:boolean;sms_ready:boolean;privacy_version:string;message:string;}
async function call(path:string,body?:unknown,method='POST') {
  const response=await fetch('/api/auth'+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'请求失败，请检查输入');
  return value;
}
export function PhoneLogin({status}:{status:Status}) {
  const [phone,setPhone]=useState(''),[code,setCode]=useState(''),[accepted,setAccepted]=useState(false);
  const [challenge,setChallenge]=useState(''),[sentPhone,setSentPhone]=useState(''),[deadline,setDeadline]=useState(0),[remaining,setRemaining]=useState(0);
  const [busy,setBusy]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState('');
  useEffect(()=>{const refresh=()=>setRemaining(Math.max(0,Math.ceil((deadline-Date.now())/1000)));refresh();const timer=setInterval(refresh,1000);return()=>clearInterval(timer);},[deadline]);
  async function send(){
    setBusy('send');setError('');setMessage('');
    try{const d=await call('/sms/request',{phone,privacy_accepted:accepted,privacy_version:status.privacy_version});setChallenge(d.challenge_id);setSentPhone(phone);setDeadline(Date.now()+d.retry_after*1000);setMessage(d.message);}
    catch(e){setError(e instanceof Error?e.message:'验证码请求失败');}finally{setBusy('');}
  }
  async function login(e:React.FormEvent){
    e.preventDefault();setBusy('login');setError('');
    try{const d=await call('/sms/verify',{phone,code,challenge_id:challenge,privacy_accepted:accepted,privacy_version:status.privacy_version});localStorage.setItem('shenmou-session-v1',d.session_id);window.location.assign('/');}
    catch(e){setError(e instanceof Error?e.message:'登录失败');}finally{setBusy('');}
  }
  return <main className="phone-page"><section className="phone-content"><a className="phone-brand" href="/">深谋远虑</a><div className="phone-mark"><Phone size={28}/></div><h1>登录营销工作台</h1><p className="phone-description">使用手机号验证身份，保存自己的数据和决策记录。</p>
    <form onSubmit={login}><label htmlFor="login-phone">手机号</label><input id="login-phone" type="tel" inputMode="numeric" autoComplete="tel-national" maxLength={11} value={phone} onChange={e=>{setPhone(e.target.value.replace(/\D/g,''));setCode('');setChallenge('');}} placeholder="输入中国大陆手机号"/>
    <label htmlFor="login-code">短信验证码</label><div className="phone-code"><input id="login-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))} placeholder="6 位验证码"/><button type="button" onClick={send} disabled={!status.sms_ready||!!busy||!!remaining||!accepted||!/^1[3-9]\d{9}$/.test(phone)}>{remaining?`${remaining} 秒后重试`:busy==='send'?'正在发送':'获取验证码'}</button></div>
    <label className="phone-consent"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/><span>我已阅读并同意<a href="/privacy/" target="_blank" rel="noreferrer">隐私说明</a></span></label>
    {!status.sms_ready&&<p className="phone-notice">{status.message}</p>}{message&&<p className="phone-notice" role="status">{message}</p>}{error&&<p className="phone-error" role="alert">{error}</p>}
    <button className="phone-submit" type="submit" disabled={!status.sms_ready||!!busy||!accepted||phone!==sentPhone||!challenge||!/^\d{6}$/.test(code)}>{busy==='login'?'正在登录':'登录'}<ArrowRight size={18}/></button></form>
    <p className="phone-footnote">验证码 5 分钟内有效。只用于登录验证。</p></section></main>;
}
export default function AuthGate({children,forceLogin=false}:{children?:React.ReactNode;forceLogin?:boolean}) {
  const [status,setStatus]=useState<Status|null>(null),[user,setUser]=useState<{phone_mask:string}|null>(null),[checked,setChecked]=useState(false),[error,setError]=useState('');
  useEffect(()=>{let live=true;(async()=>{try{
    const s=await call('/status',undefined,'GET');
    const r=await fetch('/api/auth/me');
    if(r.ok){const a=await r.json();if(live){localStorage.setItem('shenmou-session-v1',a.session_id);setUser(a.user);}}
    else if(r.status!==401)throw new Error('无法读取登录状态');
    if(live){setStatus(s);setChecked(true);}
  }catch(e){if(live)setError(e instanceof Error?e.message:'无法连接服务');}})();return()=>{live=false;};},[]);
  async function logout(){try{await call('/logout');localStorage.removeItem('shenmou-session-v1');window.location.reload();}catch(e){setError(e instanceof Error?e.message:'退出失败');}}
  if(error)return <main className="phone-page"><p role="alert">{error}</p><button onClick={()=>window.location.reload()}>重新连接</button></main>;
  if(!checked||!status)return <main className="phone-page"><p>正在连接工作台…</p></main>;
  if(forceLogin||status.login_required&&!user)return <PhoneLogin status={status}/>;
  return <>{user&&<div className="phone-account"><span>{user.phone_mask}</span><a href="/privacy/">隐私说明</a><button onClick={logout}>退出登录</button></div>}{children}</>;
}
