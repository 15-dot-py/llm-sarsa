import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.service import Platform
from sarsa import DeepSARSA

@pytest.fixture
def setup(tmp_path):
    platform=Platform(tmp_path); client=TestClient(create_app(platform))
    sid=client.post('/api/session').json()['session_id']
    return platform,client,sid,{'X-Session-Id':sid}

def decision(client,headers):
    r=client.post('/api/decisions',headers=headers,json={'question':'抖音获客成本高，库存很多，怎么调整？','reward_profile':'inventory_clearance'})
    assert r.status_code==200,r.text
    return r.json()

def test_reward_catalog_matches_scoring_and_current_goal(setup):
    from reward.engine import REWARD_KEYS, BOUNDS, PROFILES, RewardEngine
    p,c,sid,h=setup
    assert c.get('/api/reward').status_code==401
    response=c.get('/api/reward',headers=h)
    assert response.status_code==200
    catalog=response.json()
    assert [f['name'] for f in catalog['factors']]==REWARD_KEYS
    assert len([f for f in catalog['factors'] if f['sign']==1])==7
    assert len([f for f in catalog['factors'] if f['sign']==-1])==5
    goal=next(x for x in catalog['profiles'] if x['name']=='inventory_clearance')
    assert goal['weights']['inventory_turnover']==pytest.approx(.24)
    assert goal['weights']['inventory_pressure']==pytest.approx(.20)
    metrics=c.get('/api/dashboard',headers=h).json()['metrics']
    score=RewardEngine().calculate(metrics,PROFILES[goal['name']])
    for f,term,bounds in zip(catalog['factors'],score['contributions'],BOUNDS):
        assert (f['lower'],f['upper'])==bounds
        assert f['sign']==term['sign']
        assert goal['weights'][f['name']]==term['weight']
    assert '不同来源' in catalog['factors'][-1]['note']

def test_feedback_loop_exact_confirmed_action_idempotence(setup):
    p,c,sid,h=setup; d=decision(c,h)
    assert d['decision_source']=='Deep SARSA'
    assert d['explanation_source'] in {'Template','LLM'}
    assert len(d['state_vector'])==72 and d['status']=='draft'
    assert c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'simulation'}).status_code==409
    before=DeepSARSA.from_bytes(p.store.session(sid)['model']).updates
    executed=c.post(f"/api/decisions/{d['id']}/execute",headers=h,json={})
    assert executed.status_code==200,executed.text
    response=c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'simulation','rating':'effective'})
    assert response.status_code==200,response.text
    payload=response.json(); next_d=payload['next_decision']
    assert payload['decision']['status']=='awaiting_next'
    assert DeepSARSA.from_bytes(p.store.session(sid)['model']).updates==before
    legal=next(x for x in next_d['q_values'] if x['legal'] and x['name']!=next_d['action_name'])
    result=c.post(f"/api/decisions/{next_d['id']}/execute",headers=h,json={'action_name':legal['name'],'reason':'测试确认实际动作'})
    assert result.status_code==200,result.text
    a=DeepSARSA.from_bytes(p.store.session(sid)['model'])
    assert a.updates==before+1
    prior=p.store.decision(sid,d['id'])
    assert prior['transition']['next_action']==legal['index']
    assert prior['transition']['update']['next_action']==legal['index']
    assert prior['transition']['next_action_confirmed']
    # Duplicate execute and feedback must not change weights or updates.
    assert c.post(f"/api/decisions/{next_d['id']}/execute",headers=h,json={}).status_code==200
    assert c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'simulation','rating':'effective'}).json()['idempotent']
    assert DeepSARSA.from_bytes(p.store.session(sid)['model']).updates==before+1

def test_actual_feedback_terminal_missing_stays_missing(setup):
    p,c,sid,h=setup; d=decision(c,h)
    c.post(f"/api/decisions/{d['id']}/execute",headers=h,json={})
    response=c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'actual','terminal':True,
        'outcome':{'revenue':40000,'roi':.7,'cac':70,'inventory_level':20000,'profit':5000,'conversion_rate':.04}})
    assert response.status_code==200,response.text
    x=response.json()['decision']
    assert x['status']=='terminal' and x['actual_reward']['coverage']<1
    assert 'return_rate' in x['actual_reward']['missing']
    assert x['transition']['update']['target']==pytest.approx(x['actual_reward']['total'])
    assert p.store.session(sid)['active_decision'] is None
    assert p.store.session(sid)['metrics']['repeat_purchase_rate'] is None
    for path in ['/api/library','/api/lab','/api/data','/api/dashboard']:
        follow=c.get(path,headers=h)
        assert follow.status_code==200,(path,follow.text)

def test_session_isolation_import_and_restart(setup,tmp_path):
    p,c,sid,h=setup; d=decision(c,h)
    sid2=c.post('/api/session').json()['session_id']; h2={'X-Session-Id':sid2}
    assert c.get('/api/decisions',headers=h2).json()==[]
    assert c.post(f"/api/decisions/{d['id']}/execute",headers=h2,json={}).status_code==404
    assert c.get('/api/dashboard').status_code==401
    assert c.post('/api/data/demo',headers=h).status_code==409
    assert c.post('/api/data/upload',headers=h2,files={'file':('bad.csv',b'date,foo\n2026-01-01,0','text/csv')}).status_code==422
    reloaded=Platform(p.storage)
    assert reloaded.store.decision(sid,d['id'])['id']==d['id']
    np.testing.assert_allclose(DeepSARSA.from_bytes(p.store.session(sid)['model']).q_values(d['state_vector']),
                               DeepSARSA.from_bytes(reloaded.store.session(sid)['model']).q_values(d['state_vector']))

def test_http_input_ranges_and_fallback_actual_next_decision(setup):
    p,c,sid,h=setup; d=decision(c,h); c.post(f"/api/decisions/{d['id']}/execute",headers=h,json={})
    outcome={'revenue':30000,'roi':.5,'cac':90,'inventory_level':25000,'profit':4000,'conversion_rate':.035}
    r=c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'actual','outcome':outcome})
    assert r.status_code==200,r.text
    assert r.json()['next_decision']['status']=='draft'
    outcome['conversion_rate']=5
    assert c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'actual','outcome':outcome}).status_code==422

def test_end_pending_episode_without_fabricating_next_action(setup):
    p,c,sid,h=setup; d=decision(c,h)
    c.post(f"/api/decisions/{d['id']}/execute",headers=h,json={})
    x=c.post(f"/api/decisions/{d['id']}/feedback",headers=h,json={'mode':'simulation'}).json()
    r=c.post(f"/api/decisions/{d['id']}/finish",headers=h)
    assert r.status_code==200,r.text
    record=r.json()
    assert record['transition']['terminal'] and record['transition']['next_action'] is None
    assert record['transition']['update']['bootstrap_q']==0
    assert p.store.decision(sid,x['next_decision']['id'])['status']=='cancelled'
    assert p.store.session(sid)['active_decision'] is None
    count=DeepSARSA.from_bytes(p.store.session(sid)['model']).updates
    c.post(f"/api/decisions/{d['id']}/finish",headers=h)
    assert DeepSARSA.from_bytes(p.store.session(sid)['model']).updates==count
