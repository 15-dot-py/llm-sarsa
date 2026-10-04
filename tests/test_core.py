import numpy as np
import pytest
import torch
from factor_engine import FactorEngine, Factor
from reward import RewardEngine, PROFILES, RewardProfile
from decision_models import ACTIONS, action_mask, ActionConstraints
from sarsa import DeepSARSA, SARSAConfig
from environments import MarketingEnvironment
from bias_engine import BiasEngine

def test_normalization_and_missing_mask():
    f=Factor('x','performance',10,20,'test')
    assert f.normalize(15)==(.5,True)
    assert f.normalize(100)==(1.,True)
    assert f.normalize(float('nan'))==(0.,False)
    e=FactorEngine(); s=e.build({'roi':1},PROFILES['balanced_growth'])
    assert len(s['vector'])==72
    assert s['vector'][0]==.5 and s['vector'][30]==1 and s['vector'][31]==0
    s2=e.build({'roi':1},PROFILES['inventory_clearance'])
    assert s['vector'][-12:]!=s2['vector'][-12:]

def test_reward_normalization_and_direction():
    e=RewardEngine(); p=PROFILES['profit_maximization']
    a=e.calculate({'profit_margin':.1,'cac':30},p)
    b=e.calculate({'profit_margin':.2,'cac':30},p)
    c=e.calculate({'profit_margin':.2,'cac':100},p)
    assert b['total']>a['total'] and c['total']<b['total']
    assert -1<=c['total']<=1 and c['missing']
    with pytest.raises(ValueError): RewardProfile('bad',(0,)*12)

def test_action_constraints_current_and_future():
    env=MarketingEnvironment()
    env.context['inventory']=100
    rules=ActionConstraints(max_daily_budget=7200,stopped_channels=('抖音',),prohibited_promotions=True)
    mask,why=action_mask(env.context,rules)
    assert not mask[0] and not mask[16] and mask[-1]
    assert 'clear_inventory_promotion' in why
    agent=DeepSARSA(72)
    for _ in range(30): assert mask[agent.select_action(env.state(),mask)]

def test_no_keep_escape_when_budget_already_exceeds_cap():
    env=MarketingEnvironment(); mask,_=action_mask(env.context,ActionConstraints(max_daily_budget=100))
    assert not mask.any()
    with pytest.raises(ValueError,match='没有合法'): DeepSARSA(72).select_action(env.state(),mask)

def test_forward_actual_next_action_target_and_terminal():
    config=SARSAConfig(gamma=.9,learning_rate=.001)
    a=DeepSARSA(72,config); s=np.zeros(72,dtype=np.float32)
    with torch.no_grad():
        for p in a.network.parameters(): p.zero_()
        a.network.layers[-1].bias.copy_(torch.arange(len(ACTIONS),dtype=torch.float32))
    assert a.q_values(s).shape==(len(ACTIONS),)
    result=a.update(s,0,.5,s,2,next_mask=np.ones(len(ACTIONS),bool))
    assert result['target']==pytest.approx(.5+.9*2)
    assert result['target']!=pytest.approx(.5+.9*17)
    assert a.q_values(s)[0]>0
    terminal=a.update(s,0,.5,s,None,done=True)
    assert terminal['target']==pytest.approx(.5) and terminal['bootstrap_q']==0
    with pytest.raises(ValueError): a.update(s,0,.5,s,None)
    with pytest.raises(ValueError): a.update(s,0,.5,s,2,next_mask=np.zeros(len(ACTIONS),bool))

def test_save_load_optimizer_and_policy_rng(tmp_path):
    a=DeepSARSA(72,signature='abc'); s=np.zeros(72,dtype=np.float32)
    a.update(s,0,.4,s,1); a.decay(); a.save(tmp_path/'m.pt')
    b=DeepSARSA.load(tmp_path/'m.pt','abc')
    np.testing.assert_allclose(a.q_values(s),b.q_values(s))
    assert b.updates==1 and b.epsilon==a.epsilon
    mask=np.ones(len(ACTIONS),bool)
    assert a.select_action(s,mask)==b.select_action(s,mask)
    with pytest.raises(ValueError): DeepSARSA.load(tmp_path/'m.pt','different')

def test_seeded_stochastic_environment_and_loop():
    a=MarketingEnvironment(seed=23); b=MarketingEnvironment(seed=23)
    s,r,_,info=a.step(17); sb,rb,_,_=b.step(17)
    assert r==rb; np.testing.assert_allclose(s,sb)
    c=MarketingEnvironment(seed=24); _,rc,_,_=c.step(17)
    assert rc!=r
    agent=DeepSARSA(72); state=a.state(); action=agent.select_action(state,a.mask()[0])
    state2,reward,done,_=a.step(action); mask=a.mask()[0]; next_action=agent.select_action(state2,mask)
    assert np.isfinite(agent.update(state,action,reward,state2,next_action,done,mask)['loss'])

def test_bias_requires_evidence_and_calculates():
    e=BiasEngine(); assert all(x['score'] is None for x in e.analyze([]))
    h=[{'date':str(i),'roi':-.3,'profit':-50,'advertising_budget':100+i*20,'revenue':150} for i in range(5)]
    result={x['name']:x for x in e.analyze(h)}
    assert result['sunk_cost_score']['score']==1
    assert result['sunk_cost_score']['evidence']
    assert result['herding_score']['score'] is None
