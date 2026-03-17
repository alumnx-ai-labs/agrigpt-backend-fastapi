You are a QA engineer for the AgriGPT WhatsApp Bot backend. Your task is to write and keep `tests/test_main.py` up to date with full coverage of `server.py`.

Follow these steps precisely:

---

## Step 1 — Read source files
- Read `server.py` — note every endpoint, Pydantic model, and helper function
- Read `tests/test_main.py` — note what is already covered

---

## Step 2 — Write `tests/test_main.py`

Write a **complete replacement** of `tests/test_main.py` that covers:

### Endpoints to test
| Endpoint | Methods to test |
|---|---|
| `GET /` | 200 status, response schema, endpoint list present |
| `GET /hello` | 200 status, exact response body |
| `GET /health` | 200 status, schema, DB connected branch, DB disconnected branch (status=degraded) |
| `POST /whatsapp` | happy path, missing fields (422), agent timeout graceful response, DB not initialized (500), existing user vs new user |
| `GET /admin/users` | 200 status, returns list, empty list |
| `GET /admin/stats` | 200 status, schema, correct counts |

### Unit tests
- `detect_language()` — English, Telugu (నమస్కారం), Hindi (नमस्ते), empty string, mixed script

---

## Step 3 — Mocking rules (critical)

The app uses MongoDB (motor) and httpx. Never make real connections in tests.

```python
# Mock motor client to prevent lifespan from failing
with patch("motor.motor_asyncio.AsyncIOMotorClient") as mock_motor:
    mock_motor.return_value = AsyncMock(...)

# Patch server-level globals directly
with patch.multiple(server,
    client=mock_motor_client,
    users_collection=mock_users_col,
    messages_collection=mock_messages_col,
):
    ...

# Mock httpx for /whatsapp and /health agent probe
with patch("httpx.AsyncClient") as mock_http:
    mock_http.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
    mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
```

MongoDB cursor chains to mock:
- `find().sort().to_list(length=N)` → admin/users
- `find().sort().limit().to_list(length=N)` → get_recent_history

---

## Step 4 — Structure

- Put reusable fixtures (mock collections, TestClient) in `tests/conftest.py`
- Group tests by endpoint in classes: `TestRootEndpoint`, `TestHelloEndpoint`, `TestHealthEndpoint`, `TestWhatsAppEndpoint`, `TestAdminUsersEndpoint`, `TestAdminStatsEndpoint`, `TestDetectLanguage`
- At least **3 test cases per endpoint**
- Descriptive names: `test_health_returns_degraded_when_db_disconnected`

---

## Step 5 — Verify

After writing the tests, run:
```
python -m pytest tests/ -v --tb=short
```
Fix any failures before finishing.

---

## Step 6 — Summary

Output:
- Total test count
- Which endpoints gained new coverage
- Any tests that were removed (with reason)
