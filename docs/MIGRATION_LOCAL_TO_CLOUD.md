# Future Migration Reference Only: Local to Cloud

This document is **future migration reference only**. It is not part of the current pilot. Do not run Render, GCP, Vercel, Docker, cloud scheduler, or cloud deployment commands now.

## Current Mode: Local Windows Pilot

The current pilot remains local-first:

- Windows local execution only.
- Explicit system Python: `C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe`.
- Recommended next config: `config.pilot.local.example.yaml` copied to `config.pilot.local.yaml`.
- Local SQLite under `.radar-data/pilot/radar.db`.
- Dry-run/preview email only.
- No live SMTP.
- No registered Windows scheduled task unless separately approved.
- No cloud setup.

## Current local pilot lane

Recommended clean pilot layout:

```text
C:\AI Fusion Labs\PROJECTS\competitor-content-monitor\
  config.pilot.local.yaml
  .radar-data\pilot\
    radar.db
    logs\
    reports\
    backups\
```

Setup:

```powershell
cd "C:\AI Fusion Labs\PROJECTS\competitor-content-monitor"
copy config.pilot.local.example.yaml config.pilot.local.yaml
$Py = "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe"
$Cfg = "config.pilot.local.yaml"
```

Stable local command:

```powershell
& $Py -m radar.cli scan --config $Cfg --no-hermes
```

For local warning-strict runs after pilot warnings are understood:

```powershell
& $Py -m radar.cli scan --config $Cfg --no-hermes --fail-on-source-errors
```

Windows Task Scheduler should remain unregistered unless separately approved. Use `install-scheduled-task.ps1 -WhatIf` only if an operator explicitly asks for a prepared check.

## What would migrate later

Future migration would recreate or migrate:

- config file, minus secrets
- database state or a chosen clean baseline strategy
- report artifacts that must be retained
- Hermes CLI installation
- dedicated Hermes profile: `amy-radar`
- dedicated Hermes skill: `competitor-content-radar`
- SMTP env var names and secret injection mechanism
- scheduler command and timing policy

Do not migrate:

- Hermes Desktop UI assumptions
- local test fixture DBs as production state
- `.pytest_cache`, `__pycache__`, generated writer scaffolds
- secrets embedded in config files or reports

## Future migration reference only: Render Cron Job

Potential future resources:

- Render Cron Job for scheduler.
- Managed PostgreSQL for durable state, supplied via `database_url`.
- Persistent disk or object storage strategy for reports.

Future config path example only:

```text
/etc/radar/config.yaml
```

Future dry-run/no-Hermes validation example only:

```bash
python -m radar.cli scan --config /etc/radar/config.yaml --no-hermes
```

Future warning-strict command example only:

```bash
python -m radar.cli scan --config /etc/radar/config.yaml --fail-on-source-errors
```

Do not run these during the current local pilot.

## Future migration reference only: Google Cloud Run Jobs

Potential future resources:

- Cloud Run Jobs for one-shot execution.
- Cloud Scheduler trigger only after separate approval.
- Cloud SQL PostgreSQL for state.
- Google Cloud Storage for report retention, or a future report-storage adapter.
- Secret Manager for SMTP/provider secrets.

Future config path example only:

```text
/config/config.yaml
```

Future command example only:

```bash
python -m radar.cli scan --config /config/config.yaml --fail-on-source-errors
```

Do not run these during the current local pilot.

## Future database migration choices

### Clean-baseline migration

Recommended for a future cloud pilot:

1. Start with empty managed DB.
2. Run baseline with `--baseline --no-hermes`.
3. Run immediate second scan to prove no duplicate new items.
4. Enable Hermes/delivery only after review.

### Stateful migration

Use only if local pilot history must be preserved:

1. Stop scheduled/local runs.
2. Backup local SQLite DB.
3. Transform/import into PostgreSQL using an explicit migration script.
4. Validate counts with `state-audit` before any scan.
5. Keep the SQLite source archive read-only.

## Future live-email activation checklist

Before switching any environment to live SMTP:

- `dry_run` has intentionally been changed to `false` by operator approval.
- `email.enabled` is `true` and `email.preview_only` is `false` by approval.
- SMTP credentials exist only in the environment/secret manager.
- `state-audit` shows expected counts and `sent_email_count` baseline is understood.
- Latest report has no unsafe/unwanted content.
- Source warnings are visible in digest files.
- Outbox idempotency has been tested.

## Future dashboard migration posture

Dashboard remains future/read-only. A future migration target should expose only durable data contracts and artifacts for future dashboard work: workspace, source, article, report, run, health/state audit. Do not build a public dashboard, login, billing, or writable dashboard controls as part of the current pilot.
