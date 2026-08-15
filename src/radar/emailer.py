from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

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


def _add_report_link(html: str, text: str, report_url: str | None) -> tuple[str, str]:
    if not report_url:
        return html, text
    safe_url = html_lib.escape(report_url, quote=True)
    cta = (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:20px 0 4px;">'
        '<tr><td align="center">'
        f'<a href="{safe_url}" style="display:inline-block;background:#008a92;color:#ffffff;'
        'font-weight:800;text-decoration:none;padding:12px 18px;border-radius:6px;">Open interactive report</a>'
        '</td></tr></table>'
    )
    if "</main>" in html:
        html = html.replace("</main>", cta + "</main>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", cta + "</body>", 1)
    else:
        html += cta
    text = text.rstrip() + f"\n\nOpen the interactive report:\n{report_url}\n"
    return html, text


def read_email_artifacts(report_dir: Path, report_url: str | None = None) -> tuple[str, str, str | None, dict]:
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
    html, text = _add_report_link(html, text, report_url)
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
        "report_url": cfg.email.report_url,
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

    html, text, md, artifact_metadata = read_email_artifacts(report_dir, cfg.email.report_url)
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


def editorial_message_key(delivery_id: str, recipient: str) -> str:
    payload = json.dumps(
        {"kind": "editorial_review", "delivery_id": delivery_id, "recipient": recipient},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_hosted_email_url(value: str, label: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").casefold().rstrip(".")
    placeholder_hosts = {"example.com", "example.net", "example.org", "invalid"}
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError(f"Editorial email {label} must be an absolute HTTPS URL")
    if (
        host in {"localhost", "127.0.0.1", "::1"}
        or host.endswith((".localhost", ".local", ".test", ".invalid"))
        or host in placeholder_hosts
        or any(host.endswith(f".{suffix}") for suffix in placeholder_hosts)
    ):
        raise ValueError(f"Editorial email {label} uses a local or placeholder host")
    return value.strip()


def validate_editorial_email_urls(html: str, text: str, metadata: dict) -> dict:
    concept_count = int(metadata.get("concept_count") or 0)
    review_url = _safe_hosted_email_url(str(metadata.get("review_url") or ""), "review_url")
    page = BeautifulSoup(html, "html.parser")
    hrefs = [str(link.get("href") or "").strip() for link in page.select("a[href]")]
    sources = [str(image.get("src") or "").strip() for image in page.select("img[src]")]
    if not hrefs:
        raise ValueError("Editorial email must contain hosted links")
    for index, href in enumerate(hrefs, start=1):
        _safe_hosted_email_url(href, f"link {index}")
    for index, source in enumerate(sources, start=1):
        _safe_hosted_email_url(source, f"image {index}")
    text_urls = [match.rstrip(".,;:)") for match in re.findall(r"https?://\S+", text)]
    for index, text_url in enumerate(text_urls, start=1):
        _safe_hosted_email_url(text_url, f"text link {index}")

    quick_links = [href for href in hrefs if "?view=quick" in href]
    full_links = [href for href in hrefs if "?view=full" in href]
    if len(quick_links) != concept_count or len(full_links) != concept_count:
        raise ValueError("Editorial email must contain one hosted Quick Read and Full Guide link per concept")

    normalized_review = review_url.rstrip("/")
    valid_hub_urls = {normalized_review, f"{normalized_review}/", f"{normalized_review}/index.html"}
    if not valid_hub_urls.intersection(hrefs):
        raise ValueError("Editorial email is missing its hosted review hub link")
    if review_url not in text and normalized_review not in text:
        raise ValueError("Editorial email text preview is missing its hosted review URL")

    return {
        "hosted_link_count": len(hrefs),
        "hosted_image_count": len(sources),
        "text_link_count": len(text_urls),
        "quick_read_link_count": len(quick_links),
        "full_guide_link_count": len(full_links),
        "all_urls_absolute_https": True,
    }


def load_editorial_email(review_dir: Path) -> tuple[str, str, dict, dict]:
    review_dir = review_dir.resolve()
    html_path = review_dir / "email-preview.html"
    text_path = review_dir / "email-preview.txt"
    metadata_path = review_dir / "email-preview.json"
    missing = [path.name for path in (html_path, text_path, metadata_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing editorial email artifact(s): {', '.join(missing)}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    delivery_id = str(metadata.get("delivery_id") or "").strip()
    subject = str(metadata.get("subject") or "").strip()
    review_url = str(metadata.get("review_url") or "").strip()
    parsed_review_url = urlsplit(review_url)
    if not delivery_id or not subject:
        raise ValueError("Editorial email metadata requires delivery_id and subject")
    if parsed_review_url.scheme != "https" or not parsed_review_url.netloc:
        raise ValueError("Editorial email metadata requires an absolute HTTPS review_url")
    if metadata.get("concept_count", 0) <= 0:
        raise ValueError("Editorial email metadata requires at least one concept")
    verification = metadata.get("claim_verification")
    if not isinstance(verification, dict) or int(verification.get("claim_count") or 0) <= 0:
        raise ValueError("Editorial email metadata requires a claim-verification summary")
    verification_total = sum(
        int(verification.get(key) or 0)
        for key in ("verified_count", "needs_review_count", "editorial_count")
    )
    if verification_total != int(verification["claim_count"]):
        raise ValueError("Editorial email claim-verification summary is inconsistent")
    html = html_path.read_text(encoding="utf-8")
    text = text_path.read_text(encoding="utf-8")
    url_validation = validate_editorial_email_urls(html, text, metadata)
    artifacts = {
        "html_artifact": html_path.name,
        "text_artifact": text_path.name,
        "metadata_artifact": metadata_path.name,
        **url_validation,
    }
    return (
        html,
        text,
        metadata,
        artifacts,
    )


def editorial_delivery_preflight(cfg, review_dir: Path) -> dict:
    _html, _text, metadata, artifacts = load_editorial_email(review_dir)
    return {
        "from": cfg.email.sender_email,
        "to": cfg.email.recipient_email,
        "reply_to": cfg.email.reply_to_email,
        "subject": metadata["subject"],
        "delivery_id": metadata["delivery_id"],
        "concept_count": metadata["concept_count"],
        "review_url": metadata["review_url"],
        "supporting_report_url": metadata.get("supporting_report_url"),
        "claim_verification": metadata["claim_verification"],
        "review_dir": str(review_dir),
        "smtp_username_env_set": bool(os.getenv(cfg.email.smtp_username_env)) if cfg.email.smtp_username_env else False,
        "smtp_password_env_set": bool(os.getenv(cfg.email.smtp_password_env)) if cfg.email.smtp_password_env else False,
        **artifacts,
    }


def deliver_editorial_review(
    repo,
    cfg,
    review_dir: Path,
    *,
    send: bool = False,
    provider: EmailProvider | None = None,
) -> dict:
    html, text, metadata, artifacts = load_editorial_email(review_dir)
    preflight = editorial_delivery_preflight(cfg, review_dir)
    live_config = (not cfg.dry_run) and cfg.email.enabled and (not cfg.email.preview_only)
    if live_config and not send:
        raise ValueError("Refusing live-send-capable config without --send")
    if send:
        if not live_config:
            raise ValueError("Refusing send unless dry_run=false, email.enabled=true, email.preview_only=false, and --send is present")
        cfg.email.assert_live_send_allowed()

    key = editorial_message_key(str(metadata["delivery_id"]), cfg.email.recipient_email)
    subject = str(metadata["subject"])
    outbox, created = repo.outbox_get_or_create(key, cfg.email.recipient_email, subject)
    outbox.subject = subject
    if not created and outbox.status == "sent":
        return {"preflight": preflight, "delivery": {"status": "duplicate_skipped", "message_key": key}}

    msg = build_email(cfg.email, subject, html, text)
    if cfg.dry_run or not cfg.email.enabled or cfg.email.preview_only:
        outbox.status = "preview"
        outbox.provider_response = f"preview_only_no_smtp; html={artifacts['html_artifact']}; text={artifacts['text_artifact']}"
        outbox.attempt_count += 1
        return {"preflight": preflight, "delivery": {"status": "preview", "message_key": key, **artifacts}}

    cfg.email.assert_live_send_allowed()
    if provider is None:
        provider = SMTPEmailProvider.from_config(cfg.email)
    outbox.attempt_count += 1
    try:
        response = provider.send(msg)
    except Exception as exc:
        outbox.status = "failed"
        outbox.sent_at = None
        outbox.provider_response = _safe_provider_error(exc)
        return {
            "preflight": preflight,
            "delivery": {
                "status": "failed",
                "message_key": key,
                "provider_response": outbox.provider_response,
                **artifacts,
            },
        }
    outbox.status = "sent"
    outbox.sent_at = utcnow()
    outbox.provider_response = str(response)[:500]
    return {"preflight": preflight, "delivery": {"status": "sent", "message_key": key, **artifacts}}
