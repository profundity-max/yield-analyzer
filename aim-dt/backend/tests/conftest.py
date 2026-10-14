from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="aim-dt-tests-"))
os.environ["AIM_ENVIRONMENT"] = "test"
os.environ["AIM_SECRET_KEY"] = "test-secret-key-with-enough-length"
os.environ["AIM_DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.sqlite3'}"
os.environ["AIM_DUCKDB_PATH"] = str(TEST_ROOT / "test.duckdb")
os.environ["AIM_STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["AIM_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["AIM_BOOTSTRAP_ADMIN_PASSWORD"] = "AdminPass123!"
os.environ["AIM_COOKIE_SECURE"] = "false"
os.environ["AIM_FORCE_PASSWORD_CHANGE"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_client(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "AdminPass123!"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": token})
    return client
