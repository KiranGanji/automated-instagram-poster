from __future__ import annotations

from pathlib import Path

from src import post
from src.content import QueueItem
from src.exceptions import GitHubAPIError


def test_main_image_flow_skips_polling(monkeypatch, tmp_path):
    events: list[tuple] = []
    item = QueueItem(
        identifier="001.png",
        media_type="image",
        paths=[tmp_path / "channels" / "drifted-lines" / "queue" / "001.png"],
    )

    class FakeClient:
        def __init__(self, ig_user_id: str, access_token: str):
            events.append(("init", ig_user_id, access_token))

        def create_image_container(self, image_url: str, caption: str) -> str:
            events.append(("create_image", image_url, caption))
            return "container-1"

        def poll_container_status(self, *args, **kwargs):
            raise AssertionError("Image posts should not poll container status")

        def publish_container(self, container_id: str) -> str:
            events.append(("publish", container_id))
            return "media-1"

        def get_permalink(self, ig_media_id: str) -> str | None:
            events.append(("permalink", ig_media_id))
            return None

    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        item,
        events,
        FakeClient,
        queue_count=3,
    )

    assert post.main() == 0
    assert [event[0] for event in events] == [
        "init",
        "signed_url",
        "create_image",
        "publish",
        "permalink",
        "log",
        "git",
    ]
    assert events[-2] == ("log", "001.png", "image", None)
    assert events[-1] == ("git", "001.png", False, "image")


def test_main_reel_flow_polls_before_publish(monkeypatch, tmp_path):
    events: list[tuple] = []
    item = QueueItem(
        identifier="003.mp4",
        media_type="reel",
        paths=[tmp_path / "channels" / "drifted-lines" / "queue" / "003.mp4"],
    )

    class FakeClient:
        def __init__(self, ig_user_id: str, access_token: str):
            events.append(("init", ig_user_id, access_token))

        def create_reel_container(self, video_url: str, caption: str) -> str:
            events.append(("create_reel", video_url, caption))
            return "container-1"

        def poll_container_status(
            self,
            container_id: str,
            max_wait_seconds: int = 600,
            poll_interval: int = 5,
        ) -> str:
            events.append(("poll", container_id, max_wait_seconds, poll_interval))
            return "FINISHED"

        def publish_container(self, container_id: str) -> str:
            events.append(("publish", container_id))
            return "media-1"

        def get_permalink(self, ig_media_id: str) -> str | None:
            events.append(("permalink", ig_media_id))
            return None

    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        item,
        events,
        FakeClient,
        queue_count=2,
    )

    assert post.main() == 0
    assert [event[0] for event in events] == [
        "init",
        "signed_url",
        "create_reel",
        "poll",
        "publish",
        "permalink",
        "log",
        "git",
    ]
    assert events[-2] == ("log", "003.mp4", "reel", None)
    assert events[-1] == ("git", "003.mp4", False, "reel")


def test_main_carousel_flow_polls_parent_for_video_and_records_slide_count(
    monkeypatch,
    tmp_path,
):
    events: list[tuple] = []
    item = QueueItem(
        identifier="004",
        media_type="carousel",
        paths=[
            tmp_path / "channels" / "drifted-lines" / "queue" / "004" / "01.jpg",
            tmp_path / "channels" / "drifted-lines" / "queue" / "004" / "02.mp4",
            tmp_path / "channels" / "drifted-lines" / "queue" / "004" / "03.jpg",
        ],
    )

    class FakeClient:
        def __init__(self, ig_user_id: str, access_token: str):
            events.append(("init", ig_user_id, access_token))

        def create_carousel_child_container(self, media_url: str, is_video: bool) -> str:
            child_id = f"child-{len([event for event in events if event[0] == 'child']) + 1}"
            events.append(("child", media_url, is_video, child_id))
            return child_id

        def create_carousel_parent_container(self, children: list[str], caption: str) -> str:
            events.append(("parent", children, caption))
            return "parent-1"

        def poll_container_status(
            self,
            container_id: str,
            max_wait_seconds: int = 600,
            poll_interval: int = 5,
        ) -> str:
            events.append(("poll", container_id, max_wait_seconds, poll_interval))
            return "FINISHED"

        def publish_container(self, container_id: str) -> str:
            events.append(("publish", container_id))
            return "media-1"

        def get_permalink(self, ig_media_id: str) -> str | None:
            events.append(("permalink", ig_media_id))
            return None

    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        item,
        events,
        FakeClient,
        queue_count=1,
    )

    assert post.main() == 0
    assert [event[0] for event in events] == [
        "init",
        "signed_url",
        "child",
        "signed_url",
        "child",
        "signed_url",
        "child",
        "parent",
        "poll",
        "publish",
        "permalink",
        "log",
        "git",
    ]
    assert events[2][2] is False
    assert events[4][2] is True
    assert events[6][2] is False
    assert events[7] == ("parent", ["child-1", "child-2", "child-3"], "caption")
    assert events[-2] == ("log", "004", "carousel", 3)
    assert events[-1] == ("git", "004", True, "carousel")


def test_main_fails_before_publish_when_posted_log_is_invalid(monkeypatch, tmp_path):
    events: list[tuple] = []
    item = QueueItem(
        identifier="001.png",
        media_type="image",
        paths=[tmp_path / "channels" / "drifted-lines" / "queue" / "001.png"],
    )

    class FakeClient:
        def __init__(self, ig_user_id: str, access_token: str):
            events.append(("init", ig_user_id, access_token))

    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        item,
        events,
        FakeClient,
        queue_count=3,
    )
    monkeypatch.setattr(
        post,
        "validate_posted_log",
        lambda channel_id: (_ for _ in ()).throw(GitHubAPIError("bad posted log")),
    )

    assert post.main() == 2
    assert events == []


def _patch_main_dependencies(
    monkeypatch,
    tmp_path: Path,
    item: QueueItem,
    events: list[tuple],
    fake_client_class,
    queue_count: int,
) -> None:
    class FakeConfig:
        channel_id = "drifted-lines"
        secret_prefix = "DRIFTED_LINES"
        root_dir = tmp_path

        class Posting:
            enabled = True
            min_queue_warning = 14

        class Content:
            default_caption_key = "default"
            media_types = ["image", "reel", "carousel"]

        posting = Posting()
        content = Content()

    class FakeSecrets:
        ig_user_id = "123"
        ig_access_token = "access"

    monkeypatch.setattr(
        post.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {"channel": "drifted-lines", "dry_run": False},
        )(),
    )
    monkeypatch.setattr(post, "load_channel_config", lambda channel_id: FakeConfig())
    monkeypatch.setattr(post, "load_secrets", lambda prefix: FakeSecrets())
    monkeypatch.setattr(post, "count_queue_items", lambda channel_id, allowed_media_types=None: queue_count)
    monkeypatch.setattr(post, "pick_next_item", lambda channel_id, allowed_media_types=None: item)
    monkeypatch.setattr(post, "resolve_caption", lambda channel_id, filename, default_key: ("caption", "custom"))
    monkeypatch.setattr(post, "resolve_token", lambda: "token")
    monkeypatch.setattr(post, "require_env", lambda name: "repo/name")
    monkeypatch.setattr(post, "validate_posted_log", lambda channel_id: None)
    monkeypatch.setattr(
        post,
        "get_signed_download_url",
        lambda repo, path, github_token: events.append(("signed_url", path)) or f"https://example.com/{path}",
    )
    monkeypatch.setattr(post, "InstagramClient", fake_client_class)
    monkeypatch.setattr(
        post,
        "append_to_posted_log",
        lambda channel_id, entry: events.append(
            ("log", entry["filename"], entry["media_type"], entry.get("slide_count"))
        ),
    )
    monkeypatch.setattr(
        post,
        "git_move_and_commit",
        lambda channel_id, identifier, is_directory, ig_media_id, media_type: events.append(
            ("git", identifier, is_directory, media_type)
        ),
    )
