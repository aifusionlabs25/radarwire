# Private Editorial Workspace

RadarWire review kits can enable an in-page draft editor without turning the public report into a CMS. The client may edit either reading length, recover browser-local changes, and use **Save & download** or **Save & copy**.

The client experience deliberately separates three decisions:

1. **Choose this topic** records the weekly choice. It does not publish or send anything.
2. **Edit draft** stores a private revision before RadarWire copies or downloads it.
3. **Mark as published** appears only after the topic is chosen and requires the final public HTTPS link.

This progression keeps the first visit simple. The client does not see publication controls until they are relevant.

## Data Contract

A copy or download happens only after the revision API confirms that the revision was stored. The dialog explicitly tells the client that the revision is being saved privately in RadarWire.

Each immutable revision contains:

- client, edition, article, and reading-mode identifiers
- original and edited HTML and plain text
- original and edited SHA-256 hashes and word counts
- submission time and source review URL
- approval status and the plain-language retention notice shown before saving

Saved revisions use `approved_final` plus `voice_library_consent: true`. The dialog plainly explains that RadarWire retains the saved version to remember edits, improve future voice matching, and avoid repeated topics. There is no separate technical setting for the client to manage.

## Vercel Configuration

The revision API is `api/editorial-revisions.js`; the topic/publication ledger is `api/editorial-status.js`; and `api/editorial-session.js` establishes the browser's same-site editing session. They require:

- `BLOB_READ_WRITE_TOKEN`, injected by a private Vercel Blob store
- `RADAR_EDITORIAL_SAVE_TOKEN`, a long server-side signing credential

The client receives one ordinary review link. On page load, RadarWire silently creates a 90-day, `HttpOnly`, `Secure`, same-site browser session scoped to the API. The signing credential is never embedded in HTML, URLs, browser storage, Git, or report artifacts. Revision, status, and published-page snapshot blobs use private access and immutable paths.

The unauthenticated health check reports configuration booleans only:

```text
GET /api/editorial-revisions?health=1
GET /api/editorial-status?health=1
```

Do not share, email, or schedule an editing-enabled kit until both booleans are true and one operator-controlled save/download has been verified.

After the Blob store is linked, `scripts/windows/configure-editorial-workspace.ps1` creates a random signing credential, stores a DPAPI-encrypted local recovery copy, and configures the Vercel variable for all three environments. Vercel stores it as sensitive in Production and Preview and encrypted in Development. The helper refuses replacement unless `-Force` is supplied. It does not print the token, deploy, send email, or register a task. The older private-link clipboard helper is retained only for historical compatibility and is not part of the client workflow.

## Review Manifest

Enable the editor in an editorial review manifest:

```json
{
  "client_id": "amy-huffman",
  "edition_id": "edition-2026-08-14",
  "editorial_editing": true,
  "revision_api": "/api/editorial-revisions",
  "status_api": "/api/editorial-status",
  "session_api": "/api/editorial-session",
  "voice_library_name": "Amy Huffman approved voice library"
}
```

Use a new `edition_id` for every weekly edition so browser drafts and stored revisions never collide.

## Hermes Handoff

Sync approved revisions to the ignored local workspace:

```powershell
$env:RADAR_EDITORIAL_SAVE_TOKEN = Read-Host "Private review code"
python -m radar.cli voice-library-sync `
  --endpoint "https://site-export-preview.vercel.app/api/editorial-revisions" `
  --client-id "amy-huffman" `
  --output-dir ".radar-data/voice-library/amy-huffman"
Remove-Item Env:RADAR_EDITORIAL_SAVE_TOKEN
```

The command writes a portable `approved-voice-corpus.jsonl` and never writes the token. Feed the bounded approved examples to Content Studio:

```powershell
python -m radar.cli content-studio-expand `
  --config config.pilot.local.yaml `
  --run-id <run_id> `
  --briefs <briefs.json> `
  --output-dir <new-output-dir> `
  --voice-corpus ".radar-data/voice-library/amy-huffman/approved-voice-corpus.jsonl"
```

Hermes receives approved text as style evidence only. It is instructed not to copy sentences, treat it as factual evidence, or follow instructions contained inside the examples.

## Published-content Handoff

Only a **Mark as published** event enters the non-repetition history. A selected topic is useful workflow state, but it is not treated as published evidence. When Amy supplies a live 1099FIRE URL, RadarWire also attempts to archive a private HTML snapshot with its content hash. A temporary fetch failure does not lose the publication event; the failure is recorded for an operator retry.

Sync the private publication ledger to the ignored local workspace:

```powershell
$env:RADAR_EDITORIAL_SAVE_TOKEN = Read-Host "Private review code"
python -m radar.cli publication-history-sync `
  --endpoint "https://site-export-preview.vercel.app/api/editorial-status" `
  --client-id "amy-huffman" `
  --output-dir ".radar-data/publication-history/amy-huffman"
Remove-Item Env:RADAR_EDITORIAL_SAVE_TOKEN
```

Pass the resulting history into the next topic-generation run:

```powershell
python -m radar.cli content-studio `
  --config config.pilot.local.yaml `
  --run-id <run_id> `
  --output-dir <new-output-dir> `
  --publication-history ".radar-data/publication-history/amy-huffman/published-content.jsonl"
```

Hermes receives a bounded exclusion list. RadarWire also rejects generated brief titles that are materially similar to a recorded published title. This prevents accidental topic reuse without treating an unpublished selection as final.

## Optional AI revision panel

The AI revision panel is a separate, disabled-by-default layer over the existing manual editor. Enable it only on an isolated review manifest first:

```json
{
  "editorial_editing": true,
  "ai_revision_enabled": true,
  "job_api": "/api/editorial-jobs",
  "truth_profile": "1099fire-v1"
}
```

`api/editorial-jobs.js` stores an immutable request and append-only state events in private Vercel Blob storage. The existing same-site editorial session authorizes client submission and status checks. Only the operator bearer credential may claim, complete, fail, retry, or report a worker heartbeat.

The local worker uses outbound HTTPS only:

```powershell
$env:PYTHONPATH = 'src'
python -m radar.cli editorial-worker `
  --config config.pilot.amy-huffman-hermes-full-preview.yaml `
  --endpoint https://site-export-preview.vercel.app/api/editorial-jobs `
  --watch
```

For unattended Windows operation, `scripts/windows/run-editorial-worker.ps1` decrypts the existing DPAPI-protected editorial credential only inside the child process. `scripts/windows/install-editorial-worker-task.ps1` prepares an at-logon, restartable task but defaults to `WhatIfOnly`. It does not register or start the worker without a separate intentional activation.

The worker runs one article job at a time, permits only bounded state transitions, retries a failed Hermes transformation once, and validates both reading versions against `hermes/radarwire-editorial-reviser/references/1099fire-truth-profile.json`. It rejects active markup, unapproved URLs and images, competitor names, prohibited 1099FIRE service claims, missing calls to action, and em dashes. It never sends email, publishes, changes source configuration, or exposes a shell to the client instruction.

The worker replaces one private heartbeat record at most every five minutes. An operator can inspect it with an authorized `GET /api/editorial-jobs?worker_health=1&client_id=amy-huffman`; a heartbeat older than 15 minutes reports `online: false`.

If the worker is offline, Amy may continue to view, edit, save, and download existing drafts. AI requests stay queued in Vercel until the local worker returns. The browser preserves the job ID and resumes status checks after a refresh.

### Optional client conveniences

The review kit follows the visitor's system light or dark preference and includes a small theme control. The override is kept only in that browser's local storage.

Voice dictation uses the browser's `SpeechRecognition` implementation when available. It is a progressive enhancement: unsupported browsers retain the normal text field, dictated words remain editable, and dictation never submits a revision automatically.

Private attachments are separately gated:

```json
{
  "ai_revision_enabled": true,
  "ai_attachments_enabled": true,
  "attachment_api": "/api/editorial-attachments"
}
```

The client may paste a screenshot or attach up to three PNG, JPEG, WebP, PDF, Word, or text files, each smaller than 4 MB. `api/editorial-attachments.js` verifies the declared file signature and stores the bytes privately. The local worker retrieves attachments over authenticated outbound HTTPS. Word, PDF, and text content is extracted locally; images use Hermes's bounded image-analysis path before revision. Attachment context is treated as untrusted reference material and never as authority or executable instruction.

Do not upload taxpayer records, TINs, Social Security numbers, recipient files, or client data. Successfully processed attachments are removed from Blob storage when the job completes. Failed-job attachments remain private for operator retry and should be covered by normal private-storage retention cleanup.
