from __future__ import annotations

import textwrap

import pytest

from src import config as config_module
from src.config import load_channel_config, load_secrets
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


def test_load_channel_config_rejects_unsupported_media_types(tmp_path, monkeypatch):
    channel_dir = tmp_path / "channels" / "demo"
    channel_dir.mkdir(parents=True)
    (channel_dir / "config.yml").write_text(
        textwrap.dedent(
            """
            channel_id: demo
            display_name: "Demo"
            secret_prefix: DEMO
            content:
              media_types: [image, story]
              default_caption_key: default
            posting:
              enabled: true
              min_queue_warning: 1
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ConfigError) as exc_info:
        load_channel_config("demo")

    assert "unsupported values" in str(exc_info.value)
