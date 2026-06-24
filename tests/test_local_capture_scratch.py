from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml


def test_prepare_local_capture_scratch_uses_fresh_unsent_workspace_even_when_source_sent(tmp_path):
    src_data = tmp_path / "source-data"
    report_dir = src_data / "reports" / "run-1"
    report_dir.mkdir(parents=True)
    (report_dir / "digest.json").write_text('{"schema_version":"x","article_count":1,"articles":[{"url":"https://example.test/a","title":"A","summary":"S","content_hash":"h"}]}', encoding="utf-8")
    (report_dir / "digest.html").write_text("<html>A</html>", encoding="utf-8")
    (report_dir / "digest.txt").write_text("A", encoding="utf-8")
    (report_dir / "digest.md").write_text("# A", encoding="utf-8")
    (report_dir / "run-summary.json").write_text('{"run_id":"run-1"}', encoding="utf-8")

    source_db = src_data / "radar.db"
    con = sqlite3.connect(source_db)
    con.execute("create table outbox (id integer primary key, workspace_id text, message_key text, status text, recipient text, subject text, provider_response text, attempt_count integer, created_at text, sent_at text)")
    con.execute("insert into outbox (workspace_id,message_key,status,recipient,subject,provider_response,attempt_count,created_at,sent_at) values (?,?,?,?,?,?,?,?,?)", ("source-workspace", "k", "sent", "recipient@example.com", "old", "sent", 1, "now", "now"))
    con.commit(); con.close()

    cfg_path = tmp_path / "source.yaml"
    cfg = {
        "workspace_id": "source-workspace",
        "data_dir": src_data.as_posix(),
        "database_url": "sqlite:///" + source_db.as_posix(),
        "dry_run": False,
        "log_level": "INFO",
        "hermes": {"profile": "p", "skill": "s", "command": "hermes", "one_shot_flag": "-z", "profile_flag": "-p", "skill_flag": "-s", "toolsets_flag": "-t", "toolsets": "safe", "timeout_seconds": 1, "enabled": True, "max_chars": 1000},
        "email": {"enabled": True, "preview_only": False, "smtp_host": "localhost", "smtp_port": 1025, "smtp_username_env": "RADAR_SMTP_USERNAME", "smtp_password_env": "RADAR_SMTP_PASSWORD", "use_tls": False, "sender_email": "reply@example.com", "recipient_email": "reply@example.com", "reply_to_email": "reply@example.com", "subject_prefix": "[Competitor Radar]", "attach_markdown": True},
        "crawl": {"user_agent": "test", "timeout_seconds": 1, "max_articles_per_source": 1, "min_update_delta": 0.08, "respect_robots": True},
        "sources": [{"id":"s","name":"S","url":"https://example.test/a","allowed_domains":["example.test"],"allowed_paths":["/"],"seed_article": True, "seed_only": False, "monitor_url": None, "disable_feed_discovery": False, "disable_sitemap_discovery": False, "disable_listing_discovery": False, "excluded_paths": [], "excluded_url_contains": [], "excluded_title_patterns": []}],
    }
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    scratch_root = tmp_path / "scratch"
    result = subprocess.run([
        sys.executable,
        "scripts/prepare_local_capture_scratch.py",
        "--source-config", str(cfg_path),
        "--run-id", "run-1",
        "--scratch-root", str(scratch_root),
        "--timestamp", "20260624T000000",
    ], text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    scratch_cfg_path = Path(payload["config_path"])
    scratch_cfg = yaml.safe_load(scratch_cfg_path.read_text(encoding="utf-8"))
    assert scratch_cfg["workspace_id"] != "source-workspace"
    assert Path(scratch_cfg["data_dir"]).name.endswith("20260624T000000")
    assert (Path(scratch_cfg["data_dir"]) / "reports" / "run-1" / "digest.json").exists()
    scratch_db = Path(scratch_cfg["database_url"].replace("sqlite:///", ""))
    assert not scratch_db.exists()


def test_prepare_local_capture_scratch_fails_before_helper_when_report_missing(tmp_path):
    cfg_path = tmp_path / "source.yaml"
    data_dir = tmp_path / "data"
    cfg_path.write_text(yaml.safe_dump({"workspace_id": "w", "data_dir": data_dir.as_posix(), "database_url": "sqlite:///" + (data_dir / "radar.db").as_posix(), "dry_run": False, "email": {"enabled": True, "preview_only": False}}), encoding="utf-8")
    result = subprocess.run([
        sys.executable,
        "scripts/prepare_local_capture_scratch.py",
        "--source-config", str(cfg_path),
        "--run-id", "missing",
        "--scratch-root", str(tmp_path / "scratch"),
        "--timestamp", "20260624T000001",
    ], text=True, capture_output=True)
    assert result.returncode != 0
    assert "missing report artifact directory" in result.stderr



def test_prepare_local_capture_scratch_requires_digest_md_when_markdown_attachment_enabled(tmp_path):
    src_data = tmp_path / "source-data-md"
    report_dir = src_data / "reports" / "run-md"
    report_dir.mkdir(parents=True)
    (report_dir / "digest.json").write_text('{"schema_version":"x","article_count":1,"articles":[]}', encoding="utf-8")
    (report_dir / "digest.html").write_text("<html>A</html>", encoding="utf-8")
    (report_dir / "digest.txt").write_text("A", encoding="utf-8")
    (report_dir / "run-summary.json").write_text('{"run_id":"run-md"}', encoding="utf-8")
    cfg_path = tmp_path / "source-md.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "workspace_id": "w-md",
        "data_dir": src_data.as_posix(),
        "database_url": "sqlite:///" + (src_data / "radar.db").as_posix(),
        "dry_run": False,
        "email": {"enabled": True, "preview_only": False, "attach_markdown": True},
    }), encoding="utf-8")

    result = subprocess.run([
        sys.executable,
        "scripts/prepare_local_capture_scratch.py",
        "--source-config", str(cfg_path),
        "--run-id", "run-md",
        "--scratch-root", str(tmp_path / "scratch"),
        "--timestamp", "20260624T000002",
    ], text=True, capture_output=True)

    assert result.returncode != 0
    assert "digest.md" in result.stderr
    assert not (tmp_path / "scratch").exists()
