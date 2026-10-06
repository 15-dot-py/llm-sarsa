"""Reproduce lost ephemeral workspaces and verify the complete decision cycle."""
from dataclasses import replace
import base64
import json
import zlib
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.service import Platform
from backend.phone_auth import PhoneAuth, AuthConfig
from backend.workspace_backup import MAX_RAW, WorkspaceBackup
from backend.schemas import DecisionInput, ExecuteInput, FeedbackInput
from sarsa import DeepSARSA


def application(path):
    p=Platform(path)
    cfg=replace(AuthConfig.from_env(),secret='TEST_RECOVERY_'+('x'*40))
    a=PhoneAuth(p,cfg)
    return p,a,TestClient(create_app(p,a))


def first_cycle(p,sid,terminal=False,profit=5000,roi=.7):
    d=p.decide(sid,DecisionInput(question='如何改善营销利润？',reward_profile='profit_maximization'))
    p.execute(sid,d['id'],ExecuteInput())
    result=p.feedback(sid,d['id'],FeedbackInput(mode='actual',terminal=terminal,outcome={
        'revenue':40000,'profit':profit,'roi':roi,'cac':40,'inventory_level':12000,'conversion_rate':.06,
        'advertising_cost':6000,'promotion_cost':200}))
    return d,result


def test_restore_restart_preserves_pending_actual_action_and_model(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false')
    p,a,c=application(tmp_path/'original');sid=p.new_session()['session_id'];h={'X-Session-Id':sid}
    d,result=first_cycle(p,sid)
    archive=c.get('/api/workspace/backup',headers=h).json()
    original=p.store.session(sid)
    p2,a2,c2=application(tmp_path/'fresh-instance')
    expired=c2.get('/api/dashboard',headers=h)
    assert expired.status_code==401 and expired.json()['detail']['code']=='workspace_expired'
    restored=c2.post('/api/workspace/restore',json=archive)
    assert restored.status_code==200,restored.text
    assert restored.json()['restored']
    recovered=p2.store.session(sid)
    for key in ('dataset','metrics','model','config','active_decision','created','updated'):
        assert recovered[key]==original[key]
    assert p2.store.history(sid)==p.store.history(sid)
    assert p2.store.get_metadata('training:'+sid)==p.store.get_metadata('training:'+sid)
    child=result['next_decision'];agent=DeepSARSA.from_bytes(recovered['model']);before=agent.updates
    other=next(x for x in child['q_values'] if x['legal'] and x['name']!=child['action_name'])
    body={'action_name':other['name'],'reason':'核验恢复后实际下一动作'}
    x=c2.post(f"/api/decisions/{child['id']}/execute",headers=h,json=body)
    assert x.status_code==200,x.text
    assert p2.store.decision(sid,d['id'])['transition']['next_action']==other['index']
    assert DeepSARSA.from_bytes(p2.store.session(sid)['model']).updates==before+1
    assert c2.post(f"/api/decisions/{child['id']}/execute",headers=h,json=body).status_code==200
    assert DeepSARSA.from_bytes(p2.store.session(sid)['model']).updates==before+1
    summary=c2.get('/api/dashboard',headers=h).json()['operations']
    assert summary['confirmed']==2 and summary['accepted']==1 and summary['overrides']==1
    # A stale archive cannot roll back a newer confirmed action or model.
    assert c2.post('/api/workspace/restore',json=archive).json()['restored'] is False
    assert DeepSARSA.from_bytes(p2.store.session(sid)['model']).updates==before+1


def test_unsigned_archive_rejected_before_checkpoint_read(tmp_path,monkeypatch):
    p,a,c=application(tmp_path);sid=p.new_session()['session_id']
    archive=c.get('/api/workspace/backup',headers={'X-Session-Id':sid}).json()
    bad={**archive,'signature':'0'*64}
    def no_pickle(*args): raise AssertionError('must not deserialize unsigned model')
    monkeypatch.setattr(p,'_agent',no_pickle)
    assert c.post('/api/workspace/restore',json=bad).status_code==422
    wrong={**archive,'session_id':'x'*43}
    assert c.post('/api/workspace/restore',json=wrong).status_code==422
    inflater_payload=base64.b64encode(zlib.compress(b'x'*(MAX_RAW+1))).decode()
    excessive={**archive,'payload':inflater_payload,'signature':WorkspaceBackup(p,a)._sign(inflater_payload)}
    assert c.post('/api/workspace/restore',json=excessive).status_code==422


def test_owner_cannot_restore_to_another_account(tmp_path):
    p,a,c=application(tmp_path/'one');sid=p.new_session()['session_id']
    with p.store.connect() as db:
        db.execute('INSERT INTO auth_users VALUES (?,?,?,?)',('owner','138****0000',1,'test'))
    a.bind(sid,{'id':'owner'})
    archive=WorkspaceBackup(p,a).export(sid)
    p2,a2,c2=application(tmp_path/'two')
    with pytest.raises(Exception) as e: WorkspaceBackup(p2,a2).restore(archive,{'id':'other'})
    assert e.value.status_code==403
    with pytest.raises(KeyError): p2.store.session(sid)


@pytest.mark.parametrize('profit,roi',[(8000,1.29),(-3000,-.48)])
def test_confirmation_and_feedback_are_distinct_and_results_keep_sign(tmp_path,monkeypatch,profit,roi):
    monkeypatch.setenv('LLM_ENABLED','false')
    p,a,c=application(tmp_path);sid=p.new_session()['session_id'];h={'X-Session-Id':sid}
    baseline=p.dashboard(sid)['metrics']['profit']
    d,result=first_cycle(p,sid,terminal=True,profit=profit,roi=roi)
    dashboard=c.get('/api/dashboard',headers=h).json()
    assert dashboard['metrics']['profit']==profit and dashboard['metrics']['roi']==roi
    assert dashboard['comparison']['profit_change']==profit-baseline
    assert dashboard['operations']['confirmed']==1 and dashboard['operations']['overrides']==0
    assert dashboard['operations']['actual_feedback']==1
    signal=next(x for x in dashboard['bias'] if x['name']=='overconfidence_score')
    assert signal['score'] is None and '0/3' in signal['interpretation']
    assert dashboard['comparison']['source'].startswith('用户填报')


def test_snapshot_and_export_include_records_beyond_history_page_limit(tmp_path):
    p,a,c=application(tmp_path);sid=p.new_session()['session_id'];h={'X-Session-Id':sid}
    with p.store.connect() as db:
        for i in range(205):
            p.store.put_decision(sid,{'id':f'test-{i}','timestamp':f'2026-10-06T00:00:{i:03}',
                                    'status':'cancelled','execution':None,'user_feedback':None},db)
    assert len(c.get('/api/decisions',headers=h).json())==200
    assert len(c.get('/api/export/history.json',headers=h).json()['decisions'])==205
    archive=c.get('/api/workspace/backup',headers=h).json()
    payload=json.loads(zlib.decompress(base64.b64decode(archive['payload'])))
    assert len(payload['decisions'])==205
    assert p.dashboard(sid)['operations']['decisions']==205


def test_same_observation_and_action_do_not_randomize_by_decision_id(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false')
    p,a,c=application(tmp_path);sid=p.new_session()['session_id']
    calls=[];original=p.llm.extract
    def counted(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(p.llm,'extract',counted)
    d=p.decide(sid,DecisionInput(question='如何改善营销利润？',reward_profile='profit_maximization'))
    executed=p.execute(sid,d['id'],ExecuteInput())
    outcome=FeedbackInput(mode='simulation')
    m,source=p._outcome(executed,outcome)
    twin={**executed,'id':'a-completely-different-uuid'}
    m2,source2=p._outcome(twin,outcome)
    assert m==m2 and source['seed']==source2['seed']
    result=p.feedback(sid,d['id'],outcome)
    assert len(calls)==1 and result['next_decision']['stability_audit']['semantic_reused']
    assert result['next_decision']['semantic']==d['semantic']
    legal=sorted((x['q'] for x in d['q_values'] if x['legal']),reverse=True)
    assert d['stability_audit']['q_gap']==pytest.approx(legal[0]-legal[1])
