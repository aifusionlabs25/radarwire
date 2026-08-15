from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx


class VoiceLibraryError(RuntimeError):
    pass


def _safe_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value):
        raise VoiceLibraryError(f"{label} must use lowercase letters, numbers, and hyphens")
    return value


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise VoiceLibraryError("Voice-library endpoint must be an absolute HTTPS URL")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise VoiceLibraryError("Voice-library endpoint cannot use localhost")
    return endpoint.rstrip("/")


def validate_voice_revision(raw: Any, *, client_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise VoiceLibraryError("Voice-library revision must be a JSON object")
    if raw.get("client_id") != client_id:
        raise VoiceLibraryError("Voice-library revision client_id mismatch")
    if raw.get("voice_library_eligible") is not True or raw.get("approval_status") != "approved_final":
        raise VoiceLibraryError("Voice-library revision is not explicitly approved")
    for field in ("revision_id", "saved_at", "edition_id", "article_slug", "article_title", "reading_mode", "edited_text"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise VoiceLibraryError(f"Voice-library revision is missing {field}")
    if len(raw["edited_text"]) > 160_000:
        raise VoiceLibraryError("Voice-library revision edited_text is too large")
    return raw


def sync_voice_library(
    endpoint: str,
    client_id: str,
    output_dir: Path,
    *,
    token_env: str = "RADAR_EDITORIAL_SAVE_TOKEN",
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    endpoint = _validate_endpoint(endpoint)
    client_id = _safe_id(client_id, "client_id")
    token = os.getenv(token_env, "")
    if not token:
        raise VoiceLibraryError(f"Required token environment variable is not set: {token_env}")
    query = urlencode({"client_id": client_id, "format": "jsonl"})
    with httpx.Client(timeout=30, transport=transport) as client:
        response = client.get(f"{endpoint}?{query}", headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        raise VoiceLibraryError(f"Voice-library export failed with HTTP {response.status_code}")

    records: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        if line.strip():
            records.append(validate_voice_revision(json.loads(line), client_id=client_id))
    records.sort(key=lambda item: (item["saved_at"], item["revision_id"]))

    output_dir = output_dir.resolve()
    revisions_dir = output_dir / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        revision_id = re.sub(r"[^a-zA-Z0-9-]", "", record["revision_id"])
        if not revision_id:
            raise VoiceLibraryError("Voice-library revision_id is invalid")
        target = revisions_dir / f"{revision_id}.json"
        if not target.exists():
            target.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    corpus_path = output_dir / "approved-voice-corpus.jsonl"
    corpus = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records)
    corpus_path.write_text(corpus, encoding="utf-8")
    manifest = {
        "status": "synced",
        "client_id": client_id,
        "revision_count": len(records),
        "corpus_sha256": hashlib.sha256(corpus.encode("utf-8")).hexdigest(),
        "corpus_file": corpus_path.name,
        "token_env": token_env,
        "contains_secrets": False,
    }
    (output_dir / "voice-library-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "output_dir": str(output_dir)}


def load_voice_examples(corpus_path: Path, *, max_examples: int = 4, max_total_chars: int = 12_000) -> list[dict[str, str]]:
    if not corpus_path.is_file():
        raise VoiceLibraryError(f"Missing approved voice corpus: {corpus_path}")
    records: list[dict[str, Any]] = []
    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            records.append(validate_voice_revision(raw, client_id=str(raw.get("client_id") or "")))
    examples: list[dict[str, str]] = []
    remaining = max_total_chars
    seen: set[str] = set()
    for record in reversed(records):
        fingerprint = str(record.get("edited_sha256") or hashlib.sha256(record["edited_text"].encode()).hexdigest())
        if fingerprint in seen or remaining <= 0:
            continue
        seen.add(fingerprint)
        text = record["edited_text"][:remaining]
        examples.append(
            {
                "article_title": record["article_title"],
                "reading_mode": record["reading_mode"],
                "approved_at": record["saved_at"],
                "approved_text": text,
            }
        )
        remaining -= len(text)
        if len(examples) >= max_examples:
            break
    return examples
