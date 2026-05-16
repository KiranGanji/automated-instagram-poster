from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
from typing import Any

import requests
from nacl import encoding, public

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

try:
    from .config import ConfigError, load_channel_config, load_secrets
    from .exceptions import GitHubAPIError, InstagramAPIError
    from .instagram import refresh_access_token
except ImportError:  # pragma: no cover - script execution fallback
    from config import ConfigError, load_channel_config, load_secrets
    from exceptions import GitHubAPIError, InstagramAPIError
    from instagram import refresh_access_token


GITHUB_API_BASE_URL = "https://api.github.com"


if load_dotenv is not None:
    load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the Instagram token for one channel.")
    parser.add_argument("--channel", required=True, help="Channel ID to refresh.")
    args = parser.parse_args()

    logger = configure_logging(args.channel)

    try:
        config = load_channel_config(args.channel)
        secrets = load_secrets(config.secret_prefix)
        repository = require_env("GITHUB_REPOSITORY")
        github_token = (
            os.getenv("SECRETS_WRITE_PAT", "").strip()
            or os.getenv("TOKEN", "").strip()
            or require_env("GITHUB_TOKEN")
        )

        response = refresh_access_token(secrets.ig_access_token)
        new_token = response.get("access_token")
        if not isinstance(new_token, str) or not new_token.strip():
            raise InstagramAPIError(f"Refresh response missing access_token: {response!r}")

        update_repo_secret(
            repo=repository,
            secret_name=f"{config.secret_prefix}_IG_ACCESS_TOKEN",
            secret_value=new_token,
            github_token=github_token,
        )
        logger.info("Refreshed and updated %s_IG_ACCESS_TOKEN.", config.secret_prefix)
        return 0

    except ConfigError as exc:
        emit_github_actions_error(str(exc))
        logger.error(str(exc))
        return 1
    except (GitHubAPIError, InstagramAPIError) as exc:
        emit_github_actions_error(str(exc))
        logger.error(str(exc))
        return 2
    except Exception:
        emit_github_actions_error("Unexpected error during token refresh.")
        logger.exception("Unexpected error during token refresh.")
        return 3


def configure_logging(channel_id: str) -> logging.LoggerAdapter:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(channel)s] %(message)s",
        force=True,
    )
    return logging.LoggerAdapter(logging.getLogger("token_refresh"), {"channel": channel_id})


def update_repo_secret(
    repo: str,
    secret_name: str,
    secret_value: str,
    github_token: str,
) -> None:
    key_payload = get_repo_public_key(repo, github_token)
    encrypted_value = encrypt_secret(secret_value, key_payload["key"])

    try:
        response = requests.put(
            f"{GITHUB_API_BASE_URL}/repos/{repo}/actions/secrets/{secret_name}",
            headers=github_headers(github_token),
            json={
                "encrypted_value": encrypted_value,
                "key_id": key_payload["key_id"],
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc

    if response.status_code not in {201, 204}:
        message = f"GitHub API error {response.status_code}: {response.text}"
        if response.status_code in {401, 403}:
            message = f"{message}. Check SECRETS_WRITE_PAT, TOKEN, or GITHUB_TOKEN permissions."
        raise GitHubAPIError(message)


def get_repo_public_key(repo: str, github_token: str) -> dict[str, str]:
    try:
        response = requests.get(
            f"{GITHUB_API_BASE_URL}/repos/{repo}/actions/secrets/public-key",
            headers=github_headers(github_token),
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc
    payload = parse_github_json(response)

    key = payload.get("key")
    key_id = payload.get("key_id")
    if not isinstance(key, str) or not isinstance(key_id, str):
        raise GitHubAPIError(f"GitHub public key response missing key fields: {payload!r}")
    return {"key": key, "key_id": key_id}


def encrypt_secret(secret_value: str, base64_public_key: str) -> str:
    public_key = public.PublicKey(base64_public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def github_headers(github_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def parse_github_json(response: requests.Response) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        message = f"GitHub API error {response.status_code}: {response.text}"
        if response.status_code in {401, 403}:
            message = f"{message}. Check SECRETS_WRITE_PAT, TOKEN, or GITHUB_TOKEN permissions."
        raise GitHubAPIError(message)

    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubAPIError(f"GitHub API returned non-JSON response: {response.text}") from exc

    if not isinstance(payload, dict):
        raise GitHubAPIError(f"GitHub API returned unexpected payload: {payload!r}")
    return payload


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            "GitHub Actions provides GITHUB_REPOSITORY automatically."
        )
    return value


def emit_github_actions_error(message: str) -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    escaped = (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )
    print(f"::error::{escaped}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
