import json

import httpx
import pytest

from radar.publication_history import (
    PublicationHistoryError,
    load_publication_history,
    sync_publication_history,
)


def event(**overrides):
    value = {
        "client_id": "amy-huffman",
        "event_id": "event-1",
        "recorded_at": "2026-08-15T16:00:00.000Z",
        "edition_id": "edition-2026-08-14",
        "article_slug": "pre-filing-readiness",
        "article_title": "Pre-Filing Readiness",
        "status": "published",
        "published_url": "https://1099fire.com/blog/pre-filing-readiness",
    }
    value.update(overrides)
    return value


def test_syncs_only_published_events_without_storing_token(tmp_path, monkeypatch):
    lines = [event(status="selected", published_url=None), event()]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="\n".join(json.dumps(item) for item in lines) + "\n")
    )
    monkeypatch.setenv("RADAR_EDITORIAL_SAVE_TOKEN", "private-value")

    result = sync_publication_history(
        "https://radarwire.example/api/editorial-status",
        "amy-huffman",
        tmp_path,
        transport=transport,
    )

    assert result["published_count"] == 1
    assert result["contains_secrets"] is False
    assert "private-value" not in (tmp_path / "published-content.jsonl").read_text(encoding="utf-8")
    loaded = load_publication_history(tmp_path / "published-content.jsonl")
    assert loaded[0]["article_title"] == "Pre-Filing Readiness"


def test_refuses_missing_token_and_non_https_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("RADAR_EDITORIAL_SAVE_TOKEN", raising=False)
    with pytest.raises(PublicationHistoryError, match="token"):
        sync_publication_history("https://radarwire.example/api/editorial-status", "amy-huffman", tmp_path)
    monkeypatch.setenv("RADAR_EDITORIAL_SAVE_TOKEN", "private-value")
    with pytest.raises(PublicationHistoryError, match="HTTPS"):
        sync_publication_history("http://radarwire.example/api/editorial-status", "amy-huffman", tmp_path)


def test_rejects_invalid_published_record(tmp_path):
    corpus = tmp_path / "published-content.jsonl"
    corpus.write_text(json.dumps(event(published_url="http://example.com/post")) + "\n", encoding="utf-8")
    with pytest.raises(PublicationHistoryError, match="HTTPS"):
        load_publication_history(corpus)
