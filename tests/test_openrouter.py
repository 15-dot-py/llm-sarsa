import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.schemas import DecisionInput
from backend.service import Platform
from llm.service import LLMService


@pytest.fixture
def free_llm(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-test-key')
    return LLMService()


def signals():
    return dict(summary='流量下降', inventory_pressure='unknown', douyin_cac='unknown',
        repeat_purchase='unknown', holiday_index=None, competitor_intensity=None,
        platform_traffic_change=-.2, market_demand_index=None, evidence=['流量下降'], unknowns=[])


def sdk(monkeypatch, content=None, finish='stop'):
    calls=[]

    def client(**settings):
        def create(**request):
            calls.append(dict(settings=settings, request=request))
            payload=json.loads(request['messages'][1]['content'])
            data=content
            if data is None:
                data=json.dumps(dict(selected_action=payload['action_name'], summary='解释已选动作',
                    reasons=['依据已提供的指标'], watch_metrics=['营销贡献利润'], limitations=['合成数据']), ensure_ascii=False) if 'action_name' in payload else json.dumps(signals(),ensure_ascii=False)
            return SimpleNamespace(model='qwen/test-model:free', choices=[SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=data))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr('openai.OpenAI', client)
    return calls


def test_free_route_uses_zero_price_and_records_actual_response_model(free_llm,monkeypatch):
    calls=sdk(monkeypatch)
    out=free_llm.extract('流量下降，怎样调整营销？')
    assert out['source']=='LLM' and out['provider']=='openrouter'
    assert out['model']=='qwen/test-model:free' and out['requested_model']=='openrouter/free'
    request=calls[0]['request']
    assert request['model']=='openrouter/free'
    assert request['response_format']['json_schema']['strict'] is True
    assert request['extra_body']['provider']['max_price']=={'prompt':0,'completion':0,'request':0}
    assert request['extra_body']['provider']['require_parameters'] is True
    assert calls[0]['settings']['base_url']=='https://openrouter.ai/api/v1'
    status=free_llm.status()
    assert status['last_used_model']==out['model'] and status['last_success_at']
    assert status['daily_limit']==50 and status['free_only']
    assert 'private-test-key' not in json.dumps([out,status])


@pytest.mark.parametrize('model',['openai/gpt-4.1-mini','openrouter/auto','openrouter/auto:free'])
def test_paid_and_ambiguous_router_models_are_blocked_before_network(free_llm,monkeypatch,model):
    monkeypatch.setenv('OPENROUTER_MODEL',model)
    calls=sdk(monkeypatch)
    assert free_llm.extract('如何提高销售收入？')['source']=='Rule parser'
    assert calls==[] and not free_llm.status()['available']
    assert '仅允许' in free_llm.status()['mode']


@pytest.mark.parametrize('content,finish',[
    ('{}','stop'),
    (json.dumps(dict(signals(),selected_action='increase_price')),'stop'),
    (json.dumps(signals()),'length'),
    ('','stop'),
])
def test_invalid_or_truncated_free_output_is_rejected(free_llm,monkeypatch,content,finish):
    sdk(monkeypatch,content,finish)
    out=free_llm.extract('流量下降，怎样调整营销？')
    assert out['source']=='Rule parser' and out['fallback_reason']
    assert 'private-test-key' not in json.dumps([out,free_llm.status()])


def test_free_service_respects_daily_limit_and_resets_on_utc_day(free_llm,monkeypatch):
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT','1')
    calls=sdk(monkeypatch)
    assert free_llm.extract('流量下降')['source']=='LLM'
    assert free_llm.extract('流量下降')['source']=='Rule parser'
    assert len(calls)==1 and '当日调用上限' in free_llm.status()['mode']
    free_llm._day=datetime.now(timezone.utc).date()-timedelta(days=1)
    assert free_llm.status()['calls_today']==0 and free_llm.available
    assert free_llm.extract('流量下降')['source']=='LLM'


def test_missing_free_key_never_uses_old_openai_credentials(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','openrouter')
    monkeypatch.setenv('OPENAI_API_KEY','old-private-key')
    llm=LLMService();calls=sdk(monkeypatch)
    out=llm.extract('如何提高销售收入？')
    assert not llm.status()['configured'] and calls==[]
    assert 'OpenRouter' in out['fallback_reason'] and 'old-private-key' not in json.dumps(out)


def test_free_pipeline_retains_sarsa_action_and_budget_constraint(tmp_path,free_llm,monkeypatch):
    sdk(monkeypatch)
    platform=Platform(tmp_path);sid=platform.new_session()['session_id']
    out=platform.decide(sid,DecisionInput(question='流量下降，如何提高销售收入？不要增加淘宝预算。',reward_profile='auto'))
    assert out['decision_source']=='Deep SARSA'
    assert out['semantic']['source']=='LLM' and out['semantic']['model']=='qwen/test-model:free'
    assert out['explanation_source']=='LLM' and out['explanation']['model']=='qwen/test-model:free'
    assert out['explanation']['selected_action']==out['action_name']
    assert not next(q for q in out['q_values'] if q['name']=='increase_new_customer_acquisition')['legal']
    assert out['action_name']!='increase_new_customer_acquisition'


def test_free_explanation_cannot_change_selected_action(free_llm,monkeypatch):
    sdk(monkeypatch,json.dumps(dict(selected_action='increase_price',summary='错误动作',reasons=[],watch_metrics=[],limitations=[])))
    out=free_llm.explain(dict(action_name='keep_strategy',action_label='保持策略',q_selected=.1,
        expected_reward={},metrics={},bias=[],mask_reasons={}))
    assert out['source']=='Template' and out['selected_action']=='keep_strategy'
