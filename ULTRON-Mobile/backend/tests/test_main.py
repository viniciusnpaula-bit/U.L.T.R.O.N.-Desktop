import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Make the backend directory importable whether pytest is launched from the
# repository root or from ULTRON-Mobile/backend (as in GitHub Actions).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.pop("GROQ_API_KEY", None)
os.environ["ULTRON_API_TOKEN"] = "token-de-teste"
from app import main

client = TestClient(main.app)
HEADERS = {"X-Ultron-Token": "token-de-teste"}


def setup_function():
    main._requests.clear()


def test_health_does_not_expose_secret():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ai_configured": "false"}


def test_chat_fails_closed_without_key():
    response = client.post("/v1/chat", json={"message": "Olá"}, headers=HEADERS)
    assert response.status_code == 503
    assert "GROQ" not in response.text


def test_chat_requires_token():
    assert client.post("/v1/chat", json={"message": "Olá"}).status_code == 401
    wrong = {"X-Ultron-Token": "errado"}
    assert client.post("/v1/chat", json={"message": "Olá"}, headers=wrong).status_code == 401


def test_rejects_empty_or_oversized_message():
    assert client.post("/v1/chat", json={"message": ""}, headers=HEADERS).status_code == 422
    assert client.post("/v1/chat", json={"message": "x" * 4001}, headers=HEADERS).status_code == 422


def test_history_limit_is_validated():
    history = [{"role": "user", "content": "oi"}] * 13
    assert client.post("/v1/chat", json={"message": "Olá", "history": history},
                       headers=HEADERS).status_code == 422


def test_rate_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT_REQUESTS", 1)
    request = {"message": "Olá"}
    # First chat consumes the bucket even though no key is configured.
    assert client.post("/v1/chat", json=request, headers=HEADERS).status_code == 503
    assert client.post("/v1/chat", json=request, headers=HEADERS).status_code == 429
