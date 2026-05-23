from __future__ import annotations

import logging
import time
from typing import Any

import requests

try:
    from .exceptions import (
        InstagramAPIError,
        InstagramPermissionError,
        InstagramRateLimitError,
        InstagramTimeoutError,
        InstagramTokenError,
    )
except ImportError:  # pragma: no cover - script execution fallback
    from exceptions import (
        InstagramAPIError,
        InstagramPermissionError,
        InstagramRateLimitError,
        InstagramTimeoutError,
        InstagramTokenError,
    )


GRAPH_BASE_URL = "https://graph.instagram.com"
LOGGER = logging.getLogger(__name__)


class InstagramClient:
    def __init__(self, ig_user_id: str, access_token: str, api_version: str = "v21.0"):
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self.api_version = api_version

    def create_image_container(self, image_url: str, caption: str) -> str:
        payload = self._post_media(
            {
                "image_url": image_url,
                "caption": caption,
                "media_type": "IMAGE",
                "access_token": self.access_token,
            }
        )
        return _extract_id(payload, "container_id")

    def publish_container(self, container_id: str) -> str:
        try:
            response = requests.post(
                self._versioned_url(f"{self.ig_user_id}/media_publish"),
                data={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise InstagramAPIError(f"Instagram API request failed: {exc}") from exc
        payload = _parse_json_response(response)
        return _extract_id(payload, "ig_media_id")

    def get_permalink(self, ig_media_id: str) -> str | None:
        try:
            response = requests.get(
                self._versioned_url(ig_media_id),
                params={
                    "fields": "permalink",
                    "access_token": self.access_token,
                },
                timeout=30,
            )
        except requests.RequestException:
            return None

        if response.status_code < 200 or response.status_code >= 300:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        permalink = payload.get("permalink")
        return permalink if isinstance(permalink, str) and permalink.strip() else None

    def create_reel_container(
        self,
        video_url: str,
        caption: str,
        cover_url: str | None = None,
        share_to_feed: bool = True,
    ) -> str:
        data: dict[str, Any] = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": str(share_to_feed).lower(),
            "access_token": self.access_token,
        }
        if cover_url:
            data["cover_url"] = cover_url

        payload = self._post_media(data)
        return _extract_id(payload, "container_id")

    def create_carousel_child_container(
        self,
        media_url: str,
        is_video: bool,
    ) -> str:
        data: dict[str, Any] = {
            "is_carousel_item": "true",
            "access_token": self.access_token,
        }
        if is_video:
            data["media_type"] = "VIDEO"
            data["video_url"] = media_url
        else:
            data["image_url"] = media_url

        payload = self._post_media(data)
        return _extract_id(payload, "container_id")

    def create_carousel_parent_container(
        self,
        children: list[str],
        caption: str,
    ) -> str:
        payload = self._post_media(
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": self.access_token,
            }
        )
        return _extract_id(payload, "container_id")

    def poll_container_status(
        self,
        container_id: str,
        max_wait_seconds: int = 600,
        poll_interval: int = 5,
    ) -> str:
        deadline = time.monotonic() + max_wait_seconds

        while time.monotonic() <= deadline:
            try:
                response = requests.get(
                    self._versioned_url(container_id),
                    params={
                        "fields": "status_code,status",
                        "access_token": self.access_token,
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise InstagramAPIError(f"Instagram API request failed: {exc}") from exc
            payload = _parse_json_response(response)
            status = payload.get("status_code")
            if not isinstance(status, str):
                raise InstagramAPIError(
                    f"Instagram status polling returned an invalid payload: {payload!r}"
                )
            if status == "FINISHED":
                return status
            if status == "PUBLISHED":
                LOGGER.info("Instagram container %s is already published.", container_id)
                return status
            if status in {"ERROR", "EXPIRED"}:
                detail = payload.get("status")
                suffix = f" Detail: {detail}" if isinstance(detail, str) and detail.strip() else ""
                raise InstagramAPIError(
                    f"Instagram container {container_id} failed with status_code={status}.{suffix}"
                )
            LOGGER.info(
                "Instagram container %s still processing (status_code=%s).",
                container_id,
                status,
            )
            time.sleep(poll_interval)

        raise InstagramTimeoutError(
            f"Timed out waiting for Instagram container {container_id} to finish processing."
        )

    def _versioned_url(self, path: str) -> str:
        return f"{GRAPH_BASE_URL}/{self.api_version}/{path}"

    def _post_media(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                self._versioned_url(f"{self.ig_user_id}/media"),
                data=data,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise InstagramAPIError(f"Instagram API request failed: {exc}") from exc
        return _parse_json_response(response)


def refresh_access_token(access_token: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{GRAPH_BASE_URL}/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": access_token,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise InstagramAPIError(f"Instagram API request failed: {exc}") from exc
    return _parse_json_response(response)


def _parse_json_response(response: requests.Response) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        _raise_instagram_error(response)

    try:
        payload = response.json()
    except ValueError as exc:
        raise InstagramAPIError(
            f"Instagram API returned non-JSON response: {response.text}"
        ) from exc

    if not isinstance(payload, dict):
        raise InstagramAPIError(f"Instagram API returned unexpected payload: {payload!r}")

    return payload


def _extract_id(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get("id")
    if not isinstance(value, str) or not value.strip():
        raise InstagramAPIError(f"Instagram API response missing id for {field_name}: {payload!r}")
    return value


def _raise_instagram_error(response: requests.Response) -> None:
    response_text = response.text
    payload: dict[str, Any] | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = None

    error = payload.get("error", {}) if payload else {}
    message = error.get("message", "") if isinstance(error, dict) else ""
    code = error.get("code") if isinstance(error, dict) else None
    detail = (
        f"Instagram API error {response.status_code}: {response_text or message or 'unknown error'}"
    )

    if code == 190 or "(#190)" in message or "(#190)" in response_text:
        raise InstagramTokenError(f"{detail}. Refresh the long-lived token.")
    if code == 10 or "(#10)" in message or "(#10)" in response_text:
        raise InstagramPermissionError(
            f"{detail}. Re-check instagram_business_content_publish permissions."
        )
    if (
        code == 4
        or response.status_code == 429
        or "(#4)" in message
        or "(#4)" in response_text
    ):
        retry_after = response.headers.get("Retry-After")
        suffix = f" Retry-After: {retry_after} seconds." if retry_after else ""
        raise InstagramRateLimitError(f"{detail}.{suffix}")

    raise InstagramAPIError(detail)
