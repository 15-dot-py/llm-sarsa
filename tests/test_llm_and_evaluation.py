import pytest
import numpy as np
from llm.service import LLMService,Signals,Explanation
from environments import MarketingEnvironment
from evaluation.experiments import choose,evaluate
from sarsa import DeepSARSA,SARSAConfig,TabularSARSA
from sarsa.training import train
from bias_engine import BiasEngine

def test_llm_explanation_cannot_change_action(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','fake-test-key')
    llm=LLMService()
    def fake_call(schema,prompt,payload):
        return Explanation(selected_action='increase_price',summary='bad override',reasons=[],watch_metrics=[],limitations=[])
    monkeypatch.setattr(llm,'_call',fake_call)
    record={'action_name':'keep_strategy','action_label':'保持当前策略','q_selected':.2,'expected_reward':{},
            'metrics':{'roi':.2,'cac':40,'inventory_pressure':.6},'bias':[],'mask_reasons':{}}
    out=llm.explain(record)
    assert out['source']=='Template' and out['selected_action']=='keep_strategy'
    assert record['action_name']=='keep_strategy'

def test_out_of_range_semantic_output_is_rejected(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','fake-test-key'); llm=LLMService()
    invalid=Signals(summary='x',inventory_pressure='high',douyin_cac='unknown',repeat_purchase='unknown',
         holiday_index=12,competitor_intensity=None,platform_traffic_change=None,market_demand_index=None,evidence=[],unknowns=[])
    monkeypatch.setattr(llm,'_call',lambda *a:invalid)
    assert llm.extract('库存高')['source']=='Rule parser'

def test_short_training_reproducible_and_baseline_same_state_contract():
    cfg=SARSAConfig(episodes=3,horizon=7,seed=18)
    a,ra=train(cfg); b,rb=train(cfg)
    assert ra['curves']==rb['curves']
    state=MarketingEnvironment(seed=18).state()
    np.testing.assert_allclose(a.q_values(state),b.q_values(state))
    class Capture:
        def select_action(self,s,m,explore=False): self.state=s; return 17
    capture=Capture(); env=MarketingEnvironment()
    choose('Tabular SARSA',env,capture)
    assert capture.state==env.state(semantic=False)
    x=evaluate('结构化输入 Deep SARSA',a,seeds=[10010,10011],horizon=7)
    assert x['n_episodes']==2 and x['summary']['reward_standard_error']>=0

def test_all_six_biases_require_explicit_history():
    h=[{'date':str(i),'roi':.4,'profit':100,'advertising_budget':500,'revenue':1000,'forecast_revenue':1500,
        'reason_category':'competitor_follow','supporting_experiment':False,
        'channels':[{'channel':'抖音','roi':-.3,'advertising_cost':100+i*20}]} for i in range(7)]
    results={x['name']:x for x in BiasEngine().analyze(h)}
    assert results['sunk_cost_score']['score']==1 and results['sunk_cost_score']['evidence'][0]['channel']=='抖音'
    assert results['herding_score']['score']==1 and results['overconfidence_score']['score']==pytest.approx(.5)
    for row in h: row['reason_category']='historical_anchor';row['current_evidence_conflict']=True;row['anchor_value']=60
    assert next(x for x in BiasEngine().analyze(h) if x['name']=='anchoring_score')['score']==1
