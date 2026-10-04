from pathlib import Path
import pandas as pd
import numpy as np
from datetime import date,timedelta
from environments import MarketingEnvironment
from decision_models.actions import CHANNELS

def generate_sample(path=None,seed=2026,days=60):
    env=MarketingEnvironment(seed=seed,horizon=days)
    rows=[]
    for d in range(days):
        # A synthetic operational scenario, not company financial data.
        action=0 if d in (8,15,22,29,36,43,50) and env.mask()[0][0] else 17
        _,_,_,info=env.step(action)
        for r in info['rows']:
            r['date']=(date(2026,7,1)+timedelta(days=d)).isoformat()
            r['list_price']=env.context['price']; r['unit_cost']=env.context['unit_cost']
            r['inventory']=float(r['inventory']+d*70) # synthetic warehousing accumulation
            rows.append(r)
    df=pd.DataFrame(rows)
    numeric=df.select_dtypes(include='number').columns
    df[numeric]=df[numeric].round(2)
    target=Path(path or Path(__file__).with_name('sample_marketing.csv'))
    df.to_csv(target,index=False,encoding='utf-8-sig')
    return df

if __name__=='__main__':
    df=generate_sample(); print(f'Generated synthetic demo: {len(df)} rows / {df.date.nunique()} days')
