import pytest


@pytest.fixture(autouse=True)
def isolate_llm_accounts(monkeypatch):
    """Tests never spend a developer's real API credentials loaded from .env."""
    for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY',
                 'TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY', 'WECHAT_APP_ID', 'WECHAT_APP_SECRET',
                 'SMS_APP_ID', 'SMS_SIGN_NAME', 'SMS_TEMPLATE_ID', 'AUTH_SECRET'):
        monkeypatch.delenv(name, raising=False)
    for name in ('AUTH_REQUIRE_LOGIN', 'SMS_SEND_ENABLED', 'AUTH_STORAGE_CONFIRMED', 'WECHAT_RELEASE_CONFIRMED'):
        monkeypatch.setenv(name, 'false')
    monkeypatch.setenv('LLM_PROVIDER', 'auto')
    monkeypatch.setenv('LLM_ENABLED', 'true')
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '120')
    monkeypatch.setenv('OPENROUTER_MODEL', 'openrouter/free')
