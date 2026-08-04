import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_languages():
    response = client.get("/languages")
    assert response.status_code == 200
    data = response.json()
    assert "python" in data
    assert "template" in data["python"]
    assert "entrypoint" in data["python"]
