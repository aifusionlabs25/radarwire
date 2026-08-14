# Operations Runbook

## Current Mode: Local Windows Pilot

The current pilot is local-first only:

- Windows local execution only.
- Explicit system Python: `C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe`.
- Recommended next config: copy `config.pilot.local.example.yaml` to `config.pilot.local.yaml`.
- Local SQLite state: `.radar-data/pilot/radar.db`.
- Dry-run/preview email only: `dry_run: true`, `email.enabled: false`, `email.preview_only: true`.
- No live SMTP.
- No registered Windows scheduled task unless separately approved.
- No Render, GCP, Vercel, Docker deployment, or cloud setup for this pilot.

## Local pilot setup

From the repo root:

```powershell
cd "C:\AI Fusion Labs\PROJECTS\competitor-content-monitor"
copy config.pilot.local.example.yaml config.pilot.local.yaml
```

Do not delete or reuse current build/test `.radar-data` evidence. The clean pilot lane is `.radar-data/pilot/`.

## Operating commands

- `radar doctor` validates config and blocks syntactically invalid email placeholders such as the old `#` form. The current configured sender/recipient/reply-to addresses are operator-controlled testing values and must not be removed or treated as invalid merely because they are real addresses.
- `radar scan --fixture` runs fully offline deterministic fixture mode; it does not call live discovery/fetch, Hermes, or SMTP, and by default writes to `<data_dir>/fixture/radar.fixture.db` instead of the pilot database. Use `--fixture-data-dir` or `RADAR_FIXTURE_DATA_DIR` to choose another isolated fixture store.
- `radar scan --baseline --no-hermes` seeds the clean pilot baseline using deterministic analysis; no Hermes calls and no email sends.
- `radar scan --no-hermes` is the recommended live-source dry test mode: it crawls/fetches, runs deterministic analysis, marks articles analyzed, writes normal reports, and keeps `hermes_calls=0`.
- Empty digest policy: if no articles were analyzed and no source warnings occurred, report artifacts are still written but email preview/delivery is skipped with `skipped_empty_digest`; warning-only reports remain preview/delivery eligible.
- If `radar scan` returns a failed pipeline summary, the CLI prints the summary and exits with status code 1; Windows runner preserves that exit code.
- `radar source-check --config config.pilot.local.yaml` is app-state read-only live public-web discovery. It shows discovered URLs per source, likely article vs non-article URL buckets, source quality notes, and skipped/warning reasons such as robots, scope, redirects, and listing errors. It does not write articles, send email, call Hermes, open/create SQLite state, or create `data_dir`/logs/reports/tmp. It may make public web requests to listing/feed/sitemap/robots URLs.
- `radar state-audit` is read-only and redacts database URLs; it reports counts, sent-email evidence, active locks, fixture-looking records, latest warning status, and cleanup/archive guidance.
- `radar status` and `radar health-json` inspect state, including latest run status, last error, source errors, log path, and active lock count.
- `radar content-studio --config <config> --run-id <run_id>` reads an existing source-clean digest and writes three blog briefs plus one internal draft. It makes two bounded Hermes calls but does not crawl, use SQLite, send email, schedule, deploy, or publish.
- `radar backup` creates a zip under data dir; `radar restore ARCHIVE` restores.
- Pipeline logs are written to `.radar-data/pilot/logs/pipeline-<run_id>.log` when using `config.pilot.local.yaml`; per-run file handlers are closed after each run.
- Robots checks use bounded-timeout per-host caching within a run. Conservative behavior remains: if robots cannot be safely verified, the URL is skipped.

## How to swap client competitor websites

1. Fill out `docs/SOURCE_INTAKE_TEMPLATE.md` for each competitor.
2. Change source targets in `config.pilot.local.yaml`; keep source changes config-only unless a new adapter is explicitly required.
3. Use narrow `allowed_domains` and `allowed_paths`. Do not broaden scope to a whole domain unless explicitly intended.
4. Add generic exclusions when source-check repeatedly classifies URLs as non-articles:
   - `excluded_paths` for path prefixes such as `/blog/category/` or archive sections
   - `excluded_url_contains` for URL substrings such as `/webinars`
   - `excluded_title_patterns` for later title-aware filtering notes; source-check does not apply title patterns because it does not fetch titles
5. If uncertain, configure one representative `seed_article: true` first, validate it, then broaden to the listing page.
6. Run:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli source-check --config config.pilot.local.yaml
```

7. Review discovered URLs, likely article/non-article buckets, source quality notes, skipped URLs, robots warnings, and scope errors. Fix config before running scans.
8. Only after source-check looks sane, run `scan --no-hermes` with dry-run email still enabled.

## Email test path

Current pilot posture is dry-run/preview only. Do not enable live SMTP without explicit approval.

1. Keep `dry_run: true`, `email.enabled: false`, and `email.preview_only: true`.
2. Run the desired dry scan and inspect generated digest artifacts under `.radar-data/pilot/reports/<run_id>/`.
3. Confirm configured `sender_email`, `recipient_email`, and `reply_to_email` are the operator-controlled addresses intended for testing.
4. Only after explicit approval, run one live SMTP test by intentionally changing the three live-send gates and supplying SMTP credentials through environment variables.
5. After that approved test, run `radar state-audit` and inspect outbox state: the intended sent message should have `sent_at` populated, and retrying the same digest should be skipped by idempotency rather than sent again.

### Client delivery formats

Each scan writes both email-friendly and browser-friendly report artifacts:

- `digest_email.html` and `digest_email.txt`: compact email memo for the client inbox.
- `digest.html`: interactive report page with search, filters, source drill-down, theme drill-down, and expandable article cards.
- `digest.json`: dashboard-ready data contract for later product work.

Recommended pilot packaging:

1. Review `digest_email.html` as the actual email body.
2. Review `digest.html` as the optional interactive report page.
3. If the client only wants email, send only the compact memo after explicit live-send approval.
4. If the client wants a report link, export the static report page first and host it only after a separate deployment approval.

### Draft-content review path

1. Run Content Studio only against a reviewed, source-clean report.
2. Review `content-studio/briefs.md` and choose an editorial direction.
3. Treat `content-studio/draft.md` as an internal proof even when it reads cleanly.
4. Verify every item in its factual-review checklist against primary sources before client review.
5. Confirm tone, offer emphasis, and CTA with the client.
6. Keep WordPress or other CMS publishing manual and separately approved.

To expand approved briefs independently, use `content-studio-expand` with an existing `briefs.json`, explicit ranks, and a new output directory. Run one rank per invocation for clear status and inexpensive retries. The command does not rerun discovery or mutate app state.

To create a polished local review package after factual and visual approval, use `editorial-review-kit` with a reviewed article manifest and local output directory. The builder refuses unresolved `[VERIFY]` markers, missing images, paths outside the kit, and existing generated pages unless overwrite is explicitly requested. Building the review kit is not approval to email, host, deploy, or publish it.

Prepared static export command, no deploy:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli export-report-site --config config.pilot.local.yaml --run-id <run_id>
```

The export command writes `.radar-data/site-export/reports/<run_id>/index.html` and companion artifacts. It does not send email, run discovery/fetch, call Hermes, use SQLite beyond loading the existing report config, register a scheduler, or deploy to Vercel.

If an export folder already exists, the command refuses to overwrite it unless `--overwrite` is supplied after manual review.

## Windows runner and scheduler posture

`run-radar.ps1` accepts `-PythonExe` or `RADAR_PYTHON_EXE`, prefers `.venv`, and falls back to the known system Python path on this machine.

Safe runner smoke example:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& { .\scripts\windows\run-radar.ps1 -PythonExe 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe' -ConfigPath 'config.pilot.local.yaml' -ExtraArgs '--fixture','--fixture-data-dir','.radar-data/pilot-runner-fixture'; exit $LASTEXITCODE }"
```

Scheduler scripts are reference/prepared artifacts only for now. Do not register, start, enable, or modify a Windows Task Scheduler task unless separately approved. `install-scheduled-task.ps1 -WhatIf` is the only acceptable scheduler check in the current pilot lane.

## Future migration reference only

Cloud/container guidance is future reference only. Do not run Docker, Render, GCP, Vercel, or cloud scheduler commands for the current pilot.

## Rollback

Because scheduler and live SMTP are disabled, rollback is local and simple: stop running commands, preserve `.radar-data/pilot`, and inspect `radar state-audit`. Do not delete runtime state without approval.
