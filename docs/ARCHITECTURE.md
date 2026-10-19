# Architecture

Request → eligibility → permitted cache → atomic local reservation → adapter → normalize/filter/dedupe
→ response or bounded fallback. Models, configuration, state and provider adapters are separate modules.
CLI, HTTP and MCP call the same Router. Adapters never fall back to each other.

No inference, browser, scraper, scheduler, arbitrary endpoint configuration, payment mechanism or paid switch.
The async router uses ordered priority rather than unproven adaptive scoring. Modes and dates are explicit.

SQLite transactions reserve slots before dispatch; failed/cancelled requests are not refunded. Credentials
are HMAC-derived into pool identifiers. Multiple keys of the same external account are not detectable;
other applications consume upstream quota outside this local ledger. Unknown engine provenance stays unknown.
SQLite critical sections are synchronous with a five-second contention timeout; network budget is rechecked
before dispatch. State failure aborts rather than sending an untracked search. No quota-reset command.

Implementation order: library/CLI → thin HTTP API → MCP. Live provider validation and optional further
adapters follow fixture-based verification. No publication-date verifier or learned relevance scorer yet.
