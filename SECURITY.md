# Security

Do not post credentials in public issues. Use GitHub private vulnerability reporting if enabled;
otherwise contact the repository owner privately before disclosing exploit details.

HTTP binds to loopback, rejects cross-origin/external Host requests and supports an optional bearer token.
Same-origin dashboard requests are permitted. Administrative mutations require a per-launch session
header; keys are stored only in server process memory and never echoed. The public HTML shell contains
no provider credentials or private data. Set a local bearer token to protect API data from other local apps.
Other local processes may reach unauthenticated loopback services. Do not expose publicly.
Use free accounts without payment methods: arbitrary API keys can be billable.
External providers see queries and connection metadata. Returned content is untrusted.
No result URL fetching. Error summaries never serialize upstream bodies or credential-bearing URLs.
