from fastapi.testclient import TestClient
import os
import sys

# Ensure repo root is on sys.path for tests
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200


def test_say_hi():
    response = client.get("/hi")
    assert response.status_code == 200
    assert response.json() == {"message": "Hi Claude"}