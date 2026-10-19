# Reuse assessment

Inspected current https://github.com/loudon84/web-search-mcp source before implementation, specifically
wsp_sdk/api.py, provider_adapter_protocol.py, budget_preflight_v3.py and pyproject.toml.
It has contracts, budget preflight and MCP support, but adapter contracts pass broader search/extraction
modules, research settings and compatibility envelopes. Its SDK ships with that larger distribution.
Using it still requires this project's free-account gating, dates and narrow routing contract.

Decision: independent small implementation on standard HTTP/MCP libraries. No code copied or modified
from that repository. Do not rebuild scraper engines: use reviewed official endpoints instead.
Revisit reuse if a small independently maintained adapter package supports these boundaries.

Related references: https://github.com/diegosouzapw/OmniRoute,
https://github.com/searxng/searxng, https://github.com/sweetcornna/free-search-mcp.
