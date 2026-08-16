import json
import zipfile
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from radar.cli import app
from radar.content_studio import normalize_content_studio_data
from radar.editorial_worker import (
    EditorialRevisionOutput,
    _extract_attachment_text,
    load_truth_profile,
    run_editorial_worker,
    validate_revision_result,
)


def test_cli_tracebacks_do_not_render_sensitive_locals():
    assert app.pretty_exceptions_show_locals is False


def job():
    return {
        "job_id": "job-1",
        "client_id": "amy-huffman",
        "edition_id": "edition-2026-08-14",
        "instruction": "Remove all direct state filing references.",
        "scope": "both",
        "versions": {
            "short": {"html": '<p>Old copy.</p><p><a href="https://www.irs.gov/">IRS</a></p>', "text": "Old copy. IRS"},
            "full": {"html": '<p>Old full copy.</p><img src="https://review.example/image.png" alt="Workflow">', "text": "Old full copy."},
        },
    }


def profile(tmp_path):
    value = {
        "profile_id": "1099fire-v1",
        "client_id": "amy-huffman",
        "prohibited_claim_patterns": ["direct state filing"],
        "forbidden_competitor_brands": ["TaxBandits"],
    }
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def output(**overrides):
    value = {
        "short_html": '<p>1099FIRE supports a practical Combined Federal/State Filing path.</p><p><a href="https://www.irs.gov/">IRS</a></p>',
        "full_html": '<p>1099FIRE helps teams prepare a practical Combined Federal/State Filing workflow.</p><img src="https://review.example/image.png" alt="Workflow">',
        "change_summary": ["Removed the unsupported service reference from both versions."],
        "removed_concepts": ["Direct state service claim"],
        "unresolved_review_items": [],
    }
    value.update(overrides)
    return EditorialRevisionOutput.model_validate(value)


def test_validates_both_versions_against_client_truth(tmp_path):
    truth = load_truth_profile(profile(tmp_path))
    result = validate_revision_result(job(), output(), truth)
    assert result["validation"]["quick_read_checked"] is True
    assert result["validation"]["full_guide_checked"] is True
    assert result["validation"]["remaining_prohibited_references"] == []
    assert "https://www.irs.gov/" in result["versions"]["short"]["html"]
    assert "https://review.example/image.png" in result["versions"]["full"]["html"]


def test_rejects_prohibited_claims_competitors_and_active_markup(tmp_path):
    truth = load_truth_profile(profile(tmp_path))
    for bad in (
        output(short_html="<p>1099FIRE offers direct state filing.</p>"),
        output(full_html="<p>1099FIRE works like TaxBandits.</p>"),
        output(short_html="<script>alert(1)</script><p>1099FIRE can help.</p>"),
    ):
        try:
            validate_revision_result(job(), bad, truth)
        except Exception:
            pass
        else:
            raise AssertionError("unsafe revision was accepted")


def test_rejects_truncated_or_reported_incomplete_versions(tmp_path):
    truth = load_truth_profile(profile(tmp_path))
    long_job = job()
    long_full = "".join(
        f"<h2>Section {index}</h2><p>1099FIRE filing workflow detail {index}. " + ("Useful reviewed guidance. " * 20) + "</p>"
        for index in range(1, 6)
    )
    long_job["versions"]["full"] = {
        "html": long_full,
        "text": BeautifulSoup(long_full, "html.parser").get_text(" ", strip=True),
    }

    with pytest.raises(Exception, match="incomplete full version"):
        validate_revision_result(long_job, output(full_html="<p>1099FIRE short fragment.</p>"), truth)

    with pytest.raises(Exception, match="source payload was incomplete"):
        validate_revision_result(
            job(),
            output(unresolved_review_items=["The supplied Full Guide payload appears truncated."]),
            truth,
        )


def test_worker_claims_processes_and_completes_one_job(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_EDITORIAL_SAVE_TOKEN", "worker-secret")
    seen = []

    def handler(request):
        assert request.headers["Authorization"] == "Bearer worker-secret"
        if request.method == "GET":
            return httpx.Response(200, json={"ok": True, "jobs": [job()]})
        payload = json.loads(request.content)
        if payload.get("action") == "heartbeat":
            return httpx.Response(200, json={"ok": True})
        seen.append(payload["state"])
        return httpx.Response(200, json={"ok": True})

    class Runner:
        def revise(self, _job, _truth):
            return output(), {"call_count": 1, "duration_ms": 12, "repair_used": False}

    cfg = type("Config", (), {})()
    result = run_editorial_worker(
        cfg,
        "https://radarwire.example/api/editorial-jobs",
        profile(tmp_path),
        transport=httpx.MockTransport(handler),
        runner=Runner(),
    )
    assert result["status"] == "completed"
    assert seen == ["processing", "completed"]


def test_windows_worker_scripts_are_outbound_only_and_prepare_without_registering():
    root = Path(__file__).resolve().parents[1]
    runner = (root / "scripts" / "windows" / "run-editorial-worker.ps1").read_text(encoding="utf-8")
    installer = (root / "scripts" / "windows" / "install-editorial-worker-task.ps1").read_text(encoding="utf-8")
    assert "RADAR_EDITORIAL_SAVE_TOKEN" in runner
    assert "ZeroFreeBSTR" in runner
    assert "--watch" in runner
    assert "editorial-jobs" in runner
    assert "AtLogOn" in installer
    assert "prepared_only" in installer
    assert "registered = $false" in installer


def test_normalizes_common_hermes_revision_list_variation():
    data, notes = normalize_content_studio_data(
        {
            "short_html": "<p>Short.</p>",
            "full_html": "<p>Full.</p>",
            "change_summary": "Updated both versions.",
            "removed_concepts": [],
            "unresolved_review_items": [],
        },
        EditorialRevisionOutput,
    )
    assert data["change_summary"] == ["Updated both versions."]
    assert notes == ["normalized editorial_revision.change_summary from string to list"]


def test_extracts_private_text_and_word_attachment_context(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("Remove this unsupported service reference.", encoding="utf-8")
    assert "unsupported service" in _extract_attachment_text(note, "text/plain")

    document = tmp_path / "brief.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Use a warmer opening.</w:t></w:r></w:p></w:body></w:document>',
        )
    assert "warmer opening" in _extract_attachment_text(
        document, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
