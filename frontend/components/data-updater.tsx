'use client';

import {useEffect,useRef,useState} from 'react';
import {Check,Download,Plus,Upload,X} from 'lucide-react';
import {api,post} from '@/lib/api';
import type {Dataset,DataPreview,Num} from '@/lib/types';

type Row=Record<string,string|number>;
const CHANNELS=['抖音','小红书','淘宝','搜索广告','私域'];
const FIELDS=[['revenue','销售收入 / 元'],['sales','销量 / 件'],['advertising_cost','广告费 / 元'],
  ['promotion_cost','额外促销费 / 元'],['impressions','曝光 / 次'],['clicks','点击 / 次'],['orders','订单 / 单'],
  ['new_customers','新客 / 人'],['returning_customers','回流客户 / 人'],['price','成交单价 / 元'],
  ['discount','折扣 / 小数'],['inventory','分仓库存 / 件'],['returns','退货 / 件']] as const;
const MONEY=(n:Num)=>n==null?'未提供':n.toLocaleString('zh-CN',{maximumFractionDigits:2});

export default function DataUpdater({data,editing,onEdit,run,busy,onSaved}:{data:Dataset;editing:Row|null;
  onEdit:(row:Row|null)=>void;run:(s:string,f:()=>Promise<void>)=>Promise<void>;busy:string;onSaved:()=>Promise<void>}){
  const [values,setValues]=useState<Record<string,string>>({}),[formOpen,setFormOpen]=useState(false);
  const editor=useRef<HTMLFormElement>(null);
  const [test,setTest]=useState(data.quality.source==='demo'),[note,setNote]=useState('更新运营观测');
  const [preview,setPreview]=useState<DataPreview|null>(null),[asFeedback,setAsFeedback]=useState(false),[terminal,setTerminal]=useState(false);
  useEffect(()=>{if(editing){setValues(Object.fromEntries(Object.entries(editing).map(([k,v])=>[k,String(v)])));
    if(editing.cost_method==='estimated')setValues(v=>({...v,cogs:'',return_loss:''}));
    setTest(['demo','demo_upload','simulation'].includes(String(editing.observation_source||data.quality.source)));
    setNote(`核对 ${editing.date} ${editing.channel} 记录`);setFormOpen(true);setPreview(null);
  }},[editing,data.quality.source]);
  useEffect(()=>{if(formOpen){editor.current?.scrollIntoView({block:'start'});editor.current?.querySelector('input')?.focus({preventScroll:true});}},[formOpen,editing]);
  const clearPreview=()=>{setPreview(null);setAsFeedback(false);setTerminal(false);};
  const readPreview=(p:DataPreview)=>{setPreview(p);setAsFeedback(false);setTerminal(false);};
  const upload=(file:File)=>{clearPreview();setFormOpen(false);onEdit(null);run('预览数据更新',async()=>{const body=new FormData();body.append('file',file);
    body.append('source',test?'demo_upload':'uploaded');body.append('note',note);
    readPreview(await api<DataPreview>('/data/preview-upload',{method:'POST',body}));});};
  const submit=(e:React.FormEvent)=>{e.preventDefault();clearPreview();run('校验观测记录',async()=>{
    const row:Row={date:values.date,channel:values.channel};
    for(const [key] of FIELDS)row[key]=Number(values[key]);
    for(const key of ['cogs','return_loss'])if(values[key]?.trim())row[key]=Number(values[key]);
    readPreview(await post<DataPreview>('/data/preview',{rows:[row],source:test?'demo_upload':'manual',note}));
  });};
  const apply=()=>{if(!preview)return;run('保存观测与数据版本',async()=>{
    await post('/data/apply',{preview_token:preview.preview_token,as_feedback:asFeedback,terminal});
    await onSaved();clearPreview();onEdit(null);setFormOpen(false);
  });};
  const updateValue=(key:string,value:string)=>{setValues(v=>({...v,[key]:value}));clearPreview();};
  const blocked=preview&&(preview.blocked||(preview.active_status==='executed'&&!asFeedback));
  return <section className="data-update" aria-labelledby="data-update-title">
    <div className="data-update-heading"><div><h3 id="data-update-title">更新运营观测</h3><p>按日期与渠道保存。新增记录追加，同一天同渠道修正；旧决策依据保留。</p></div>
      <span>数据版本 {data.quality.revision?`v${data.quality.revision}`:'待首次更新'}</span></div>
    <div className="data-update-tools"><button className="button subtle" disabled={!!busy} onClick={()=>{
      onEdit(null);setValues({date:new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'}),channel:'抖音'});
      setNote('新增渠道观测');clearPreview();setFormOpen(true);
    }}><Plus size={14}/>新增记录</button>
      <label className={`button subtle upload-button ${busy?'disabled':''}`}><Upload size={14}/>导入增量 CSV
        <input type="file" accept=".csv" aria-label="导入增量 CSV" disabled={!!busy} onChange={e=>{const file=e.target.files?.[0];if(file)upload(file);e.target.value='';}}/></label>
      <a className="button subtle" href="/api/data/template.csv" download><Download size={14}/>空白模板</a>
      <label className="check-field"><input type="checkbox" disabled={!!busy} checked={test} onChange={e=>{setTest(e.target.checked);clearPreview();}}/>合成 / 测试数据</label></div>
    <p className="fine-print">真实运营记录请取消“合成 / 测试数据”。首次导入真实数据会移出演示样例。只更新旧日期不会把它当成最新观察日。</p>
    {formOpen&&<form ref={editor} className="data-row-editor" onSubmit={submit}>
      <div className="data-editor-title"><strong>{editing?'修正已有记录':'新增渠道记录'}</strong><button type="button" aria-label="关闭记录编辑" onClick={()=>{setFormOpen(false);onEdit(null);clearPreview();}}><X size={15}/></button></div>
      <div className="data-editor-fields"><label className="field-label">观察日期<input aria-label="观察日期" type="date" required value={values.date||''} onChange={e=>updateValue('date',e.target.value)}/></label>
        <label className="field-label">渠道<select aria-label="记录渠道" value={values.channel||'抖音'} onChange={e=>updateValue('channel',e.target.value)}>{CHANNELS.map(ch=><option key={ch}>{ch}</option>)}</select></label>
        {FIELDS.map(([key,label])=><label className="field-label" key={key}>{label}<input aria-label={label} type="number" min={key==='price'?0.01:0} max={key==='discount'?.5:undefined} step="any" required value={values[key]||''} onChange={e=>updateValue(key,e.target.value)} placeholder="填写实测值"/></label>)}
        {(['cogs','return_loss'] as const).map(key=><label className="field-label" key={key}>{key==='cogs'?'商品成本 / 元（可选）':'退货损失 / 元（可选）'}<input aria-label={key==='cogs'?'商品成本':'退货损失'} type="number" min={0} step="any" value={values[key]||''} onChange={e=>updateValue(key,e.target.value)} placeholder="留空会显示成本估算提示"/></label>)}</div>
      <p className="fine-print">收入填折后金额；库存填渠道独立分仓。单条新增只代表一个渠道，建议完整上传当日各渠道数据后再决策。</p>
      <label className="field-label">更新说明<input value={note} maxLength={200} onChange={e=>{setNote(e.target.value);clearPreview();}}/></label>
      <button type="submit" className="button subtle" disabled={!!busy}>预览变化</button>
    </form>}
    {preview&&<div className="data-update-preview" role="region" aria-label="数据更新预览">
      <h4>保存前核对</h4><p>新增 {preview.changes.added_rows} 行 · 修正 {preview.changes.corrected_rows} 行 · 数值相同 {preview.changes.unchanged_rows} 行</p><p>本次涉及日期：{preview.changes.incoming_dates.join('、')} · {test?'合成/测试数据':'用户提供观测'}</p>
      <div className="table-scroll"><table><thead><tr><th>当前观测</th><th>保存前</th><th>保存后 · v{preview.after.quality.revision}</th></tr></thead><tbody>
        <tr><td>最新观察日</td><td>{preview.before.metrics.date}</td><td>{preview.after.metrics.date}</td></tr>
        <tr><td>销售收入 / 元</td><td>{MONEY(preview.before.metrics.revenue)}</td><td>{MONEY(preview.after.metrics.revenue)}</td></tr>
        <tr><td>营销贡献利润 / 元</td><td>{MONEY(preview.before.metrics.profit)}</td><td>{MONEY(preview.after.metrics.profit)}</td></tr>
        <tr><td>营销 ROI</td><td>{MONEY(preview.before.metrics.roi)}</td><td>{MONEY(preview.after.metrics.roi)}</td></tr>
      </tbody></table></div>
      <ul>{preview.warnings.map((warning,i)=><li key={i}>{warning}</li>)}</ul>
      {preview.blocked?<p className="data-update-warning">上一轮正在等待下一实际动作。请回工作台确认执行或结束周期，再保存更新。</p>:preview.active_status==='executed'?<>
        {preview.feedback_allowed?<><label className="check-field"><input type="checkbox" checked={asFeedback} onChange={e=>setAsFeedback(e.target.checked)}/>将新增观察日作为已确认动作的经营反馈</label>
          {asFeedback&&<label className="check-field"><input type="checkbox" checked={terminal} onChange={e=>setTerminal(e.target.checked)}/>结束本轮周期</label>}</>:<p className="data-update-warning">当前动作已执行。反馈须只新增一个后续观察日，真实数据不能与初始合成样例组成训练转移。请先在工作台完成当前周期，再导入。</p>}
      </>:preview.active_status==='draft'?<p className="fine-print">保存后旧草稿归档为“已取消”；下一次建议将基于更新后的观测重新计算。</p>:<p className="fine-print">保存仅更新观测；模型不会把导入数据自动当成执行效果学习。</p>}
      <div className="data-preview-actions"><button className="button primary" disabled={!!busy||!!blocked} onClick={apply}><Check size={14}/>{asFeedback?'保存观测与经营反馈':'确认保存更新'}</button><button className="button subtle" disabled={!!busy} onClick={clearPreview}>放弃预览</button></div>
    </div>}
    {!!data.revisions?.length&&<details className="data-revisions"><summary>更新记录 · {data.revisions.length} 次</summary>
      <ol>{data.revisions.slice(-10).reverse().map(item=><li key={item.revision}><span>v{item.revision} · {item.observation_date}</span><strong>{item.note}</strong><small>{new Date(item.updated_at).toLocaleString('zh-CN')} · {['demo','simulation','demo_upload'].includes(item.source)?'合成/测试':'用户提供'}</small></li>)}</ol></details>}
  </section>;
}
