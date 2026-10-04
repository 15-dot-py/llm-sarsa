import io
import numpy as np
import pandas as pd
from environments import metrics_from_rows
from decision_models.actions import CHANNELS

REQUIRED=['date','sales','revenue','advertising_cost','impressions','clicks','orders',
          'new_customers','returning_customers','channel','price','discount','promotion_cost','inventory','returns']
NUMERIC=[x for x in REQUIRED if x not in {'date','channel'}]

def process_csv(blob: bytes,source='uploaded'):
    if len(blob)>2*1024*1024: raise ValueError('CSV 最大 2 MB')
    text=None; encoding=''
    for enc in ['utf-8-sig','gb18030']:
        try: text=blob.decode(enc); encoding=enc; break
        except UnicodeDecodeError: continue
    if text is None: raise ValueError('请使用 UTF-8 或 GBK 编码的 CSV')
    try: df=pd.read_csv(io.StringIO(text))
    except Exception: raise ValueError('无法解析 CSV，请检查分隔符与列名') from None
    df.columns=df.columns.str.strip()
    missing=sorted(set(REQUIRED)-set(df.columns))
    if missing: raise ValueError('缺少必填列：'+', '.join(missing))
    if not 10<=len(df)<=9000: raise ValueError('至少 10 行，最多 9000 行数据')
    df=df.copy()
    try: dates=pd.to_datetime(df['date'],errors='raise',format='mixed')
    except Exception: raise ValueError('date 必须为有效日期，建议 YYYY-MM-DD') from None
    df['date']=dates.dt.strftime('%Y-%m-%d')
    df['channel']=df['channel'].astype(str).str.strip()
    if not set(df.channel).issubset(CHANNELS): raise ValueError('渠道限定为：'+', '.join(CHANNELS))
    if df.duplicated(['date','channel']).any(): raise ValueError('同一日期、渠道只能一行；请先汇总，库存按渠道分仓填写')
    optional=[x for x in ['cogs','return_loss','unit_cost','list_price','forecast_revenue'] if x in df]
    for col in NUMERIC+optional:
        df[col]=pd.to_numeric(df[col],errors='coerce')
        if df[col].isna().any() or not np.isfinite(df[col].to_numpy()).all(): raise ValueError(f'{col} 存在空值或非法数字')
        if (df[col]<0).any(): raise ValueError(f'{col} 不能为负数')
    if (df['discount']>.5).any(): raise ValueError('discount 应为 0–0.5 的小数，例如 0.1')
    if (df['price']<=0).any(): raise ValueError('price 必须大于零')
    for larger,smaller in [('impressions','clicks'),('clicks','orders'),('sales','returns'),('sales','orders')]:
        if (df[smaller]>df[larger]).any(): raise ValueError(f'{smaller} 不能大于 {larger}')
    if ((df.new_customers+df.returning_customers)>df.orders).any(): raise ValueError('新客与回流客户人数之和不能超过订单数')
    warnings=[]; estimates=[]
    if 'cogs' not in df:
        if 'unit_cost' in df: df['cogs']=df['unit_cost']*df['sales']
        else: df['cogs']=df.revenue*.58; estimates.append('商品成本按收入的 58% 估算（可在 CSV 补充 cogs 或 unit_cost）')
    if 'return_loss' not in df:
        df['return_loss']=df.returns*df.price*.7; estimates.append('退货损失按退货件数 × 成交价格 × 70% 估算')
    if 'list_price' not in df: df['list_price']=df.price/(1-df.discount)
    if df.date.nunique()<30: warnings.append('观察期不足 30 天，趋势与重要性分析可能不稳定')
    if len(set(CHANNELS)-set(df.channel)): warnings.append('部分渠道缺失，相关预算调整会被屏蔽')
    warnings.extend(['回流客户占比是复购代理，缺少客户标识无法计算真实复购率',
                     '库存必须是渠道独立分仓，共享总库存不可重复填报',
                     '单日利润是营销贡献利润，未包含管理、税费等完整会计费用'])
    df=df.sort_values(['date','channel']).reset_index(drop=True)
    daily=[]; prev=None
    for date,g in df.groupby('date',sort=True):
        m=metrics_from_rows(g.to_dict('records'),prev); m['date']=date
        m['unit_cost']=float(g.cogs.sum()/max(g.sales.sum(),1))
        m['list_price']=float(np.average(g.list_price,weights=np.maximum(g.sales,1)))
        m['cost_method']='estimated' if estimates else 'provided'
        if 'forecast_revenue' in g: m['forecast_revenue']=float(g.forecast_revenue.sum())
        daily.append(m); prev=m['revenue']
    for i,m in enumerate(daily):
        window=[x['revenue'] for x in daily[max(0,i-6):i+1]]
        m['volatility']=float(np.std(window)/max(np.mean(window),1))
    quality={'rows':len(df),'days':df.date.nunique(),'start':df.date.min(),'end':df.date.max(),
             'encoding':encoding,'warnings':warnings,'estimates':estimates,'source':source,
             'label':'合成营销演示数据，非三只松鼠内部数据' if source=='demo' else '用户上传经营数据；真实性由数据提供方确认',
             'cost_method':'估算营销贡献利润' if estimates else '按提供的成本计算营销贡献利润'}
    return {'rows':df.to_dict('records'),'daily':daily,'current':daily[-1],'quality':quality}
