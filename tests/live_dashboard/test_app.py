import pytest
from fastapi.testclient import TestClient

from services.live_dashboard.app import create_app


@pytest.mark.parametrize("configured_token", [None, "", "   "])
def test_data_endpoints_fail_closed_without_a_nonempty_bearer_secret(
    tmp_path, monkeypatch, configured_token
):
    if configured_token is None:
        monkeypatch.delenv("TUTOU_LIVE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", configured_token)
    app = create_app(database=tmp_path / "events.db")

    with TestClient(app) as client:
        response = client.get(
            "/api/live/history",
            headers={"Authorization": f"Bearer {configured_token or ''}"},
        )

    assert response.status_code == 503


def test_health_is_public_while_every_data_endpoint_requires_bearer_auth(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")
    app = create_app(database=tmp_path / "events.db")

    with TestClient(app) as client:
        health = client.get("/api/live/health")
        history = client.get("/api/live/history")
        stream = client.get("/api/live/stream")
        post = client.post("/api/live/events", json={"status": "running"})

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert history.status_code == 401
    assert stream.status_code == 401
    assert post.status_code == 401
    assert all(
        response.headers["www-authenticate"] == "Bearer"
        for response in (history, stream, post)
    )


def test_authenticated_post_is_redacted_and_available_from_history(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")
    app = create_app(database=tmp_path / "events.db")
    headers = {"Authorization": "Bearer test-token"}
    raw_secret = "never-store-this-value"

    with TestClient(app) as client:
        posted = client.post(
            "/api/live/events",
            headers=headers,
            json={
                "goal_id": "goal-9",
                "status": "passed",
                "action": f"https://ci.test/job?access_token={raw_secret}",
                "prompt": f"raw prompt: {raw_secret}",
                "tool_payload": {"password": raw_secret},
            },
        )
        history = client.get("/api/live/history", headers=headers)

    assert posted.status_code == 201
    created = posted.json()
    assert created["id"]
    assert created["goal_id"] == "goal-9"
    assert raw_secret not in posted.text
    assert "prompt" not in created
    assert "tool_payload" not in created
    assert history.status_code == 200
    assert history.json() == [created]


def test_event_request_body_is_rejected_when_actual_size_exceeds_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")
    app = create_app(database=tmp_path / "events.db", max_request_bytes=96)
    headers = {
        "Authorization": "Bearer test-token",
        "Content-Length": "1",
        "Content-Type": "application/json",
    }
    oversized_body = '{"output_excerpt":"' + ("x" * 200) + '"}'

    with TestClient(app) as client:
        response = client.post(
            "/api/live/events",
            headers=headers,
            content=oversized_body,
        )

    assert response.status_code == 413


def test_live_assets_are_public_and_use_explicit_media_types(tmp_path, monkeypatch):
    monkeypatch.delenv("TUTOU_LIVE_TOKEN", raising=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<main>live</main>", encoding="utf-8")
    (static / "app.js").write_text("console.log('live')", encoding="utf-8")
    (static / "style.css").write_text("main { color: red; }", encoding="utf-8")
    app = create_app(
        database=tmp_path / "events.db",
        static_directory=static,
    )

    with TestClient(app) as client:
        index = client.get("/live")
        javascript = client.get("/live/app.js")
        stylesheet = client.get("/live/style.css")

    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert javascript.headers["content-type"].startswith("application/javascript")
    assert stylesheet.headers["content-type"].startswith("text/css")


def test_live_slash_route_and_environment_database_path(tmp_path, monkeypatch):
    token = "x" * 32
    database = tmp_path / "from-env" / "events.db"
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", token)
    monkeypatch.setenv("TUTOU_LIVE_DB", str(database))
    app = create_app()

    with TestClient(app) as client:
        slash = client.get("/live/")
        posted = client.post(
            "/api/live/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"stage": "test", "status": "passed"},
        )

    assert slash.status_code == 200
    assert posted.status_code == 201
    assert database.is_file()
