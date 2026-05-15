from __future__ import annotations

import json

from src import content


def test_pick_next_image_returns_first_supported_file_sorted(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "010.png").write_text("", encoding="utf-8")
    (queue_dir / "001.JPEG").write_text("", encoding="utf-8")
    (queue_dir / "002.jpg").write_text("", encoding="utf-8")
    (queue_dir / "notes.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    assert content.pick_next_image("demo") == "001.JPEG"


def test_pick_next_image_returns_none_for_empty_queue(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    assert content.pick_next_image("demo") is None


def test_resolve_caption_prefers_custom_and_falls_back_to_default(tmp_path, monkeypatch):
    channel_dir = tmp_path / "channels" / "demo"
    channel_dir.mkdir(parents=True)
    captions = {
        "default": "Default caption",
        "001.png": "Custom caption",
    }
    (channel_dir / "captions.json").write_text(
        json.dumps(captions),
        encoding="utf-8",
    )

    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)

    assert content.resolve_caption("demo", "001.png", "default") == ("Custom caption", "custom")
    assert content.resolve_caption("demo", "002.png", "default") == (
        "Default caption",
        "default",
    )
