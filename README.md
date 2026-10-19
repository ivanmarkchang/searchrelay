# SearchRelay

A lightweight, local-first web search router for AI agents, local models, and ordinary applications.
One interface, ordered provider fallback, local quota tracking, and **free-only operation**. MIT licensed.

**Pilot / 0.1.0:** no paid providers, billing integration, scraping, or identity rotation.
No model, browser, Docker, or cloud database required. Not yet published to PyPI.

## Install

Requires Python 3.10+.

```sh
git clone https://github.com/ivanmarkchang/searchrelay.git
cd searchrelay
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[http,mcp]'
searchrelay init
```

Core library/CLI only: `python -m pip install -e .`. Windows activation: `.venv\Scripts\activate`.
The `mcp` extra also enables the You.com keyless adapter.

## Setup: no billing

Configuration defaults to `~/.config/searchrelay/config.toml`. `SEARCHRELAY_HOME` changes the config/state
directory; `--config /path/config.toml` changes only the config file. Generated config enables **nothing**.

1. Create a **Free** account with Tavily, Firecrawl, or SerpApi.
2. Do not add a payment method, paid subscription, marketplace billing, or automatic top-up/renewal.
3. Set the key in your process environment, e.g. `export TAVILY_API_KEY='your-key'`. Avoid saving real keys
   in shell history; inject them through an OS secret manager where available.
4. Set that provider's `enabled = true` and `free_plan_confirmed = true` in config.
5. For keyless You.com, install the `mcp` extra and set `[providers.you] enabled = true`.
6. Run `searchrelay status`, then `searchrelay search "Python asyncio documentation"`.

Keys are never saved to config or state. `.env` files are **not automatically loaded**.

**Account boundary:** a normal API key can belong to a paid account. SearchRelay cannot revoke its billing
agreement. `free_plan_confirmed` is your explicit attestation, not a remotely verified guarantee.
SerpApi additionally checks the Account API before each search and refuses unknown/paid plans.
Tavily and Firecrawl require your dashboard confirmation: do not enable them with paid keys.
The router never upgrades accounts, purchases credits, authorizes payments, or attempts paid fallback.

| Adapter | Documented free access | Exhaustion | Modes |
| --- | --- | --- | --- |
| Tavily | 1,000 credits/month; basic search fixed to 1 credit | Provider stops until reset/upgrade | web, articles |
| Firecrawl | 1,000 credits/month; 2 credits per up-to-10 search results | HTTP 402; Free has no PAYG | web, articles |
| SerpApi | 250 searches/month, 50/hour | HTTP 429; paid plans rejected by preflight | web, articles, video |
| You.com | Official keyless MCP free profile; 100 queries/day, evaluation use | Provider rate/tool errors | web |

Reviewed **2026-10-18**. Third-party conditions can change; disable providers that no longer offer a
non-billing setup. See [provider evidence](docs/PROVIDERS.md). No unlimited-search promise.

## Search

```sh
searchrelay search "local AI releases" --mode articles --freshness week
searchrelay search "Python tutorial" --mode video
searchrelay search "asyncio" --include-domain docs.python.org
searchrelay status
searchrelay clear-cache
```

General mode accepts homepages, docs, forums and other useful web pages. Article mode requests news
sources and rejects obvious landing pages; it is a heuristic, not content verification. Video mode requires
SerpApi. Unsupported modes are skipped explicitly. No transcripts or page extraction.

Exit codes: `0` useful, `2` empty, `3` unavailable, `1` invalid setup/input. Responses include attempt
outcomes and retry times where known. `empty` means at least one provider successfully returned no hits;
inspect attempts for other failures. `unavailable` includes unusable results and exhausted routing budgets.

### Python

```python
import asyncio
from searchrelay import Router, SearchRequest

async def main():
    async with Router() as router:
        response = await router.search(SearchRequest(query="Python asyncio documentation"))
        print(response.model_dump_json(indent=2))

asyncio.run(main())
```

### Local HTTP

```sh
searchrelay serve
curl http://127.0.0.1:8765/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Python asyncio documentation","limit":5}'
```

Open **http://127.0.0.1:8765/** for the local dashboard. If the port is occupied,
use `searchrelay serve --port 8768` and open that port instead.

The dashboard includes provider configuration, fallback-order arrows, local usage/cooldown status,
a search playground, recent operational activity, retention/cache settings, and cache clearing.
Provider keys entered there stay in **that server process's memory until restart**; they are never
returned to the page or written to settings. Other CLI/MCP processes do not inherit session keys.
Supply environment variables to those processes for persistent use. Forgetting a session key does
not remove a pre-existing environment key. Settings save atomically to the active config file and
apply to new searches immediately; other running processes need restarting to reload those settings.
Saving settings rewrites TOML formatting/comments. Dashboard controls never clear quota counters.

Endpoints: `GET /health`, `GET /v1/providers`, `POST /v1/search`; schema: `/openapi.json`.
Always binds to `127.0.0.1`. Rejects external Host headers and cross-origin browser requests;
same-origin dashboard requests are allowed. Settings/key/cache mutations also require a per-launch
dashboard session token. A strict Content Security Policy blocks remote scripts and framing.
Set `SEARCHRELAY_API_TOKEN` for local authentication; clients send `Authorization: Bearer <token>`.
The dashboard will ask for this token and retain it only in page memory. The HTML shell and static
assets remain public on loopback, while all data/API access requires the token when configured.
Do not expose through a public proxy. Access logs are off.

### MCP stdio

```json
{
  "mcpServers": {
    "searchrelay": {
      "command": "/absolute/path/searchrelay/.venv/bin/searchrelay",
      "args": ["mcp"]
    }
  }
}
```

Tools: `search`, `provider_status`. Inject provider credentials into the server's environment.
Ollama/Qwen need an application/agent harness to invoke search and provide the results to the model;
SearchRelay itself performs no inference. See [Ollama example](examples/ollama_agent.py).

## Routing

- Config order is preference order: Tavily → Firecrawl → SerpApi → You.com in the template.
- Skip disabled, unconfirmed, unsupported, locally exhausted, rate-spaced or cooling routes.
- Default: three search dispatches and a 20-second deadline, including at most one transient retry per
  provider with exponential backoff/jitter. Account preflight and MCP handshake add protocol calls.
- Honor REST `Retry-After`; never sleep through long rate limits. CAPTCHA/403 means cooldown, not bypass.
- Empty results permit fallback without declaring a provider unhealthy. Unknown upstream quota resets
  get a conservative 24-hour hold; the next upstream request still enforces its real limits.
- SQLite reserves local search-call slots atomically across processes. Failures/timeouts consume local
  slots conservatively. Local caps count **searches**, not upstream credit units.
- Local windows are UTC calendar day/month; actual billing cycles may differ. Other applications/account
  keys consume upstream quota outside this ledger. Local counts are estimates, not entitlements.
- One key per provider, no rotation. Engine provenance is Google for SerpApi, otherwise unknown.

No learned relevance ranking yet: explicit priority and failure cooldowns come first.

## Dates, results, filters

Results have title, URL, snippet, provider, upstream engine, kind, retrieved time, nullable publication time,
date status, date source, and raw date. Status: `verified`, `provider_reported`, `inferred`, or `unknown`.
Tavily dates are inferred because they may estimate publication/modification. Relative dates stay raw;
we do not invent exact timestamps. This pilot independently verifies **no publication dates**.
`--strict-dates` therefore rejects all current adapter results, intentionally.

Freshness is best effort; parsed dates older than the requested range are also rejected locally. Without
strict dates, undated hits may remain. Recent modification is not proof of recent publication.
Deduplication removes fragments and known tracking parameters while preserving meaningful URL parameters.
Domain filters match hostname boundaries, not lookalikes.

## Privacy, caching, retention

External providers receive queries, necessary filters, credentials where required, IP and connection
metadata. Fallback exposes queries to additional enabled providers. No conversation history is sent.
Provider retention still applies: local-first is not offline or anonymous.

Default SQLite state contains HMAC-derived credential pool IDs, counters, cooldowns and operational events
(provider/outcome/time); no raw queries, credentials, snippets or upstream bodies. Default event retention
is seven days; `retention_days=0` disables events. Pruning happens on the next search. Current quota
counters remain to enforce caps. State has owner-only file permissions where supported, not encryption.

Result caching is off. Only enable `cache_ttl_seconds` and per-provider `cache_allowed=true` after checking
storage permissions. Cached content is plaintext; TTL is at most 24 hours and expiration is lazy.
`clear-cache` deletes cached results/events, retaining counters and cooldowns. SQLite deletion is logical,
not guaranteed forensic erasure. Disk encryption is recommended for stronger local protection.

All returned content is untrusted. Never execute snippets or treat them as model instructions.
SearchRelay does not fetch result URLs; applications must escape content before rendering HTML.

## Development

```sh
python -m pip install -e '.[dev,http,mcp]' hatchling
python -m pytest -q
ruff check src tests
python -m build --no-isolation
```

Synthetic tests cover exhaustion, concurrent reservations, paid-plan rejection, deadlines, fallback,
cooldown persistence, dates, deduplication, caching, API guards and redaction. Live quality is a separate
evaluation. [Architecture](docs/ARCHITECTURE.md) · [Reuse assessment](docs/REUSE.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [MIT license](LICENSE).
