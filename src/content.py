from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .exceptions import ConfigError
except ImportError:  # pragma: no cover - script execution fallback
    from exceptions import ConfigError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def list_queue_images(channel_id: str) -> list[str]:
    queue_dir = PROJECT_ROOT / "channels" / channel_id / "queue"
    if not queue_dir.exists():
        raise ConfigError(f"Queue directory does not exist: {queue_dir}")

    files = [
        path.name
        for path in queue_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(files)


def pick_next_image(channel_id: str) -> str | None:
    files = list_queue_images(channel_id)
    return files[0] if files else None


def resolve_caption(channel_id: str, filename: str, default_key: str) -> tuple[str, str]:
    captions_path = PROJECT_ROOT / "channels" / channel_id / "captions.json"
    if not captions_path.exists():
        raise ConfigError(f"Missing captions file: {captions_path}")

    try:
        data = json.loads(captions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {captions_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Captions file must contain a JSON object: {captions_path}")

    if default_key not in data:
        raise ConfigError(f"Default caption key '{default_key}' is missing in {captions_path}")

    if filename in data:
        caption = _validate_caption(data, filename, captions_path)
        return caption, "custom"

    caption = _validate_caption(data, default_key, captions_path)
    return caption, "default"


def _validate_caption(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Caption '{key}' must be a non-empty string in {path}")
    return value
