"""New observations must update state without inventing execution or SARSA steps."""
from dataclasses import replace
from datetime import date,timedelta
import json
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.service import Platform,BusinessError
from backend.schemas import DecisionInput,ExecuteInput,FeedbackInput
from backend.phone_auth import PhoneAuth,AuthConfig
from data.updates import csv_from_rows
from sarsa import DeepSARSA

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_ENABLED','false')
    p=Platform(tmp_path);sid=p.new_session()['session_id']
    return p,sid

def day_rows(p,sid,days=1,multiplier=1):
    s=p.store.session(sid);latest=s['dataset']['rows'][-1]['date']
    new_date=(date.fromisoformat(s['metrics']['date'])+timedelta(days=days)).isoformat()
    rows=[]
    for original in s['dataset']['rows']:
        if original['date']==latest:
            r=dict(original);r['date']=new_date;r['revenue']*=multiplier
            r['cogs']=r['revenue']*.58;r['return_loss']=0
            rows.append(r)
    return rows

def save(p,sid,rows,source='demo_upload',**kwargs):
    preview=p.preview_data(sid,csv_from_rows(rows),source)
    return preview,p.apply_data(sid,preview['preview_token'],**kwargs)

def decision(p,sid):
    return p.decide(sid,DecisionInput(question='根据最新渠道数据改善营销利润',reward_profile='profit_maximization'))

def test_preview_is_read_only_and_incremental_state_is_used(workspace):
    p,sid=workspace;before=p.store.session(sid);rows=day_rows(p,sid,multiplier=1.4)
    preview=p.preview_data(sid,csv_from_rows(rows),'demo_upload')
    assert p.store.session(sid)==before
    assert preview['changes']['added_rows']==5
    receipt=p.apply_data(sid,preview['preview_token'])
    after=p.store.session(sid)
    assert after['model']==before['model']
    assert len(after['dataset']['rows'])==len(before['dataset']['rows'])+5
    assert after['metrics']['revenue']==pytest.approx(sum(r['revenue'] for r in rows))
    d=decision(p,sid)
    assert d['metrics']==after['metrics']
    assert d['data_context']['revision']==receipt['revision']==2
    assert d['data_context']['content_hash']==after['dataset']['quality']['content_hash']
    assert d['factor_values']!=p.factors.build(before['metrics'],__import__('reward').PROFILES['profit_maximization'])['factors']

def test_same_key_upsert_one_row_and_historical_correction_keeps_latest(workspace):
    p,sid=workspace;rows=day_rows(p,sid)
    save(p,sid,rows);latest=p.store.session(sid)['metrics']
    old_metric=p.store.session(sid)['dataset']['daily'][0]['revenue']
    old=dict(p.store.session(sid)['dataset']['rows'][0]);old['revenue']+=500
    preview,_=save(p,sid,[old])
    s=p.store.session(sid)
    assert preview['changes']['corrected_rows']==1
    assert s['metrics']['date']==latest['date'] and s['metrics']['revenue']==latest['revenue']
    keys=[(r['date'],r['channel']) for r in s['dataset']['rows']]
    assert len(keys)==len(set(keys))
    assert s['dataset']['daily'][0]['revenue']==pytest.approx(old_metric+500)

def test_first_real_import_excludes_demo_and_preserves_decision_snapshot(workspace):
    p,sid=workspace;d=decision(p,sid);original=json.loads(json.dumps(d['metrics']))
    rows=day_rows(p,sid,multiplier=1.2)
    preview,_=save(p,sid,rows,'uploaded')
    assert preview['changes']['replaced_demo']
    s=p.store.session(sid)
    assert len(s['dataset']['rows'])==5 and len(s['dataset']['daily'])==1
    old=p.store.decision(sid,d['id'])
    assert old['status']=='cancelled' and old['metrics']==original
    assert old['data_context']['revision']==1 and s['dataset']['quality']['revision']==2
    assert s['active_decision'] is None and s['dataset']['quality']['source']=='uploaded'

def test_stale_preview_and_wrong_workspace_cannot_write(workspace):
    p,sid=workspace;rows=day_rows(p,sid);preview=p.preview_data(sid,csv_from_rows(rows),'demo_upload')
    other=p.new_session()['session_id']
    with pytest.raises(BusinessError):p.apply_data(other,preview['preview_token'])
    d=decision(p,sid)
    with pytest.raises(BusinessError,match='重新预览'):p.apply_data(sid,preview['preview_token'])
    assert p.store.session(sid)['active_decision']==d['id']

def test_actual_observations_require_confirmation_and_learn_actual_next_action(workspace):
    p,sid=workspace;save(p,sid,day_rows(p,sid),'uploaded')
    d=decision(p,sid);p.execute(sid,d['id'],ExecuteInput())
    before=p.store.session(sid);preview=p.preview_data(sid,csv_from_rows(day_rows(p,sid,multiplier=1.3)),'uploaded')
    assert preview['feedback_allowed']
    with pytest.raises(BusinessError,match='已经执行'):p.apply_data(sid,preview['preview_token'])
    assert p.store.session(sid)==before
    receipt=p.apply_data(sid,preview['preview_token'],as_feedback=True)
    s=p.store.session(sid);parent=p.store.decision(sid,d['id']);child=p.store.decision(sid,s['active_decision'])
    assert receipt['feedback_saved'] and parent['status']=='awaiting_next'
    assert s['model']==before['model']
    assert parent['user_feedback']['mode']=='actual'
    assert len(parent['outcome_metrics']['channels'])==5
    assert parent['outcome_metrics']==s['metrics']==s['dataset']['daily'][-1]
    assert child['data_context']['revision']==s['dataset']['quality']['revision']==3
    assert p.apply_data(sid,preview['preview_token'],as_feedback=True)['idempotent']
    pending=p.preview_data(sid,csv_from_rows(day_rows(p,sid)),'uploaded')
    assert pending['blocked']
    with pytest.raises(BusinessError,match='等待下一实际动作'):p.apply_data(sid,pending['preview_token'])
    other=next(x for x in child['q_values'] if x['legal'] and x['name']!=child['action_name'])
    execution=ExecuteInput(action_name=other['name'],reason='按运营证据调整')
    p.execute(sid,child['id'],execution)
    assert p.store.decision(sid,d['id'])['transition']['next_action']==other['index']
    assert DeepSARSA.from_bytes(p.store.session(sid)['model']).updates==DeepSARSA.from_bytes(before['model']).updates+1
    p.execute(sid,child['id'],execution)
    assert DeepSARSA.from_bytes(p.store.session(sid)['model']).updates==DeepSARSA.from_bytes(before['model']).updates+1

def test_feedback_only_day_survives_old_data_edit_and_optional_costs(workspace):
    p,sid=workspace;d=decision(p,sid);p.execute(sid,d['id'],ExecuteInput())
    p.feedback(sid,d['id'],FeedbackInput(mode='simulation',terminal=True))
    latest=p.store.session(sid)['metrics']['date']
    row=dict(p.store.session(sid)['dataset']['rows'][0]);row['unit_cost']=10;row['forecast_revenue']=10000;row['revenue']+=10
    save(p,sid,[row])
    s=p.store.session(sid)
    assert s['metrics']['date']==latest and s['dataset']['daily'][-1]['observation_source']=='simulation'
    assert s['dataset']['quality']['latest_feedback_decision_id']==d['id']
    assert s['dataset']['revisions'][-1]['corrected_rows']==1

def test_explicit_feedback_date_validation_and_json_audit(workspace):
    p,sid=workspace;d=decision(p,sid);p.execute(sid,d['id'],ExecuteInput())
    body={'revenue':20000,'profit':2000,'roi':.2,'cac':40,'inventory_level':10000,'conversion_rate':.05}
    with pytest.raises(BusinessError,match='晚于'):p.feedback(sid,d['id'],FeedbackInput(outcome=body,observed_date=d['metrics']['date']))
    observed=(date.fromisoformat(d['metrics']['date'])+timedelta(days=4)).isoformat()
    request=FeedbackInput(outcome=body,terminal=True,observed_date=observed)
    result=p.feedback(sid,d['id'],request)
    assert result['decision']['outcome_metrics']['date']==observed
    assert result['decision']['user_feedback']['request']['observed_date']==observed
    assert p.feedback(sid,d['id'],request)['idempotent']

def test_preview_apply_routes_and_signed_recovery(workspace,tmp_path):
    p,sid=workspace;cfg=replace(AuthConfig.from_env(),secret='TEST_DATA_RECOVERY_'+('x'*40))
    c=TestClient(create_app(p,PhoneAuth(p,cfg)));h={'X-Session-Id':sid};rows=day_rows(p,sid)
    preview=c.post('/api/data/preview',headers=h,json={'rows':rows,'source':'demo_upload'})
    assert preview.status_code==200,preview.text
    token=preview.json()['preview_token']
    assert c.post('/api/data/apply',headers=h,json={'preview_token':token}).status_code==200
    assert c.post('/api/data/apply',headers=h,json={'preview_token':token}).json()['idempotent']
    assert c.post('/api/data/preview-upload',headers=h,files={'file':('update.csv',csv_from_rows(rows),'text/csv')},data={'source':'demo_upload'}).status_code==200
    invalid=dict(rows[0],clicks=0,orders=10)
    assert c.post('/api/data/preview',headers=h,json={'rows':[invalid]}).status_code==422
    archive=c.get('/api/workspace/backup',headers=h).json()
    p2=Platform(tmp_path/'fresh');c2=TestClient(create_app(p2,PhoneAuth(p2,cfg)))
    assert c2.post('/api/workspace/restore',json=archive).status_code==200
    assert p2.store.session(sid)['dataset']==p.store.session(sid)['dataset']
    assert c2.post('/api/data/apply',headers=h,json={'preview_token':token}).json()['idempotent']
    assert c.get('/api/data/template.csv').content.startswith(b'\xef\xbb\xbfdate,')

def test_blank_optional_columns_and_missing_latest_channels_are_explicit(workspace):
    p,sid=workspace;row=day_rows(p,sid)[0]
    for key in ['cogs','return_loss','unit_cost']:row.pop(key,None)
    import pandas as pd
    frame=pd.DataFrame([dict(row,cogs=None,return_loss=None)])
    preview=p.preview_data(sid,frame.to_csv(index=False).encode(),'uploaded')
    assert len(preview['after']['metrics']['channels'])==1
    assert preview['after']['quality']['estimates']
    assert any('最新观察日未提供' in w for w in preview['warnings'])
    assert len(p.store.session(sid)['dataset']['rows'])==300

def test_real_workspace_cannot_accept_test_upload(workspace):
    p,sid=workspace;save(p,sid,day_rows(p,sid),'uploaded')
    with pytest.raises(ValueError,match='测试更新请使用新演示工作区'):
        p.preview_data(sid,csv_from_rows(day_rows(p,sid)),'demo_upload')

def test_first_raw_real_update_preserves_real_feedback_only_day(workspace):
    p,sid=workspace;d=decision(p,sid);p.execute(sid,d['id'],ExecuteInput())
    p.feedback(sid,d['id'],FeedbackInput(terminal=True,outcome={
        'revenue':20000,'profit':2000,'roi':.2,'cac':40,'inventory_level':10000,'conversion_rate':.05}))
    actual_day=p.store.session(sid)['metrics']['date']
    save(p,sid,day_rows(p,sid),'uploaded')
    s=p.store.session(sid)
    assert len(s['dataset']['rows'])==5
    assert [day['date'] for day in s['dataset']['daily']]==[actual_day,s['metrics']['date']]

def test_partial_invalid_optional_value_is_not_silently_dropped(workspace):
    p,sid=workspace;rows=day_rows(p,sid)
    rows[0]['forecast_revenue']='invalid'
    with pytest.raises(ValueError,match='forecast_revenue'):csv_from_rows(rows)
