from __future__ import annotations

import pytest

from src.exceptions import (
    InstagramPermissionError,
    InstagramRateLimitError,
    InstagramTokenError,
)
from src.instagram import InstagramClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str | None = None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else str(payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_create_image_container_sends_expected_request(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["timeout"] = timeout
        return FakeResponse(200, {"id": "container-1"})

    monkeypatch.setattr("src.instagram.requests.post", fake_post)

    client = InstagramClient("123", "secret-token")
    container_id = client.create_image_container(
        image_url="https://example.com/image.png",
        caption="caption body",
    )

    assert container_id == "container-1"
    assert captured["url"] == "https://graph.instagram.com/v21.0/123/media"
    assert captured["data"] == {
        "image_url": "https://example.com/image.png",
        "caption": "caption body",
        "media_type": "IMAGE",
        "access_token": "secret-token",
    }
    assert captured["timeout"] == 30


def test_publish_container_sends_expected_request(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return FakeResponse(200, {"id": "media-1"})

    monkeypatch.setattr("src.instagram.requests.post", fake_post)

    client = InstagramClient("123", "secret-token")
    media_id = client.publish_container("container-1")

    assert media_id == "media-1"
    assert captured["url"] == "https://graph.instagram.com/v21.0/123/media_publish"
    assert captured["data"] == {
        "creation_id": "container-1",
        "access_token": "secret-token",
    }


def test_get_permalink_sends_expected_request(monkeypatch):
    captured: dict[str, object] = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse(200, {"id": "media-1", "permalink": "https://instagram.com/p/test"})

    monkeypatch.setattr("src.instagram.requests.get", fake_get)

    client = InstagramClient("123", "secret-token")
    permalink = client.get_permalink("media-1")

    assert permalink == "https://instagram.com/p/test"
    assert captured["url"] == "https://graph.instagram.com/v21.0/media-1"
    assert captured["params"] == {
        "fields": "permalink",
        "access_token": "secret-token",
    }
    assert captured["timeout"] == 30


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"error": {"code": 190, "message": "(#190) token expired"}}, InstagramTokenError),
        (
            {"error": {"code": 10, "message": "(#10) permission denied"}},
            InstagramPermissionError,
        ),
        ({"error": {"code": 4, "message": "(#4) application request limit reached"}}, InstagramRateLimitError),
    ],
)
def test_create_image_container_maps_instagram_errors(monkeypatch, payload, error_type):
    def fake_post(url, data, timeout):
        return FakeResponse(400, payload, text=str(payload), headers={"Retry-After": "15"})

    monkeypatch.setattr("src.instagram.requests.post", fake_post)

    client = InstagramClient("123", "secret-token")
    with pytest.raises(error_type):
        client.create_image_container("https://example.com/image.png", "caption")
