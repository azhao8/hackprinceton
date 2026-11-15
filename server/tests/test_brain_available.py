"""The brain starts with a Claude key, or with no key at all when it runs locally (#81)."""

from app.__main__ import brain_available


def test_needs_a_key_for_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MIGUEL_LLM", raising=False)
    assert not brain_available()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert brain_available()


def test_local_needs_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MIGUEL_LLM", "local")
    assert brain_available()
