from fastapi.testclient import TestClient
from backend.access import access_info, usable_address
from backend.main import create_app
from backend.service import Platform

def test_company_evidence_persists_and_decision_keeps_sources(tmp_path):
    p=Platform(tmp_path)
    rows=p.store.company_evidence()
    assert len(rows)==10
    assert next(r for r in rows if r['id']=='half_profit')['value']==249032902.02
    matches=p.store.retrieve_company_evidence('三只松鼠平台推广费用与利润')
    assert any('平台' in r['metric'] for r in matches)
    c=TestClient(create_app(p))
    sid=c.post('/api/session').json()['session_id']; h={'X-Session-Id':sid}
    before=c.get('/api/dashboard',headers=h).json()['metrics']
    response=c.post('/api/decisions',headers=h,json={'question':'三只松鼠平台推广费增加，怎么控制获客成本？','reward_profile':'acquisition_efficiency'})
    assert response.status_code==200,response.text
    d=response.json()
    assert d['company_evidence'] and all(r['source_url'].startswith('https://') for r in d['company_evidence'])
    assert c.get('/api/dashboard',headers=h).json()['metrics']==before
    reloaded=Platform(tmp_path)
    assert reloaded.store.decision(sid,d['id'])['company_evidence']==d['company_evidence']
    assert c.get('/api/company').json()['company']=='三只松鼠股份有限公司'

def test_localhost_is_not_a_phone_share_address(monkeypatch,tmp_path):
    monkeypatch.setenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')
    monkeypatch.delenv('RENDER_EXTERNAL_URL',raising=False)
    monkeypatch.setenv('HOST','127.0.0.1')
    monkeypatch.setenv('LAN_ADDRESS','192.168.1.199')
    monkeypatch.setenv('PORT','8000')
    assert access_info()['share_url'] is None
    for address in ['http://localhost:8000','http://127.0.0.1:8000','http://[::1]:8000','file:///tmp/x','http://0.0.0.0:8000']:
        assert not usable_address(address)
    c=TestClient(create_app(Platform(tmp_path)))
    assert c.get('/api/share/qr.png').status_code==409

def test_lan_and_public_addresses_generate_real_qr(monkeypatch,tmp_path):
    monkeypatch.setenv('HOST','0.0.0.0'); monkeypatch.setenv('PORT','8123')
    monkeypatch.setenv('LAN_ADDRESS','192.168.1.199'); monkeypatch.setenv('PUBLIC_BASE_URL','')
    monkeypatch.delenv('RENDER_EXTERNAL_URL',raising=False)
    a=access_info()
    assert a['mode']=='lan' and a['share_url']=='http://192.168.1.199:8123'
    c=TestClient(create_app(Platform(tmp_path)))
    response=c.get('/api/share/qr.png')
    assert response.status_code==200 and response.content.startswith(b'\x89PNG\r\n\x1a\n')
    monkeypatch.setenv('PUBLIC_BASE_URL','https://marketing-example.onrender.com')
    assert access_info()['mode']=='public'
    assert c.get('/api/access').json()['share_url']=='https://marketing-example.onrender.com'
    monkeypatch.setenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')
    monkeypatch.setenv('RENDER_EXTERNAL_URL','https://rendered-example.onrender.com')
    assert c.get('/api/access').json()['share_url']=='https://rendered-example.onrender.com'
