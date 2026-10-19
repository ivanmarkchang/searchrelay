import re

from fastapi.testclient import TestClient

from searchrelay.config import Config, load_config
from searchrelay.http import create_app
from searchrelay.router import Router


def client_for(tmp_path):
    def factory(config):
        return Router(config, tmp_path / "state.sqlite3")
    return TestClient(create_app(Config(), factory, tmp_path / "config.toml"),
                      base_url="http://127.0.0.1")


def session_headers(client):
    page = client.get("/")
    assert page.status_code == 200
    token = re.search('name="searchrelay-session" content="([^"]+)"', page.text).group(1)
    return {"X-SearchRelay-Session": token, "Origin": "http://127.0.0.1"}


def test_settings_persist_order_and_guard_free_accounts(tmp_path):
    with client_for(tmp_path) as client:
        headers = session_headers(client)
        cfg = client.get("/v1/dashboard/settings").json()
        assert len(cfg["providers"]) == 4
        assert client.put("/v1/dashboard/settings", json=cfg).status_code == 403
        cfg["providers"]["tavily"]["enabled"] = True
        assert client.put("/v1/dashboard/settings", headers=headers, json=cfg).status_code == 409
        cfg["providers"]["tavily"]["enabled"] = False
        cfg["providers"] = dict(reversed(list(cfg["providers"].items())))
        cfg["retention_days"] = 0
        response = client.put("/v1/dashboard/settings", headers=headers, json=cfg)
        assert response.status_code == 200
        assert list(load_config(tmp_path / "config.toml").providers)[0] == "you"
        assert client.get("/v1/dashboard/settings").json()["retention_days"] == 0


def test_credentials_never_returned_or_persisted(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with client_for(tmp_path) as client:
        headers = session_headers(client)
        key = "synthetic-test-key-never-persist"
        response = client.put("/v1/dashboard/credentials/tavily", headers=headers, json={"value": key})
        assert response.status_code == 200 and key not in response.text
        cfg = client.get("/v1/dashboard/settings").json()
        client.put("/v1/dashboard/settings", headers=headers, json=cfg)
        for path in ("/v1/providers", "/v1/dashboard/settings", "/v1/dashboard/activity"):
            assert key not in client.get(path).text
        assert client.get("/v1/providers").json()["providers"][0]["credential_present"]
        assert client.delete("/v1/dashboard/credentials/tavily", headers=headers).status_code == 200
        assert not client.get("/v1/providers").json()["providers"][0]["credential_present"]
    for file in tmp_path.iterdir():
        assert key.encode() not in file.read_bytes()


def test_browser_security_and_static_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHRELAY_API_TOKEN", "local-token")
    with client_for(tmp_path) as client:
        assert client.get("/").status_code == 200  # public shell, private data
        asset = client.get("/assets/dashboard.js")
        assert asset.status_code == 200
        assert "script-src 'self'" in asset.headers["content-security-policy"]
        assert client.get("/assets/not-allowed").status_code == 404
        assert client.get("/v1/dashboard/settings").status_code == 401
        headers = session_headers(client) | {"Authorization": "Bearer local-token"}
        assert client.get("/v1/dashboard/settings", headers=headers).status_code == 200
        headers["Origin"] = "http://evil.test"
        assert client.get("/v1/dashboard/settings", headers=headers).status_code == 403


def test_clear_cache_preserves_current_quota(tmp_path):
    with client_for(tmp_path) as client:
        headers = session_headers(client)
        state = client.app.state.router.state
        cfg = client.app.state.router.config.providers["you"]
        state.reserve("test", cfg)
        state.event("you", "empty")
        assert client.get("/v1/dashboard/activity").json()["events"]
        assert client.delete("/v1/dashboard/cache", headers=headers).status_code == 200
        assert state.status("test")["daily_used"] == 1
        assert not client.get("/v1/dashboard/activity").json()["events"]
