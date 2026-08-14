import json

import pytest

from radar.editorial_review import EditorialReviewError, build_editorial_review_kit, validate_editorial_review_kit


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
    assert "assets/inline-1.png" in page
    assert "[VERIFY]" not in page

    validation = validate_editorial_review_kit(manifest, tmp_path)
    assert validation["status"] == "ok"
    assert validation["article_count"] == 3
    assert validation["images_checked"] == 6
    assert all(value is False for value in validation["side_effect_flags"].values())


def test_build_editorial_review_kit_refuses_overwrite(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "index.html").write_text("keep", encoding="utf-8")

    with pytest.raises(EditorialReviewError, match="Refusing to overwrite"):
        build_editorial_review_kit(manifest, tmp_path)

    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "keep"


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
    assert "<script" not in email_preview

    validation = validate_editorial_review_kit(manifest, tmp_path)
    assert validation["status"] == "ok"
    assert validation["dual_length_articles"] == 1
    assert validation["images_checked"] == 6
    assert validation["email_preview"] is True
    assert validation["email_links_checked"] == 7


def test_build_editorial_review_kit_rejects_unreviewed_marker(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "content" / "article-2.md").write_text("[VERIFY]\n\n[[INLINE_VISUAL]]", encoding="utf-8")

    with pytest.raises(EditorialReviewError, match="not ready"):
        build_editorial_review_kit(manifest, tmp_path)
