import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from radar.cli import app
from radar.config import SourceConfig, load_config
from radar.discovery import discover_urls, is_excluded_url
from radar.models import Article, make_session_factory

runner = CliRunner()


def cfg_file(tmp_path):
    data = yaml.safe_load(Path("config.pilot.local.example.yaml").read_text())
    data["data_dir"] = str(tmp_path / "pilot")
    data["database_url"] = "sqlite:///" + str(tmp_path / "pilot" / "radar.db").replace("\\", "/")
    data["sources"] = [
        {
            "id": "example-blog",
            "name": "Example Blog",
            "url": "https://example.com/blog/",
            "allowed_domains": ["example.com"],
            "allowed_paths": ["/blog/"],
        }
    ]
    p = tmp_path / "config.pilot.local.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_source_check_prints_would_crawl_and_warnings_without_mutating_db(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    cfg = load_config(config_path)
    Session, _ = make_session_factory(cfg.database_url)
    with Session.begin() as s:
        s.add(Article(workspace_id=cfg.workspace_id, source_id="existing", canonical_url="https://example.com/blog/existing", title="Existing", content_hash="h", sanitized_text="existing", status="analyzed"))

    import radar.source_check as sc

    def fake_discover(source, crawl):
        return ["https://example.com/blog/a", "https://example.com/blog/b"], ["robots disallow https://example.com/blog/private", "URL outside configured scope: https://example.com/about"]

    monkeypatch.setattr(sc, "discover_urls", fake_discover)

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mutates_state"] is False
    assert payload["calls_hermes"] is False
    assert payload["sends_email"] is False
    assert payload["source_count"] == 1
    src = payload["sources"][0]
    assert src["source_id"] == "example-blog"
    assert src["discovered_url_count"] == 2
    assert "https://example.com/blog/a" in src["would_crawl_urls"]
    assert src["skipped_or_warning_count"] == 2
    assert src["skipped_count"] == 0
    assert src["warning_count"] == 2
    assert src["ok"] is False
    assert any("robots" in item["reason"] for item in src["skipped_or_warnings"])
    assert any("outside configured scope" in item["reason"] for item in src["skipped_or_warnings"])

    with Session() as s:
        assert s.query(Article).count() == 1


def test_source_check_does_not_create_configured_data_dir(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    configured_data_dir = tmp_path / "pilot"
    assert not configured_data_dir.exists()

    import radar.source_check as sc
    monkeypatch.setattr(sc, "discover_urls", lambda source, crawl: (["https://example.com/blog/a"], []))

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert not configured_data_dir.exists()


def test_source_check_classifies_likely_articles_and_non_articles(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    import radar.source_check as sc

    monkeypatch.setattr(
        sc,
        "discover_urls",
        lambda source, crawl: (
            [
                "https://example.com/blog/how-to-file-taxes/",
                "https://example.com/blog/category/sales-tax/",
                "https://example.com/blog/resources",
                "https://example.com/blog/2026/06/nexus-guide/",
            ],
            [],
        ),
    )

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    src = json.loads(result.output)["sources"][0]
    assert "https://example.com/blog/how-to-file-taxes/" in src["likely_article_urls"]
    assert "https://example.com/blog/2026/06/nexus-guide/" in src["likely_article_urls"]
    assert "https://example.com/blog/category/sales-tax/" in src["likely_non_article_urls"]
    assert "https://example.com/blog/resources" in src["likely_non_article_urls"]
    assert any("category path" in item["reason"] for item in src["non_article_reasons"])
    assert any("listing/resource path" in item["reason"] for item in src["non_article_reasons"])
    assert src["source_quality_notes"]["likely_article_count"] == 2
    assert src["source_quality_notes"]["likely_non_article_count"] == 2


def test_source_check_applies_generic_url_exclusions(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    data = yaml.safe_load(Path(config_path).read_text())
    data["sources"][0]["excluded_paths"] = ["/blog/category/"]
    data["sources"][0]["excluded_url_contains"] = ["/webinars"]
    Path(config_path).write_text(yaml.safe_dump(data), encoding="utf-8")

    import radar.source_check as sc
    monkeypatch.setattr(
        sc,
        "discover_urls",
        lambda source, crawl: (
            [
                "https://example.com/blog/tax-guide/",
                "https://example.com/blog/category/sales-tax/",
                "https://example.com/blog/webinars",
            ],
            [],
        ),
    )

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    src = json.loads(result.output)["sources"][0]
    assert src["would_crawl_urls"] == ["https://example.com/blog/tax-guide/"]
    assert src["skipped_count"] == 2
    assert src["warning_count"] == 0
    assert src["ok"] is True
    assert any("excluded_paths" in item["reason"] for item in src["skipped_or_warnings"])
    assert any("excluded_url_contains" in item["reason"] for item in src["skipped_or_warnings"])


def test_source_check_treats_discovery_exclusions_as_skips_not_failures(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    import radar.source_check as sc

    monkeypatch.setattr(
        sc,
        "discover_urls",
        lambda source, crawl, **kwargs: (
            ["https://example.com/blog/tax-guide/"],
            ["excluded https://example.com/blog/category/tax/: excluded_paths:/blog/category/"],
        ),
    )

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    src = payload["sources"][0]
    assert src["skipped_count"] == 1
    assert src["warning_count"] == 0
    assert src["ok"] is True
    assert payload["total_skipped_urls"] == 1
    assert payload["total_warnings"] == 0


def test_discovery_url_exclusion_helper_is_config_driven():
    source = SourceConfig(
        id="example",
        name="Example",
        url="https://example.com/blog/",
        allowed_domains=["example.com"],
        allowed_paths=["/blog/"],
        excluded_paths=["/blog/category/"],
        excluded_url_contains=["/webinars"],
    )

    assert is_excluded_url("https://example.com/blog/category/tax/", source) == "excluded_paths:/blog/category/"
    assert is_excluded_url("https://example.com/blog/webinars", source) == "excluded_url_contains:/webinars"
    assert is_excluded_url("https://example.com/blog/tax-guide/", source) is None


def test_excluded_path_without_trailing_slash_blocks_exact_child_and_slash_taxjar_root():
    source = SourceConfig(
        id="taxjar-blog",
        name="TaxJar Blog",
        url="https://www.taxjar.com/blog/2026-sales-tax-holidays",
        allowed_domains=["www.taxjar.com", "taxjar.com"],
        allowed_paths=["/blog/", "/resources/blog"],
        excluded_paths=["/resources/blog"],
    )

    assert is_excluded_url("https://www.taxjar.com/resources/blog", source) == "excluded_paths:/resources/blog"
    assert is_excluded_url("https://www.taxjar.com/resources/blog/", source) == "excluded_paths:/resources/blog"
    assert is_excluded_url("https://www.taxjar.com/resources/blog/anything", source) == "excluded_paths:/resources/blog"
    assert is_excluded_url("https://www.taxjar.com/resources/blogger", source) is None
    assert is_excluded_url("https://www.taxjar.com/blog/2026-sales-tax-holidays", source) is None


def test_source_discovery_controls_can_disable_feed_sitemap_and_listing(monkeypatch):
    source = SourceConfig(
        id="quickbooks-taxes",
        name="QuickBooks Taxes",
        url="https://quickbooks.intuit.com/r/taxes/how-to-fill-out-a-1099-form/",
        monitor_url="https://quickbooks.intuit.com/r/taxes/",
        allowed_domains=["quickbooks.intuit.com"],
        allowed_paths=["/r/taxes/"],
        seed_article=True,
        disable_feed_discovery=True,
        disable_sitemap_discovery=True,
        disable_listing_discovery=True,
    )
    cfg = load_config("config.pilot.local.example.yaml", ensure_dirs=False).crawl
    monkeypatch.setattr("radar.discovery.robots_allowed", lambda *args, **kwargs: True)

    def fail_client(*args, **kwargs):
        raise AssertionError("disabled feed/sitemap/listing discovery must not open an HTTP client")

    monkeypatch.setattr("radar.discovery.httpx.Client", fail_client)

    urls, errors = discover_urls(source, cfg)

    assert urls == ["https://quickbooks.intuit.com/r/taxes/how-to-fill-out-a-1099-form/"]
    assert errors == []


def test_explicit_feed_url_can_live_outside_article_path(monkeypatch):
    source = SourceConfig(
        id="example-blog",
        name="Example Blog",
        url="https://example.com/blog/",
        allowed_domains=["example.com"],
        allowed_paths=["/blog/"],
        feed_urls=["https://example.com/feed/"],
        disable_sitemap_discovery=True,
        disable_listing_discovery=True,
    )
    cfg = load_config("config.pilot.local.example.yaml", ensure_dirs=False).crawl
    monkeypatch.setattr("radar.discovery.robots_allowed", lambda *args, **kwargs: True)

    class Response:
        status_code = 200
        text = """<?xml version="1.0"?><rss version="2.0"><channel><item><link>https://example.com/blog/tax-guide/</link></item></channel></rss>"""

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url == "https://example.com/feed/"
            return Response()

    monkeypatch.setattr("radar.discovery.httpx.Client", Client)

    urls, errors = discover_urls(source, cfg)

    assert urls == ["https://example.com/blog/tax-guide/"]
    assert errors == []


def test_seed_only_source_discovers_only_seed_without_feed_or_listing(monkeypatch):
    source = SourceConfig(
        id="example",
        name="Example",
        url="https://example.com/blog/seed-article/",
        monitor_url="https://example.com/blog/seed-article/",
        allowed_domains=["example.com"],
        allowed_paths=["/blog/seed-article/"],
        seed_article=True,
        seed_only=True,
    )
    cfg = load_config("config.pilot.local.example.yaml", ensure_dirs=False).crawl
    monkeypatch.setattr("radar.discovery.robots_allowed", lambda *args, **kwargs: True)

    def fail_client(*args, **kwargs):
        raise AssertionError("seed_only must not open feed/listing HTTP client")

    monkeypatch.setattr("radar.discovery.httpx.Client", fail_client)

    urls, errors = discover_urls(source, cfg)

    assert urls == ["https://example.com/blog/seed-article/"]
    assert errors == []


def test_source_check_reports_config_scope_error_without_writing(tmp_path):
    config_path = cfg_file(tmp_path)
    data = yaml.safe_load(Path(config_path).read_text())
    data["sources"][0]["url"] = "https://evil.example.net/blog/"
    Path(config_path).write_text(yaml.safe_dump(data), encoding="utf-8")

    result = runner.invoke(app, ["source-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    src = payload["sources"][0]
    assert src["ok"] is False
    assert src["skipped_or_warning_count"] >= 1
    assert any("outside configured scope" in item["reason"] for item in src["skipped_or_warnings"])
