from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from .exceptions import ConfigError, ContentValidationError
except ImportError:  # pragma: no cover - script execution fallback
    from exceptions import ConfigError, ContentValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
SUPPORTED_MEDIA_TYPES = {"image", "reel", "carousel"}
REEL_MIN_DURATION_SECONDS = 3
REEL_MAX_DURATION_SECONDS = 90
CAROUSEL_MIN_ITEMS = 2
CAROUSEL_MAX_ITEMS = 10
CAROUSEL_VIDEO_MAX_DURATION_SECONDS = 60
FILE_SIZE_WARNING_BYTES = 100 * 1024 * 1024
FILE_SIZE_ERROR_BYTES = 500 * 1024 * 1024

LOGGER = logging.getLogger(__name__)
_HAS_WARNED_FFPROBE_UNAVAILABLE = False


@dataclass(frozen=True)
class QueueItem:
    identifier: str
    media_type: Literal["image", "reel", "carousel"]
    paths: list[Path]


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float | None
    width: int | None
    height: int | None


def list_queue_images(channel_id: str) -> list[str]:
    queue_dir = _get_queue_dir(channel_id)
    files = [
        path.name
        for path in queue_dir.iterdir()
        if path.is_file()
        and not _is_hidden(path)
        and _detect_single_media_type(path) == "image"
    ]
    return sorted(files)


def count_queue_items(channel_id: str, allowed_media_types: list[str] | None = None) -> int:
    allowed = _normalize_media_types(allowed_media_types)
    return sum(
        1
        for entry in _list_queue_entries(channel_id)
        if _entry_media_type(entry) in allowed
    )


def pick_next_image(channel_id: str) -> str | None:
    item = pick_next_item(channel_id, allowed_media_types=["image"])
    return item.identifier if item else None


def pick_next_item(
    channel_id: str,
    allowed_media_types: list[str] | None = None,
) -> QueueItem | None:
    allowed = _normalize_media_types(allowed_media_types)

    for entry in _list_queue_entries(channel_id):
        media_type = _entry_media_type(entry)
        if media_type is None:
            LOGGER.warning("Skipping unsupported queue entry: %s", entry.name)
            continue

        if media_type not in allowed:
            LOGGER.warning(
                "Skipping %s because media type '%s' is not enabled for this channel.",
                entry.name,
                media_type,
            )
            continue

        if media_type == "carousel":
            paths = _validate_carousel_directory(entry)
            return QueueItem(identifier=entry.name, media_type="carousel", paths=paths)

        if media_type == "reel":
            _validate_reel(entry)

        return QueueItem(identifier=entry.name, media_type=media_type, paths=[entry])

    return None


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


def _get_queue_dir(channel_id: str) -> Path:
    queue_dir = PROJECT_ROOT / "channels" / channel_id / "queue"
    if not queue_dir.exists():
        raise ConfigError(f"Queue directory does not exist: {queue_dir}")
    return queue_dir


def _list_queue_entries(channel_id: str) -> list[Path]:
    queue_dir = _get_queue_dir(channel_id)
    return sorted(
        [path for path in queue_dir.iterdir() if not _is_hidden(path)],
        key=lambda path: path.name,
    )


def _entry_media_type(path: Path) -> Literal["image", "reel", "carousel"] | None:
    if path.is_dir():
        return "carousel"
    if not path.is_file():
        return None
    return _detect_single_media_type(path)


def _detect_single_media_type(path: Path) -> Literal["image", "reel"] | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "reel"
    return None


def _normalize_media_types(allowed_media_types: list[str] | None) -> set[str]:
    if not allowed_media_types:
        return set(SUPPORTED_MEDIA_TYPES)
    return {
        media_type.strip().lower()
        for media_type in allowed_media_types
        if media_type.strip().lower() in SUPPORTED_MEDIA_TYPES
    }


def _validate_reel(path: Path) -> None:
    _validate_file_size(path)

    metadata = _probe_video(path)
    if metadata is None:
        return

    duration = _require_duration(metadata, path, "Reel")
    if duration < REEL_MIN_DURATION_SECONDS or duration > REEL_MAX_DURATION_SECONDS:
        raise ContentValidationError(
            f"Reel {path.name} must be between {REEL_MIN_DURATION_SECONDS} and "
            f"{REEL_MAX_DURATION_SECONDS} seconds; found {duration:.2f} seconds."
        )

    if metadata.width and metadata.height and not _is_nine_by_sixteen(
        metadata.width,
        metadata.height,
    ):
        LOGGER.warning(
            "Reel %s has aspect ratio %sx%s; Instagram may crop or letterbox it.",
            path.name,
            metadata.width,
            metadata.height,
        )


def _validate_file_size(path: Path) -> None:
    size_bytes = path.stat().st_size
    if size_bytes > FILE_SIZE_ERROR_BYTES:
        raise ContentValidationError(
            f"Video file {path.name} exceeds the 500 MB limit: {_format_bytes(size_bytes)}."
        )
    if size_bytes > FILE_SIZE_WARNING_BYTES:
        LOGGER.warning(
            "Video file %s is larger than 100 MB (%s); consider reducing the size.",
            path.name,
            _format_bytes(size_bytes),
        )


def _validate_carousel_directory(path: Path) -> list[Path]:
    children = sorted(
        [child for child in path.iterdir() if not _is_hidden(child)],
        key=lambda child: child.name,
    )

    unsupported = [
        child.name
        for child in children
        if not child.is_file() or _detect_single_media_type(child) is None
    ]
    if unsupported:
        joined = ", ".join(unsupported)
        raise ContentValidationError(
            f"Carousel {path.name} contains unsupported items: {joined}."
        )

    if len(children) < CAROUSEL_MIN_ITEMS or len(children) > CAROUSEL_MAX_ITEMS:
        raise ContentValidationError(
            f"Carousel {path.name} must contain between {CAROUSEL_MIN_ITEMS} and "
            f"{CAROUSEL_MAX_ITEMS} items; found {len(children)}."
        )

    for child in children:
        if _detect_single_media_type(child) == "reel":
            _validate_carousel_video(child, path.name)

    return children


def _validate_carousel_video(path: Path, carousel_name: str) -> None:
    metadata = _probe_video(path)
    if metadata is None:
        return

    duration = _require_duration(metadata, path, "Carousel video")
    if duration > CAROUSEL_VIDEO_MAX_DURATION_SECONDS:
        raise ContentValidationError(
            f"Carousel {carousel_name} contains video {path.name} longer than "
            f"{CAROUSEL_VIDEO_MAX_DURATION_SECONDS} seconds: {duration:.2f} seconds."
        )


def _probe_video(path: Path) -> VideoMetadata | None:
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        _warn_ffprobe_unavailable()
        return None

    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ffprobe error"
        raise ContentValidationError(f"ffprobe failed for {path.name}: {detail}")

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ContentValidationError(
            f"ffprobe returned invalid JSON for {path.name}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ContentValidationError(f"ffprobe returned an unexpected payload for {path.name}.")

    streams = payload.get("streams")
    video_stream = None
    if isinstance(streams, list):
        video_stream = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ),
            None,
        )

    width = _coerce_int(video_stream.get("width")) if isinstance(video_stream, dict) else None
    height = _coerce_int(video_stream.get("height")) if isinstance(video_stream, dict) else None

    duration = None
    if isinstance(video_stream, dict):
        duration = _coerce_float(video_stream.get("duration"))
    if duration is None:
        format_data = payload.get("format")
        if isinstance(format_data, dict):
            duration = _coerce_float(format_data.get("duration"))

    return VideoMetadata(duration_seconds=duration, width=width, height=height)


def _require_duration(metadata: VideoMetadata, path: Path, label: str) -> float:
    if metadata.duration_seconds is None:
        raise ContentValidationError(f"{label} {path.name} is missing duration metadata.")
    return metadata.duration_seconds


def _warn_ffprobe_unavailable() -> None:
    global _HAS_WARNED_FFPROBE_UNAVAILABLE
    if _HAS_WARNED_FFPROBE_UNAVAILABLE:
        return
    LOGGER.warning("ffprobe is unavailable; skipping local video validation.")
    _HAS_WARNED_FFPROBE_UNAVAILABLE = True


def _is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def _is_nine_by_sixteen(width: int, height: int) -> bool:
    return math.isclose(width / height, 9 / 16, rel_tol=0.03)


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _format_bytes(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"
