"""Official free-plan adapters. No billing, upgrade, wallet or top-up APIs."""
import asyncio
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .models import Result, SearchRequest


class ProviderError(Exception):
    def __init__(self, outcome: str, cooldown: float = 60):
        super().__init__(outcome)  # Never retain upstream error text, which may contain secrets.
        self.outcome = outcome
        self.cooldown = cooldown


def retry_after(value: str | None) -> float:
    try:
        seconds = float(value)
        return min(366 * 86400, max(1, seconds)) if math.isfinite(seconds) else 60
    except (TypeError, ValueError):
        try:
            return min(366 * 86400, max(1, parsedate_to_datetime(value).timestamp()
                                       - datetime.now(timezone.utc).timestamp()))
        except (TypeError, ValueError, OverflowError):
            return 60


async def request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise ProviderError("timeout") from None
    except httpx.HTTPError:
        raise ProviderError("transport_error") from None
    if response.status_code == 402 or response.status_code == 432:
        # Quota reset is unknown: persist a conservative hold; do not infer a monthly reset.
        raise ProviderError("quota_exhausted", 86400)
    if response.status_code == 429:
        text = response.text.lower()
        exhausted = any(word in text for word in ("run out", "quota", "credit", "monthly limit"))
        raise ProviderError("quota_exhausted" if exhausted else "rate_limited",
                            max(86400 if exhausted else 1, retry_after(response.headers.get("retry-after"))))
    if response.status_code in (401, 403):
        raise ProviderError("blocked" if response.status_code == 403 else "unauthorized", 3600)
    if response.status_code >= 500:
        raise ProviderError("server_error")
    if response.status_code >= 400:
        raise ProviderError("request_rejected", 300)
    if len(response.content) > 5_000_000:
        raise ProviderError("unusable", 300)
    try:
        data = response.json()
    except ValueError:
        raise ProviderError("blocked" if "captcha" in response.text.lower() else "unusable", 3600) from None
    if not isinstance(data, dict):
        raise ProviderError("unusable")
    metadata = data.get("search_metadata")
    known_empty = (url == "https://serpapi.com/search.json" and isinstance(metadata, dict) and
                   data.get("error") == "Google hasn't returned any results for this query." and
                   metadata.get("status") == "Success")
    if data.get("success") is False or (data.get("error") and not known_empty):
        raise ProviderError("unusable")
    return data


def publication(raw, inferred: bool = False) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    parsed = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            pass
    if parsed is not None:
        parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    # Relative/ambiguous dates stay raw; never invent precision or claim verification.
    return {"published_at": parsed, "date_raw": raw[:200],
            "date_status": "inferred" if inferred else "provider_reported",
            "date_source": "provider_metadata"}


def rows_to_results(rows, provider: str, request: SearchRequest, *, engine="unknown", inferred=False):
    if not isinstance(rows, list):
        raise ProviderError("unusable")
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title, url = row.get("title"), row.get("url") or row.get("link")
        snippet = row.get("content") or row.get("description") or row.get("snippet") or ""
        if not isinstance(snippet, str):
            snippet = ""
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
            continue
        try:
            results.append(Result(title=title[:1000], url=url, snippet=snippet[:4000], provider=provider,
                                  upstream_engine=engine,
                                  kind={"web": "web", "articles": "article", "video": "video"}[request.mode],
                                  **publication(row.get("published_date") or row.get("date") or row.get("age"),
                                                inferred)))
        except ValueError:
            continue
    if rows and not results:
        raise ProviderError("unusable")
    return results


class Provider:
    modes = {"web", "articles"}
    freshness = True

    def __init__(self, name: str, key: str | None, client: httpx.AsyncClient):
        self.name, self.key, self.client = name, key, client

    async def search(self, req: SearchRequest) -> list[Result]:
        if self.name == "tavily":
            body = {"query": req.query, "max_results": req.limit, "search_depth": "basic",
                    "topic": "news" if req.mode == "articles" else "general",
                    "include_answer": False, "include_raw_content": False, "auto_parameters": False,
                    "include_domains": req.include_domains, "exclude_domains": req.exclude_domains}
            if req.freshness:
                body["time_range"] = req.freshness
            data = await request_json(self.client, "POST", "https://api.tavily.com/search",
                                      headers={"Authorization": f"Bearer {self.key}"}, json=body)
            return rows_to_results(data.get("results"), self.name, req, inferred=True)
        if self.name == "firecrawl":
            body = {"query": req.query, "limit": req.limit,
                    "sources": ["news" if req.mode == "articles" else "web"],
                    "includeDomains": req.include_domains, "excludeDomains": req.exclude_domains}
            if req.freshness:
                body["tbs"] = "qdr:" + {"day": "d", "week": "w", "month": "m", "year": "y"}[req.freshness]
            data = await request_json(self.client, "POST", "https://api.firecrawl.dev/v2/search",
                                      headers={"Authorization": f"Bearer {self.key}"}, json=body)
            source = data.get("data")
            rows = source.get("news" if req.mode == "articles" else "web") if isinstance(source, dict) else None
            return rows_to_results(rows, self.name, req)
        if self.name == "serpapi":
            # A read-only, free account check protects against an accidentally supplied paid key.
            account = await request_json(self.client, "GET", "https://serpapi.com/account.json",
                                         params={"api_key": self.key})
            if str(account.get("plan_id", "")).lower() != "free" or account.get("plan_monthly_price") != 0:
                raise ProviderError("free_plan_unverified", 3600)
            if account.get("total_searches_left", 0) <= 0:
                raise ProviderError("quota_exhausted", 86400)
            query = req.query
            if req.include_domains:
                query += " (" + " OR ".join("site:" + d for d in req.include_domains) + ")"
            query += "".join(" -site:" + d for d in req.exclude_domains)
            params = {"api_key": self.key, "q": query, "engine": "google"}
            if req.mode == "articles":
                params["tbm"] = "nws"
            elif req.mode == "video":
                params["tbm"] = "vid"
            if req.freshness:
                params["tbs"] = "qdr:" + {"day": "d", "week": "w", "month": "m", "year": "y"}[req.freshness]
            data = await request_json(self.client, "GET", "https://serpapi.com/search.json", params=params)
            field = {"web": "organic_results", "articles": "news_results", "video": "video_results"}[req.mode]
            metadata = data.get("search_metadata")
            if field not in data and (not isinstance(metadata, dict) or metadata.get("status") != "Success"):
                raise ProviderError("unusable")
            return rows_to_results(data.get(field, []), self.name, req, engine="google")
        if self.name == "you":
            return await self._you(req)
        raise ProviderError("unsupported")

    async def _you(self, req: SearchRequest) -> list[Result]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError:
            raise ProviderError("missing_mcp_dependency", 3600) from None
        # Fixed free-profile host. No auth, payment rails, custom endpoints, or identity rotation.
        try:
            async with streamablehttp_client("https://api.you.com/mcp?profile=free") as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    arguments = {"query": req.query, "count": req.limit, "extraction": "none"}
                    if req.freshness:
                        arguments["freshness"] = req.freshness
                    if req.exclude_domains:
                        arguments["exclude_domains"] = req.exclude_domains
                    params = {"name": "you-search", "arguments": arguments}
                    if req.include_domains:
                        params["_meta"] = {"com.you.com/search": {"include_domains": req.include_domains}}
                    # send_request preserves the documented host-supplied metadata.
                    from mcp import types
                    reply = await session.send_request(
                        types.ClientRequest(types.CallToolRequest(method="tools/call", params=params)),
                        types.CallToolResult)
                    if reply.isError:
                        raise ProviderError("upstream_tool_error", 300)
                    data = reply.structuredContent
                    if data is None:
                        for block in reply.content:
                            if block.type == "text":
                                try:
                                    data = json.loads(block.text)
                                    break
                                except ValueError:
                                    continue
                    if not isinstance(data, dict):
                        raise ProviderError("unusable")
                    payload = data.get("results")
                    if not isinstance(payload, dict):
                        raise ProviderError("unusable")
                    return rows_to_results(payload.get("web"), self.name, req)
        except (ProviderError, asyncio.CancelledError):
            raise
        except Exception:
            # SDK ExceptionGroups may carry headers/body; never serialize them to callers/logs.
            raise ProviderError("mcp_transport_error", 300) from None


def create_provider(name, key, client):
    provider = Provider(name, key, client)
    if name == "serpapi":
        provider.modes = {"web", "articles", "video"}
    if name == "you":
        provider.modes = {"web"}  # Do not present generic web hits as dedicated news/video search.
    return provider
