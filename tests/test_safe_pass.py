import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from radar.config import load_config
from radar.discovery import robots_allowed
from radar.emailer import SMTPEmailProvider, message_key
from radar.extract import extract_article
from radar.models import Article, make_session_factory
from radar.pipeline import run_pipeline, status
from radar.repository import RadarRepository
from radar.urlsec import validate_public_http_url


def cfg_file(tmp_path):
    data = yaml.safe_load(Path("config.v0.2.example.yaml").read_text())
    data["data_dir"] = str(tmp_path / "data")
    data["database_url"] = "sqlite:///" + str(tmp_path / "data" / "radar.db").replace("\\", "/")
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_fixture_scan_is_offline_without_monkeypatch(tmp_path, monkeypatch):
    import radar.pipeline as p

    def explode(*args, **kwargs):
        raise AssertionError("network discovery/fetch should not run in fixture mode")

    monkeypatch.setattr(p, "discover_urls", explode)
    monkeypatch.setattr(p, "fetch_html", explode)
    c = load_config(cfg_file(tmp_path))
    out = run_pipeline(c, fixture=True)
    assert out["fixture"] is True
    assert out["discovered"] == len(c.sources)
    assert out["hermes_calls"] == 0


def test_stable_message_key_ignores_run_id():
    digest = {
        "run_id": "run-a",
        "article_count": 1,
        "articles": [{"url": "https://example.com/a", "title": "A", "summary": "S", "content_hash": "h"}],
    }
    key1 = message_key(digest, "recipient@example.com")
    digest["run_id"] = "run-b"
    key2 = message_key(digest, "recipient@example.com")
    assert key1 == key2


def test_smtp_provider_loads_credentials_from_env_without_logging(monkeypatch):
    cfg = SimpleNamespace(
        smtp_host="localhost",
        smtp_port=1025,
        use_tls=False,
        smtp_username_env="RADAR_SMTP_USERNAME",
        smtp_password_env="RADAR_SMTP_PASSWORD",
    )
    monkeypatch.setenv("RADAR_SMTP_USERNAME", "recipient@example.com")
    monkeypatch.setenv("RADAR_SMTP_PASSWORD", "fake-test-password-placeholder")
    provider = SMTPEmailProvider.from_config(cfg)
    assert provider.username == "recipient@example.com"
    assert provider.password == "fake-test-password-placeholder"
    assert "fake-test-password-placeholder" not in repr(provider)


def test_material_update_threshold_suppresses_minor_changes(tmp_path):
    c = load_config(cfg_file(tmp_path))
    Session, _ = make_session_factory(c.database_url)
    with Session.begin() as s:
        repo = RadarRepository(s, c.workspace_id)
        first = extract_article("<article>" + ("alpha " * 100) + "</article>", "https://www.taxjar.com/blog/a")
        _, status1 = repo.upsert_article("taxjar-blog", first, min_update_delta=c.crawl.min_update_delta)
        repo.mark_analyzed(repo.pending_articles()[0])
        second = extract_article("<article>" + ("alpha " * 100) + "tiny</article>", "https://www.taxjar.com/blog/a")
        _, status2 = repo.upsert_article("taxjar-blog", second, min_update_delta=c.crawl.min_update_delta)
        assert status1 == "new"
        assert status2 == "minor_update"
        assert repo.pending_articles() == []


def test_failed_run_is_recorded_and_health_exposes_latest_error(tmp_path, monkeypatch):
    c = load_config(cfg_file(tmp_path))
    import radar.pipeline as p

    monkeypatch.setattr(p, "render_reports", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render boom")))
    out = run_pipeline(c, fixture=True)
    assert out["status"] == "failed"
    assert "render boom" in out["last_error"]
    health = status(c)
    assert health["latest_run"]["status"] == "failed"
    assert "render boom" in health["latest_run"]["last_error"]


def test_taxjar_resources_blog_scope_is_allowed_but_other_paths_are_not():
    domains = ["www.taxjar.com", "taxjar.com"]
    paths = ["/blog/", "/resources/blog"]
    assert validate_public_http_url("https://www.taxjar.com/resources/blog", domains, paths)
    with pytest.raises(ValueError):
        validate_public_http_url("https://www.taxjar.com/resources/ebooks", domains, paths)


def test_robots_allowed_respects_disabled_flag(monkeypatch):
    source = SimpleNamespace(allowed_domains=["example.com"], allowed_paths=["/"])
    crawl = SimpleNamespace(respect_robots=False, user_agent="Radar")
    assert robots_allowed("https://example.com/private", source, crawl) is True
