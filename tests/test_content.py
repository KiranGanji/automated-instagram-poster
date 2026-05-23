from __future__ import annotations

import json

import pytest

from src import content
from src.exceptions import ContentValidationError


def test_pick_next_item_returns_first_supported_file_sorted(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "010.png").write_text("", encoding="utf-8")
    (queue_dir / "001.JPEG").write_text("", encoding="utf-8")
    (queue_dir / "002.jpg").write_text("", encoding="utf-8")
    (queue_dir / "notes.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    item = content.pick_next_item("demo")

    assert item is not None
    assert item.identifier == "001.JPEG"
    assert item.media_type == "image"
    assert [path.name for path in item.paths] == ["001.JPEG"]


def test_pick_next_item_returns_reel(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "001.mp4").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        content,
        "_probe_video",
        lambda path: content.VideoMetadata(duration_seconds=10.0, width=1080, height=1920),
    )

    item = content.pick_next_item("demo")

    assert item is not None
    assert item.identifier == "001.mp4"
    assert item.media_type == "reel"
    assert [path.name for path in item.paths] == ["001.mp4"]


def test_pick_next_item_returns_carousel_with_sorted_children(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    carousel_dir = queue_dir / "004"
    carousel_dir.mkdir(parents=True)
    (carousel_dir / "02.jpg").write_text("", encoding="utf-8")
    (carousel_dir / "01.png").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    item = content.pick_next_item("demo")

    assert item is not None
    assert item.identifier == "004"
    assert item.media_type == "carousel"
    assert [path.name for path in item.paths] == ["01.png", "02.jpg"]


def test_pick_next_item_skips_unsupported_and_hidden_entries(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / ".DS_Store").write_text("", encoding="utf-8")
    (queue_dir / "001.txt").write_text("", encoding="utf-8")
    (queue_dir / "002.jpg").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    item = content.pick_next_item("demo")

    assert item is not None
    assert item.identifier == "002.jpg"
    assert item.media_type == "image"


def test_pick_next_item_skips_media_types_disabled_by_config(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "001.mp4").write_text("", encoding="utf-8")
    (queue_dir / "002.jpg").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    item = content.pick_next_item("demo", allowed_media_types=["image"])

    assert item is not None
    assert item.identifier == "002.jpg"
    assert item.media_type == "image"


@pytest.mark.parametrize("item_count", [1, 11])
def test_pick_next_item_rejects_invalid_carousel_size(tmp_path, monkeypatch, item_count):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    carousel_dir = queue_dir / "004"
    carousel_dir.mkdir(parents=True)
    for index in range(item_count):
        (carousel_dir / f"{index + 1:02}.jpg").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ContentValidationError) as exc_info:
        content.pick_next_item("demo")

    assert "Carousel 004 must contain between 2 and 10 items" in str(exc_info.value)


def test_pick_next_item_rejects_unsupported_carousel_child(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    carousel_dir = queue_dir / "004"
    carousel_dir.mkdir(parents=True)
    (carousel_dir / "01.jpg").write_text("", encoding="utf-8")
    (carousel_dir / "02.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ContentValidationError) as exc_info:
        content.pick_next_item("demo")

    assert "unsupported items: 02.txt" in str(exc_info.value)


def test_pick_next_item_rejects_reel_duration_outside_bounds(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "001.mp4").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        content,
        "_probe_video",
        lambda path: content.VideoMetadata(duration_seconds=91.0, width=1080, height=1920),
    )

    with pytest.raises(ContentValidationError) as exc_info:
        content.pick_next_item("demo")

    assert "must be between 3 and 90 seconds" in str(exc_info.value)


def test_resolve_caption_prefers_custom_and_falls_back_to_default(tmp_path, monkeypatch):
    channel_dir = tmp_path / "channels" / "demo"
    channel_dir.mkdir(parents=True)
    captions = {
        "default": "Default caption",
        "001.png": "Custom caption",
        "004": "Carousel caption",
    }
    (channel_dir / "captions.json").write_text(
        json.dumps(captions),
        encoding="utf-8",
    )

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    assert content.resolve_caption("demo", "001.png", "default") == ("Custom caption", "custom")
    assert content.resolve_caption("demo", "004", "default") == ("Carousel caption", "custom")
    assert content.resolve_caption("demo", "002.png", "default") == (
        "Default caption",
        "default",
    )
