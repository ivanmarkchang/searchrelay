import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest

from searchrelay import Router, SearchRequest
from searchrelay.config import Config, ProviderConfig
from searchrelay.models import Result
from searchrelay.providers import ProviderError, publication, retry_after
from searchrelay.router import useful_results
from searchrelay.state import State


def configured(**changes):
    values = dict(enabled=True, free_plan_confirmed=True, key_env="TEST_KEY", min_interval_seconds=1)
    return ProviderConfig(**(values | changes))


def hit(provider="tavily", url="https://example.org/story", **kwargs):
    return Result(title="A useful result", url=url, snippet="Evidence", provider=provider, **kwargs)


def fake_factory(actions, calls):
    class Fake:
        modes = {"web", "articles", "video"}

        def __init__(self, name):
            self.name = name

        async def search(self, req):
            calls.append(self.name)
            action = actions[self.name]
            if isinstance(action, Exception):
                raise action
            if callable(action):
                return await action()
            return action
    return lambda name, key, client: Fake(name)


@pytest.mark.parametrize("outcome", ["quota_exhausted", "blocked", "unauthorized", "rate_limited", "unusable"])
async def test_failure_falls_back_and_cooldown_survives_restart(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv("TEST_KEY", "secret")
    cfg = Config(providers={"tavily": configured(), "firecrawl": configured()})
    calls = []
    factory = fake_factory({"tavily": ProviderError(outcome, 300), "firecrawl": [hit("firecrawl")]}, calls)
    async with Router(cfg, tmp_path / "state.db", provider_factory=factory) as router:
        response = await router.search("test")
        assert response.status == "useful"
        assert [a.outcome for a in response.attempts] == [outcome, "useful"]
    calls.clear()
    async with Router(cfg, tmp_path / "state.db", provider_factory=factory) as router:
        await router.search("test")
        assert "tavily" not in calls


async def test_unconfirmed_and_missing_keys_never_dispatch(tmp_path):
    calls = []
    cfg = Config(providers={"tavily": configured(free_plan_confirmed=False),
                            "firecrawl": configured(key_env="MISSING_TEST_KEY")})
    async with Router(cfg, tmp_path / "s.db", provider_factory=fake_factory({}, calls)) as router:
        result = await router.search("test")
        assert result.status == "unavailable"
        assert not calls


async def test_empty_is_not_transport_failure(tmp_path):
    cfg = Config(providers={"you": configured()})
    async with Router(cfg, tmp_path / "s.db", provider_factory=fake_factory({"you": []}, [])) as router:
        result = await router.search("gibberish")
        assert result.status == "empty"
        assert result.attempts[0].outcome == "empty"


async def test_max_attempts_and_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    cfg = Config(max_attempts=1, providers={"tavily": configured(), "firecrawl": configured()})
    calls = []
    async with Router(cfg, tmp_path / "s.db", provider_factory=fake_factory(
        {"tavily": [], "firecrawl": [hit()]}, calls)) as router:
        await router.search("test")
        assert calls == ["tavily"]
    async def slow():
        await asyncio.sleep(2)
        return [hit()]
    cfg = Config(deadline_seconds=1, providers={"you": configured()})
    async with Router(cfg, tmp_path / "deadline.db", provider_factory=fake_factory({"you": slow}, [])) as router:
        result = await router.search("test")
        assert result.status == "unavailable"
        assert result.attempts[0].outcome == "timeout"


def test_atomic_last_slot_across_connections(tmp_path):
    path = tmp_path / "s.db"
    first = State(path)
    first.close()
    def reserve(_):
        state = State(path)
        try:
            return state.reserve("shared-pool", configured(daily_limit=1))[0]
        finally:
            state.close()
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(8))) == 1


def test_utc_quota_windows_and_conservative_account_scope(tmp_path):
    state = State(tmp_path / "s.db")
    cfg = configured(daily_limit=1)
    jan31 = datetime(2026, 1, 31, 12, tzinfo=timezone.utc).timestamp()
    feb1 = datetime(2026, 2, 1, 12, tzinfo=timezone.utc).timestamp()
    assert state.reserve("a", cfg, jan31)[0]
    assert not state.reserve("a", cfg, jan31 + 2)[0]
    assert state.reserve("a", cfg, feb1)[0]
    assert state.identity("tavily", "key") != state.identity("tavily", "other-key")
    state.close()


def test_filters_dedupe_dates_and_homepages():
    rows = [hit(url="https://example.org/"), hit(url="https://example.org/story?utm_source=x"),
            hit(url="https://example.org/story"), hit(url="https://example.org.evil.test/story")]
    assert len(useful_results(rows, SearchRequest(query="test", include_domains=["example.org"]))) == 2
    assert len(useful_results(rows, SearchRequest(query="test", mode="articles",
                                                 include_domains=["example.org"]))) == 1
    assert useful_results(rows, SearchRequest(query="test", strict_dates=True)) == []
    date = publication("2026-10-18", inferred=True)
    assert date["date_status"] == "inferred"
    assert publication("2 hours ago")["published_at"] is None


async def test_cache_opt_in_filters_and_disable(tmp_path):
    cfg = Config(cache_ttl_seconds=60, providers={"you": configured(cache_allowed=True)})
    calls = []
    async with Router(cfg, tmp_path / "s.db", provider_factory=fake_factory({"you": [hit("you")]}, calls)) as router:
        await router.search("test")
        assert (await router.search("test")).cached
        assert calls == ["you"]
        router.config.providers["you"].enabled = False
        assert not (await router.search("test")).cached


async def test_request_payload_and_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret-do-not-record")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(402, json={"error": "secret-do-not-record sensitive query"})
    cfg = Config(providers={"tavily": configured()})
    async with Router(cfg, tmp_path / "s.db", transport=httpx.MockTransport(handler)) as router:
        response = await router.search("sensitive query")
        body = json.loads(requests[0].content)
        assert body["search_depth"] == "basic" and body["auto_parameters"] is False
        assert not body["include_answer"] and not body["include_raw_content"]
        assert "secret-do-not-record" not in response.model_dump_json()
        assert "secret-do-not-record" not in json.dumps(router.status())
    assert b"secret-do-not-record" not in (tmp_path / "s.db").read_bytes()
    assert b"sensitive query" not in (tmp_path / "s.db").read_bytes()


async def test_serpapi_paid_plan_never_searches(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"plan_id": "starter", "plan_monthly_price": 25})
    cfg = Config(providers={"serpapi": configured()})
    async with Router(cfg, tmp_path / "s.db", transport=httpx.MockTransport(handler)) as router:
        response = await router.search("test")
        assert response.attempts[0].outcome == "free_plan_unverified"
        assert requests == ["/account.json"]


def test_retry_after_and_invalid_inputs():
    assert retry_after("123") == 123
    assert retry_after("nonsense") == 60
    with pytest.raises(ValueError):
        SearchRequest(query=" ")
    with pytest.raises(ValueError):
        SearchRequest(query="test", include_domains=["https://example.org/path"])
    with pytest.raises(ValueError):
        Config.model_validate({"paid_enabled": True})
