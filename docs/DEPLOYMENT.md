# Deployment Notes

## Current Mode: Local Windows Pilot

This project is **not deploying to cloud now**. The current pilot is local-first:

- Windows local execution only.
- Explicit system Python: `C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe`.
- Recommended next config: `config.pilot.local.example.yaml` copied to `config.pilot.local.yaml`.
- Local SQLite under `.radar-data/pilot/radar.db`.
- Dry-run/preview email only.
- No live SMTP.
- No registered Windows scheduled task unless separately approved.
- No Render, GCP, Vercel, Docker deployment, or cloud setup.

## Local pilot path first

Recommended local pilot layout:

```text
C:\AI Fusion Labs\PROJECTS\competitor-content-monitor\
  config.pilot.local.yaml
  .radar-data\pilot\
    radar.db
    logs\
    reports\
    backups\
```

Recommended config setup:

```powershell
cd "C:\AI Fusion Labs\PROJECTS\competitor-content-monitor"
copy config.pilot.local.example.yaml config.pilot.local.yaml
```

Recommended explicit Python variable:

```powershell
$Py = "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe"
$Cfg = "config.pilot.local.yaml"
```

Stable local command:

```powershell
& $Py -m radar.cli scan --config $Cfg --no-hermes
```

Warning-strict local command, after source scope is tuned:

```powershell
& $Py -m radar.cli scan --config $Cfg --no-hermes --fail-on-source-errors
```

Keep `--fail-on-source-errors` off during exploratory pilot scans if you prefer fail-soft reporting while source warnings are being tuned.

## Local required configuration and environment

Configuration file supplies non-secret settings:

- `workspace_id`
- `data_dir: .radar-data/pilot`
- `database_url: sqlite:///.radar-data/pilot/radar.db`
- `dry_run: true`
- crawl scope/source allowlists
- Hermes profile/skill command flags
- sender/recipient/reply-to addresses
- SMTP env-var names, not SMTP secret values

For the current pilot, live SMTP env vars are not required because email remains disabled/preview-only. Do not print env var values in logs, reports, status output, or support tickets.

## Local Windows runner path

Runner smoke command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& { .\scripts\windows\run-radar.ps1 -PythonExe 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe' -ConfigPath 'config.pilot.local.yaml' -ExtraArgs '--fixture','--fixture-data-dir','.radar-data/pilot-runner-fixture'; exit $LASTEXITCODE }"
```

Prepared scheduled-task check only, if explicitly requested later:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install-scheduled-task.ps1 -WhatIf
```

Do not register or enable the task until manual scans, runner smoke, warning visibility, state audit, and live-email gates pass and the operator separately approves scheduling.

## Live-email activation checklist — local future step only

Before live email anywhere:

1. Clean pilot state audited with `radar state-audit`.
2. Baseline and immediate second scan prove no duplicate new items.
3. Reports show source warnings clearly.
4. `sent_email_count` is zero before activation.
5. SMTP credentials are supplied only through configured env vars.
6. Outbox idempotency is verified in dry-run/preview mode.
7. Operator explicitly approves setting `dry_run: false`, `email.enabled: true`, and `email.preview_only: false`.

## Future migration reference only: cloud/container

The sections below are **future migration reference only**. They are not part of the current pilot. Do not run Docker builds, Render setup, GCP setup, Vercel setup, cloud scheduler commands, or cloud deployment commands now.

### Future migration reference only: Render Cron Job

Potential future managed-host shape:

- Render Cron Job for scheduler.
- Managed PostgreSQL for durable state, supplied via `database_url`.
- Persistent disk or object storage strategy for reports.
- Hermes CLI/profile/skill installed in the image or build step.

Future command example only:

```bash
python -m radar.cli scan --config /etc/radar/config.yaml --fail-on-source-errors
```

### Future migration reference only: Google Cloud Run Jobs

Potential future shape:

- Cloud Run Jobs for one-shot execution.
- Cloud Scheduler trigger only after separate approval.
- Cloud SQL PostgreSQL for state.
- Google Cloud Storage for report retention or future storage adapter.
- Secret Manager for SMTP/provider secrets.

Future command example only:

```bash
python -m radar.cli scan --config /config/config.yaml --fail-on-source-errors
```

## Dashboard posture

Dashboard remains future/read-only. Current local pilot produces dashboard-ready JSON (`digest.json`) and state audit output only. Do not add client login, billing, public dashboards, or writable dashboard controls in this pilot lane.
