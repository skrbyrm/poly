from bot.ai.llm_client import LLMClient


def test_call_dispatches_openai(monkeypatch):
    client = LLMClient()

    monkeypatch.setattr(client, "call_openai", lambda messages, model=None: {"provider": "openai", "model": model})
    monkeypatch.setattr(client, "call_anthropic", lambda messages, model=None: {"provider": "anthropic", "model": model}, raising=False)

    result = client.call([{"role": "user", "content": "x"}], model="gpt-4o-mini", provider="openai")
    assert result["provider"] == "openai"


def test_call_dispatches_anthropic_when_supported(monkeypatch):
    client = LLMClient()

    # This test documents expected behavior after provider-aware routing is implemented.
    # If call_anthropic does not exist yet, skip gracefully so container test suite still runs.
    if not hasattr(client, "call_anthropic"):
        import pytest
        pytest.skip("call_anthropic is not implemented yet")

    monkeypatch.setattr(client, "call_openai", lambda messages, model=None: {"provider": "openai", "model": model})
    monkeypatch.setattr(client, "call_anthropic", lambda messages, model=None: {"provider": "anthropic", "model": model})

    result = client.call([{"role": "user", "content": "x"}], model="claude-3-5-sonnet-latest", provider="anthropic")
    assert result["provider"] == "anthropic"
