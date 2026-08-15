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
- `radar content-studio --run-id <run_id>` — use an existing source-clean digest to generate three ranked blog briefs and one internal draft; no crawl, email, SQLite mutation, scheduler, deployment, or publishing.
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

Generated reports now separate the two client-facing delivery formats:

- `digest_email.html` and `digest_email.txt` are the compact email memo. Delivery prefers these files when present.
- `digest.html` is the interactive browser report with filters, search, and drill-down controls.
- `digest.md` remains the optional markdown attachment/source artifact.

For a client pilot, the recommended offer is: send the short email brief, then link to the interactive report page only when a hosted report has been explicitly approved.

## Content Studio proof

Content Studio is an explicit post-report step. It does not run automatically with a scan and it never publishes:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli content-studio --config <pilot-config.yaml> --run-id <run_id>
```

Default output is `<report_dir>/content-studio/` and includes:

- `briefs.json` and `briefs.md`: three ranked, multi-source editorial briefs.
- `draft.json` and `draft.md`: one internal draft expanded from rank 1.
- `review.html`: a compact operator-review page.
- `manifest.json`: provenance and side-effect declarations.

The command refuses source-warning digests and existing non-empty output folders by default. Drafts are internal proofs, not tax or legal advice. Fact-check every time-sensitive claim before client review, and never auto-publish.

Content Studio also rejects drafts that exceed the bounded reading length, overuse inline verification markers, cite URLs outside the source digest, name a competitor in client-facing prose or CTA, or fail to name the configured client in the CTA. Any bounded Hermes repair pass and deterministic list trim is disclosed in `manifest.json`.

Every generated draft now receives a separate claim-verification ledger. Hermes-created factual-review items always begin as `needs_review`; only a named, timestamped human review may promote a claim to `verified`, and that status requires an allowed official `.gov` source plus a review note. `editorial-review-build` requires a ledger for every article, and SMTP preflight refuses editorial packages without a consistent aggregate verification summary.

Expand one or more approved existing briefs without regenerating research or the brief set:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli content-studio-expand --config <config> --run-id <run_id> --briefs <briefs.json> --ranks 2,3 --output-dir <new-draft-dir>
```

Each requested brief runs as an isolated bounded Hermes draft job. The command validates the report ID, source URLs, word bounds, client branding, and output directory, and declares its call count and side-effect posture in `manifest.json`.

After human fact-checking and artwork approval, build a local static comparison hub from a reviewed article manifest:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli editorial-review-kit --manifest <articles.json> --output-dir <local-review-dir>
```

The review-kit builder requires local reviewed Markdown and images, rejects unresolved `[VERIFY]` markers, and writes only HTML, CSS, JavaScript, and a local manifest. It does not email, publish, deploy, crawl, or use SQLite.

For a dual-length article, set `body` to the concise default Markdown, add `full_body` for the extended guide, and provide `full_read_time`. The generated page renders an accessible `Quick Read / Full Guide` segmented control while preserving the single-article format for manifests without `full_body`.

Dual-length pages also accept `?view=quick` and `?view=full` so an email can open the intended edition directly. Set `email_preview: true` to generate a static, JavaScript-free `email-preview.html` with one thumbnail, synopsis, and both reading links per concept. Add `review_base_url` only after the review package has an approved hosted URL; otherwise the preview keeps local relative links and sends nothing.

For client delivery, the editorial shortlist is the primary message and the competitor radar is optional supporting research. Set a stable `delivery_id`, absolute `review_base_url`, optional `supporting_report_url`, and reviewed `email_subject` in the editorial manifest. The builder then writes `email-preview.html`, `email-preview.txt`, and `email-preview.json`. Run `editorial-email-preflight` before the separately approved `deliver-editorial-review --send`; the dedicated outbox key prevents a second send for the same delivery ID and recipient. Do not substitute the dense radar digest for this client-facing shortlist.

Run `editorial-review-validate` with the same manifest and output directory before client review. It checks page structure, approved image references, internal and external links, responsive breakpoints, competitor-brand leakage, encoding damage, unresolved verification markers, and the build's side-effect declarations.

## Interactive report page export

The app can prepare either an immutable run route or a stable client-facing route for static hosting:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli export-report-site --config config.pilot.local.yaml --run-id <run_id>
```

For a link that stays the same from week to week, add a reviewed route name and explicit overwrite:

```powershell
& "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe" -m radar.cli export-report-site --config config.pilot.local.yaml --run-id <run_id> --route-name 1099fire-radar --overwrite
```

Default output:

```text
.radar-data/site-export/reports/<run_id>/index.html
```

That `index.html` is the same interactive report as `digest.html`. The command copies files only; it does not send email, run the crawler, call Hermes, register a scheduler, or deploy to Vercel. `report-site.json` records the real run ID, export time, article count, source-error count, and stable route so a separate publisher can verify exactly what went live. If this becomes client-facing, host it behind an approved private URL, tokenized path, password, or login rather than leaving reports openly discoverable.

## Crawling scope and update detection

The crawler stays within configured public domains/path prefixes, strips common tracking params, validates redirects, and respects `robots.txt` conservatively with bounded-timeout per-host caching within each run. If robots cannot be read, the MVP skips that URL rather than guessing.

`min_update_delta` suppresses minor text changes from becoming new notifications; substantial hash/content changes are marked pending.

TaxJar permits only `/blog/` and the observed safe redirect target `/resources/blog`, not broader `/resources/` crawling.

## Windows local runner

Review scripts in `scripts/windows`. `install-scheduled-task.ps1` must remain WhatIf/prepared only unless scheduler registration is separately approved.

`run-radar.ps1` does not rely on ambiguous plain `python`; it accepts `-PythonExe`, then checks `RADAR_PYTHON_EXE`, then `.venv\Scripts\python.exe`, then the known system Python path.

`publish-weekly-report.ps1` is the guarded Sunday-report lane. It requires `dry_run: true`, `email.enabled: false`, and `email.preview_only: true`; fails closed on source errors, failed sources, warnings, or incomplete runs; preserves the last good live report when no articles changed; resumes an interrupted export/deploy; and verifies the live run ID after Vercel deploy. Its state and logs live under `.radar-data/weekly-publish/`.

`install-weekly-publish-task.ps1` prepares a Sunday 6:00 PM local-time task with `StartWhenAvailable` and bounded retries. It defaults to preview-only and must be passed `-WhatIfOnly:$false` only after the config, stable route, Vercel link, and local machine schedule are approved.

### Optional automatic email delivery

Automatic email is a separate post-publish stage and is disabled by default. `configure-weekly-email.ps1` creates a private live-delivery config plus a Windows DPAPI credential envelope under `.radar-data/weekly-publish/`. The app password is encrypted for the current Windows user and is never placed in Git, task arguments, or logs. The configurator does not send email or change Task Scheduler.

If the delivery config is already prepared and only the Gmail app password needs to be stored or replaced, run `scripts/windows/store-smtp-credential.ps1` (add `-Force` only to replace the existing local envelope). The helper hides input, removes Google's display spaces, requires exactly 16 characters, and sends no email.

When `publish-weekly-report.ps1` is explicitly run with `-EnableEmailDelivery`, it publishes and verifies the hosted report first, loads the DPAPI credential into process-only environment variables, runs `email-delivery-preflight`, and then invokes one idempotent `deliver-report --send`. The preflight refuses placeholder addresses, loopback SMTP, missing credentials, non-TLS SMTP, missing report URLs, empty reports, warnings, and source errors. Delivery state is recorded as `pending_email`, `failed_email`, or `delivered`; retries accept `duplicate_skipped` as proof that an earlier send already completed.

Client-facing editorial delivery additionally validates the final HTML and text artifacts, not only their metadata. Every review, Quick Read, Full Guide, supporting, and image URL must be absolute HTTPS and must not use a local or placeholder host; delivery fails closed when any required route is missing or unsafe.

For client-facing scheduling, `-EnableEmailDelivery` also requires `-EditorialReviewDir` and `-EditorialReviewUrl`; the worker verifies the hosted editorial route and uses the editorial preflight and sender. The dense radar email is blocked by default and requires `-AllowRadarDigestEmail`, which is reserved for an explicitly approved internal research recipient.

Do not add `-EnableEmailDelivery` to the scheduled task until a localhost capture and one separately approved real SMTP test have both passed. A week with no changed articles preserves the prior hosted report and sends no email.

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

Private client editing, immutable revision capture, and approved Hermes voice examples are documented in `docs/EDITORIAL_WORKSPACE.md`.

Cloud worker and container notes live in `docs/DEPLOYMENT.md` and `docs/MIGRATION_LOCAL_TO_CLOUD.md` as **future migration reference only**. The approved pilot still runs discovery and Hermes locally; Vercel hosts only the generated static review pages. Do not move the crawler, Hermes worker, SQLite state, or scheduler into cloud infrastructure without a separate migration decision.
