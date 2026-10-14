from __future__ import annotations


def test_spec_editor_and_categories(admin_client):
    options = admin_client.get("/api/v1/config/options").json()
    assert options["active_spec_id"]
    assert [point["code"] for point in options["points"]] == [
        "T1-T2",
        "T1-T3",
        "T1-T4",
        "T1-T5",
    ]

    editor = admin_client.get("/api/v1/specs/editor").json()
    points = editor["points"]
    points[0]["lsl"] = 0
    points[0]["usl"] = 1
    response = admin_client.post(
        "/api/v1/specs/editor",
        json={"name": "四点收紧规格", "points": points},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    updated = admin_client.get("/api/v1/config/options").json()
    assert updated["active_spec_id"] == response.json()["id"]

    category = admin_client.post(
        "/api/v1/categories",
        json={"kind": "cell", "code": "Cell-7", "label": "Cell-7", "sort_order": 70},
    )
    assert category.status_code == 200, category.text
    disabled = admin_client.patch(
        f"/api/v1/categories/{category.json()['id']}", json={"active": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
