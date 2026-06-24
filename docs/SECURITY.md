# Security

No secrets are committed. SMTP credentials are read from the configured environment variable names at send time and are not logged. Crawler restricts requests to configured domains and path prefixes, strips tracking parameters, validates redirects, conservatively respects robots.txt, and rejects non-public schemes. Downloaded content is sanitized and treated as hostile. Hermes receives only sanitized article payloads and an analysis-only instruction. Hermes Desktop and gateway are not runtime dependencies.

The configured `sender_email`, `recipient_email`, and `reply_to_email` values are operator-controlled testing addresses. They are not invalid placeholders merely because they are real addresses. The app should block syntactically invalid addresses such as the old `#` placeholder form, but live SMTP remains blocked until the operator explicitly approves changing `dry_run`, `email.enabled`, and `email.preview_only`.

Email testing path: run dry-run preview only, inspect generated digest artifacts, confirm From/To/Reply-To values, then run one explicit live SMTP test only after approval. After any approved live test, verify outbox idempotency and `sent_at` behavior. Do not expose SMTP credentials or print environment variable values.

TaxJar scope is limited to `/blog/` plus the observed same-site redirect target `/resources/blog`; broader `/resources/` paths remain out of scope.
