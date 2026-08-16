# Hermes Creative Shadow

This command is a private artwork audition. It is not part of `scan`, weekly publishing, email delivery, Vercel deployment, or Windows scheduling.

## Safety boundary

- Disabled unless `--enable-hermes-image-generation` is supplied.
- Accepts one reviewed editorial manifest and one article slug.
- Generates exactly three candidates: A, B, and C.
- Uses a dedicated Hermes profile and skill.
- Writes only to a new shadow output directory.
- Copies the current hero as an unchanged control.
- Never promotes the selected candidate into the client package.
- Never sends email, publishes, deploys, schedules, crawls, or mutates SQLite.
- Refuses a non-empty output directory.

Hermes output is instructed and normalized to contain no em dashes. Hyphens should be used sparingly and only for ordinary compound words.

## Profile

The tested profile is `radarwire-art-jury`, cloned from the updated default GPT-5.6 Sol profile. The repo-owned skill is:

```text
hermes/radarwire-creative-director/SKILL.md
```

Verify the private profile before a paid run:

```powershell
hermes -p radarwire-art-jury config get image_gen.provider
hermes -p radarwire-art-jury -s radarwire-creative-director -t safe -z 'Return strict JSON only: {"status":"READY"}. Do not call tools.'
```

The successful audition used `openai-codex`. A provider failure must stop the run; do not silently switch a shared profile.

## Run

Use a fresh output directory every time:

```powershell
$env:PYTHONPATH = 'src'
python -m radar.cli creative-shadow `
  --manifest <review-kit>/content/articles.json `
  --article-slug pre-filing-readiness `
  --output-dir .radar-data/creative-shadow/<new-run-id> `
  --enable-hermes-image-generation `
  --profile radarwire-art-jury `
  --skill radarwire-creative-director
```

If a reviewed Hermes plan or successful private candidate already exists, use `--plan-path` and `--candidate-a-ref` to resume without paying for duplicate work.

## Review gate

The jury scores brand fit, editorial credibility, human authenticity, subject relevance, composition, and artifact risk. Visible garbled text, logo imitation, distorted anatomy, fake tax forms, irrelevant imagery, or a cheap stock or AI appearance creates a rejection flag.

A recommendation still requires human review. Promotion into the client package is intentionally a separate future operation.
