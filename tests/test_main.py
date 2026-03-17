"""
Comprehensive test suite for the AgriGPT WhatsApp Bot backend (server.py).

Coverage:
  - GET  /             → TestRootEndpoint
  - GET  /hello        → TestHelloEndpoint
  - GET  /health       → TestHealthEndpoint
  - POST /whatsapp     → TestWhatsAppEndpoint
  - GET  /admin/users  → TestAdminUsersEndpoint
  - GET  /admin/stats  → TestAdminStatsEndpoint
  - Unit detect_language() → TestDetectLanguage
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# ─── Helpers ─────────────────────────────────────────────────────────────────

WHATSAPP_PAYLOAD = {
    "chatId": "chat_001",
    "phoneNumber": "+911234567890",
    "message": "How to grow tomatoes?",
    "language": "en",
}

AGENT_OK = {"response": "Tomatoes need well-drained soil.", "sources": ["agri_guide.pdf"]}


def mock_agent_response(body=None, status=200):
    """Build a mock httpx response for the agent service."""
    body = body or AGENT_OK
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def patch_httpx(post_return=None, get_return=None):
    """Context manager that patches httpx.AsyncClient for both POST and GET."""
    mock_http = MagicMock()
    ctx = MagicMock()
    ctx.post = AsyncMock(return_value=post_return or mock_agent_response())
    ctx.get = AsyncMock(return_value=get_return or mock_agent_response({"status": "ok"}, 200))
    mock_http.return_value.__aenter__ = AsyncMock(return_value=ctx)
    mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", mock_http), ctx


# ─── GET / ───────────────────────────────────────────────────────────────────

class TestRootEndpoint:
    def test_returns_200(self, api):
        assert api.get("/").status_code == 200

    def test_response_contains_service_info(self, api):
        data = api.get("/").json()
        assert data["status"] == "healthy"
        assert data["service"] == "WhatsApp Bot Service"
        assert "version" in data

    def test_response_lists_expected_endpoints(self, api):
        data = api.get("/").json()
        endpoints = data.get("endpoints", {})
        assert "health" in endpoints
        assert "whatsapp" in endpoints
        assert "docs" in endpoints


# ─── GET /hello ───────────────────────────────────────────────────────────────

class TestHelloEndpoint:
    def test_returns_200(self, api):
        assert api.get("/hello").status_code == 200

    def test_returns_correct_greeting(self, api):
        assert api.get("/hello").json() == {"message": "hello claude"}

    def test_response_is_json(self, api):
        resp = api.get("/hello")
        assert resp.headers["content-type"].startswith("application/json")


# ─── GET /health ─────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, api):
        assert api.get("/health").status_code == 200

    def test_response_schema(self, api):
        data = api.get("/health").json()
        for key in ("status", "service", "version", "timestamp", "dependencies"):
            assert key in data, f"missing key: {key}"

    def test_db_connected_status(self, api, mock_collections):
        mock_collections["client"].admin.command = AsyncMock(return_value={"ok": 1})
        data = api.get("/health").json()
        assert data["dependencies"]["database"] == "connected"
        assert data["status"] == "healthy"

    def test_db_disconnected_returns_degraded(self, api, mock_collections):
        mock_collections["client"].admin.command = AsyncMock(
            side_effect=Exception("connection refused")
        )
        data = api.get("/health").json()
        assert data["status"] == "degraded"
        assert data["dependencies"]["database"].startswith("error:")

    def test_timestamp_is_iso_format(self, api):
        data = api.get("/health").json()
        # Should not raise
        datetime.fromisoformat(data["timestamp"])


# ─── POST /whatsapp ───────────────────────────────────────────────────────────

class TestWhatsAppEndpoint:
    def test_happy_path_returns_200(self, api, mock_collections):
        patcher, _ = patch_httpx()
        with patcher:
            resp = api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        assert resp.status_code == 200

    def test_response_schema(self, api, mock_collections):
        patcher, _ = patch_httpx()
        with patcher:
            data = api.post("/whatsapp", json=WHATSAPP_PAYLOAD).json()
        for key in ("chatId", "phoneNumber", "message", "status", "timestamp", "sources"):
            assert key in data, f"missing key: {key}"
        assert data["status"] == "success"
        assert data["chatId"] == WHATSAPP_PAYLOAD["chatId"]

    def test_sources_included_in_response(self, api, mock_collections):
        patcher, _ = patch_httpx()
        with patcher:
            data = api.post("/whatsapp", json=WHATSAPP_PAYLOAD).json()
        assert isinstance(data["sources"], list)

    def test_missing_required_fields_returns_422(self, api):
        resp = api.post("/whatsapp", json={"phoneNumber": "+911234567890"})
        assert resp.status_code == 422

    def test_missing_chat_id_returns_422(self, api):
        payload = {k: v for k, v in WHATSAPP_PAYLOAD.items() if k != "chatId"}
        assert api.post("/whatsapp", json=payload).status_code == 422

    def test_new_user_is_created_in_db(self, api, mock_collections):
        mock_collections["users"].find_one = AsyncMock(return_value=None)
        patcher, _ = patch_httpx()
        with patcher:
            api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        mock_collections["users"].insert_one.assert_called_once()

    def test_existing_user_is_not_re_inserted(self, api, mock_collections):
        mock_collections["users"].find_one = AsyncMock(return_value={
            "phoneNumber": "+911234567890",
            "createdAt": datetime.utcnow().isoformat(),
            "messageCount": 3,
        })
        patcher, _ = patch_httpx()
        with patcher:
            api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        mock_collections["users"].insert_one.assert_not_called()

    def test_agent_timeout_returns_graceful_message(self, api, mock_collections):
        import httpx
        with patch("httpx.AsyncClient") as mock_http:
            ctx = MagicMock()
            ctx.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_http.return_value.__aenter__ = AsyncMock(return_value=ctx)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        assert resp.status_code == 200
        msg = resp.json()["message"].lower()
        assert "try again" in msg or "taking longer" in msg or "moment" in msg

    def test_agent_connection_error_returns_graceful_message(self, api, mock_collections):
        import httpx
        with patch("httpx.AsyncClient") as mock_http:
            ctx = MagicMock()
            ctx.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_http.return_value.__aenter__ = AsyncMock(return_value=ctx)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        assert resp.status_code == 200

    def test_db_not_initialized_returns_500(self, api):
        import server
        with patch.object(server, "users_collection", None):
            resp = api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        assert resp.status_code == 500

    def test_message_count_updated_after_request(self, api, mock_collections):
        patcher, _ = patch_httpx()
        with patcher:
            api.post("/whatsapp", json=WHATSAPP_PAYLOAD)
        mock_collections["users"].update_one.assert_called_once()

    def test_language_defaults_to_en(self, api, mock_collections):
        payload = {k: v for k, v in WHATSAPP_PAYLOAD.items() if k != "language"}
        patcher, _ = patch_httpx()
        with patcher:
            resp = api.post("/whatsapp", json=payload)
        assert resp.status_code == 200


# ─── GET /admin/users ─────────────────────────────────────────────────────────

class TestAdminUsersEndpoint:
    def _set_users(self, mock_collections, users):
        from tests.conftest import _make_cursor
        mock_collections["users"].find = MagicMock(return_value=_make_cursor(users))

    def test_returns_200(self, api, mock_collections):
        self._set_users(mock_collections, [])
        assert api.get("/admin/users").status_code == 200

    def test_returns_list(self, api, mock_collections):
        self._set_users(mock_collections, [])
        assert isinstance(api.get("/admin/users").json(), list)

    def test_returns_users_with_stringified_id(self, api, mock_collections):
        from bson import ObjectId
        user = {
            "_id": ObjectId(),
            "phoneNumber": "+911234567890",
            "createdAt": datetime.utcnow(),
        }
        self._set_users(mock_collections, [user])
        data = api.get("/admin/users").json()
        assert len(data) == 1
        assert isinstance(data[0]["_id"], str)

    def test_datetime_serialized_as_string(self, api, mock_collections):
        from bson import ObjectId
        user = {
            "_id": ObjectId(),
            "phoneNumber": "+91111",
            "createdAt": datetime.utcnow(),
        }
        self._set_users(mock_collections, [user])
        data = api.get("/admin/users").json()
        assert isinstance(data[0]["createdAt"], str)


# ─── GET /admin/stats ─────────────────────────────────────────────────────────

class TestAdminStatsEndpoint:
    def test_returns_200(self, api, mock_collections):
        assert api.get("/admin/stats").status_code == 200

    def test_response_schema(self, api, mock_collections):
        data = api.get("/admin/stats").json()
        for key in ("totalUsers", "totalMessages", "platformHealth"):
            assert key in data, f"missing key: {key}"

    def test_returns_correct_user_count(self, api, mock_collections):
        mock_collections["users"].count_documents = AsyncMock(return_value=42)
        mock_collections["messages"].count_documents = AsyncMock(return_value=0)
        assert api.get("/admin/stats").json()["totalUsers"] == 42

    def test_returns_correct_message_count(self, api, mock_collections):
        mock_collections["users"].count_documents = AsyncMock(return_value=0)
        mock_collections["messages"].count_documents = AsyncMock(return_value=99)
        assert api.get("/admin/stats").json()["totalMessages"] == 99


# ─── Unit: detect_language ────────────────────────────────────────────────────

class TestDetectLanguage:
    @pytest.fixture(autouse=True)
    def _import(self):
        from server import detect_language
        self.detect = detect_language

    def test_english_text(self):
        assert self.detect("How to grow tomatoes?") == "en"

    def test_telugu_script(self):
        assert self.detect("నమస్కారం") == "te"

    def test_hindi_script(self):
        assert self.detect("नमस्ते") == "hi"

    def test_empty_string_defaults_to_english(self):
        assert self.detect("") == "en"

    def test_telugu_wins_over_hindi_when_more_chars(self):
        # Telugu chars dominate → should return "te"
        assert self.detect("నమస్కారం నమస్కారం नमस्ते") == "te"

    def test_numbers_and_punctuation_return_english(self):
        assert self.detect("1234 !@#$") == "en"
