# Security

No secrets are committed. SMTP credentials are read from the configured environment variable names at send time and are not logged. Crawler restricts requests to configured domains and path prefixes, strips tracking parameters, validates redirects, conservatively respects robots.txt, and rejects non-public schemes. Downloaded content is sanitized and treated as hostile. Hermes receives only sanitized article payloads and an analysis-only instruction. Hermes Desktop and gateway are not runtime dependencies.

For the local scheduled pilot, `configure-weekly-email.ps1` stores the SMTP app password as a Windows DPAPI current-user ciphertext under ignored `.radar-data/weekly-publish/`. The weekly worker decrypts it only in the same Windows account, exposes it only to the worker process through the configured environment variable, clears those process variables after delivery, and never writes credential values to task arguments, state JSON, report metadata, or logs. Moving the task to another Windows account requires a newly created credential envelope.

The configured `sender_email`, `recipient_email`, and `reply_to_email` values are operator-controlled testing addresses. They are not invalid placeholders merely because they are real addresses. The app should block syntactically invalid addresses such as the old `#` placeholder form, but live SMTP remains blocked until the operator explicitly approves changing `dry_run`, `email.enabled`, and `email.preview_only`.

Email testing path: run dry-run preview only, inspect generated digest artifacts, confirm From/To/Reply-To values, then run one explicit live SMTP test only after approval. After any approved live test, verify outbox idempotency and `sent_at` behavior. Do not expose SMTP credentials or print environment variable values.

Automatic delivery additionally requires a non-loopback SMTP host, STARTTLS, non-placeholder addresses, both credential variables, a stable HTTPS report URL, a non-empty clean report, and explicit `-EnableEmailDelivery`. Localhost SMTP is accepted only by the dedicated capture test override. The scheduler installer keeps delivery disabled unless that switch is supplied explicitly.

TaxJar scope is limited to `/blog/` plus the observed same-site redirect target `/resources/blog`; broader `/resources/` paths remain out of scope.
