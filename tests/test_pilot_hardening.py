import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from radar.cli import app
from radar.config import load_config
from radar.models import Article, Lock, Outbox, Run, make_session_factory
from radar.pipeline import redact_database_url, run_pipeline
from radar.reporting import derive_themes, render_reports


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
                "inferred_implications": ["Implication phrase"],
                "offers_or_ctas": ["Try the offer"],
                "content_opportunities": ["Publish a clearer checklist"],
                "evidence_quotes": ["Evidence phrase"],
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


def test_reports_include_client_facing_digest_sections(tmp_path):
    report_dir = tmp_path / "report"

    digest = render_reports("run-1", report_dir, [fake_analysis()], {})
    md = (report_dir / "digest.md").read_text(encoding="utf-8")
    html = (report_dir / "digest.html").read_text(encoding="utf-8")
    email_html = (report_dir / "digest_email.html").read_text(encoding="utf-8")
    email_txt = (report_dir / "digest_email.txt").read_text(encoding="utf-8")

    assert digest["source_counts"] == {"example.com": 1}
    assert digest["opportunity_highlights"][0]["opportunity"] == "Publish a clearer checklist"
    assert "## Source Mix" in md
    assert "## Priority Content Opportunities" in md
    assert "Why it matters" in md
    assert "Priority Content Opportunities" in html
    assert "article-card" in html
    assert "theme-filter" in html
    assert "data-source-jump" in html
    assert "Source warnings/errors: none" in html
    assert "<li>None</li>" not in html
    assert "Competitor moves worth acting on" in email_html
    assert "Executive read" in email_html
    assert "Client lens:" in email_html
    assert "Open source article" in email_html
    assert 'href="https://example.com/a"' in email_html
    assert "theme-filter" not in email_html
    assert "article-card" not in email_html
    assert "Weekly competitor content brief" in email_txt
    assert "Executive read" in email_txt
    assert "Client lens:" in email_txt
    assert "Link: https://example.com/a" in email_txt


def test_email_digest_curates_top_three_priority_opportunities(tmp_path):
    report_dir = tmp_path / "report"
    analyses = []
    for idx in range(5):
        analyses.append(
            SimpleNamespace(
                content_hash=f"hash-{idx}",
                result_json={
                    "article": {
                        "title": f"Opportunity Article {idx}",
                        "url": f"https://example.com/{idx}",
                        "summary": f"Summary {idx}",
                        "observed_facts": [f"Fact {idx}"],
                        "inferred_implications": [f"Implication {idx}"],
                        "offers_or_ctas": [f"CTA {idx}"],
                        "content_opportunities": [f"Publish small-business checklist {idx}"],
                        "evidence_quotes": [f"Evidence {idx}"],
                    }
                },
            )
        )

    render_reports("run-1", report_dir, analyses, {})
    email_html = (report_dir / "digest_email.html").read_text(encoding="utf-8")
    email_txt = (report_dir / "digest_email.txt").read_text(encoding="utf-8")

    assert email_html.count("Open source article") == 3
    assert "Opportunity Article 0" in email_html
    assert "Opportunity Article 1" in email_html
    assert "Opportunity Article 2" in email_html
    assert "Opportunity Article 3" not in email_html
    assert email_txt.count("Client lens:") == 3


def test_reports_rank_client_relevance_ahead_of_feed_order(tmp_path):
    report_dir = tmp_path / "report"
    analyses = []
    for title, relevance in (("Low-fit article", 0.15), ("Direct 1099 fit", 0.96)):
        analyses.append(
            SimpleNamespace(
                content_hash=title,
                result_json={
                    "article": {
                        "title": title,
                        "url": f"https://example.com/{title.lower().replace(' ', '-')}",
                        "summary": f"Summary for {title}",
                        "observed_facts": ["Fact"],
                        "inferred_implications": ["Implication"],
                        "offers_or_ctas": ["CTA"],
                        "content_opportunities": [f"Opportunity from {title}"],
                        "evidence_quotes": ["Evidence"],
                    },
                    "client_relevance": relevance,
                    "relevance_reason": f"{round(relevance * 100)} percent fit",
                },
            )
        )

    digest = render_reports(
        "run-1",
        report_dir,
        analyses,
        {},
        {"name": "1099FIRE"},
    )
    email_html = (report_dir / "digest_email.html").read_text(encoding="utf-8")

    assert digest["articles"][0]["title"] == "Direct 1099 fit"
    assert digest["opportunity_highlights"][0]["client_relevance"] == 0.96
    assert email_html.index("Direct 1099 fit") < email_html.index("Low-fit article")
    assert "Client fit: 96%" in email_html
    assert "For 1099FIRE" in email_html
    interactive_html = (report_dir / "digest.html").read_text(encoding="utf-8")
    assert "1099FIRE Content Radar" in interactive_html
    assert "All sources clean" in interactive_html


def test_themes_ignore_low_relevance_topic_noise():
    items = [
        {
            "client_relevance": 0.95,
            "article": {
                "title": "1099 deadline and W-9 checklist",
                "summary": "Avoid a penalty with a practical 1099 workflow.",
                "observed_facts": [],
                "inferred_implications": [],
                "content_opportunities": [],
            },
        },
        {
            "client_relevance": 0.2,
            "article": {
                "title": "Sales tax permit and nexus guide",
                "summary": "Sales tax permit, nexus, sales tax, and resale certificate details.",
                "observed_facts": [],
                "inferred_implications": [],
                "content_opportunities": [],
            },
        },
    ]

    themes = derive_themes(items)

    assert "1099 and W-9 filing" in themes
    assert "Sales tax compliance" not in themes


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
