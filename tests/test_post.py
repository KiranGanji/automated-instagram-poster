from __future__ import annotations

import pytest

from src.exceptions import ConfigError
from src.post import resolve_token


def test_resolve_token_prefers_token_env(monkeypatch):
    monkeypatch.setenv("TOKEN", "token-value")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")

    assert resolve_token() == "token-value"


def test_resolve_token_falls_back_to_github_token(monkeypatch):
    monkeypatch.delenv("TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")

    assert resolve_token() == "github-token-value"


def test_resolve_token_requires_one_token_env(monkeypatch):
    monkeypatch.delenv("TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        resolve_token()

    assert "GITHUB_TOKEN" in str(exc_info.value)
