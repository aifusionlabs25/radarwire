import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from radar.cli import app
from radar.config import load_config
from radar.models import Article, Lock, Outbox, Run, make_session_factory
from radar.pipeline import redact_database_url, run_pipeline
from radar.reporting import render_reports


runner = CliRunner()


def cfg_file(tmp_path):
    data = yaml.safe_load(Path("config.v0.2.example.yaml").read_text())
    data["data_dir"] = str(tmp_path / "data")
    data["database_url"] = "sqlite:///" + str(tmp_path / "data" / "radar.db").replace("\\", "/")
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def fake_analysis():
    return SimpleNamespace(
        content_hash="hash-1",
        result_json={
            "article": {
                "title": "Warning Article",
                "url": "https://example.com/a",
                "summary": "Summary",
                "observed_facts": ["Fact phrase"],
            }
        },
    )


def test_reports_surface_source_errors_in_all_digest_outputs(tmp_path):
    report_dir = tmp_path / "report"
    warnings = {"taxjar-blog": ["robots unavailable"], "bench-tax-tips": []}

    digest = render_reports("run-1", report_dir, [fake_analysis()], warnings)

    assert digest["has_warnings"] is True
    assert digest["source_error_count"] == 1
    assert digest["failed_sources"] == ["taxjar-blog"]
    assert digest["analyzed_article_count"] == 1
    assert "robots unavailable" in json.loads((report_dir / "digest.json").read_text())["source_errors"]["taxjar-blog"]
    assert "robots unavailable" in (report_dir / "digest.md").read_text(encoding="utf-8")
    assert "robots unavailable" in (report_dir / "digest.txt").read_text(encoding="utf-8")
    assert "robots unavailable" in (report_dir / "digest.html").read_text(encoding="utf-8")
    summary = json.loads((report_dir / "run-summary.json").read_text(encoding="utf-8"))
    assert summary["has_warnings"] is True
    assert summary["source_error_count"] == 1
    assert summary["failed_sources"] == ["taxjar-blog"]


def test_cli_fail_on_source_errors_exits_nonzero_for_warning_summary(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    import radar.cli as cli

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda *args, **kwargs: {
            "status": "ok",
            "has_warnings": True,
            "source_error_count": 1,
            "failed_sources": ["taxjar-blog"],
        },
    )

    default_result = runner.invoke(app, ["scan", "--config", str(config_path), "--fixture"])
    strict_result = runner.invoke(app, ["scan", "--config", str(config_path), "--fixture", "--fail-on-source-errors"])

    assert default_result.exit_code == 0
    assert strict_result.exit_code == 2
    assert '"source_error_count": 1' in strict_result.output


def test_state_audit_reports_counts_fixture_looking_articles_and_latest_warning(tmp_path):
    config_path = cfg_file(tmp_path)
    cfg = load_config(config_path)
    Session, _ = make_session_factory(cfg.database_url)
    with Session.begin() as s:
        s.add(Article(workspace_id=cfg.workspace_id, source_id="fixture", canonical_url="https://fixture.local/a", title="Fixture", content_hash="h1", sanitized_text="Offline deterministic fixture text", status="analyzed"))
        s.add(Article(workspace_id=cfg.workspace_id, source_id="real", canonical_url="https://example.com/a", title="Real", content_hash="h2", sanitized_text="real", status="analyzed"))
        s.add(Run(id="r1", workspace_id=cfg.workspace_id, status="ok", stage="finished", summary_json={"has_warnings": True, "source_error_count": 1, "failed_sources": ["taxjar-blog"], "log_path": "logs/r1.log"}))
        from datetime import datetime
        s.add(Outbox(workspace_id=cfg.workspace_id, message_key="k1", status="sent", recipient="recipient@example.com", subject="s", sent_at=datetime(2026, 1, 1)))
        s.add(Lock(name="radar-run", workspace_id=cfg.workspace_id, owner="x", expires_at=__import__("datetime").datetime(2099, 1, 1)))

    result = runner.invoke(app, ["state-audit", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["article_count"] == 2
    assert payload["run_count"] == 1
    assert payload["outbox_count"] == 1
    assert payload["sent_email_count"] == 1
    assert payload["active_locks"] == 1
    assert payload["fixture_looking_article_count"] == 1
    assert payload["latest_run"]["has_warnings"] is True
    assert payload["latest_run"]["source_error_count"] == 1


def test_state_audit_redacts_database_password(tmp_path):
    config_path = cfg_file(tmp_path)
    data = yaml.safe_load(Path(config_path).read_text())
    raw = "postgresql://radar_user:***@db.example.com:5432/radar"

    assert redact_database_url(raw) == "postgresql://radar_user:***@db.example.com:5432/radar"
    result = runner.invoke(app, ["state-audit", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "database_url" not in payload
    assert payload["database_url_redacted"].startswith("sqlite")
    assert "fake-test-database-password-placeholder" not in result.output


def test_no_hermes_non_fixture_uses_deterministic_analysis_and_reports(tmp_path, monkeypatch):
    config_path = cfg_file(tmp_path)
    cfg = load_config(config_path)
    import radar.pipeline as p

    monkeypatch.setattr(p, "discover_urls", lambda src, crawl: ([src.monitor_url or src.url], []))
    monkeypatch.setattr(p, "fetch_html", lambda url, src, crawl: (url, "<html><title>Dry</title><article>Dry no Hermes article</article></html>"))
    monkeypatch.setattr(p, "HermesCliAnalysisAdapter", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Hermes must not be called")))

    out = run_pipeline(cfg, fixture=False, use_hermes=False)

    assert out["status"] == "ok"
    assert out["hermes_calls"] == 0
    assert out["pending_analyzed"] > 0
    report_dir = Path(out["report_dir"])
    digest = json.loads((report_dir / "digest.json").read_text(encoding="utf-8"))
    assert digest["article_count"] == out["pending_analyzed"]
    assert digest["articles"]


def test_empty_digest_without_warnings_skips_delivery_preview_but_writes_reports(tmp_path):
    config_path = cfg_file(tmp_path)
    cfg = load_config(config_path)
    out = run_pipeline(cfg, fixture=True)
    out2 = run_pipeline(cfg, fixture=True)

    assert out["pending_analyzed"] > 0
    assert out2["pending_analyzed"] == 0
    assert out2["source_error_count"] == 0
    assert out2["delivery"]["status"] == "skipped_empty_digest"
    assert (Path(out2["report_dir"]) / "digest.json").exists()
