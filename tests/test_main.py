"""The page at GET /. Run: pytest tests/test_main.py

The API routes are tested in tests/test_api.py and tests/contract/.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_index_answers_html():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Watchtower is running" in response.text
