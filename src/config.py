from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from .exceptions import ConfigError
except ImportError:  # pragma: no cover - script execution fallback
    from exceptions import ConfigError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_MEDIA_TYPES = {"image", "reel", "carousel"}


@dataclass(frozen=True)
class ContentConfig:
    media_types: list[str]
    default_caption_key: str


@dataclass(frozen=True)
class PostingConfig:
    enabled: bool
    min_queue_warning: int


@dataclass(frozen=True)
class ChannelConfig:
    channel_id: str
    display_name: str
    secret_prefix: str
    content: ContentConfig
    posting: PostingConfig
    root_dir: Path

    @property
    def channel_dir(self) -> Path:
        return self.root_dir / "channels" / self.channel_id

    @property
    def queue_dir(self) -> Path:
        return self.channel_dir / "queue"

    @property
    def posted_dir(self) -> Path:
        return self.channel_dir / "posted"

    @property
    def captions_path(self) -> Path:
        return self.channel_dir / "captions.json"

    @property
    def posted_log_path(self) -> Path:
        return self.channel_dir / "posted.json"


@dataclass(frozen=True)
class ChannelSecrets:
    ig_access_token: str
    ig_user_id: str
    ig_app_id: str
    ig_app_secret: str


def load_channel_config(channel_id: str) -> ChannelConfig:
    config_path = PROJECT_ROOT / "channels" / channel_id / "config.yml"
    if not config_path.exists():
        raise ConfigError(f"Missing channel config: {config_path}")

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Config file must contain a mapping: {config_path}")

    raw_channel_id = _require_non_empty_string(data, "channel_id", config_path)
    if raw_channel_id != channel_id:
        raise ConfigError(
            f"Config channel_id '{raw_channel_id}' does not match folder '{channel_id}'."
        )

    display_name = _require_non_empty_string(data, "display_name", config_path)
    secret_prefix = _require_non_empty_string(data, "secret_prefix", config_path)

    content_data = _require_mapping(data, "content", config_path)
    posting_data = _require_mapping(data, "posting", config_path)

    media_types = content_data.get("media_types")
    if not isinstance(media_types, list) or not media_types or not all(
        isinstance(item, str) and item.strip() for item in media_types
    ):
        raise ConfigError(
            f"Field 'content.media_types' must be a non-empty list of strings in {config_path}."
        )
    normalized_media_types = [item.strip().lower() for item in media_types]
    invalid_media_types = [
        item for item in normalized_media_types if item not in SUPPORTED_MEDIA_TYPES
    ]
    if invalid_media_types:
        joined = ", ".join(sorted(set(invalid_media_types)))
        raise ConfigError(
            f"Field 'content.media_types' contains unsupported values in {config_path}: {joined}."
        )

    default_caption_key = _require_non_empty_string(
        content_data, "default_caption_key", config_path, parent="content"
    )

    enabled = posting_data.get("enabled")
    if not isinstance(enabled, bool):
        raise ConfigError(f"Field 'posting.enabled' must be a boolean in {config_path}.")

    min_queue_warning = posting_data.get("min_queue_warning")
    if not isinstance(min_queue_warning, int) or min_queue_warning < 0:
        raise ConfigError(
            f"Field 'posting.min_queue_warning' must be a non-negative integer in {config_path}."
        )

    return ChannelConfig(
        channel_id=channel_id,
        display_name=display_name,
        secret_prefix=secret_prefix,
        content=ContentConfig(
            media_types=normalized_media_types,
            default_caption_key=default_caption_key,
        ),
        posting=PostingConfig(
            enabled=enabled,
            min_queue_warning=min_queue_warning,
        ),
        root_dir=PROJECT_ROOT,
    )


def load_secrets(secret_prefix: str) -> ChannelSecrets:
    secret_names = {
        "ig_access_token": f"{secret_prefix}_IG_ACCESS_TOKEN",
        "ig_user_id": f"{secret_prefix}_IG_USER_ID",
        "ig_app_id": f"{secret_prefix}_IG_APP_ID",
        "ig_app_secret": f"{secret_prefix}_IG_APP_SECRET",
    }

    values: dict[str, str] = {}
    missing: list[str] = []

    for attr_name, env_name in secret_names.items():
        value = os.getenv(env_name, "").strip()
        if value:
            values[attr_name] = value
        else:
            missing.append(env_name)

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing required secrets: {joined}")

    return ChannelSecrets(**values)


def _require_mapping(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Field '{key}' must be a mapping in {path}.")
    return value


def _require_non_empty_string(
    data: dict[str, Any], key: str, path: Path, parent: str | None = None
) -> str:
    value = data.get(key)
    field_name = f"{parent}.{key}" if parent else key
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Field '{field_name}' must be a non-empty string in {path}.")
    return value.strip()
