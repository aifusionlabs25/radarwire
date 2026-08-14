# Source Intake Template

Use this template whenever swapping Competitor Content Radar to a new client or competitor set. Source changes should be config-only whenever possible; do not hard-code client targets in Python.

## Client / workspace

- Client or workspace name:
- Pilot owner:
- Date collected:
- Notes / business context:

## Competitor source entry

Repeat this section once per competitor/content source.

### 1. Competitor name

- Human-readable name:
- Short source ID suggestion, lowercase/kebab-case, e.g. `acme-tax-blog`:

### 2. Blog/content URL

- Primary blog/content listing URL:
- Is this a listing/category page, homepage, resource center, or article page?
- If the URL has tracking params, provide the clean version if known:

### 3. Optional RSS/feed URL if known

- RSS/feed URL:
- Atom URL:
- Sitemap URL:
- Unknown / not available:

When a valid feed or sitemap lives outside the article path, configure it explicitly with `feed_urls` or `sitemap_urls`. Discovery endpoints must remain on an allowed public domain; URLs extracted from them are still restricted to `allowed_paths`.

### 4. Expected content paths

List URL path prefixes that are expected to contain public content. Keep scope narrow.

Examples:

```text
/blog/
/resources/blog/
/articles/
/learn/tax/
```

- Allowed content path prefixes:
- Paths that should explicitly stay out of scope:
- URL substrings that should be excluded, if any:
- Title patterns that may indicate non-article pages, if known:

### 5. Domains/subdomains

List only public domains/subdomains the crawler may access for this source.

Examples:

```text
www.example.com
example.com
blog.example.com
```

- Allowed domains/subdomains:
- Known redirects to include, if any:
- Domains/subdomains to exclude:

### 6. Seed article test

Should one known article be tested first before enabling broader listing discovery?

- Seed article URL:
- Should `seed_article: true` be used initially? yes/no
- Why this article is representative:

### 7. Access and ethics check

- Publicly accessible without login? yes/no
- Any paywall, CAPTCHA, or blocked crawler notice? yes/no
- Does robots.txt permit crawling the intended path? unknown/yes/no
- Any terms or sensitivity concerns?

### 8. Proposed YAML snippet

Draft config-only source entry:

```yaml
- id: example-source
  name: Example Source
  url: https://www.example.com/blog/
  monitor_url: https://www.example.com/blog/   # optional
  seed_article: false                           # true only for a seed article test
  allowed_domains:
    - www.example.com
    - example.com
  allowed_paths:
    - /blog/
  excluded_paths:
    - /blog/category/
  excluded_url_contains:
    - /webinars
  excluded_title_patterns:
    - "(?i)category|archive|webinar"
```

Use exclusions only after source-check shows recurring non-article URLs. `excluded_paths` and `excluded_url_contains` are applied during source discovery; `excluded_title_patterns` documents later title-aware filtering intent and is not applied by source-check because source-check does not fetch titles.

## Local validation workflow

After adding sources to `config.pilot.local.yaml`, run the read-only source check first:

```powershell
cd "C:\AI Fusion Labs\PROJECTS\competitor-content-monitor"
$Py = "C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe"
$Cfg = "config.pilot.local.yaml"
& $Py -m radar.cli source-check --config $Cfg
```

`source-check` is app-state read-only live public-web discovery: it does not write articles, send email, call Hermes, open/create SQLite state, or create `data_dir`/logs/reports/tmp. It may make public web requests to listing/feed/sitemap/robots URLs to print discovered URLs per source, likely article vs non-article URL buckets, source quality notes, and skipped URLs/warnings such as robots, scope, redirect, exclusion, or listing errors.

Only after source-check output looks sane should you run dry pilot scans with `--no-hermes` and live email disabled.
