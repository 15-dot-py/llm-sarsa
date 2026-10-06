"""Validated incremental observations, with explicit provenance and revisions."""
import hashlib
import json
import math
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from data.processing import process_csv, REQUIRED
from decision_models.actions import CHANNELS

OPTIONAL=['cogs','return_loss','unit_cost','list_price','forecast_revenue']

def csv_from_rows(rows):
    for row in rows:
        for key in OPTIONAL:
            if row.get(key) is not None:
                try:value=float(row[key])
                except (TypeError,ValueError):raise ValueError(f'{key} 存在非法数字') from None
                if not math.isfinite(value) or value<0:raise ValueError(f'{key} 应为非负有限数字')
    frame=pd.DataFrame(rows)
    # Optional fields may be available on only some days. Do not serialize
    # missing optional values as invalid numeric CSV cells.
    frame=frame[[c for c in REQUIRED+OPTIONAL if c in frame.columns and
                 (c in REQUIRED or frame[c].notna().all())]]
    return frame.to_csv(index=False).encode('utf-8-sig')

def stamp(dataset,source,note,previous=None,changes=None):
    previous=previous or {}
    q=dataset['quality'];daily=dataset['daily']
    digest=hashlib.sha256(json.dumps({'rows':dataset['rows'],'daily':daily},sort_keys=True,
                                  ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    revision=previous.get('quality',{}).get('revision',0)+1
    updated=datetime.now(timezone.utc).isoformat()
    q.update(revision=revision,content_hash=digest,updated_at=updated,
             current_source=dataset['current'].get('observation_source',source),
             days=len(daily),start=daily[0]['date'],end=daily[-1]['date'])
    event={'revision':revision,'content_hash':digest,'updated_at':updated,'source':source,
           'note':note,'observation_date':q['end'],'rows':q['rows'],**(changes or {})}
    dataset['revisions']=[*previous.get('revisions',[]),event]
    return dataset

def prepare_update(existing,incoming,source,note):
    real_sources={'uploaded','manual'}
    # A real dataset must not silently inherit the initial synthetic example.
    has_real=any(r.get('observation_source',existing['quality']['source']) in real_sources|{'actual'} for r in existing['daily'])
    if has_real and source=='demo_upload':raise ValueError('此工作区已有实际观测；测试更新请使用新演示工作区，避免混入真实数据')
    real_rows=any(r.get('observation_source',existing['quality']['source']) in real_sources|{'actual'} for r in existing['rows'])
    replace_demo=bool(existing['rows']) and not real_rows and source in real_sources
    old_rows=[] if replace_demo else existing['rows']
    incoming_rows=incoming['rows']
    rowmap={(r['date'],r['channel']):dict(r) for r in old_rows}
    added=corrected=unchanged=0
    for row in incoming_rows:
        key=(row['date'],row['channel']);old=rowmap.get(key)
        if old is None:added+=1
        elif all(old.get(k)==row.get(k) for k in REQUIRED+OPTIONAL if k in row):unchanged+=1
        else:corrected+=1
        rowmap[key]={**row,'observation_source':source}
    merged=sorted(rowmap.values(),key=lambda r:(r['date'],r['channel']))
    dataset=process_csv(csv_from_rows(merged),source,min_rows=1)
    dataset['rows']=merged
    touched={r['date'] for r in incoming_rows}
    old_daily={r['date']:r for r in existing['daily'] if not replace_demo or r.get('observation_source') in real_sources|{'actual'}}
    derived={r['date']:r for r in dataset['daily']}
    # Feedback-only days have no CSV rows and must not disappear on an import.
    dates=sorted(set(old_daily)|set(derived))
    daily=[]
    for date in dates:
        m=dict(derived[date] if date in touched or date not in old_daily else old_daily[date])
        if date in touched:m['observation_source']=source
        elif not m.get('observation_source'):m['observation_source']=existing['quality'].get('source','uploaded')
        if date in touched:
            group=[r for r in merged if r['date']==date]
            if all(r.get('forecast_revenue') is not None for r in group):
                m['forecast_revenue']=sum(r['forecast_revenue'] for r in group)
            m['cost_method']='estimated' if incoming['quality']['estimates'] or any(r.get('cost_method')=='estimated' for r in group) else 'provided'
        if daily:m['gmv_growth']=m['revenue']/max(daily[-1]['revenue'],1)-1
        window=[x['revenue'] for x in daily[-6:]]+[m['revenue']]
        m['volatility']=float(np.std(window)/max(np.mean(window),1))
        daily.append(m)
    dataset['daily']=daily;dataset['current']=daily[-1]
    if incoming['quality']['estimates']:
        dataset['quality']['estimates']=list(dict.fromkeys(existing['quality'].get('estimates',[])+incoming['quality']['estimates'])) if not replace_demo else incoming['quality']['estimates']
    elif not replace_demo:dataset['quality']['estimates']=existing['quality'].get('estimates',[])
    current_source=dataset['current']['observation_source']
    dataset['quality']['source']='demo' if current_source in {'demo','simulation','demo_upload'} else current_source
    dataset['quality']['label']='合成/测试运营数据，非企业实际业绩' if current_source in {'demo','simulation','demo_upload'} else '用户提供运营观测，真实性由提供方确认'
    dataset['quality']['cost_method']='估算营销贡献利润' if dataset['quality']['estimates'] else '按提供的成本计算营销贡献利润'
    if not replace_demo and daily[-1]['date'] not in touched:
        for key in ['latest_result_source','latest_feedback_decision_id']:
            if key in existing['quality']:dataset['quality'][key]=existing['quality'][key]
    present={c['channel'] for c in dataset['current']['channels']}
    if present and present!=set(CHANNELS):
        dataset['quality']['warnings'].append('最新观察日未提供：'+','.join(ch for ch in CHANNELS if ch not in present)+'；不会沿用旧日数据补齐')
    changes={'added_rows':added,'corrected_rows':corrected,'unchanged_rows':unchanged,
             'replaced_demo':replace_demo,'incoming_dates':sorted(touched)}
    stamp(dataset,source,note,existing,changes)
    return dataset,changes
