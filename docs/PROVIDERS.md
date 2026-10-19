# Provider access evidence

Reviewed 2026-10-18. Only use free accounts without payment methods or automatic renewal/top-up.
No provider keys are supplied with SearchRelay.

| Provider | Official evidence | Pilot policy |
| --- | --- | --- |
| Tavily | [Free and stop-at-exhaustion FAQ](https://www.tavily.com/pricing), [search schema](https://docs.tavily.com/documentation/api-reference/endpoint/search) | Free attestation required; fixed basic search, no answers/raw content/auto parameters. |
| Firecrawl | [Free has no PAYG; returns 402 at zero](https://docs.firecrawl.dev/billing), [search schema](https://docs.firecrawl.dev/api-reference/endpoint/search) | Free attestation required; no scrape options, at most 10 search results. |
| SerpApi | [Free plan](https://serpapi.com/pricing), [exhaustion 429](https://serpapi.com/api-status-and-error-codes), [Account API](https://serpapi.com/account-api) | Free attestation and per-search free-plan check; unknown/paid plans refused. |
| You.com | [Free MCP profile](https://you.com/docs/agents/mcp-server), [authentication](https://you.com/docs/using-the-api/authentication) | Fixed free profile, no authentication/payment/extraction. Evaluation use; install MCP extra. |

Tavily/Firecrawl account attestation cannot detect a later account upgrade. Recheck dashboard conditions
and disable adapters if accounts change. No claim that arbitrary keys cannot bill.

You.com tool errors may not expose structured quota/reset information: classify as upstream_tool_error,
cool down five minutes, and fall back. Numeric reset scope/timezone is unknown. Local UTC caps are extra
restrictions, not upstream entitlements. MCP handshake errors are separate transport failures.

REST Retry-After supports seconds and HTTP dates. Exhaustion with no known reset gets a conservative
24-hour hold; the next upstream recheck remains authoritative. No automatic mode/identity switch to evade caps.

## Held/excluded

- [Exa](https://exa.ai/pricing): no-card Starter documented, exact official exhaustion contract needs confirmation.
- [Brave](https://api-dashboard.search.brave.com/documentation/resources/help-feedback): card/authorization
  hold required; auto-reload and legacy postpaid exist. Excluded from no-billing pilot.
- [Parallel](https://parallel.ai/blog/free-tier-parallel): recurring allowance requires card and excess is billed.
- [Linkup](https://docs.linkup.so/pages/documentation/platform/pricing): zero-balance 429 documented;
  full no-billing account conditions require confirmation.
- [Serper](https://serper.dev/): introductory credits; full exhaustion contract not confirmed.
- [Mojeek](https://www.mojeek.com/services/search/web-search-api/): paid API with arranged trial.
- DDGS/direct HTML search and public SearXNG pools: no dependable access/allowance contract established.

## Storage and evaluation

[Tavily terms](https://www.tavily.com/terms) restrict performance disclosure and competitive use: seek
clarification before publishing comparisons. Cache defaults off for every provider; enable only with
permission. Free API access does not grant rights to third-party page content.

Before changing priority, run a modest authorized evaluation across web, articles, videos, freshness,
domain filters and legitimate empty queries. Measure useful-hit rate separately from transport success,
latency, duplicates, date provenance and quota outcomes. Test exhaustion synthetically, not by draining quotas.
