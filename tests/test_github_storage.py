from __future__ import annotations

from src import github_storage


def test_git_move_and_commit_creates_posted_dir_before_git_mv(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "001.png").write_text("image", encoding="utf-8")
    posted_log = tmp_path / "channels" / "demo" / "posted.json"
    posted_log.write_text("[]\n", encoding="utf-8")

    commands: list[list[str]] = []

    def fake_run_git_command(command: list[str]):
        if command[:2] == ["git", "mv"]:
            assert (tmp_path / "channels" / "demo" / "posted").exists()
        commands.append(command)
        return None

    monkeypatch.setattr(github_storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(github_storage, "_run_git_command", fake_run_git_command)
    monkeypatch.setattr(github_storage, "_push_with_retry", lambda max_attempts=3: None)

    github_storage.git_move_and_commit("demo", "001.png", False, "ig-123", "image")

    assert ["git", "mv", "channels/demo/queue/001.png", "channels/demo/posted/001.png"] in commands
    assert ["git", "commit", "-m", "post: demo image 001.png -> ig-123"] in commands


def test_git_move_and_commit_accepts_directory_moves(tmp_path, monkeypatch):
    queue_dir = tmp_path / "channels" / "demo" / "queue" / "004"
    queue_dir.mkdir(parents=True)
    (queue_dir / "01.jpg").write_text("image", encoding="utf-8")
    posted_log = tmp_path / "channels" / "demo" / "posted.json"
    posted_log.write_text("[]\n", encoding="utf-8")

    commands: list[list[str]] = []

    monkeypatch.setattr(github_storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(github_storage, "_run_git_command", lambda command: commands.append(command))
    monkeypatch.setattr(github_storage, "_push_with_retry", lambda max_attempts=3: None)

    github_storage.git_move_and_commit("demo", "004", True, "ig-456", "carousel")

    assert ["git", "mv", "channels/demo/queue/004", "channels/demo/posted/004"] in commands
    assert ["git", "commit", "-m", "post: demo carousel 004 -> ig-456"] in commands
