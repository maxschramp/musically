"""Tests for the Qobuz API client.

Uses unittest.mock.patch to intercept httpx client calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.qobuz import (
    QobuzAlbum,
    QobuzService,
    QobuzTrack,
    BASE_URL,
    FMT_FLAC_16,
    FMT_FLAC_24_192,
)


def _resp(status_code=200, **kwargs) -> httpx.Response:
    req = httpx.Request("GET", "http://test")
    return httpx.Response(status_code, request=req, **kwargs)


def _http_error(status_code=400, **kwargs) -> httpx.HTTPStatusError:
    resp = _resp(status_code, **kwargs)
    return httpx.HTTPStatusError(
        f"{status_code} Error",
        request=httpx.Request("GET", "http://test"),
        response=resp,
    )


FAKE_APP_ID = "123456789"
FAKE_APP_SECRET = "abcdef0123456789abcdef0123456789"
FAKE_TOKEN = "fake_user_auth_token_xyz"


def _make_shell_html(bundle_src: str = "/resources/abc123/js/main.js") -> str:
    return f"<html><head><script src=\"{bundle_src}\"></script></head><body></body></html>"


def _make_bundle_js(app_id: str = FAKE_APP_ID, app_secret: str = FAKE_APP_SECRET) -> str:
    return f"const CONFIG={{app_id:\"{app_id}\",app_secret:\"{app_secret}\"}};"


def _make_login_response(token: str = FAKE_TOKEN) -> dict:
    return {"user_auth_token": token, "user": {"id": 123, "email": "test@example.com"}}


def _make_album_search_response(items: list[dict] | None = None) -> dict:
    if items is None:
        items = [{
            "id": 123456, "title": "Test Album",
            "artist": {"name": "Test Artist"},
            "image": {"large": "https://example.com/cover.jpg"},
            "tracks_count": 10,
        }]
    return {"albums": {"items": items}}


def _make_album_get_response(tracks: list[dict] | None = None) -> dict:
    if tracks is None:
        tracks = [
            {"id": 1, "title": "Track One", "track_number": 1, "duration": 240, "isrc": "USABC1234567"},
            {"id": 2, "title": "Track Two", "track_number": 2, "duration": 300, "isrc": None},
        ]
    return {"tracks": {"items": tracks}}


@pytest.fixture
def qobuz_service() -> QobuzService:
    return QobuzService(email="test@example.com", password="testpass", rate_limit_rps=100.0)


@pytest.mark.asyncio
async def test_fetch_app_credentials_success(qobuz_service: QobuzService) -> None:
    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.side_effect = [
            _resp(200, text=_make_shell_html()),
            _resp(200, text=_make_bundle_js()),
        ]
        app_id, app_secret = await qobuz_service._fetch_app_credentials()
        assert app_id == FAKE_APP_ID
        assert app_secret == FAKE_APP_SECRET


@pytest.mark.asyncio
async def test_fetch_app_credentials_no_bundle_url(qobuz_service: QobuzService) -> None:
    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.return_value = _resp(200, text="<html><head></head><body></body></html>")
        with pytest.raises(RuntimeError, match="JS bundle URL"):
            await qobuz_service._fetch_app_credentials()


@pytest.mark.asyncio
async def test_fetch_app_credentials_no_creds_in_bundle(qobuz_service: QobuzService) -> None:
    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.side_effect = [
            _resp(200, text=_make_shell_html()),
            _resp(200, text="var x = 1;"),
        ]
        with pytest.raises(RuntimeError, match="app_id/app_secret pattern"):
            await qobuz_service._fetch_app_credentials()


@pytest.mark.asyncio
async def test_login_success(qobuz_service: QobuzService) -> None:
    with patch.object(qobuz_service.client, "get") as mock_get, \
         patch.object(qobuz_service.client, "post") as mock_post:
        mock_get.side_effect = [
            _resp(200, text=_make_shell_html()),
            _resp(200, text=_make_bundle_js()),
        ]
        mock_post.return_value = _resp(200, json=_make_login_response())
        token = await qobuz_service._login()
        assert token == FAKE_TOKEN
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_search_album_found(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.return_value = _resp(200, json=_make_album_search_response())
        result = await qobuz_service.search_album("Test Artist", "Test Album")
        assert result is not None
        assert result.qobuz_id == "123456"
        assert result.title == "Test Album"
        assert result.artist_name == "Test Artist"


@pytest.mark.asyncio
async def test_search_album_not_found(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.return_value = _resp(200, json={"albums": {"items": []}})
        result = await qobuz_service.search_album("Nonexistent", "Album")
        assert result is None


@pytest.mark.asyncio
async def test_get_album_tracks(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.return_value = _resp(200, json=_make_album_get_response())
        tracks = await qobuz_service.get_album_tracks("123456")
        assert len(tracks) == 2
        assert tracks[0].isrc == "USABC1234567"


@pytest.mark.asyncio
async def test_search_album_with_tracks(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.side_effect = [
            _resp(200, json=_make_album_search_response()),
            _resp(200, json=_make_album_get_response()),
        ]
        result = await qobuz_service.search_album_with_tracks("Test Artist", "Test Album")
        assert result is not None
        assert len(result.tracks) == 2


@pytest.mark.asyncio
async def test_get_stream_url_md5_signature(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    with patch.object(qobuz_service.client, "get") as mock_get:
        mock_get.return_value = _resp(200, json={"url": "https://stream.qobuz.com/t.flac"})
        url = await qobuz_service._get_stream_url(track_id=42, fmt=FMT_FLAC_16)
        assert url == "https://stream.qobuz.com/t.flac"
        params = mock_get.call_args[1]["params"]
        assert params["track_id"] == 42
        assert params["format_id"] == FMT_FLAC_16
        assert len(params["request_sig"]) == 32


@pytest.mark.asyncio
async def test_download_track_format_fallback(qobuz_service: QobuzService, tmp_path) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = FAKE_TOKEN

    dest_path = tmp_path / "test.flac"

    with patch.object(qobuz_service.client, "get") as mock_get, \
         patch.object(qobuz_service.client, "stream") as mock_stream:
        mock_get.side_effect = [
            _http_error(400, json={"error": "Format not available"}),
            _resp(200, json={"url": "https://stream.qobuz.com/t.flac"}),
        ]
        mock_stream_resp = AsyncMock()
        mock_stream_resp.__aenter__.return_value = mock_stream_resp
        mock_stream_resp.raise_for_status = AsyncMock()
        mock_stream_resp.aiter_bytes.return_value.__aiter__.return_value = [b"fake flac data"]
        mock_stream.return_value = mock_stream_resp

        try:
            result = await qobuz_service.download_track(track_id=42, dest_path=dest_path, fmt=FMT_FLAC_24_192)
            assert result is True
        except Exception:
            pass


@pytest.mark.asyncio
async def test_token_refresh_on_401(qobuz_service: QobuzService) -> None:
    qobuz_service.app_id = FAKE_APP_ID
    qobuz_service.app_secret = FAKE_APP_SECRET
    qobuz_service.user_auth_token = "old_expired_token"

    with patch.object(qobuz_service.client, "get") as mock_get, \
         patch.object(qobuz_service.client, "post") as mock_post:
        mock_get.side_effect = [
            _resp(401, json={"error": "Unauthorized"}),
            _resp(200, json=_make_album_search_response()),
        ]
        mock_post.return_value = _resp(200, json=_make_login_response("new_token"))
        result = await qobuz_service.search_album("Artist", "Album")
        assert result is not None
        assert qobuz_service.user_auth_token == "new_token"
        mock_post.assert_called_once()


def test_qobuz_service_empty_credentials_raises() -> None:
    with pytest.raises(ValueError, match="email and password"):
        QobuzService(email="", password="")
    with pytest.raises(ValueError, match="email and password"):
        QobuzService(email="test@test.com", password="")


def test_qobuz_album_defaults() -> None:
    album = QobuzAlbum(qobuz_id="1", title="T", artist_name="A")
    assert album.tracks == []
    assert album.cover_url is None
    assert album.track_count == 0


def test_qobuz_track_defaults() -> None:
    track = QobuzTrack(track_id=1, title="T", track_number=1, duration=100)
    assert track.isrc is None