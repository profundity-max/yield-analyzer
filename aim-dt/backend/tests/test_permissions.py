from __future__ import annotations


def test_csrf_and_role_enforcement(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPass123!"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    denied = client.post(
        "/api/v1/admin/users",
        json={"username": "analyst1", "password": "AnalystPass123!", "role": "analyst"},
    )
    assert denied.status_code == 403
    created = client.post(
        "/api/v1/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={"username": "analyst1", "password": "AnalystPass123!", "role": "analyst"},
    )
    assert created.status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204

    analyst_login = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst1", "password": "AnalystPass123!"},
    )
    analyst_csrf = analyst_login.json()["csrf_token"]
    assert client.get("/api/v1/batches").status_code == 200
    assert (
        client.post(
            "/api/v1/admin/users",
            headers={"X-CSRF-Token": analyst_csrf},
            json={"username": "viewer1", "password": "ViewerPass123!", "role": "viewer"},
        ).status_code
        == 403
    )
