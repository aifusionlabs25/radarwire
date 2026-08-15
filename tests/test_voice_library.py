import json

import httpx
import pytest

from radar.voice_library import VoiceLibraryError, load_voice_examples, sync_voice_library


def approved_revision(**overrides):
    value = {
        "client_id": "amy-huffman",
        "revision_id": "revision-1",
        "saved_at": "2026-08-14T18:30:00Z",
        "edition_id": "edition-2026-08-14",
        "article_slug": "pre-filing-readiness",
        "article_title": "Pre-Filing Readiness",
        "reading_mode": "short",
        "edited_text": "Amy prefers a direct and practical opening.",
        "edited_sha256": "abc123",
        "approval_status": "approved_final",
        "voice_library_eligible": True,
    }
    value.update(overrides)
    return value


def test_sync_voice_library_writes_only_approved_portable_corpus(tmp_path, monkeypatch):
    rows = [approved_revision(), approved_revision(revision_id="revision-2", saved_at="2026-08-15T18:30:00Z")]

    def handler(request):
        assert request.headers["Authorization"] == "Bearer private-token"
        assert request.url.params["client_id"] == "amy-huffman"
        assert request.url.params["format"] == "jsonl"
        return httpx.Response(200, text="".join(json.dumps(row) + "\n" for row in rows))

    monkeypatch.setenv("RADAR_EDITORIAL_SAVE_TOKEN", "private-token")
    result = sync_voice_library(
        "https://radarwire.example/api/editorial-revisions",
        "amy-huffman",
        tmp_path,
        transport=httpx.MockTransport(handler),
    )

    assert result["revision_count"] == 2
    assert result["contains_secrets"] is False
    assert "private-token" not in (tmp_path / "voice-library-manifest.json").read_text(encoding="utf-8")
    assert len(list((tmp_path / "revisions").glob("*.json"))) == 2
    examples = load_voice_examples(tmp_path / "approved-voice-corpus.jsonl")
    assert examples[0]["approved_at"] == "2026-08-15T18:30:00Z"
    assert examples[0]["approved_text"].startswith("Amy prefers")


def test_sync_voice_library_refuses_missing_token_or_unapproved_record(tmp_path, monkeypatch):
    monkeypatch.delenv("RADAR_EDITORIAL_SAVE_TOKEN", raising=False)
    with pytest.raises(VoiceLibraryError, match="environment variable"):
        sync_voice_library("https://radarwire.example/api/editorial-revisions", "amy-huffman", tmp_path)

    corpus = tmp_path / "bad.jsonl"
    corpus.write_text(json.dumps(approved_revision(voice_library_eligible=False)) + "\n", encoding="utf-8")
    with pytest.raises(VoiceLibraryError, match="not explicitly approved"):
        load_voice_examples(corpus)
