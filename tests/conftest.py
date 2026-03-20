"""
Shared pytest fixtures for the AgriGPT backend test suite.

Key design decision:
  TestClient is used WITHOUT a context manager so the lifespan never runs.
  If we used `with TestClient(app)`, the lifespan would fire, connect to the
  real MongoDB (MONGODB_URL is in .env), and overwrite our mocked globals.
  Skipping the lifespan is safe here — we test endpoint logic, not startup.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ─── cursor helpers ───────────────────────────────────────────────────────────

def _make_cursor(rows=None):
    """Mock that supports .sort().limit().to_list() and .sort().to_list()"""
    rows = rows or []

    inner = AsyncMock()
    inner.to_list = AsyncMock(return_value=rows)

    after_sort = MagicMock()
    after_sort.to_list = AsyncMock(return_value=rows)
    after_sort.limit = MagicMock(return_value=inner)

    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=after_sort)
    return cursor


def make_mock_collection(rows=None):
    """Build a fully mocked async Motor collection."""
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=None)
    col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="507f1f77bcf86cd799439011"))
    col.update_one = AsyncMock(return_value=None)
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=_make_cursor(rows))
    return col


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_collections():
    """
    Patch server-level MongoDB globals with controlled async mocks.

    Uses patch.multiple so all changes are automatically reverted after the test.
    Works because we skip the lifespan (no context-manager TestClient), which
    means the lifespan never re-assigns these globals.
    """
    import server

    mock_motor_client = AsyncMock()
    mock_motor_client.admin.command = AsyncMock(return_value={"ok": 1})
    mock_motor_client.close = MagicMock()

    users_col = make_mock_collection()
    messages_col = make_mock_collection()

    with patch.multiple(
        server,
        client=mock_motor_client,
        users_collection=users_col,
        messages_collection=messages_col,
    ):
        yield {
            "client": mock_motor_client,
            "users": users_col,
            "messages": messages_col,
        }


@pytest.fixture
def api(mock_collections):
    """
    FastAPI TestClient backed by mocked MongoDB.

    Deliberately NOT used as a context manager so the lifespan (which would
    overwrite our mocked globals by connecting to the real MongoDB) never runs.
    """
    import server
    return TestClient(server.app, raise_server_exceptions=False)
