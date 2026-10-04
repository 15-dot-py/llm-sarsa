"""Measured forecasting associations and policy sensitivity; no causal importance claim."""
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from factor_engine import FactorEngine
from factor_engine.engine import FactorRegistry,CORE
from reward import PROFILES
from bias_engine import BiasEngine

def evaluate_factors(daily,agent=None):
    total_observations=len(daily)
    daily=daily[-180:]
    engine=FactorEngine(FactorRegistry(CORE[:30])) if agent and agent.state_dim==72 else FactorEngine()
    factors=engine.registry.factors; n=len(factors)
    prepared=[{**m,**{x['name']:x['score'] for x in BiasEngine().analyze(daily[:i+1])}} for i,m in enumerate(daily)]
    vectors=np.array([engine.build(m,PROFILES['balanced_growth'])['vector'][:n] for m in prepared])
    output={'target':'下一天收入增长（按时间分割；非因果解释）','n':max(len(daily)-1,0),'importance':[],
            'total_observations':total_observations,'window_days':180,
            'method':'RandomForest held-out permutation + Spearman correlation + neural Q sensitivity',
            'warning':'相关性、预测重要性和策略敏感度不能证明改变因子会产生相同营销收益。缺失因子不用于筛选。'}
    if len(daily)<20:
        output['status']='insufficient_data'; return output
    x=vectors[:-1]; y=np.array([daily[i+1]['revenue']/max(daily[i]['revenue'],1)-1 for i in range(len(daily)-1)])
    split=max(10,int(len(x)*.7)); train=x[:split]; test=x[split:]
    rf=RandomForestRegressor(n_estimators=80,max_depth=4,min_samples_leaf=3,random_state=19,n_jobs=1)
    rf.fit(train,y[:split]); pi=permutation_importance(rf,test,y[split:],n_repeats=8,random_state=19,scoring='neg_mean_squared_error')
    output.update(status='computed',train_n=split,test_n=len(test),test_mse=float(np.mean((rf.predict(test)-y[split:])**2)))
    for i,f in enumerate(factors):
        sensitivity=None
        if agent:
            s=np.array(engine.build(prepared[-1],PROFILES['balanced_growth'])['vector'],np.float32)
            up=s.copy(); dn=s.copy(); up[i]=min(1,up[i]+.1); dn[i]=max(0,dn[i]-.1)
            sensitivity=float(np.mean(np.abs(agent.q_values(up)-agent.q_values(dn))))
        if np.std(x[:,i])>1e-8 and np.std(y)>1e-8:
            import pandas as pd
            corr=float(pd.Series(x[:,i]).corr(pd.Series(y),method='spearman'))
        else: corr=None
        output['importance'].append({'name':f.name,'label':f.description,'permutation_mean':float(pi.importances_mean[i]),
                    'permutation_std':float(pi.importances_std[i]),'spearman':corr,'q_sensitivity':sensitivity,
                    'present':any(m.get(f.name) is not None for m in prepared)})
    output['importance'].sort(key=lambda v:v['permutation_mean'],reverse=True)
    return output
