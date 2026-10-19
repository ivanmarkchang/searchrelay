# Pilot validation

Local environment: macOS arm64, Python 3.12.14. Checked 2026-10-18.

- 41 synthetic/local tests passed, including official payload fixtures, REST errors/Retry-After,
  paid SerpApi preflight rejection, fallback, concurrent quota reservations across SQLite connections,
  restart cooldowns, timeout budgets, dates, domain boundaries, deduplication, cache permission,
  credential/query redaction, CLI initialization/exit codes, HTTP safeguards and complete MCP stdio calls.
- Ruff checks and git whitespace checks passed.
- Wheel and source distribution built successfully.
- One authorized live search through You.com's fixed keyless free MCP profile returned five results.
  This validates that connection and response parser for one request, not ongoing reliability or quality.
- No keyed provider live calls: no user free-account credentials have been configured.
- Ollama example not exercised against a running model. Python 3.10/3.13 checks are configured in CI,
  not locally executed. CI has not run on GitHub yet.
- One upstream Starlette TestClient deprecation warning; no failed tests.

Dashboard extension: browser-verified provider enable/save and a live keyless playground query returning
five sources, with attempts and date provenance rendered. New tests verify config/order persistence,
free-account gating, session-key redaction/no disk persistence, authenticated data access, same-origin
and session-token protections, static asset headers, and retaining quotas when clearing cache.
All three dashboard assets were verified inside the built wheel. No keyed live queries were performed.

Tests never exhaust real quotas, purchase credits, upgrade accounts or configure billing.
