import json
from types import SimpleNamespace

import pytest

from llm.service import LLMService


@pytest.fixture
def deepseek(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-test-key')
    monkeypatch.setenv('LLM_ENABLED', 'true')
    return LLMService()


def mock_sdk(monkeypatch, content, finish_reason='stop'):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )])

    def client(**kwargs):
        captured['base_url'] = kwargs['base_url']
        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))

    monkeypatch.setattr('openai.OpenAI', client)
    return captured


def signals(**extra):
    return json.dumps(dict(summary='库存积压', inventory_pressure='high',
        douyin_cac='unknown', repeat_purchase='unknown', holiday_index=None,
        competitor_intensity=None, platform_traffic_change=None,
        market_demand_index=None, evidence=['库存积压'], unknowns=[], **extra))


def test_deepseek_uses_json_contract_and_retains_evidence(deepseek, monkeypatch):
    captured = mock_sdk(monkeypatch, signals())
    out = deepseek.extract('库存积压', [{'id':'verified-source'}])
    assert out['source'] == 'LLM' and out['provider'] == 'deepseek'
    assert out['signals']['inventory_pressure'] == 'high'
    assert captured['base_url'] == 'https://api.deepseek.com'
    assert captured['response_format'] == {'type':'json_object'}
    assert captured['extra_body']['thinking'] == {'type':'disabled'}
    assert json.loads(captured['messages'][1]['content'])['company_background'] == [{'id':'verified-source'}]


@pytest.mark.parametrize('content,finish', [
    (signals(), 'length'),
    ('', 'stop'),
    (signals(selected_action='increase_price'), 'stop'),
    ('{"summary":"incomplete"}', 'stop'),
])
def test_invalid_or_truncated_response_is_never_used(deepseek, monkeypatch, content, finish):
    mock_sdk(monkeypatch, content, finish)
    out = deepseek.extract('库存积压')
    assert out['source'] == 'Rule parser'
    assert out['fallback_reason']
    assert 'fake-test-key' not in json.dumps(out)


def test_deepseek_cannot_override_sarsa_action(deepseek, monkeypatch):
    mock_sdk(monkeypatch, json.dumps(dict(selected_action='increase_price',
        summary='错误动作', reasons=[], watch_metrics=[], limitations=[])))
    record = dict(action_name='keep_strategy', action_label='保持策略',
        q_selected=.2, expected_reward={}, metrics={}, bias=[], mask_reasons={})
    out = deepseek.explain(record)
    assert out['source'] == 'Template' and out['selected_action'] == 'keep_strategy'


def test_provider_configuration_never_exposes_keys(deepseek, monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'auto')
    assert deepseek.status()['provider'] == 'deepseek'
    assert 'fake-test-key' not in json.dumps(deepseek.status())
    monkeypatch.setenv('LLM_PROVIDER', 'unsupported')
    assert not deepseek.available
