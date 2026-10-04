'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, ChevronDown, Database, History, LayoutDashboard, LoaderCircle, Plus, RefreshCw, Settings2, Smartphone, X, Menu, FileText } from 'lucide-react';
import { api, post, downloadHistory } from '@/lib/api';
import type { AccessInfo, CompanyProfile, Dashboard, Dataset, Decision, Lab, LibraryComponent, Num, PageId, RewardCatalog } from '@/lib/types';
import { DataCenter, DecisionDetail, ExperimentView, FeedbackForm, HistoryView, Laboratory, LibraryView } from './platform';

type Drawer = 'data' | 'company' | 'model' | 'history' | 'share' | null;
const SCENARIOS = [
  {name:'坚果大促与库存',profile:'inventory_clearance',question:'坚果大促前，库存较多，竞品正在降价。如何在毛利底线内调整渠道投入和促销？'},
  {name:'渠道投入与获客',profile:'acquisition_efficiency',question:'电商场景中，抖音获客成本上升，流量下降。如何在每日预算内调整渠道投入？'},
  {name:'老客与经营利润',profile:'profit_maximization',question:'老客回流较好，但促销成本偏高。怎样兼顾客户留存与营销贡献利润？'},
];
const STATUS:Record<string,string>={draft:'等待执行确认',executed:'等待经营结果',awaiting_next:'等待下一动作',updated:'已完成学习',terminal:'周期已结束',cancelled:'已取消'};
const REWARDS:Record<string,string>={profit_margin:'贡献利润率',roi:'营销 ROI',conversion_rate:'转化率',repeat_purchase_rate:'回流客户占比',inventory_turnover:'库存周转',gmv_growth:'收入增长',new_customer_ratio:'新客占比',cac:'获客成本',return_rate:'退货率',promotion_cost_ratio:'促销成本',inventory_pressure:'库存压力',volatility:'收入波动'};
function number(v:Num|undefined,digits=2){return v==null||!Number.isFinite(v)?'—':v.toLocaleString('zh-CN',{maximumFractionDigits:digits});}
function yuan(v:Num|undefined){return v==null?'—':`¥${number(v,0)}`;}
function date(v:string){return new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});}
function legacyDrawer(page:PageId):Drawer{return page==='data'?'data':page==='history'?'history':['lab','library','experiments'].includes(page)?'model':null;}

export default function Workspace({initialPage='dashboard'}:{initialPage?:PageId}){
  const [dashboard,setDashboard]=useState<Dashboard|null>(null),[company,setCompany]=useState<CompanyProfile|null>(null),[access,setAccess]=useState<AccessInfo|null>(null);
  const [data,setData]=useState<Dataset|null>(null),[lab,setLab]=useState<Lab|null>(null),[library,setLibrary]=useState<LibraryComponent[]>([]),[history,setHistory]=useState<Decision[]>([]);
  const [record,setRecord]=useState<Decision|null>(null),[drawer,setDrawer]=useState<Drawer>(legacyDrawer(initialPage)),[modelTab,setModelTab]=useState('decision');
  const [rewardCatalog,setRewardCatalog]=useState<RewardCatalog|null>(null);
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[toast,setToast]=useState(''),[menu,setMenu]=useState(false);
  const [question,setQuestion]=useState(SCENARIOS[0].question),[profile,setProfile]=useState(SCENARIOS[0].profile),[scenario,setScenario]=useState(SCENARIOS[0].name);
  const [budget,setBudget]=useState(18000),[floor,setFloor]=useState(20),[margin,setMargin]=useState(.15),[promo,setPromo]=useState(false),[stopped,setStopped]=useState<string[]>([]),[custom,setCustom]=useState(false),[weights,setWeights]=useState<Record<string,number>>({});
  const composer=useRef<HTMLTextAreaElement>(null),drawerBody=useRef<HTMLElement>(null),opener=useRef<HTMLElement|null>(null);
  const refresh=useCallback(async()=>{const [d,h]=await Promise.all([api<Dashboard>('/dashboard'),api<Decision[]>('/decisions')]);setDashboard(d);setHistory(h);if(d.active_decision)setRecord(d.active_decision);return d;},[]);
  const run=useCallback(async(label:string,fn:()=>Promise<void>)=>{setBusy(label);setError('');try{await fn();}catch(e){setError(e instanceof Error?e.message:'操作失败');}finally{setBusy('');}},[]);
  useEffect(()=>{run('读取数据库',async()=>{await refresh();const [c,a]=await Promise.all([api<CompanyProfile>('/company'),api<AccessInfo>('/access')]);setCompany(c);setAccess(a);});},[run,refresh]);
  useEffect(()=>{if(dashboard)setWeights(dashboard.profiles.find(p=>p.name===profile)?.weights||{});},[profile,dashboard]);
  useEffect(()=>{if(!toast)return;const id=setTimeout(()=>setToast(''),5000);return()=>clearTimeout(id);},[toast]);
  useEffect(()=>{
    if(!drawer||!dashboard)return;let cancelled=false;
    const read=async()=>{try{
      if(drawer==='data'){const d=await api<Dataset>('/data');if(!cancelled)setData(d);}
      if(drawer==='model'&&modelTab==='reward'){const r=await api<RewardCatalog>('/reward');if(!cancelled)setRewardCatalog(r);}
      if(drawer==='model'&&!['decision','reward'].includes(modelTab)){const l=await api<Lab>('/lab');if(!cancelled)setLab(l);if(modelTab==='components'){const v=await api<LibraryComponent[]>('/library');if(!cancelled)setLibrary(v);}}
    }catch(e){if(!cancelled)setError(e instanceof Error?e.message:'读取失败');}};
    read();return()=>{cancelled=true;};
  },[drawer,modelTab,dashboard]);
  useEffect(()=>{
    if(!drawer)return;opener.current=document.activeElement as HTMLElement;
    const old=document.body.style.overflow;document.body.style.overflow='hidden';drawerBody.current?.focus();
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setDrawer(null);if(e.key==='Tab'){
      const els=Array.from(drawerBody.current?.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea,summary')||[]).filter(x=>x.getClientRects().length);
      if(!els.length)return;const first=els[0],last=els[els.length-1];
      if(e.shiftKey&&(document.activeElement===first||document.activeElement===drawerBody.current)){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }};window.addEventListener('keydown',key);return()=>{document.body.style.overflow=old;window.removeEventListener('keydown',key);opener.current?.focus();};
  },[drawer]);
  const open=(d:Drawer)=>{setDrawer(d);setMenu(false);setError('');};
  const newDecision=()=>{if(dashboard?.active_decision){setRecord(dashboard.active_decision);setToast('先完成正在进行的决策，再新建问题');}else{setRecord(null);composer.current?.focus();}setDrawer(null);setMenu(false);};
  const chooseScenario=(s:typeof SCENARIOS[number])=>{setScenario(s.name);setQuestion(s.question);setProfile(s.profile);newDecision();};
  const submit=(e:React.FormEvent)=>{e.preventDefault();run('计算营销建议',async()=>{const d=await post<Decision>('/decisions',{question,reward_profile:profile,weights:custom?weights:null,constraints:{max_daily_budget:budget,min_price:floor,min_gross_margin:margin,prohibited_promotions:promo,stopped_channels:stopped}});setRecord(d);await refresh();});};
  const onExecute=(d:Decision,body:unknown)=>run('保存执行动作',async()=>{const x=await post<Decision>(`/decisions/${d.id}/execute`,body);setRecord(x);await refresh();setToast(x.previous_update?'下一实际动作已确认，上一轮模型已更新':'执行动作已保存，请记录经营结果');});
  const onFeedback=(d:Decision,body:unknown)=>run('保存结果',async()=>{const x=await post<{decision:Decision;next_decision:Decision|null}>(`/decisions/${d.id}/feedback`,body);setRecord(x.next_decision||x.decision);await refresh();setToast(x.next_decision?'结果已保存；确认下一实际动作后完成学习':'本轮已结束，模型和记录已保存');});
  const cancel=(d:Decision)=>run('取消草稿',async()=>{await post(`/decisions/${d.id}/cancel`);setRecord(null);await refresh();});
  const end=(d:Decision)=>run('结束周期',async()=>{if(!d.parent_decision)return;const previous=await post<Decision>(`/decisions/${d.parent_decision}/finish`);setRecord(previous);await refresh();setToast('周期已结束，没有虚构下一执行动作');});
  const newSession=()=>run('创建新演示会话',async()=>{const x=await post<{session_id:string}>('/session');localStorage.setItem('shenmou-session-v1',x.session_id);setRecord(null);setData(null);setLab(null);await refresh();setToast('新会话已创建，原会话记录保留');});
  const drawerTitle=drawer==='data'?'运营数据库':drawer==='company'?'企业资料':drawer==='model'?'模型与验证':drawer==='history'?'决策记录':'手机访问';
  const active=dashboard?.active_decision;
  return <div className="desk">
    <aside className={`desk-sidebar ${menu?'is-open':''}`}>
      <a href="/" className="desk-brand" onClick={e=>{e.preventDefault();newDecision();}}><span className="desk-logo-mark" aria-hidden="true"><svg viewBox="40 410 410 430"><image href="/brand-logo.png" width="1254" height="1254"/></svg></span><div><strong>深谋远虑</strong><span>营销决策工作台</span></div></a>
      <nav className="desk-nav" aria-label="工作区导航">
        <button className={!drawer?'selected':''} onClick={()=>{setDrawer(null);setMenu(false);}}><LayoutDashboard size={17}/>营销工作台</button>
        <button className={drawer==='data'?'selected':''} onClick={()=>open('data')}><Database size={17}/>运营数据库</button>
        <button className={drawer==='history'?'selected':''} onClick={()=>open('history')}><History size={17}/>决策记录<span>{history.length}</span></button>
        <button className={drawer==='company'?'selected':''} onClick={()=>open('company')}><FileText size={17}/>企业资料</button>
        <button className={drawer==='model'?'selected':''} onClick={()=>{setModelTab('reward');open('model');}}><Settings2 size={17}/>模型与因子</button>
      </nav>
      <div className="desk-section-label history-label">最近决策</div>
      <div className="desk-history">{history.length?history.slice(0,4).map(d=><button key={d.id} className={record?.id===d.id?'selected':''} onClick={()=>{setRecord(d);setDrawer(null);setMenu(false);}}><span>{d.action_label}</span><small>{date(d.timestamp)} · {STATUS[d.status]}</small></button>):<p>暂无记录</p>}</div>
      <div className="desk-sidebar-bottom"><button onClick={()=>open('share')}><Smartphone size={16}/>分享站点<ArrowUpRight size={14}/></button><div className="desk-local-status"><i className={dashboard?'connected':''}/>{dashboard?'服务已连接':'正在连接'}</div></div>
    </aside>
    {menu&&<button className="desk-mobile-backdrop" aria-label="收起导航" onClick={()=>setMenu(false)}/>}
    <div className="desk-main"><header className="desk-header"><div><button className="desk-mobile-menu" aria-label="打开导航" onClick={()=>setMenu(!menu)}><Menu size={20}/></button><span className="desk-crumb">深谋远虑</span><span className="desk-crumb-divider">/</span><span>营销工作台</span></div><div className="desk-header-actions"><button onClick={()=>open('share')}><Smartphone size={15}/><span>手机访问</span></button></div></header>
      <main className="desk-content">
        {error&&<div className="error-banner" role="alert"><span>{error}</span><button aria-label="关闭错误" onClick={()=>setError('')}><X size={15}/></button></div>}
        {toast&&<div className="desk-toast" role="status"><Check size={15}/>{toast}</div>}
        {!dashboard?<div className="desk-loading"><LoaderCircle className="spinning" size={22}/><p>{error?'暂时无法读取，请检查服务。':'正在读取数据和嵌入模型…'}</p><button onClick={()=>run('重新读取',async()=>{await refresh();})}>重新读取</button></div>:<>
          <div className="desk-page-heading"><div><h1>营销工作台</h1><p>{dashboard.quality.source==='demo'?'合成演示数据':'用户上传数据'} · {dashboard.quality.days} 天 · {dashboard.quality.rows} 行</p></div><button className="button subtle" onClick={newDecision}><Plus size={15}/>新建决策</button></div>
          <div className="desk-metrics">{[['营销 ROI',number(dashboard.metrics.roi)],['广告获客成本',yuan(dashboard.metrics.cac)],['分仓库存',`${number(dashboard.metrics.inventory_level,0)} 件`],['营销贡献利润',yuan(dashboard.metrics.profit)]].map(([label,v])=><div key={label}><span>{label}</span><strong className={v.includes("-")?"is-negative":undefined}>{v}</strong></div>)}</div>
          <div className={`desk-workbench ${record?'has-record':''}`}><section className="desk-channel-section"><div className="desk-block-heading"><h2>渠道经营</h2><button onClick={()=>open('data')}>导入 / 查看明细<ArrowUpRight size={13}/></button></div><p className="desk-observation-date">当前观察日 · {dashboard.metrics.date}</p><div className="desk-channel-scroll"><table className="desk-channel-table"><thead><tr><th>渠道</th><th>收入 / 元</th><th>广告费 / 元</th><th>ROI</th><th>CAC / 元</th><th>库存 / 件</th></tr></thead><tbody>{dashboard.metrics.channels.length?dashboard.metrics.channels.map(ch=><tr key={ch.channel}><td>{ch.channel}</td><td>{number(ch.revenue,0)}</td><td>{number(ch.advertising_cost,0)}</td><td>{number(ch.roi)}</td><td>{number(ch.cac)}</td><td>{number(ch.inventory,0)}</td></tr>):<tr><td colSpan={6} className="desk-empty-row">本轮反馈为汇总数据，未提供渠道明细。</td></tr>}</tbody></table></div><RevenueStrip dashboard={dashboard}/><p className="desk-data-note">{dashboard.quality.source==='demo'?'日级示例为合成数据，非企业内部业绩。':'日级数据由上传方提供。'}<br/>利润口径：营销贡献利润。</p></section>
          <section className="desk-decision-section"><div className="desk-block-heading"><h2>{record?'决策与执行':'制定决策'}</h2><button onClick={()=>{setModelTab('reward');open('model');}}>收益与惩罚因子<ArrowUpRight size={13}/></button></div>
          {!active&&!record&&<form className="desk-composer" onSubmit={submit}>
            <label className="field-label">经营场景<select aria-label="经营场景" value={scenario} onChange={e=>{const s=SCENARIOS.find(x=>x.name===e.target.value);if(s)chooseScenario(s);}}>{SCENARIOS.map(s=><option key={s.name} value={s.name}>{s.name}</option>)}</select></label>
            <label className="field-label" htmlFor="business-question">经营问题<textarea ref={composer} id="business-question" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={1600} rows={3} required placeholder="填写这次需要解决的经营问题"/></label>
            <div className="desk-composer-options"><label>经营目标<select aria-label="经营目标" value={profile} onChange={e=>setProfile(e.target.value)}>{dashboard.profiles.map(p=><option key={p.name} value={p.name}>{p.label}</option>)}</select></label><label>每日预算<input aria-label="每日预算" type="number" min={0} max={1000000} value={budget} onChange={e=>setBudget(Number(e.target.value))}/><span>元</span></label></div>
            <details className="desk-constraints"><summary><Settings2 size={14}/>业务约束与目标权重<ChevronDown size={13}/></summary><div className="form-row"><label className="field-label">成交价底线 / 元<input aria-label="成交价底线" type="number" min={1} value={floor} onChange={e=>setFloor(Number(e.target.value))}/></label><label className="field-label">毛利底线 / 小数<input aria-label="毛利底线" type="number" min={0} max={.9} step={.01} value={margin} onChange={e=>setMargin(Number(e.target.value))}/></label></div><label className="check-field"><input type="checkbox" checked={promo} onChange={e=>setPromo(e.target.checked)}/>禁止新增促销</label><div className="checks-inline">{['抖音','小红书','淘宝','搜索广告','私域'].map(ch=><label className="check-field" key={ch}><input type="checkbox" checked={stopped.includes(ch)} onChange={e=>setStopped(e.target.checked?[...stopped,ch]:stopped.filter(x=>x!==ch))}/>停用{ch}</label>)}</div><label className="check-field"><input type="checkbox" checked={custom} onChange={e=>setCustom(e.target.checked)}/>自定义奖励权重</label>{custom&&<div className="weights-grid">{Object.entries(weights).map(([k,v])=><label key={k}>{REWARDS[k]}<input type="number" min={0} step={.01} value={v} onChange={e=>setWeights({...weights,[k]:Number(e.target.value)})}/></label>)}</div>}</details>
            <div className="desk-composer-footer"><button type="submit" aria-label="生成营销建议" disabled={!!busy||question.trim().length<2}>{busy?<LoaderCircle className="spinning" size={16}/>:<ArrowRight size={16}/>}{busy?'正在计算建议…':'生成营销建议'}</button></div>
          </form>}
          {record&&<EmbeddedDecision decision={record} active={active?.id===record.id} busy={busy} onExecute={onExecute} onFeedback={onFeedback} onCancel={cancel} onEnd={end} onInspect={()=>{setModelTab('decision');open('model');}}/>}
          {!active&&record&&<button className="desk-next" onClick={newDecision}><Plus size={15}/>新建下一次决策</button>}
          </section></div>
          <div className="desk-footnote"><span>{dashboard.quality.latest_result_source||'数据 → 建议 → 执行确认 → 经营反馈'}</span><button onClick={()=>{setModelTab('decision');open('model');}}>Deep SARSA · {dashboard.model_version}<ArrowUpRight size={12}/></button></div>
        </>}
      </main>
    </div>
    {drawer&&<div className="desk-drawer-layer"><button className="desk-drawer-backdrop" aria-label="关闭侧栏" onClick={()=>setDrawer(null)}/><aside ref={drawerBody} tabIndex={-1} className={`desk-drawer ${drawer==='share'?'share-drawer':''}`} role="dialog" aria-modal="true" aria-labelledby="drawer-title"><header><div><span>工作区</span><h2 id="drawer-title">{drawerTitle}</h2></div><button aria-label="关闭侧栏" onClick={()=>setDrawer(null)}><X size={19}/></button></header><div className="desk-drawer-body">
      {error&&<div className="error-banner" role="alert">{error}</div>}
      {drawer==='data'&&(data?<DataCenter data={data} busy={busy} run={run} refresh={refresh} onNewSession={newSession}/>:<p className="drawer-loading">正在读取运营明细…</p>)}
      {drawer==='company'&&company&&<CompanyView company={company}/>}
      {drawer==='history'&&<HistoryView history={history} busy={busy} onExport={()=>run('导出记录',downloadHistory)} onContinue={d=>{setRecord(d);setDrawer(null);}}/>}
      {drawer==='model'&&<><div className="desk-drawer-tabs">{[['reward','收益与惩罚'],['decision','决策依据'],['training','训练记录'],['experiments','对照结果'],['components','组件']].map(([k,v])=><button key={k} className={modelTab===k?'active':''} onClick={()=>setModelTab(k)}>{v}</button>)}</div>
        {modelTab==='reward'&&(rewardCatalog&&dashboard?<RewardGuide catalog={rewardCatalog} profile={record?.reward_profile||profile} weights={record?Object.fromEntries(rewardCatalog.factors.map((f,i)=>[f.name,record.reward_weights[i]])):weights} custom={!!record||custom}/>:<p className="drawer-loading">正在读取奖励定义…</p>)}
        {modelTab==='decision'&&(record?<DecisionDetail decision={record} busy={busy}/>:<div className="model-summary"><h3>模型已经嵌入工作台</h3><p>输入经营问题后，工作台直接调用状态构建、约束检查和 Deep SARSA，生成一个可执行动作。公开资料用于补充业务背景。</p><dl><dt>当前版本</dt><dd>{dashboard?.model_version}</dd><dt>输入 / 动作</dt><dd>72 维状态 / 18 个可控动作</dd><dt>语义理解</dt><dd>{dashboard?.llm.available?'LLM 已配置，实际调用来源保存在记录中':'未配置密钥，当前使用规则解析和模板解释'}</dd><dt>企业证据</dt><dd>字符 TF-IDF 检索；公开资料不覆盖日级指标</dd></dl><p>算法融合已有研究。这里的改进集中在企业资料、经营约束与实际反馈流程。</p><a href="https://arxiv.org/abs/2607.24779" target="_blank" rel="noreferrer">参考 HOBA 研究 <ArrowUpRight size={13}/></a></div>)}
        {modelTab==='training'&&(lab?<Laboratory lab={lab} busy={busy} run={run} onTrained={async()=>{setLab(await api<Lab>('/lab'));await refresh();}}/>:<p className="drawer-loading">正在读取训练记录…</p>)}
        {modelTab==='experiments'&&(lab?<ExperimentView experiments={lab.experiments}/>:<p className="drawer-loading">正在读取实验结果…</p>)}
        {modelTab==='components'&&<LibraryView items={library}/>}
      </>}
      {drawer==='share'&&<ShareView access={access} onRefresh={()=>run('检查共享地址',async()=>setAccess(await api<AccessInfo>('/access')))}/>}
    </div></aside></div>}
  </div>;
}

function RevenueStrip({dashboard:d}:{dashboard:Dashboard}){
  const rows=d.series.slice(-7),values=rows.map(r=>r.revenue),lo=Math.min(...values),hi=Math.max(...values);
  const points=values.map((v,i)=>`${12+i*276/Math.max(values.length-1,1)},${50-(v-lo)/Math.max(hi-lo,1)*36}`).join(' ');
  return <div className="desk-revenue-strip"><div><span>最近 {rows.length} 个观察日 · 收入</span><strong>{yuan(d.metrics.revenue)}</strong><small>{rows[0]?.date} — {rows.at(-1)?.date}</small></div><svg viewBox="0 0 300 64" role="img" aria-label="最近观察日收入趋势"><line x1="12" y1="51" x2="288" y2="51" stroke="var(--line)"/><polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/>{values.length===1&&<circle cx="12" cy="50" r="2" fill="var(--accent)"/>}</svg></div>;
}

function RewardGuide({catalog:c,profile,weights,custom}:{catalog:RewardCatalog;profile:string;weights:Record<string,number>;custom:boolean}){
  const [selected,setSelected]=useState(profile);
  useEffect(()=>setSelected(profile),[profile]);
  const goal=c.profiles.find(p=>p.name===selected)||c.profiles[0];
  const source=custom&&selected===profile?weights:goal.weights;
  const total=Object.values(source).reduce((a,b)=>a+b,0);
  return <section className="reward-guide"><div className="reward-guide-heading"><div><h3>收益与惩罚因子</h3><p>七项收益加分，五项成本与风险扣分。</p></div><span>{c.version}</span></div><div className="reward-goal"><label className="field-label">查看目标权重<select aria-label="查看目标权重" value={selected} onChange={e=>setSelected(e.target.value)}>{c.profiles.map(p=><option key={p.name} value={p.name}>{p.label}</option>)}</select></label><p>只查看权重，不改变已生成的决策。{custom&&selected===profile?'下表使用当前设置或决策快照中的权重。':''}</p></div>
    <div className="reward-formula"><strong>{c.formula}</strong><code>{c.normalization}</code><p>{c.weight_rule}</p></div>
    {[1,-1].map(sign=><div key={sign} className="reward-group"><h4>{sign===1?'收益因子 · 越高加分越多':'惩罚因子 · 越高扣分越多'}</h4><div className="table-scroll"><table><thead><tr><th>因子 / 计算口径</th><th>标准化范围</th><th>权重</th></tr></thead><tbody>{c.factors.filter(f=>f.sign===sign).map(f=><tr key={f.name}><td><strong>{f.label}</strong><span className="reward-calculation">{f.formula}</span><small>{f.note}</small></td><td>{number(f.lower,3)} ～ {number(f.upper,3)}</td><td>{number((source[f.name]||0)/Math.max(total,1e-12)*100,1)}%</td></tr>)}</tbody></table></div></div>)}
    <p className="reward-boundary">{c.boundary}</p><details className="reward-extra"><summary>外部扰动与奖励因子的区别</summary><p>季节性、节日强度、竞品压力、平台流量变化和市场需求进入状态，帮助 SARSA 选择动作；它们没有直接作为扣分项。停用渠道、预算、价格与毛利底线通过动作约束限制执行。</p></details>
    <p className="fine-print">单项贡献 = 归一化权重 × 标准化值 × 正负号。每轮实际贡献、缺失项和覆盖率可在“决策依据”中追踪；缺失不能解释为经营表现良好。</p>
  </section>;
}

function EmbeddedDecision({decision:d,active,busy,onExecute,onFeedback,onCancel,onEnd,onInspect}:{decision:Decision;active:boolean;busy:string;onExecute:(d:Decision,b:unknown)=>void;onFeedback:(d:Decision,b:unknown)=>void;onCancel:(d:Decision)=>void;onEnd:(d:Decision)=>void;onInspect:()=>void}){
  const [chosen,setChosen]=useState(d.action_name),[reason,setReason]=useState('');
  const [forecast,setForecast]=useState(''),[category,setCategory]=useState('business_evidence'),[supporting,setSupporting]=useState(false),[anchor,setAnchor]=useState(''),[conflict,setConflict]=useState(false);
  useEffect(()=>{setChosen(d.action_name);setReason('');setForecast('');setCategory('business_evidence');setSupporting(false);setAnchor('');setConflict(false);},[d.id,d.action_name]);
  return <article className="desk-decision"><div className="desk-decision-title"><span className="desk-result-icon">松</span><div><span>建议动作</span><h2>{d.action_label}</h2></div><span className="desk-record-status">{STATUS[d.status]}</span></div><p className="desk-explanation">{d.explanation.summary}</p><div className="desk-reasons">{d.explanation.reasons.slice(0,3).map((x,i)=><p key={i}>{x}</p>)}</div>
    <div className="desk-result-meta"><span>动作由 Deep SARSA 选择</span><span>解释：{d.explanation_source==='LLM'?'LLM':'模板'}</span><button onClick={onInspect}>查看模型依据<ArrowUpRight size={13}/></button></div>
    {!!d.company_evidence?.length&&<details className="desk-evidence"><summary>本次检索的企业资料 · {d.company_evidence.length} 条<ChevronDown size={13}/></summary><p>仅作业务背景；模型的当前状态来自运营数据和明确标注的语义信号。</p>{d.company_evidence.map(e=><div key={e.id}><strong>{e.period} · {e.metric}</strong><p>{e.note}</p><a href={e.source_url} target="_blank" rel="noreferrer">{e.source_title}{e.page?` · 第 ${e.page} 页`:''}<ArrowUpRight size={12}/></a></div>)}</details>}
    {active&&d.status==='draft'&&<div className="desk-execution"><h3>{d.parent_decision?'确认下一实际动作':'记录实际执行'}</h3>{d.parent_decision&&<p>上一轮结果已保存，确认这一步后才完成 SARSA 更新。</p>}<label className="field-label" htmlFor="actual-action">实际动作<select id="actual-action" aria-label="实际动作" value={chosen} onChange={e=>setChosen(e.target.value)}>{d.q_values.filter(q=>q.legal).map(q=><option key={q.name} value={q.name}>{q.label}</option>)}</select></label>{chosen!==d.action_name&&<label className="field-label" htmlFor="override-reason">调整理由<input id="override-reason" aria-label="调整理由" value={reason} maxLength={300} onChange={e=>setReason(e.target.value)} placeholder="请记录人工调整的依据"/></label>}<details className="settings-details execution-evidence"><summary>执行依据（可选）<ChevronDown size={13}/></summary><div className="form-row"><label className="field-label">本期收入预测 / 元<input aria-label="本期收入预测" type="number" min={0} value={forecast} onChange={e=>setForecast(e.target.value)} placeholder="留空表示未做预测"/></label><label className="field-label">执行依据<select aria-label="执行依据" value={category} onChange={e=>setCategory(e.target.value)}><option value="business_evidence">当前经营数据与模型</option><option value="competitor_follow">跟随竞品动作</option><option value="historical_anchor">参照历史价格或预算</option></select></label></div>{category==='competitor_follow'&&<label className="check-field"><input type="checkbox" checked={supporting} onChange={e=>setSupporting(e.target.checked)}/>已有支持本次投入的对照实验</label>}{category==='historical_anchor'&&<><label className="field-label">历史参照 / 元<input aria-label="历史参照" type="number" min={0} value={anchor} onChange={e=>setAnchor(e.target.value)}/></label><label className="check-field"><input type="checkbox" checked={conflict} onChange={e=>setConflict(e.target.checked)}/>当前证据与该历史参照存在冲突</label></>}<p className="fine-print">这些记录用于后续风险分析；没有记录时不推断心理原因。</p></details><div className="desk-execution-buttons"><button className="button primary" disabled={!!busy||(chosen!==d.action_name&&!reason.trim())} onClick={()=>onExecute(d,{action_name:chosen,reason:reason||null,forecast_revenue:forecast?Number(forecast):null,reason_category:category,supporting_experiment:supporting,anchor_value:anchor?Number(anchor):null,current_evidence_conflict:conflict})}><Check size={15}/>确认实际执行</button>{!d.parent_decision?<button className="button subtle" disabled={!!busy} onClick={()=>onCancel(d)}>取消草稿</button>:<button className="button subtle" disabled={!!busy} onClick={()=>onEnd(d)}>结束周期，不执行下一建议</button>}</div></div>}
    {active&&d.status==='executed'&&<FeedbackForm decision={d} busy={busy} onFeedback={onFeedback}/>}
    {(d.previous_update||d.transition?.update)&&<div className="desk-learning"><Check size={15}/><span>模型已完成第 {(d.previous_update||d.transition?.update)?.updates} 次更新，记录已保存。</span><button onClick={onInspect}>查看凭证</button></div>}
    {d.actual_reward&&<div className="desk-saved-result"><span>综合回报 {number(d.actual_reward.total,5)}</span><span>{d.user_feedback?.provenance.label}</span></div>}
  </article>;
}

function CompanyView({company:c}:{company:CompanyProfile}){
  const [tab,setTab]=useState('financial');const rows=c.records.filter(r=>tab==='financial'?r.value!=null:r.value==null);
  return <div className="company-view"><div className="company-heading"><span className="desk-monogram">松</span><div><h3>{c.company}</h3><p>{c.stock_code} · 来源核验 {c.verified_on}</p></div></div><p className="company-boundary">{c.boundary}</p><div className="desk-drawer-tabs"><button className={tab==='financial'?'active':''} onClick={()=>setTab('financial')}>公开财务数据</button><button className={tab==='financial'?'':'active'} onClick={()=>setTab('business')}>经营与 AI 应用</button></div><div className="table-scroll"><table><thead><tr><th>报告期 / 指标</th><th>本期</th><th>上年同期</th><th>来源</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td><strong>{r.metric}</strong><small>{r.period} · {r.kind}</small></td><td>{r.value==null?'已披露':`${number(r.value/1e8)} 亿元`}</td><td>{r.previous==null?'—':`${number(r.previous/1e8)} 亿元`}</td><td><a href={r.source_url} target="_blank" rel="noreferrer">{r.source_title}{r.page?` · p.${r.page}`:''}<ArrowUpRight size={12}/></a></td></tr>)}</tbody></table></div><div className="company-notes">{rows.map(r=><div key={r.id}><strong>{r.period} · {r.metric}</strong><p>{r.note}</p></div>)}</div><p className="fine-print">资料写入独立企业证据表。公开汇总数据与日运营示例分别保存，模型不会把年报金额当作日级订单数据。</p></div>;
}

function ShareView({access:a,onRefresh}:{access:AccessInfo|null;onRefresh:()=>void}){
  return <div className="share-view"><div className="share-kind"><Smartphone size={20}/><span>{a?.mode==='public'?'公网访问':a?.mode==='lan'?'同一 Wi-Fi 访问':'当前仅本机访问'}</span></div>{a?.share_url?<><img src="/api/share/qr.png" width={240} height={240} alt="手机访问二维码"/><a className="share-url" href={a.share_url} target="_blank" rel="noreferrer">{a.share_url}</a></>:<p>先使用项目里的“手机共享启动.cmd”开启局域网服务，或完成 Render 公网发布。</p>}<p>{a?.mode==='public'?'扫码或把网址发给朋友，手机和电脑都可以访问。':a?.description}</p>{a?.mode==='lan'&&<ol><li>手机和电脑连接同一个 Wi-Fi。</li><li>扫码或在手机浏览器输入上面的地址。</li><li>电脑保持开机，服务保持运行。</li></ol>}<button className="button subtle" onClick={onRefresh}><RefreshCw size={14}/>重新检查地址</button></div>;
}
