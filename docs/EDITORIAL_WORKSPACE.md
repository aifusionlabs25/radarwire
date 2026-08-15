# Private Editorial Workspace

RadarWire review kits can enable an in-page draft editor without turning the public report into a CMS. The client may edit either reading length, recover browser-local changes, and use **Save & download** or **Save & copy**.

The client experience deliberately separates three decisions:

1. **Choose this topic** records the weekly choice. It does not publish or send anything.
2. **Edit draft** stores a private revision. Voice matching remains optional and requires a separate checkbox.
3. **Mark as published** appears only after the topic is chosen and requires the final public HTTPS link.

This progression keeps the first visit simple. The client does not see publication controls until they are relevant.

## Data Contract

A copy or download happens only after the revision API confirms that the revision was stored. The dialog explicitly tells the client that the revision is being saved privately in RadarWire.

Each immutable revision contains:

- client, edition, article, and reading-mode identifiers
- original and edited HTML and plain text
- original and edited SHA-256 hashes and word counts
- submission time and source review URL
- approval status and the client's explicit voice-library consent

Ordinary submissions use `submitted`. A revision is eligible for Hermes voice matching only when the client checks the approval box, producing `approved_final` plus `voice_library_consent: true`.

## Vercel Configuration

The revision API is `api/editorial-revisions.js`; the topic/publication ledger is `api/editorial-status.js`. Both require:

- `BLOB_READ_WRITE_TOKEN`, injected by a private Vercel Blob store
- `RADAR_EDITORIAL_SAVE_TOKEN`, a long private review code shared with the client outside the report URL

The token is sent in an authorization header and retained only in browser session storage. It is not embedded in generated HTML, query strings, Git, or report artifacts. Revision blobs use private access and unique immutable paths.

The unauthenticated health check reports configuration booleans only:

```text
GET /api/editorial-revisions?health=1
GET /api/editorial-status?health=1
```

Do not share, email, or schedule an editing-enabled kit until both booleans are true and one operator-controlled save/download has been verified.

After the Blob store is linked, `scripts/windows/configure-editorial-workspace.ps1` creates a random review code, stores a DPAPI-encrypted local recovery copy, and configures the Vercel variable for all three environments. Vercel stores it as sensitive in Production and Preview and encrypted in Development. The helper refuses replacement unless `-Force` is supplied. It does not print the token, deploy, send email, or register a task.

## Review Manifest

Enable the editor in an editorial review manifest:

```json
{
  "client_id": "amy-huffman",
  "edition_id": "edition-2026-08-14",
  "editorial_editing": true,
  "revision_api": "/api/editorial-revisions",
  "status_api": "/api/editorial-status",
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

Only a **Mark as published** event enters the non-repetition history. A selected topic is useful workflow state, but it is not treated as published evidence.

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
