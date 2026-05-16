from __future__ import annotations

from src import post


def test_main_polls_container_before_publish(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, ig_user_id: str, access_token: str):
            events.append(("init", ig_user_id))

        def create_image_container(self, image_url: str, caption: str) -> str:
            events.append(("create", image_url))
            return "container-1"

        def poll_container_status(
            self,
            container_id: str,
            max_wait_seconds: int = 300,
            poll_interval: int = 5,
        ) -> str:
            events.append(("poll", container_id))
            return "FINISHED"

        def publish_container(self, container_id: str) -> str:
            events.append(("publish", container_id))
            return "media-1"

        def get_permalink(self, ig_media_id: str) -> str | None:
            events.append(("permalink", ig_media_id))
            return None

    class FakeConfig:
        channel_id = "drifted-lines"
        secret_prefix = "DRIFTED_LINES"

        class Posting:
            enabled = True
            min_queue_warning = 14

        class Content:
            default_caption_key = "default"

        posting = Posting()
        content = Content()

    class FakeSecrets:
        ig_user_id = "123"
        ig_access_token = "access"

    monkeypatch.setattr(post.argparse.ArgumentParser, "parse_args", lambda self: type("Args", (), {"channel": "drifted-lines", "dry_run": False})())
    monkeypatch.setattr(post, "load_channel_config", lambda channel_id: FakeConfig())
    monkeypatch.setattr(post, "load_secrets", lambda prefix: FakeSecrets())
    monkeypatch.setattr(post, "list_queue_images", lambda channel_id: ["001.png"])
    monkeypatch.setattr(post, "resolve_caption", lambda channel_id, filename, default_key: ("caption", "custom"))
    monkeypatch.setattr(post, "resolve_token", lambda: "token")
    monkeypatch.setattr(post, "require_env", lambda name: "repo/name")
    monkeypatch.setattr(post, "get_signed_download_url", lambda repo, path, github_token: "https://example.com/001.png")
    monkeypatch.setattr(post, "InstagramClient", FakeClient)
    monkeypatch.setattr(post, "append_to_posted_log", lambda channel_id, entry: events.append(("log", entry["filename"])))
    monkeypatch.setattr(post, "git_move_and_commit", lambda channel_id, filename, ig_media_id: events.append(("git", filename)))

    assert post.main() == 0
    assert [event[0] for event in events] == [
        "init",
        "create",
        "poll",
        "publish",
        "permalink",
        "log",
        "git",
    ]
