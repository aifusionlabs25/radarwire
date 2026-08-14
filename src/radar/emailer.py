from __future__ import annotations

import hashlib
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .models import utcnow


class EmailProvider:
    def send(self, msg: EmailMessage) -> str:
        raise NotImplementedError


class SMTPEmailProvider(EmailProvider):
    def __init__(self, cfg, username=None, password=None):
        self.cfg = cfg
        self.username = username
        self.password = password

    @classmethod
    def from_config(cls, cfg):
        username = os.getenv(cfg.smtp_username_env) if cfg.smtp_username_env else None
        password = os.getenv(cfg.smtp_password_env) if cfg.smtp_password_env else None
        return cls(cfg, username=username, password=password)

    def __repr__(self):
        return f"SMTPEmailProvider(host={self.cfg.smtp_host!r}, port={self.cfg.smtp_port!r}, username_set={bool(self.username)}, password_set={bool(self.password)})"

    def send(self, msg):
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=20) as s:
            if self.cfg.use_tls:
                s.starttls()
            if self.username and self.password:
                s.login(self.username, self.password)
            return s.send_message(msg) or "sent"


def _stable_digest_projection(digest: dict) -> dict:
    articles = []
    for article in digest.get("articles", []):
        articles.append(
            {
                "url": article.get("url", ""),
                "title": article.get("title", ""),
                "summary": article.get("summary", ""),
                "content_hash": article.get("content_hash", ""),
            }
        )
    articles.sort(key=lambda x: (x["url"], x["content_hash"], x["title"]))
    return {"schema_version": digest.get("schema_version"), "article_count": digest.get("article_count", len(articles)), "articles": articles}


def message_key(digest: dict, recipient: str) -> str:
    stable = {"recipient": recipient, "digest": _stable_digest_projection(digest)}
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def email_subject(email_cfg, article_count: int, run_id: str) -> str:
    return f"{email_cfg.subject_prefix} {article_count} article(s) - {run_id}"


def _safe_provider_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def build_email(email_cfg, subject: str, html: str, text: str, md: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = email_cfg.sender_email
    msg["To"] = email_cfg.recipient_email
    msg["Reply-To"] = email_cfg.reply_to_email
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if md and email_cfg.attach_markdown:
        msg.add_attachment(md.encode("utf-8"), maintype="text", subtype="markdown", filename="digest.md")
    return msg


def read_email_artifacts(report_dir: Path) -> tuple[str, str, str | None, dict]:
    html_path = report_dir / "digest_email.html"
    text_path = report_dir / "digest_email.txt"
    if not html_path.exists():
        html_path = report_dir / "digest.html"
    if not text_path.exists():
        text_path = report_dir / "digest.txt"
    md_path = report_dir / "digest.md"
    metadata = {
        "html_artifact": html_path.name,
        "text_artifact": text_path.name,
        "markdown_artifact": md_path.name if md_path.exists() else None,
    }
    html = html_path.read_text(encoding="utf-8")
    text = text_path.read_text(encoding="utf-8")
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else None
    return html, text, md, metadata


def load_existing_report(cfg, run_id: str) -> tuple[Path, dict]:
    report_dir = cfg.data_dir / "reports" / run_id
    required = ["digest.json", "digest.html", "digest.txt", "run-summary.json"]
    missing = [name for name in required if not (report_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing report artifact(s) for run {run_id}: {', '.join(missing)}")
    digest = json.loads((report_dir / "digest.json").read_text(encoding="utf-8"))
    return report_dir, digest


def delivery_preflight(cfg, run_id: str, report_dir: Path, digest: dict) -> dict:
    subject = email_subject(cfg.email, digest.get("article_count", 0), run_id)
    return {
        "from": cfg.email.sender_email,
        "to": cfg.email.recipient_email,
        "reply_to": cfg.email.reply_to_email,
        "subject": subject,
        "run_id": run_id,
        "report_dir": str(report_dir),
        "smtp_username_env": cfg.email.smtp_username_env,
        "smtp_username_env_set": bool(os.getenv(cfg.email.smtp_username_env)) if cfg.email.smtp_username_env else False,
        "smtp_password_env": cfg.email.smtp_password_env,
        "smtp_password_env_set": bool(os.getenv(cfg.email.smtp_password_env)) if cfg.email.smtp_password_env else False,
    }


def deliver_existing_report(repo, cfg, run_id: str, *, send: bool = False, provider: EmailProvider | None = None) -> dict:
    report_dir, digest = load_existing_report(cfg, run_id)
    preflight = delivery_preflight(cfg, run_id, report_dir, digest)
    live_config = (not cfg.dry_run) and cfg.email.enabled and (not cfg.email.preview_only)
    if live_config and not send:
        raise ValueError("Refusing live-send-capable config without --send")
    if send:
        if not live_config:
            raise ValueError("Refusing send unless dry_run=false, email.enabled=true, email.preview_only=false, and --send is present")
        cfg.email.assert_live_send_allowed()
    delivery = deliver_or_preview(repo, cfg, run_id, report_dir, digest, provider=provider)
    return {"preflight": preflight, "delivery": delivery}


def deliver_or_preview(repo, cfg, run_id: str, report_dir: Path, digest: dict, provider: EmailProvider | None = None):
    if digest.get("article_count", 0) == 0 and digest.get("source_error_count", 0) == 0:
        return {"status": "skipped_empty_digest", "message_key": None}
    subject = email_subject(cfg.email, digest.get("article_count", 0), run_id)
    key = message_key(digest, cfg.email.recipient_email)
    outbox, created = repo.outbox_get_or_create(key, cfg.email.recipient_email, subject)
    outbox.subject = subject
    if not created and outbox.status == "sent":
        return {"status": "duplicate_skipped", "message_key": key}

    html, text, md, artifact_metadata = read_email_artifacts(report_dir)
    msg = build_email(cfg.email, subject, html, text, md)

    if cfg.dry_run or not cfg.email.enabled or cfg.email.preview_only:
        outbox.status = "preview"
        outbox.provider_response = f"preview_only_no_smtp; html={artifact_metadata['html_artifact']}; text={artifact_metadata['text_artifact']}"
        outbox.attempt_count += 1
        return {"status": "preview", "message_key": key, **artifact_metadata}

    cfg.email.assert_live_send_allowed()
    if provider is None:
        provider = SMTPEmailProvider.from_config(cfg.email)
    outbox.attempt_count += 1
    try:
        resp = provider.send(msg)
    except Exception as exc:
        outbox.status = "failed"
        outbox.sent_at = None
        outbox.provider_response = _safe_provider_error(exc)
        return {"status": "failed", "message_key": key, "provider_response": outbox.provider_response, **artifact_metadata}
    outbox.status = "sent"
    outbox.sent_at = utcnow()
    outbox.provider_response = str(resp)[:500]
    return {"status": "sent", "message_key": key, **artifact_metadata}
