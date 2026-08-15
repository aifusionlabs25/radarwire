from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx


class PublicationHistoryError(RuntimeError):
    pass


def _safe_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value):
        raise PublicationHistoryError(f"{label} must use lowercase letters, numbers, and hyphens")
    return value


def _https_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PublicationHistoryError(f"{label} must be an absolute HTTPS URL")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise PublicationHistoryError(f"{label} cannot use localhost")
    return value


def validate_publication_event(raw: Any, *, client_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PublicationHistoryError("Publication event must be a JSON object")
    if raw.get("client_id") != client_id:
        raise PublicationHistoryError("Publication event client_id mismatch")
    if raw.get("status") != "published":
        raise PublicationHistoryError("Publication history accepts published events only")
    for field in ("event_id", "recorded_at", "edition_id", "article_slug", "article_title"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise PublicationHistoryError(f"Publication event is missing {field}")
    _https_url(str(raw.get("published_url") or ""), "published_url")
    return raw


def sync_publication_history(
    endpoint: str,
    client_id: str,
    output_dir: Path,
    *,
    token_env: str = "RADAR_EDITORIAL_SAVE_TOKEN",
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    endpoint = _https_url(endpoint.rstrip("/"), "Publication-history endpoint")
    client_id = _safe_id(client_id, "client_id")
    token = os.getenv(token_env, "")
    if not token:
        raise PublicationHistoryError(f"Required token environment variable is not set: {token_env}")
    query = urlencode({"client_id": client_id, "format": "jsonl"})
    with httpx.Client(timeout=30, transport=transport) as client:
        response = client.get(f"{endpoint}?{query}", headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        raise PublicationHistoryError(f"Publication-history export failed with HTTP {response.status_code}")

    records = []
    for line in response.text.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if raw.get("status") == "published":
            records.append(validate_publication_event(raw, client_id=client_id))
    records.sort(key=lambda item: (item["recorded_at"], item["event_id"]))

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = output_dir / "published-content.jsonl"
    corpus = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records)
    corpus_path.write_text(corpus, encoding="utf-8")
    manifest = {
        "status": "synced",
        "client_id": client_id,
        "published_count": len(records),
        "corpus_sha256": hashlib.sha256(corpus.encode("utf-8")).hexdigest(),
        "corpus_file": corpus_path.name,
        "token_env": token_env,
        "contains_secrets": False,
    }
    (output_dir / "publication-history-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "output_dir": str(output_dir)}


def load_publication_history(corpus_path: Path, *, max_items: int = 100) -> list[dict[str, str]]:
    if not corpus_path.is_file():
        raise PublicationHistoryError(f"Missing publication-history corpus: {corpus_path}")
    records: list[dict[str, Any]] = []
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            records.append(validate_publication_event(raw, client_id=str(raw.get("client_id") or "")))
    latest_by_url = {record["published_url"]: record for record in records}
    return [
        {
            "article_title": record["article_title"],
            "article_slug": record["article_slug"],
            "published_url": record["published_url"],
            "published_at": record["recorded_at"],
        }
        for record in sorted(latest_by_url.values(), key=lambda item: item["recorded_at"], reverse=True)[:max_items]
    ]
