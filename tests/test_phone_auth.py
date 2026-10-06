"""Real service boundaries are simulated only in tests; no live SMS is sent."""
from dataclasses import replace
import time
import json
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.service import Platform
from backend.phone_auth import PhoneAuth, AuthConfig, TencentSMS, COOKIE, PRIVACY_VERSION

class TestOnlySender:
    __test__=False
    def __init__(self): self.calls=[];self.fail=False
    def send(self,phone,code,challenge):
        self.calls.append((phone,code,challenge))
        if self.fail: raise RuntimeError('TEST_ONLY upstream failed')
        return {'provider_request_id':'TEST_ONLY','serial':'TEST_ONLY'}

@pytest.fixture
def auth_setup(tmp_path):
    p=Platform(tmp_path);sender=TestOnlySender();tick=[time.time()]
    config=AuthConfig('TEST_ONLY_'+'x'*40,True,True,True,'TEST_ONLY_ID','TEST_ONLY_KEY','TEST_APP','TEST_SIGN','TEST_TEMPLATE',100,'TEST_QUOTA',time.time()+10000)
    auth=PhoneAuth(p,config,sender,lambda:tick[0]);client=TestClient(create_app(p,auth))
    return p,auth,sender,tick,client

def request_code(client,phone='13800000000'):
    return client.post('/api/auth/sms/request',json={'phone':phone,'privacy_accepted':True,'privacy_version':PRIVACY_VERSION})

def login(client,sender,phone='13800000000'):
    r=request_code(client,phone);assert r.status_code==200,r.text
    r=client.post('/api/auth/sms/verify',json={'phone':phone,'challenge_id':r.json()['challenge_id'],
        'code':sender.calls[-1][1],'privacy_accepted':True,'privacy_version':PRIVACY_VERSION})
    assert r.status_code==200,r.text
    return r.json()

def test_disabled_provider_never_sends_or_returns_code(auth_setup):
    p,a,s,t,c=auth_setup;a.config=replace(a.config,sms_enabled=False)
    assert c.get('/api/auth/status').json()['sms_ready'] is False
    assert request_code(c).status_code==503
    assert not s.calls
    assert c.post('/api/session').status_code==401
    assert c.get('/api/health').status_code==200

def test_verified_account_owns_workspaces_and_relogin_preserves_history(auth_setup):
    p,a,s,t,c=auth_setup;first=login(c,s)
    headers={'X-Session-Id':first['session_id']}
    d=c.post('/api/decisions',headers=headers,json={'question':'库存偏高，如何在预算约束下消化库存？'}).json()
    assert d['decision_source']=='Deep SARSA'
    assert c.get('/api/dashboard',headers=headers).status_code==200
    assert c.get('/api/auth/me').json()['session_id']==first['session_id']
    c.post('/api/auth/logout');t[0]+=61
    second=login(c,s)
    assert second['session_id']==first['session_id']
    assert c.get('/api/decisions',headers=headers).json()[0]['id']==d['id']

def test_account_isolation_including_known_session_and_legacy_anonymous(auth_setup):
    p,a,s,t,c=auth_setup;one=login(c,s);c.cookies.clear();two=login(c,s,'13900000000')
    assert c.get('/api/dashboard',headers={'X-Session-Id':one['session_id']}).status_code==403
    assert c.get('/api/dashboard',headers={'X-Session-Id':two['session_id']}).status_code==200
    c.cookies.clear();a.config=replace(a.config,required=False)
    assert c.get('/api/dashboard',headers={'X-Session-Id':one['session_id']}).status_code==401
    assert c.post('/api/session').status_code==200

def test_expiration_attempt_limit_replay_and_no_plaintext_storage(auth_setup):
    p,a,s,t,c=auth_setup;r=request_code(c).json();code=s.calls[-1][1]
    body={'phone':'13800000000','challenge_id':r['challenge_id'],'code':code,'privacy_accepted':True,'privacy_version':PRIVACY_VERSION}
    assert code not in json.dumps(r)
    wrong='999999' if code!='999999' else '000000'
    for _ in range(5): assert c.post('/api/auth/sms/verify',json={**body,'code':wrong}).status_code==400
    assert c.post('/api/auth/sms/verify',json=body).status_code==400
    t[0]+=61;r=request_code(c).json();body.update(challenge_id=r['challenge_id'],code=s.calls[-1][1])
    assert c.post('/api/auth/sms/verify',json=body).status_code==200
    assert c.post('/api/auth/sms/verify',json=body).status_code==400
    c.cookies.clear();t[0]+=61;r=request_code(c).json();body.update(challenge_id=r['challenge_id'],code=s.calls[-1][1]);t[0]+=301
    assert c.post('/api/auth/sms/verify',json=body).status_code==400
    with p.store.connect() as db:
        stored=json.dumps([dict(x) for x in db.execute('SELECT * FROM auth_codes')])
        assert '13800000000' not in stored and body['code'] not in stored
        tokens=[dict(x) for x in db.execute('SELECT * FROM auth_tokens')]
        assert all(len(x['hash'])==64 for x in tokens)

def test_rate_limit_budget_ambiguity_and_no_automatic_retry(auth_setup):
    p,a,s,t,c=auth_setup;a.config=replace(a.config,quota=2)
    assert request_code(c).status_code==200
    assert request_code(c).status_code==429
    t[0]+=61;s.fail=True
    assert request_code(c).status_code==503
    t[0]+=61
    assert request_code(c).status_code==503
    assert len(s.calls)==2
    with p.store.connect() as db: assert db.execute("SELECT COUNT(*) FROM auth_codes WHERE status='failed'").fetchone()[0]==1

def test_provider_acceptance_checks_recipient_and_never_leaks_errors(auth_setup,monkeypatch):
    p,a,s,t,c=auth_setup;provider=TencentSMS(a.config);calls=[]
    def fake(url,**kwargs):
        calls.append((url,kwargs));return httpx.Response(200,json={'Response':{'SendStatusSet':[{'Code':'Ok','PhoneNumber':'+8613900000000','Fee':1}]}},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',fake)
    with pytest.raises(HTTPException) as error:provider.send('13800000000','123456','test-challenge')
    assert error.value.status_code==503
    assert '13800000000' not in error.value.detail and '123456' not in error.value.detail
    assert len(calls)==1 and calls[0][1]['headers']['X-TC-Version']=='2021-01-11'
    assert json.loads(calls[0][1]['content'])['PhoneNumberSet']==['+8613800000000']

def test_logout_expired_tokens_and_csrf(auth_setup):
    p,a,s,t,c=auth_setup;value=login(c,s);h={'X-Session-Id':value['session_id']}
    assert c.post('/api/data/demo',headers={**h,'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/auth/logout').status_code==200
    assert c.get('/api/dashboard',headers={**h,'Authorization':'Bearer '+value['access_token']}).status_code==401
    t[0]+=61;value=login(c,s);t[0]+=7*86400+1
    assert c.get('/api/auth/me',headers={'Authorization':'Bearer '+value['access_token']}).status_code==401

def test_privacy_invalid_phone_and_account_deletion(auth_setup):
    p,a,s,t,c=auth_setup
    base={'phone':'13800000000','privacy_version':PRIVACY_VERSION,'privacy_accepted':False}
    assert c.post('/api/auth/sms/request',json=base).status_code==422
    assert c.post('/api/auth/sms/request',json={**base,'privacy_accepted':True,'phone':'123'}).status_code==422
    assert not s.calls
    v=login(c,s)
    with p.store.connect() as db:
        db.execute('CREATE TABLE model_archive (session_id TEXT, archived TEXT, model BLOB, config TEXT)')
        db.execute('INSERT INTO model_archive VALUES (?,?,?,?)',(v['session_id'],'TEST_ONLY',b'test','{}'))
    assert c.delete('/api/auth/account').status_code==200
    with pytest.raises(KeyError):p.store.session(v['session_id'])
    assert c.get('/api/auth/me',headers={'Authorization':'Bearer '+v['access_token']}).status_code==401
    with p.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM auth_codes').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM model_archive').fetchone()[0]==0

def test_official_wechat_code_not_replaced_by_web_qr(auth_setup,monkeypatch):
    p,a,s,t,c=auth_setup
    monkeypatch.setenv('ADMIN_TOKEN','TEST_ONLY_ADMIN')
    headers={'X-Admin-Token':'TEST_ONLY_ADMIN'}
    assert c.get('/api/wechat/code').status_code==403
    monkeypatch.delenv('WECHAT_APP_ID',raising=False);monkeypatch.delenv('WECHAT_APP_SECRET',raising=False)
    assert c.get('/api/wechat/code',headers=headers).status_code==503
    monkeypatch.setenv('WECHAT_APP_ID','TEST_APPID');monkeypatch.setenv('WECHAT_APP_SECRET','TEST_SECRET')
    monkeypatch.setenv('WECHAT_RELEASE_CONFIRMED','false')
    assert c.get('/api/wechat/code',headers=headers).status_code==409
