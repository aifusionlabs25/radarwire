import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from radar.cli import app
from radar.editorial_review import EditorialReviewError, build_editorial_review_kit, validate_editorial_review_kit
from radar.emailer import deliver_editorial_review, editorial_delivery_preflight


def package(tmp_path):
    content = tmp_path / "content"
    assets = tmp_path / "assets"
    content.mkdir()
    assets.mkdir()
    articles = []
    for rank in range(1, 4):
        (content / f"article-{rank}.md").write_text(
            "Opening paragraph.\n\n"
            "## Useful section\n\nHelpful copy.\n\n"
            "## Practical steps\n\nHelpful copy.\n\n"
            "## Common questions\n\nHelpful copy.\n\n"
            "[[INLINE_VISUAL]]\n\n"
            "## Review points\n\nHelpful copy.\n\n"
            "## Next action\n\nHelpful copy.\n",
            encoding="utf-8",
        )
        (assets / f"hero-{rank}.png").write_bytes(b"png")
        (assets / f"inline-{rank}.png").write_bytes(b"png")
        verification_file = f"verification-{rank}.json"
        (content / verification_file).write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "article_id": f"article-{rank}",
                    "claims": [
                        {
                            "claim_id": "claim-001",
                            "claim": "Confirm current filing guidance before publication.",
                            "status": "needs_review",
                            "source_urls": [],
                            "review_note": "Requires human review.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        articles.append(
            {
                "rank": rank,
                "label": f"Direction {rank}",
                "title": f"Article {rank}",
                "dek": "A useful article direction.",
                "slug": f"article-{rank}",
                "body": f"article-{rank}.md",
                "hero": f"assets/hero-{rank}.png",
                "hero_alt": "Hero alt text",
                "inline_image": f"assets/inline-{rank}.png",
                "inline_alt": "Inline alt text",
                "inline_caption": "Useful caption.",
                "audience": "Finance teams",
                "primary_keyword": "1099 workflow",
                "read_time": "5 minute read",
                "meta_title": f"Article {rank}",
                "meta_description": "Useful description.",
                "cta_title": "Talk with 1099FIRE",
                "cta_body": "Review the filing path.",
                "cta_url": "https://www.1099fire.com/contact.htm",
                "sources": [["State filing guidance", "https://example.gov/information-returns.html"]],
                "verification_file": verification_file,
            }
        )
    manifest = content / "articles.json"
    manifest.write_text(
        json.dumps(
            {
                "client_name": "1099FIRE",
                "package_title": "Editorial Concepts",
                "package_dek": "Three directions.",
                "current_as_of": "August 13, 2026",
                "articles": articles,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_build_editorial_review_kit_writes_static_pages_without_side_effects(tmp_path):
    manifest = package(tmp_path)

    result = build_editorial_review_kit(manifest, tmp_path)

    assert result["article_count"] == 3
    assert result["sends_email"] is False
    assert result["publishes"] is False
    assert result["deploys"] is False
    assert result["runs_discovery"] is False
    assert result["uses_sqlite"] is False
    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "article-1.html").is_file()
    page = (tmp_path / "article-1.html").read_text(encoding="utf-8")
    assert "Reviewer sources" in page
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in page
    assert "source-backed item(s) for final review" in page
    assert "assets/inline-1.png" in page
    assert "[VERIFY]" not in page

    validation = validate_editorial_review_kit(manifest, tmp_path)
    assert validation["status"] == "ok"
    assert validation["article_count"] == 3
    assert validation["images_checked"] == 6
    assert validation["claim_verification"]["needs_review_count"] == 3
    assert all(value is False for value in validation["side_effect_flags"].values())


def test_build_editorial_review_kit_refuses_overwrite(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "index.html").write_text("keep", encoding="utf-8")

    with pytest.raises(EditorialReviewError, match="Refusing to overwrite"):
        build_editorial_review_kit(manifest, tmp_path)

    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "keep"


def test_build_editorial_review_kit_requires_claim_verification_ledger(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["articles"][0].pop("verification_file")
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(EditorialReviewError, match="missing verification_file"):
        build_editorial_review_kit(manifest, tmp_path)


def test_build_editorial_review_kit_supports_short_and_full_reading_modes(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    full_body = tmp_path / "content" / "article-1-full.md"
    full_body.write_text((tmp_path / "content" / "article-1.md").read_text(encoding="utf-8"), encoding="utf-8")
    data["articles"][0]["full_body"] = full_body.name
    data["articles"][0]["full_read_time"] = "6 minute read"
    data["email_preview"] = True
    manifest.write_text(json.dumps(data), encoding="utf-8")

    build_editorial_review_kit(manifest, tmp_path)

    page = (tmp_path / "article-1.html").read_text(encoding="utf-8")
    assert 'data-reading-target="short"' in page
    assert 'data-reading-target="full"' in page
    assert 'data-reading-copy="short"' in page
    assert 'data-reading-copy="full" hidden' in page
    assert "Quick Read" in page
    assert "Full Guide" in page
    assert page.index('class="article-heading"') < page.index('class="article-hero"') < page.index('id="article-start"')
    assert "Real People. Reliable Filing." in page
    assert "URLSearchParams" in (tmp_path / "review.js").read_text(encoding="utf-8")
    email_preview = (tmp_path / "email-preview.html").read_text(encoding="utf-8")
    assert "?view=quick" in email_preview
    assert "?view=full" in email_preview
    assert "Start here" in email_preview
    assert "3-draft review hub" in email_preview
    assert "source-backed drafting" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "compliance-reviewed language" not in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script" not in email_preview
    assert (tmp_path / "email-preview.txt").is_file()
    assert (tmp_path / "email-preview.json").is_file()

    validation = validate_editorial_review_kit(manifest, tmp_path)
    assert validation["status"] == "ok"
    assert validation["dual_length_articles"] == 1
    assert validation["images_checked"] == 6
    assert validation["email_preview"] is True
    assert validation["email_links_checked"] == 7


def test_editorial_review_kit_can_enable_private_revision_workspace(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    full_body = tmp_path / "content" / "article-1-full.md"
    full_body.write_text((tmp_path / "content" / "article-1.md").read_text(encoding="utf-8"), encoding="utf-8")
    data.update(
        {
            "client_id": "amy-huffman",
            "edition_id": "edition-2026-08-14",
            "editorial_editing": True,
            "revision_api": "/api/editorial-revisions",
            "status_api": "/api/editorial-status",
            "session_api": "/api/editorial-session",
        }
    )
    data["articles"][0]["full_body"] = full_body.name
    manifest.write_text(json.dumps(data), encoding="utf-8")

    result = build_editorial_review_kit(manifest, tmp_path)
    page = (tmp_path / "article-1.html").read_text(encoding="utf-8")
    script = (tmp_path / "review.js").read_text(encoding="utf-8")

    assert result["editorial_editing"] is True
    assert 'data-editorial-workspace' in page
    assert 'data-editor-action="download-original"' in page
    assert "Download Word (.doc)" in page
    assert 'data-editor-action="download"' in page
    assert 'class="editor-disclosure"' in page
    assert 'data-editor-voice-consent' not in page
    assert 'data-editor-choice="select"' in page
    assert 'data-editor-choice="publish" hidden' in page
    assert "Choose this topic" in page
    assert "Mark as published" in page
    assert "Nothing will be published or emailed from this button." in script
    assert '"status_api": "/api/editorial-status"' in page
    assert "Review access code" not in page
    assert "Private review code" not in page
    assert "data-editor-token" not in page
    assert "data-status-token" not in page
    assert "private review link" not in script
    assert "fragment.get('review')" not in script
    assert "sessionStorage" not in script
    assert "window.radarEditorialSessionReady" in script
    assert "credentials: 'same-origin'" in script
    assert '"session_api": "/api/editorial-session"' in page
    assert '"client_id": "amy-huffman"' in page
    assert '"edition_id": "edition-2026-08-14"' in page
    assert "Save to RadarWire and downloaded" not in script
    assert "actions['download-original'].addEventListener" in script
    assert "Save & download Word" in script
    assert "voice_library_consent" in script
    assert "voice_library_consent: true" in script
    assert "localStorage" in script
    assert "application/msword" in script
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'id="review-access-context"' in index
    assert '"edition_id": "edition-2026-08-14"' in index
    assert '"session_api": "/api/editorial-session"' in index
    assert '<script src="review.js"></script>' in index
    assert validate_editorial_review_kit(manifest, tmp_path)["status"] == "ok"


def test_editorial_email_uses_hosted_draft_links_and_is_idempotent(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(
        {
            "email_preview": True,
            "delivery_id": "run-123-editorial-v1",
            "review_base_url": "https://review.radarwire.app/editorial",
            "supporting_report_url": "https://review.radarwire.app/radar/",
            "email_subject": "1099FIRE: 3 blog drafts ready for review",
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    build_editorial_review_kit(manifest, tmp_path)

    class Outbox:
        status = "pending"
        subject = ""
        provider_response = None
        attempt_count = 0
        sent_at = None

    class Repo:
        def __init__(self):
            self.outbox = Outbox()
            self.created = True

        def outbox_get_or_create(self, *_args):
            created, self.created = self.created, False
            return self.outbox, created

    class Provider:
        def __init__(self):
            self.calls = 0
            self.message = None

        def send(self, message):
            self.calls += 1
            self.message = message
            return "sent"

    email = SimpleNamespace(
        sender_email="sender@radar.test",
        recipient_email="recipient@client.test",
        reply_to_email="reply@radar.test",
        attach_markdown=False,
        assert_live_send_allowed=lambda: None,
        smtp_username_env="RADAR_SMTP_USERNAME",
        smtp_password_env="RADAR_SMTP_PASSWORD",
    )
    cfg = SimpleNamespace(dry_run=False, email=email)
    cfg.email.enabled = True
    cfg.email.preview_only = False
    repo = Repo()
    provider = Provider()

    first = deliver_editorial_review(repo, cfg, tmp_path, send=True, provider=provider)
    second = deliver_editorial_review(repo, cfg, tmp_path, send=True, provider=provider)

    assert first["delivery"]["status"] == "sent"
    assert second["delivery"]["status"] == "duplicate_skipped"
    assert provider.calls == 1
    assert provider.message["Subject"] == "1099FIRE: 3 blog drafts ready for review"
    html_part = provider.message.get_body(preferencelist=("html",)).get_content()
    assert "https://review.radarwire.app/editorial/article-1.html?view=quick" in html_part
    assert "https://review.radarwire.app/radar/" in html_part


def test_editorial_email_preflight_requires_matching_hosted_review(tmp_path, monkeypatch):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(
        {
            "email_preview": True,
            "delivery_id": "run-123-editorial-v1",
            "review_base_url": "https://review.radarwire.app/editorial",
            "supporting_report_url": "https://review.radarwire.app/radar/",
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    build_editorial_review_kit(manifest, tmp_path)

    config_data = yaml.safe_load(Path("config.v0.2.example.yaml").read_text(encoding="utf-8"))
    config_data.update(
        {
            "dry_run": False,
            "data_dir": str(tmp_path / "data"),
            "database_url": "sqlite:///" + str(tmp_path / "data" / "radar.db").replace("\\", "/"),
        }
    )
    config_data["email"].update(
        {
            "enabled": True,
            "preview_only": False,
            "smtp_host": "smtp.example.net",
            "smtp_port": 587,
            "use_tls": True,
            "sender_email": "sender@radar.test",
            "recipient_email": "recipient@client.test",
            "reply_to_email": "reply@radar.test",
        }
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    monkeypatch.setenv("RADAR_SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("RADAR_SMTP_PASSWORD", "smtp-password")

    runner = CliRunner()
    accepted = runner.invoke(
        app,
        [
            "editorial-email-preflight",
            "--config",
            str(config_path),
            "--review-dir",
            str(tmp_path),
            "--expected-review-url",
            "https://review.radarwire.app/editorial/",
        ],
    )
    refused = runner.invoke(
        app,
        [
            "editorial-email-preflight",
            "--config",
            str(config_path),
            "--review-dir",
            str(tmp_path),
            "--expected-review-url",
            "https://review.radarwire.app/stale/",
        ],
    )
    no_send_flag = runner.invoke(
        app,
        ["deliver-editorial-review", "--config", str(config_path), "--review-dir", str(tmp_path)],
    )

    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["ok"] is True
    assert refused.exit_code == 2
    assert json.loads(refused.output)["review_url_matches_expected"] is False
    assert no_send_flag.exit_code == 2
    assert "without --send" in no_send_flag.output


@pytest.mark.parametrize(
    ("old", "replacement", "message"),
    [
        ("https://review.radarwire.app/editorial/article-1.html?view=quick", "article-1.html?view=quick", "absolute HTTPS"),
        ("https://review.radarwire.app/editorial/assets/hero-1.png", "http://localhost:8000/hero-1.png", "absolute HTTPS"),
        ("https://review.radarwire.app/editorial/index.html", "https://reports.example.com/editorial/", "placeholder host"),
    ],
)
def test_editorial_delivery_preflight_rejects_unsafe_outgoing_urls(tmp_path, old, replacement, message):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(
        {
            "email_preview": True,
            "delivery_id": "run-123-editorial-v1",
            "review_base_url": "https://review.radarwire.app/editorial",
            "supporting_report_url": "https://review.radarwire.app/radar/",
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    build_editorial_review_kit(manifest, tmp_path)
    email_path = tmp_path / "email-preview.html"
    email_path.write_text(email_path.read_text(encoding="utf-8").replace(old, replacement, 1), encoding="utf-8")

    email = SimpleNamespace(
        sender_email="sender@radar.test",
        recipient_email="recipient@client.test",
        reply_to_email="reply@radar.test",
        smtp_username_env="RADAR_SMTP_USERNAME",
        smtp_password_env="RADAR_SMTP_PASSWORD",
    )
    cfg = SimpleNamespace(email=email)

    with pytest.raises(ValueError, match=message):
        editorial_delivery_preflight(cfg, tmp_path)


def test_editorial_delivery_preflight_rejects_unsafe_text_link(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(
        {
            "email_preview": True,
            "delivery_id": "run-123-editorial-v1",
            "review_base_url": "https://review.radarwire.app/editorial",
            "supporting_report_url": "https://review.radarwire.app/radar/",
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    build_editorial_review_kit(manifest, tmp_path)
    text_path = tmp_path / "email-preview.txt"
    text_path.write_text(text_path.read_text(encoding="utf-8") + "\nhttp://localhost:8000/broken\n", encoding="utf-8")

    email = SimpleNamespace(
        sender_email="sender@radar.test",
        recipient_email="recipient@client.test",
        reply_to_email="reply@radar.test",
        smtp_username_env="RADAR_SMTP_USERNAME",
        smtp_password_env="RADAR_SMTP_PASSWORD",
    )

    with pytest.raises(ValueError, match="absolute HTTPS"):
        editorial_delivery_preflight(SimpleNamespace(email=email), tmp_path)


def test_editorial_delivery_preflight_requires_claim_verification_summary(tmp_path):
    manifest = package(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(
        {
            "email_preview": True,
            "delivery_id": "run-123-editorial-v1",
            "review_base_url": "https://review.radarwire.app/editorial",
        }
    )
    manifest.write_text(json.dumps(data), encoding="utf-8")
    build_editorial_review_kit(manifest, tmp_path)
    metadata_path = tmp_path / "email-preview.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("claim_verification")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="claim-verification summary"):
        editorial_delivery_preflight(SimpleNamespace(email=SimpleNamespace()), tmp_path)


def test_build_editorial_review_kit_rejects_unreviewed_marker(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "content" / "article-2.md").write_text("[VERIFY]\n\n[[INLINE_VISUAL]]", encoding="utf-8")

    with pytest.raises(EditorialReviewError, match="not ready"):
        build_editorial_review_kit(manifest, tmp_path)
