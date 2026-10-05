import pytest


@pytest.fixture(autouse=True)
def isolate_llm_accounts(monkeypatch):
    """Tests never spend a developer's real API credentials loaded from .env."""
    for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('LLM_PROVIDER', 'auto')
    monkeypatch.setenv('LLM_ENABLED', 'true')
    monkeypatch.setenv('LLM_DAILY_CALL_LIMIT', '120')
    monkeypatch.setenv('OPENROUTER_MODEL', 'openrouter/free')
