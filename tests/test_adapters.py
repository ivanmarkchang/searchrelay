import json

import httpx
import pytest

from searchrelay.models import SearchRequest
from searchrelay.providers import ProviderError, create_provider, request_json


@pytest.mark.parametrize("name,mode,field", [
    ("tavily", "web", "results"), ("tavily", "articles", "results"),
    ("firecrawl", "web", "web"), ("firecrawl", "articles", "news"),
    ("serpapi", "web", "organic_results"), ("serpapi", "articles", "news_results"),
    ("serpapi", "video", "video_results"),
])
async def test_official_payload_shapes(name, mode, field):
    calls = []
    row = {"title": "Fixture source", "url": "https://example.org/story", "snippet": "Evidence",
           "published_date": "2026-10-18T10:00:00Z"}
    def handler(request):
        calls.append(request)
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"plan_id": "free", "plan_monthly_price": 0,
                                            "total_searches_left": 10})
        body = {field: [row]}
        if name == "firecrawl":
            body = {"success": True, "data": body}
        return httpx.Response(200, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = create_provider(name, "fixture-key", client)
        results = await provider.search(SearchRequest(query="test", mode=mode, freshness="week"))
        assert results[0].title == "Fixture source"
        assert results[0].date_status != "verified"
    if name == "firecrawl":
        payload = json.loads(calls[0].content)
        assert "scrapeOptions" not in payload
        assert payload["tbs"] == "qdr:w"
    if name == "tavily":
        assert json.loads(calls[0].content)["search_depth"] == "basic"


@pytest.mark.parametrize("status,body,outcome", [
    (200, "<html>CAPTCHA</html>", "blocked"), (200, "[]", "unusable"),
    (200, '{"success":false}', "unusable"), (401, "secret", "unauthorized"),
    (402, "secret", "quota_exhausted"), (429, "slow down", "rate_limited"),
    (429, "Your account has run out of searches", "quota_exhausted"),
    (503, "secret", "server_error"),
])
async def test_transport_outcome_and_retry_after(status, body, outcome):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text=body, headers={"Retry-After": "120"})
    )) as client:
        with pytest.raises(ProviderError) as error:
            await request_json(client, "GET", "https://example.org")
        assert error.value.outcome == outcome
        if outcome == "rate_limited":
            assert error.value.cooldown == 120
        assert "secret" not in str(error.value)


async def test_serpapi_successful_empty_not_failure():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
        "search_metadata": {"status": "Success"},
        "error": "Google hasn't returned any results for this query."
    }))) as client:
        data = await request_json(client, "GET", "https://serpapi.com/search.json")
        assert data["search_metadata"]["status"] == "Success"
