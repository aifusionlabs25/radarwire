from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from radar.cli import app
from radar.config import load_config
from radar.models import Article, Run, make_session_factory
from radar.pipeline import run_pipeline


runner = CliRunner()


def cfg_file(tmp_path):
    data = yaml.safe_load(Path("config.v0.2.example.yaml").read_text())
    data["data_dir"] = str(tmp_path / "pilot-data")
    data["database_url"] = "sqlite:///" + str(tmp_path / "pilot-data" / "radar.db").replace("\\", "/")
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_cli_fixture_uses_isolated_storage_and_does_not_pollute_pilot_db(tmp_path):
    config_path = cfg_file(tmp_path)
    pilot_cfg = load_config(config_path)
    Session, _ = make_session_factory(pilot_cfg.database_url)
    with Session.begin() as s:
        s.add(Article(workspace_id=pilot_cfg.workspace_id, source_id="seed", canonical_url="https://example.com/pilot", title="pilot", content_hash="h", sanitized_text="pilot", status="analyzed"))

    result = runner.invoke(app, ["scan", "--config", str(config_path), "--fixture"])

    assert result.exit_code == 0, result.output
    with Session() as s:
        articles = s.query(Article).all()
        runs = s.query(Run).all()
    assert [a.canonical_url for a in articles] == ["https://example.com/pilot"]
    assert runs == []
    assert (tmp_path / "pilot-data" / "fixture" / "radar.fixture.db").exists()


def test_cli_fixture_data_dir_option_controls_isolated_storage(tmp_path):
    config_path = cfg_file(tmp_path)
    fixture_dir = tmp_path / "custom-fixture-state"
    result = runner.invoke(app, ["scan", "--config", str(config_path), "--fixture", "--fixture-data-dir", str(fixture_dir)])
    assert result.exit_code == 0, result.output
    assert (fixture_dir / "radar.fixture.db").exists()


def test_cli_scan_exits_nonzero_when_pipeline_summary_failed(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    import radar.cli as cli

    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"status": "failed", "last_error": "boom"})
    result = runner.invoke(app, ["scan", "--config", str(config_path), "--fixture"])

    assert result.exit_code == 1
    assert '"status": "failed"' in result.output


def test_run_pipeline_does_not_leak_file_handlers(tmp_path):
    config_path = cfg_file(tmp_path)
    cfg = load_config(config_path)
    import logging

    logger = logging.getLogger("radar")
    before = len(logger.handlers)
    first = run_pipeline(cfg, fixture=True)
    second = run_pipeline(cfg, fixture=True)
    after = len(logger.handlers)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert after == before


def test_robots_cache_avoids_repeated_reads(monkeypatch):
    from types import SimpleNamespace
    import radar.discovery as discovery

    calls = []

    class FakeResponse:
        text = "User-agent: *\nAllow: /\n"
        def raise_for_status(self):
            return None

    def fake_get(url, timeout=None, follow_redirects=None, headers=None):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(discovery.httpx, "get", fake_get)
    source = SimpleNamespace(allowed_domains=["example.com"], allowed_paths=["/"])
    crawl = SimpleNamespace(respect_robots=True, user_agent="Radar", timeout_seconds=20)
    cache = {}

    assert discovery.robots_allowed("https://example.com/a", source, crawl, cache=cache)
    assert discovery.robots_allowed("https://example.com/b", source, crawl, cache=cache)
    assert calls == ["https://example.com/robots.txt"]
