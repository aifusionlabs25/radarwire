# Competitor Content Radar

Headless, email-first dry-run MVP. Desktop UI is not a runtime dependency.

## Current Mode: Local Windows Pilot

The current pilot is **local-first only**:

- Windows local execution only.
- Explicit system Python:
  `C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe`
- Local SQLite state under `.radar-data/pilot/radar.db`.
- Recommended next config: `config.pilot.local.example.yaml` copied to `config.pilot.local.yaml`.
- Dry-run/preview email only: `dry_run: true`, `email.enabled: false`, `email.preview_only: true`.
- No live SMTP.
- No registered Windows scheduled task unless separately approved.
- No Render, GCP, Vercel, Docker deployment, or cloud setup for the current pilot.

## Quick start: clean local pilot lane

On this Windows machine, plain `python` may resolve to Hermes' stripped venv. Use the explicit system Python:

```powershell
cd "C:\AI Fusion Labs\PROJECTS\competitor-content-monitor"
copy config.pilot.local.example.yaml config.pilot.local.yaml
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli doctor --config config.pilot.local.yaml
```

`config.pilot.local.example.yaml` is the recommended next config template. It points at:

```text
.radar-data/pilot/radar.db
```

This clean pilot lane does **not** delete or reuse existing build/test `.radar-data` evidence. Preserve current artifacts, including the five old fixture-looking records, unless cleanup is separately approved.

`scan --fixture` is fully offline and isolated: it bypasses live discovery/fetch, uses deterministic local fixture article data, and writes to separate fixture storage by default (`<data_dir>/fixture/radar.fixture.db`) rather than the pilot database. Override with `--fixture-data-dir` or `RADAR_FIXTURE_DATA_DIR` for validation runs.

## Hermes one-shot

Verified installed interface: `hermes -p amy-radar -s competitor-content-radar -z "<instruction>"` with payload on stdin. Install dedicated profile/skill only if needed for live model analysis:

```bash
radar install-hermes-profile
```

## Commands

- `radar doctor` — validate config and dry-run email posture.
- `radar scan --fixture` — offline deterministic pipeline validation.
- `radar scan --baseline --no-hermes` — local live-source baseline using deterministic analysis; no Hermes calls, no email send.
- `radar scan --no-hermes` — dry test path: crawl/fetch, analyze with DeterministicAnalysisAdapter, generate normal reports, mark articles analyzed, and keep `hermes_calls=0`.
- `radar scan --fail-on-source-errors` — optional strict mode: print report summary but exit nonzero if source warnings/errors were recorded.
- `radar state-audit` — read-only pilot state audit: counts, sent-email count, active locks, fixture-looking articles, latest run warnings/log path.
- `radar source-check` — app-state read-only live public-web discovery: shows discovered URLs per source, likely article vs non-article URL buckets, source quality notes, and skipped/warning reasons without writing articles, sending email, calling Hermes, or opening/creating SQLite state.
- `radar status`, `health-json`, `backup`, `restore`, `report-list`.

## Email

Live email is disabled for the current pilot. Keep:

```yaml
dry_run: true
email:
  enabled: false
  preview_only: true
```

The configured sender, recipient, and reply-to addresses are operator-controlled testing values. Do not remove or treat them as invalid placeholders merely because they are real addresses. `doctor` should only block syntactically invalid addresses, such as the old `#` placeholder form.

### Email test path

1. Run dry-run/preview only with `dry_run: true`, `email.enabled: false`, and `email.preview_only: true`.
2. Inspect the generated digest files under `.radar-data/pilot/reports/<run_id>/`:
   - `digest.html`
   - `digest.txt`
   - `digest.md`
   - `digest.json`
   - `run-summary.json`
3. Confirm the `From`, `To`, and `Reply-To` values in config are the operator-controlled sender/recipient/reply-to addresses intended for testing.
4. Run one explicit live SMTP test only after operator approval. That approval must explicitly allow changing `dry_run`, `email.enabled`, and `email.preview_only` for the test.
5. After any approved live SMTP test, confirm outbox idempotency and `sent_at` behavior: one intended send should create one sent outbox record with `sent_at` populated, and retrying the same digest should not create a duplicate live send.

SMTP credentials are loaded only from configured environment variable names if live sending is separately approved later. Do not put secrets in config files.

Email idempotency keys are based on recipient plus stable digest/article content, not transient run IDs. Empty digests with no warnings write report artifacts but skip preview/delivery with `skipped_empty_digest`.

## Crawling scope and update detection

The crawler stays within configured public domains/path prefixes, strips common tracking params, validates redirects, and respects `robots.txt` conservatively with bounded-timeout per-host caching within each run. If robots cannot be read, the MVP skips that URL rather than guessing.

`min_update_delta` suppresses minor text changes from becoming new notifications; substantial hash/content changes are marked pending.

TaxJar permits only `/blog/` and the observed safe redirect target `/resources/blog`, not broader `/resources/` crawling.

## Windows local runner

Review scripts in `scripts/windows`. `install-scheduled-task.ps1` must remain WhatIf/prepared only unless scheduler registration is separately approved.

`run-radar.ps1` does not rely on ambiguous plain `python`; it accepts `-PythonExe`, then checks `RADAR_PYTHON_EXE`, then `.venv\Scripts\python.exe`, then the known system Python path.

Dry fixture smoke example:

```powershell
.\scripts\windows\run-radar.ps1 -PythonExe "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -ConfigPath "config.pilot.local.yaml" -ExtraArgs '--fixture','--fixture-data-dir','.radar-data/pilot-fixture-smoke'
```

## Repo hygiene

`.gitignore` excludes runtime state, reports/logs/db files, caches, egg-info, local env/config files, and generated writer scaffolds. See `docs/CLEANUP_CANDIDATES.md`; do not delete generated/runtime state without approval.

## How to swap client competitor websites

Keep target swaps config-only whenever possible:

1. Copy `docs/SOURCE_INTAKE_TEMPLATE.md` and fill it out for each competitor.
2. Edit `config.pilot.local.yaml` only; do not hard-code client targets in Python.
3. For each source, provide `name`, `url`, optional `monitor_url`, optional `seed_article`, narrow `allowed_domains`, and narrow `allowed_paths`.
4. Add generic exclusions when source-check shows recurring listing/category/resource URLs:
   - `excluded_paths` for path prefixes to suppress, such as `/blog/category/`
   - `excluded_url_contains` for URL substrings to suppress, such as `/webinars`
   - `excluded_title_patterns` for future title-based filtering notes; source-check does not apply these because it does not fetch titles
5. Start with one seed article if the site is unfamiliar or the listing scope is uncertain.
6. Run read-only source validation before any scan:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli source-check --config config.pilot.local.yaml
```

`source-check` is app-state read-only live public-web discovery: it prints discovered URLs per source and skipped/warning reasons such as robots, scope, redirects, or listing errors. It does not write articles, send email, call Hermes, open/create SQLite state, or create `data_dir`/logs/reports/tmp. Because it may make public web requests to listing/feed/sitemap/robots URLs, run it only when live public-web discovery is appropriate.

7. If source-check looks sane, run dry local scans with `--no-hermes` and email still disabled.

## Future migration reference only

Cloud and container notes live in `docs/DEPLOYMENT.md` and `docs/MIGRATION_LOCAL_TO_CLOUD.md` as **future migration reference only**. They are not part of the current pilot. Do not run Docker builds, Render/GCP/Vercel setup, cloud schedulers, or any cloud deployment commands for this pilot.
