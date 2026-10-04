"""Reproducible held-out simulations; unavailable LLM groups are never synthesized."""
import copy
import numpy as np
from environments import MarketingEnvironment
from decision_models import ACTIONS
from reward import PROFILES
from factor_engine import FactorEngine
from llm import LLMService

def rule_action(metrics,mask):
    if metrics.get('inventory_pressure',0)>.65 and mask[16]: return 16
    if metrics.get('douyin_cac',0)>90 and mask[1]: return 1
    if metrics.get('repeat_purchase_rate',0)>.3 and mask[12]: return 12
    return len(ACTIONS)-1

def choose(kind,env,agent=None,llm=None,ablate=None):
    mask=env.mask()[0]
    if kind=='Rule-based': return rule_action(env.metrics,mask)
    if kind=='LLM-only':
        name=llm.baseline_action(env.metrics,[a.name for i,a in enumerate(ACTIONS) if mask[i]])
        return next(i for i,a in enumerate(ACTIONS) if a.name==name)
    state=env.state(semantic=kind not in {'Deep SARSA','Tabular SARSA'})
    if kind=='LLM + Deep SARSA':
        # A single structured extraction per time step from an explicitly generated scenario narrative.
        narrative=f"市场需求{'增长' if env.demand>1.05 else '下降' if env.demand<.95 else '平稳'}。"+('大促窗口。' if env.metrics['holiday_index'] else '')+('竞争激烈。' if env.competitor>.6 else '')
        sem=llm.extract(narrative)
        if sem['source']!='LLM': raise RuntimeError('LLM 语义提取不可用，本实验组不计算结果')
        observed=copy.deepcopy(env.metrics)
        for k in ['seasonality','holiday_index','competitor_intensity','platform_traffic_change','market_demand_index']: observed[k]=None
        state=FactorEngine().build(observed,env.profile,sem['signals'])['vector']
    if ablate:
        n=len(FactorEngine().registry.factors)
        for idx in ablate: state[idx]=0.; state[n+idx]=0.
    return agent.select_action(state,mask,explore=False)

def evaluate(kind,agent=None,seeds=range(10000,10008),horizon=28,llm=None,ablate=None):
    episodes=[]; paths=[]
    for j,seed in enumerate(seeds):
        env=MarketingEnvironment(seed=seed,horizon=horizon,profile=list(PROFILES.values())[j%len(PROFILES)])
        rewards=[]; metrics=[]; actions=[]
        for t in range(horizon):
            action=choose(kind,env,agent,llm,ablate); _,r,_,info=env.step(action)
            rewards.append(r); metrics.append(info['metrics']); actions.append(action)
        def mean(k): return float(np.mean([m[k] for m in metrics if m.get(k) is not None]))
        episodes.append({'seed':seed,'profile':env.profile.name,'average_reward':float(np.mean(rewards)),
            'roi':mean('roi'),'profit':mean('profit'),'conversion_rate':mean('conversion_rate'),'cac':mean('cac'),
            'inventory_turnover':mean('inventory_turnover'),'reward_std':float(np.std(rewards)),
            'decision_stability':float(np.mean(np.array(actions[1:])==np.array(actions[:-1]))),
            'total_profit':float(sum(m['profit'] for m in metrics))})
        paths.append({'seed':seed,'rewards':rewards,'actions':actions})
    keys=[k for k in episodes[0] if k not in {'seed','profile'}]
    summary={k:float(np.mean([e[k] for e in episodes])) for k in keys}
    summary['reward_standard_error']=float(np.std([e['average_reward'] for e in episodes],ddof=1)/np.sqrt(len(episodes))) if len(episodes)>1 else 0.
    return {'name':kind,'status':'completed','summary':summary,'n_episodes':len(episodes),'horizon':horizon,'episodes':episodes,'paths':paths}

def run_experiments(deep,tabular,deep_no_semantic,include_llm=False,seeds=range(10000,10008),horizon=28):
    groups=[evaluate('Rule-based',seeds=seeds,horizon=horizon),
            evaluate('Tabular SARSA',tabular,seeds,horizon),
            evaluate('Deep SARSA',deep_no_semantic,seeds,horizon),
            evaluate('结构化外部信号 + Deep SARSA（输入消融）',deep,seeds,horizon)]
    llm=LLMService()
    for kind in ['LLM-only','LLM + Deep SARSA']:
        if not include_llm or not llm.available:
            groups.append({'name':kind,'status':'not_run','reason':'未配置 API 或未显式启用付费实验；没有伪造 LLM 结果','summary':None})
        else:
            try: groups.append(evaluate(kind,deep,seeds,horizon,llm))
            except Exception as exc: groups.append({'name':kind,'status':'failed','reason':str(exc)[:250],'summary':None})
    engine=FactorEngine(); f=engine.registry.factors
    ablations=[]
    base=groups[3]['summary']['average_reward']
    for category in ['channel','external','bias']:
        idx=[i for i,x in enumerate(f) if x.category==category]
        result=evaluate('结构化输入 Deep SARSA',deep,seeds,horizon,ablate=idx)
        ablations.append({'group':category,'masked_factors':[f[i].name for i in idx],
                          'reward':result['summary']['average_reward'],'difference_from_full':result['summary']['average_reward']-base,
                          'method':'固定训练策略，推理期屏蔽因子与缺失标记；未重训，不是因果结论'})
    return {'groups':groups,'ablations':ablations,'test_seeds':list(seeds),'horizon':horizon,
            'source':'合成环境独立测试；不同组使用共同种子，不能作为三只松鼠实际经营改善证据',
            'semantic_boundary':'结构化输入消融使用仿真外部信号；只有实际调用 API 的组才标记 LLM',
            'metric_definitions':{'reward_std':'越低代表回报波动越小，不等于绩效更优','decision_stability':'相邻动作相同的比例，越高不一定越优',
                                  'profit':'每日营销贡献利润，非会计净利润','inventory_turnover':'日销量 / 期初可用库存'}}
