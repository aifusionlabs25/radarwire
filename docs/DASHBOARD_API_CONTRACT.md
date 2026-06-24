# Dashboard API Contract

Future dashboard reads `digest.json` version `radar.digest.v1`. Suggested read-only resources: `/workspaces`, `/sources`, `/articles`, `/reports`, `/runs`, `/health`. The Python pipeline remains source of truth and controls crawl, analysis, recipient selection, and delivery.
