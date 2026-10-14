from __future__ import annotations


def test_login_and_health(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    good = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPass123!"},
    )
    assert good.status_code == 200
    csrf = good.json()["csrf_token"]
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
