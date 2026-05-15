from __future__ import annotations

import pytest

from src.config import load_secrets
from src.exceptions import ConfigError


def test_load_secrets_reports_all_missing_env_vars(monkeypatch):
    prefix = "DRIFTED_LINES"
    for suffix in ("IG_ACCESS_TOKEN", "IG_USER_ID", "IG_APP_ID", "IG_APP_SECRET"):
        monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_secrets(prefix)

    message = str(exc_info.value)
    assert f"{prefix}_IG_ACCESS_TOKEN" in message
    assert f"{prefix}_IG_USER_ID" in message
    assert f"{prefix}_IG_APP_ID" in message
    assert f"{prefix}_IG_APP_SECRET" in message
