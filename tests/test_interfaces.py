from fastapi.testclient import TestClient

from searchrelay.config import Config
from searchrelay.http import create_app
from searchrelay.models import SearchResponse


class StubRouter:
    def __init__(self, config):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def search(self, request):
        return SearchResponse(status="empty")

    def status(self):
        return {"free_only": True}


def test_http_contract_and_origin_host_guard(monkeypatch):
    monkeypatch.delenv("SEARCHRELAY_API_TOKEN", raising=False)
    with TestClient(create_app(Config(), StubRouter), base_url="http://127.0.0.1") as client:
        assert client.get("/health").json()["free_only"]
        assert client.post("/v1/search", json={"query": "test"}).json()["status"] == "empty"
        assert client.get("/health", headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.get("/health", headers={"Host": "evil.test"}).status_code == 403
        invalid = client.post("/v1/search", json={"query": "secret", "api_key": "secret"})
        assert invalid.status_code == 422
        assert "secret" not in invalid.text


def test_http_optional_token(monkeypatch):
    monkeypatch.setenv("SEARCHRELAY_API_TOKEN", "local-secret")
    with TestClient(create_app(Config(), StubRouter), base_url="http://localhost") as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers={"Authorization": "Bearer local-secret"}).status_code == 200


async def test_mcp_tool_schema():
    from searchrelay.mcp_server import create_server
    server = create_server(Config())
    tools = await server.list_tools()
    assert {t.name for t in tools} == {"search", "provider_status"}
    schema = next(t for t in tools if t.name == "search").inputSchema
    assert "query" in schema["properties"]
    assert "ctx" not in schema["properties"]


async def test_mcp_stdio_end_to_end(tmp_path):
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "searchrelay.cli", "mcp"],
                                   env={**os.environ, "SEARCHRELAY_HOME": str(tmp_path)})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search", {"query": "test"})
            assert not result.isError
            assert result.structuredContent["status"] == "unavailable"


def test_http_real_router_fallback(tmp_path, monkeypatch):
    import httpx

    from searchrelay.config import ProviderConfig
    from searchrelay.router import Router

    monkeypatch.setenv("TEST_HTTP_KEY", "fixture-key")
    calls = []
    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.tavily.com":
            return httpx.Response(432, json={"error": "quota exceeded"})
        return httpx.Response(200, json={"success": True, "data": {"web": [
            {"title": "Fixture", "url": "https://example.org/story", "description": "Evidence"}]}})
    cfg = Config(providers={name: ProviderConfig(enabled=True, free_plan_confirmed=True,
                                                 key_env="TEST_HTTP_KEY")
                            for name in ("tavily", "firecrawl")})
    def factory(config):
        return Router(config, tmp_path / "s.db", transport=httpx.MockTransport(handler))
    with TestClient(create_app(cfg, factory), base_url="http://127.0.0.1") as client:
        response = client.post("/v1/search", json={"query": "test"})
        assert response.status_code == 200
        assert response.json()["results"][0]["provider"] == "firecrawl"
        assert [a["outcome"] for a in response.json()["attempts"]] == ["quota_exhausted", "useful"]
    assert calls == ["api.tavily.com", "api.firecrawl.dev"]
