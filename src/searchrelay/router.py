"""One routing implementation for Python, CLI, HTTP and MCP."""
import asyncio
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import Config, config_dir, load_config
from .models import Attempt, Result, SearchRequest, SearchResponse
from .providers import ProviderError, create_provider
from .state import State


def canonical(url: str) -> str:
    parsed = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
                       urlencode(query), ""))


def matches(host: str, domains: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def useful_results(results: list[Result], req: SearchRequest) -> list[Result]:
    accepted, seen = [], set()
    for result in results:
        host = (urlsplit(result.url).hostname or "").lower().rstrip(".")
        if req.include_domains and not matches(host, req.include_domains):
            continue
        if matches(host, req.exclude_domains):
            continue
        path = urlsplit(result.url).path.rstrip("/")
        if req.mode == "articles" and path in {"", "/news", "/latest", "/articles"}:
            continue
        if req.mode == "video":
            if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
                if path != "/watch" and not path.startswith(("/shorts/", "/live/")):
                    continue
                if path == "/watch" and not dict(parse_qsl(urlsplit(result.url).query)).get("v"):
                    continue
            elif host == "youtu.be":
                if not path:
                    continue
            elif result.kind != "video":
                continue
        if req.strict_dates:
            if result.date_status != "verified" or result.published_at is None:
                continue
        if req.freshness and result.published_at is not None:
            age = datetime.now(timezone.utc) - result.published_at
            if age > timedelta(days={"day": 1, "week": 7, "month": 31, "year": 366}[req.freshness]):
                continue
        key = canonical(result.url)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(result)
    return accepted[:req.limit]


class Router:
    def __init__(self, config: Config | None = None, state_path: Path | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, provider_factory=create_provider):
        self.config = config or load_config()
        self.state = State(state_path or config_dir() / "state.sqlite3")
        self.client = httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False,
                                        transport=transport, headers={"User-Agent": "SearchRelay/0.1"})
        self.provider_factory = provider_factory
        self.credentials: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self.client.aclose()
        self.state.close()

    def _routes(self):
        for name, cfg in self.config.providers.items():
            key = (self.credentials.get(name) or os.environ.get(cfg.key_env or "")) if name != "you" else None
            yield name, cfg, key, self.state.identity(name, key or "keyless-ip")

    def status(self):
        return {"free_only": True, "usage_is_local_estimate": True, "quota_windows": "UTC calendar",
                "providers": [{"provider": name, "enabled": cfg.enabled,
                               "credential_present": bool(key) if name != "you" else True,
                               "free_plan_confirmed": cfg.free_plan_confirmed if name != "you" else True,
                               "daily_cap": cfg.daily_limit, "monthly_cap": cfg.monthly_limit,
                               "upstream_allowance": "unknown; local caps are not provider entitlements",
                               **self.state.status(pool)} for name, cfg, key, pool in self._routes()]}

    async def search(self, request: SearchRequest | str) -> SearchResponse:
        req = SearchRequest(query=request) if isinstance(request, str) else request
        routes = list(self._routes())
        self.state.prune(self.config.retention_days)
        cache_key = self.state.cache_key(req.model_dump(), self.config.model_dump(), [r[3] for r in routes])
        cached = self.state.cached(cache_key) if self.config.cache_ttl_seconds else None
        if cached:
            name, payload = cached
            route = next((r for r in routes if r[0] == name), None)
            if route and route[1].enabled and route[1].cache_allowed and (
                name == "you" or (route[1].free_plan_confirmed and route[2])
            ):
                return SearchResponse(status="useful", results=[Result.model_validate(r) for r in payload],
                                      cached=True, warnings=["Cached provider content is untrusted."])
        attempts = []
        count = 0
        deadline = time.monotonic() + self.config.deadline_seconds
        for name, cfg, key, pool in routes:
            reason = None
            if not cfg.enabled:
                reason = "disabled"
            elif name != "you" and not cfg.free_plan_confirmed:
                reason = "free_plan_unconfirmed"
            elif name != "you" and not key:
                reason = "missing_credential"
            provider = self.provider_factory(name, key, self.client)
            if reason is None and req.mode not in provider.modes:
                reason = "unsupported_mode"
            if reason:
                attempts.append(Attempt(provider=name, outcome="skipped", reason=reason))
                continue
            for retry in range(2):
                remaining = deadline - time.monotonic()
                if count >= self.config.max_attempts or remaining <= 0:
                    break
                allowed, reason = self.state.reserve(pool, cfg)
                if not allowed:
                    retry_at = self.state.status(pool)["retry_at"]
                    attempts.append(Attempt(provider=name, outcome="skipped", reason=reason,
                                            retry_at=datetime.fromtimestamp(retry_at, timezone.utc)
                                            if retry_at else None))
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                count += 1
                started = time.monotonic()
                error = None
                try:
                    raw = await asyncio.wait_for(provider.search(req), timeout=remaining)
                    results = useful_results(raw, req)
                    outcome = "useful" if results else "unusable" if raw else "empty"
                except asyncio.TimeoutError:
                    results, outcome, error = [], "timeout", ProviderError("timeout")
                except ProviderError as exc:
                    results, outcome, error = [], exc.outcome, exc
                except (TypeError, ValueError, KeyError):
                    results, outcome, error = [], "unusable", ProviderError("unusable")
                elapsed = int((time.monotonic() - started) * 1000)
                if self.config.retention_days:
                    self.state.event(name, outcome)
                attempt = Attempt(provider=name, outcome=outcome, elapsed_ms=elapsed)
                attempts.append(attempt)
                if results:
                    if cfg.cache_allowed and self.config.cache_ttl_seconds:
                        self.state.put_cache(cache_key, name, [r.model_dump(mode="json") for r in results],
                                             self.config.cache_ttl_seconds)
                    return SearchResponse(status="useful", results=results, attempts=attempts,
                                          warnings=["Provider dates are not independently verified."])
                # A short, bounded transient retry only if rate spacing and deadline permit it.
                transient = outcome in {"server_error", "transport_error"}
                delay = max(cfg.min_interval_seconds, (2 ** retry) + random.random())
                if transient and retry == 0 and count < self.config.max_attempts and (
                    deadline - time.monotonic() > delay + 1
                ):
                    await asyncio.sleep(delay)
                    continue
                if error:
                    self.state.cooldown(pool, error.cooldown, outcome)
                    until = self.state.status(pool)["retry_at"]
                    attempt.retry_at = datetime.fromtimestamp(until, timezone.utc)
                break
            if count >= self.config.max_attempts or time.monotonic() >= deadline:
                break
        status = "empty" if any(a.outcome == "empty" for a in attempts) else "unavailable"
        return SearchResponse(status=status, attempts=attempts,
                              warnings=["No useful results; no paid fallback was attempted."])
