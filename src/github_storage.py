from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

try:
    from .exceptions import GitHubAPIError
except ImportError:  # pragma: no cover - script execution fallback
    from exceptions import GitHubAPIError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GITHUB_API_BASE_URL = "https://api.github.com"


def get_signed_download_url(repo: str, path: str, github_token: str) -> str:
    if not github_token.strip():
        raise GitHubAPIError("Missing TOKEN or GITHUB_TOKEN for GitHub Contents API requests.")

    try:
        response = requests.get(
            f"{GITHUB_API_BASE_URL}/repos/{repo}/contents/{path}",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc
    payload = _parse_github_json(response)
    download_url = payload.get("download_url")
    if not isinstance(download_url, str) or not download_url.strip():
        raise GitHubAPIError(
            f"GitHub Contents API response did not include download_url for {path}: {payload!r}"
        )
    return download_url


def append_to_posted_log(channel_id: str, entry: dict[str, Any]) -> None:
    posted_path = PROJECT_ROOT / "channels" / channel_id / "posted.json"
    if not posted_path.exists():
        raise GitHubAPIError(f"Missing posted log file: {posted_path}")

    try:
        data = json.loads(posted_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(f"Invalid JSON in {posted_path}: {exc}") from exc

    if not isinstance(data, list):
        raise GitHubAPIError(f"Posted log must be a JSON array: {posted_path}")

    data.append(entry)
    temp_path = posted_path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(posted_path)


def git_move_and_commit(channel_id: str, filename: str, ig_media_id: str) -> None:
    queue_path = Path("channels") / channel_id / "queue" / filename
    posted_path = Path("channels") / channel_id / "posted" / filename
    posted_log_path = Path("channels") / channel_id / "posted.json"

    git_user_email = os.getenv(
        "GIT_USER_EMAIL", "github-actions[bot]@users.noreply.github.com"
    )
    git_user_name = os.getenv("GIT_USER_NAME", "github-actions[bot]")

    try:
        if not (PROJECT_ROOT / queue_path).exists():
            raise GitHubAPIError(f"Queue file is missing and cannot be moved: {queue_path}")
        (PROJECT_ROOT / posted_path.parent).mkdir(parents=True, exist_ok=True)
        _run_git_command(["git", "config", "user.email", git_user_email])
        _run_git_command(["git", "config", "user.name", git_user_name])
        _run_git_command(["git", "mv", str(queue_path), str(posted_path)])
        _run_git_command(["git", "add", str(posted_log_path)])
        _run_git_command(
            ["git", "commit", "-m", f"post: {channel_id} {filename} -> {ig_media_id}"]
        )
        _push_with_retry()
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        detail = stderr or stdout or str(exc)
        raise GitHubAPIError(f"Git operation failed: {detail}") from exc


def _push_with_retry(max_attempts: int = 3) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            _run_git_command(["git", "push"])
            return
        except subprocess.CalledProcessError:
            if attempt == max_attempts:
                raise
            time.sleep(2 ** (attempt - 1))


def _run_git_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _parse_github_json(response: requests.Response) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        message = f"GitHub API error {response.status_code}: {response.text}"
        if response.status_code in {401, 403}:
            message = f"{message}. Check TOKEN or GITHUB_TOKEN permissions."
        raise GitHubAPIError(message)

    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubAPIError(f"GitHub API returned non-JSON response: {response.text}") from exc

    if not isinstance(payload, dict):
        raise GitHubAPIError(f"GitHub API returned unexpected payload: {payload!r}")

    return payload
