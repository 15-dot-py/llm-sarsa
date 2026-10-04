import json
import numpy as np
import pytest
from backend.service import Platform
from backend.schemas import DecisionInput
from llm.service import LLMService
from llm.intent import infer_goal,explicit_constraints
from decision_models import ActionConstraints
from factor_engine import FactorEngine
from sarsa import DeepSARSA,SARSAConfig
from environments import MarketingEnvironment
from reward import PROFILES

def test_auto_goal_and_explicit_text_constraint_reach_sarsa(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false')
    p=Platform(tmp_path);sid=p.new_session()['session_id']
    d=p.decide(sid,DecisionInput(question='提高销售收入，但不要增加淘宝预算，预算上限15000元。',reward_profile='auto'))
    assert d['reward_profile']=='growth_maximization'
    assert d['constraints']['max_daily_budget']==15000
    assert not next(x for x in d['q_values'] if x['name']=='increase_new_customer_acquisition')['legal']
    assert d['action_name']!='increase_new_customer_acquisition'
    assert d['input_audit']['goal_source']=='根据问题识别'
    assert d['input_audit']['explicit_constraints']
    assert d['explanation']['selected_action']==d['action_name']
    assert '提高销售收入' in d['explanation']['summary']

def test_unrelated_input_creates_no_decision(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false')
    p=Platform(tmp_path);sid=p.new_session()['session_id']
    with pytest.raises(ValueError,match='无关内容'):
        p.decide(sid,DecisionInput(question='你好，今天天气如何？',reward_profile='auto'))
    assert p.store.history(sid)==[] and p.store.session(sid)['active_decision'] is None

def test_rule_parser_directions_and_negations(monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false');llm=LLMService()
    up=llm.extract('需求增长，流量增加。')['signals']
    down=llm.extract('需求下降，流量减少。')['signals']
    assert up['market_demand_index']==1.2 and down['market_demand_index']==.8
    assert up['platform_traffic_change']==.2 and down['platform_traffic_change']==-.2
    assert llm.extract('需求并未下降，不在大促窗口。')['signals']['market_demand_index'] is None
    assert llm.extract('需求并未下降，不在大促窗口。')['signals']['holiday_index'] is None
    assert infer_goal('如何清库存？')=='inventory_clearance'
    assert infer_goal('降低获客成本。')=='acquisition_efficiency'
    constraints,applied=explicit_constraints('不要停止淘宝投放。',ActionConstraints())
    assert not constraints.stopped_channels and not applied

def test_quota_failure_is_visible_and_not_retried_for_explanation(monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','true');monkeypatch.setenv('LLM_PROVIDER','openai')
    monkeypatch.setenv('OPENAI_API_KEY','private-test-key');llm=LLMService();calls=[]
    class QuotaError(Exception):
        code='credit_balance_exhausted';status_code=429
    def fail(*args):
        calls.append(1);raise QuotaError('private-test-key must not be displayed')
    monkeypatch.setattr(llm,'_call',fail)
    out=llm.extract('需求下降，如何调整营销？')
    explanation=llm.explain({'action_name':'keep_strategy','action_label':'保持当前策略','metrics':{},
                            'q_selected':.1,'expected_reward':{},'bias':[],'mask_reasons':{}})
    assert len(calls)==1 and '额度不足' in explanation['fallback_reason']
    assert not llm.status()['available'] and llm.status()['configured']
    assert 'private-test-key' not in json.dumps([out,explanation,llm.status()])

def test_published_model_does_not_collapse_across_heldout_states():
    engine=FactorEngine();agent=DeepSARSA.load('data/pretrained.pt',engine.registry.signature)
    actions=[]
    for i,seed in enumerate([12000,12001,12002,12003,12004,12005,12006]):
        env=MarketingEnvironment(seed=seed,horizon=7,diverse=True,profile=list(PROFILES.values())[i])
        for _ in range(7):
            action=agent.select_action(env.state(),env.mask()[0],explore=False);actions.append(action);env.step(action)
    assert len(set(actions))>=3
    assert max(actions.count(a) for a in set(actions))/len(actions)<.9

def test_dueling_sarsa_bootstraps_actual_action_and_terminal_batch():
    a=DeepSARSA(FactorEngine().state_dim,SARSAConfig(architecture='dueling-v2'))
    state=np.zeros(a.state_dim,dtype=np.float32);mask=np.ones(18,dtype=bool)
    before=a.q_values(state)
    result=a.update(state,0,.2,state,4,next_mask=mask)
    assert result['target']==pytest.approx(.2+a.config.gamma*before[4])
    rewards=np.zeros((2,18),dtype=np.float32)
    assert np.isfinite(a.warm_start_terminal_batch(np.stack([state,state]),rewards,np.stack([mask,mask])))
    b=DeepSARSA.from_bytes(a.to_bytes(),a.signature)
    np.testing.assert_allclose(a.q_values(state),b.q_values(state))

def test_legacy_session_keeps_active_cycle_then_migrates_without_losing_history(tmp_path,monkeypatch):
    from factor_engine.engine import FactorRegistry,CORE
    from backend.schemas import ExecuteInput,FeedbackInput
    from database.store import dumps
    monkeypatch.setenv('LLM_ENABLED','false');p=Platform(tmp_path);sid=p.new_session()['session_id']
    legacy_engine=FactorEngine(FactorRegistry(CORE[:30]))
    legacy=DeepSARSA(legacy_engine.state_dim,signature=legacy_engine.registry.signature)
    with p.store.connect() as c:c.execute('UPDATE sessions SET model=? WHERE id=?',(legacy.to_bytes(),sid))
    s=p.store.session(sid);dataset=s['dataset']
    record=p._build_decision(s,'如何改善营销利润？',PROFILES['profit_maximization'],ActionConstraints())
    with p.store.connect() as c:
        p.store.put_decision(sid,record,c)
        c.execute('UPDATE sessions SET active_decision=? WHERE id=?',(record['id'],sid))
    assert p.dashboard(sid)['state']['state_dim']==72
    assert p.lab(sid)['current_state']['state_dim']==72
    p.execute(sid,record['id'],ExecuteInput())
    result=p.feedback(sid,record['id'],FeedbackInput(mode='simulation',terminal=True))
    assert result['decision']['transition']['update']['bootstrap_q']==0
    dashboard=p.dashboard(sid)
    assert dashboard['state']['state_dim']==92
    assert p.store.history(sid)[0]['id']==record['id']
    assert len(p.store.session(sid)['dataset']['daily'])==len(dataset['daily'])+1
    with p.store.connect() as c:assert c.execute('SELECT count(*) FROM model_archive WHERE session_id=?',(sid,)).fetchone()[0]==1
