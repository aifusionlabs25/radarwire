from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


ClaimStatus = Literal["verified", "needs_review", "editorial"]


class ClaimVerification(BaseModel):
    claim_id: str = Field(min_length=1, max_length=80)
    claim: str = Field(min_length=3, max_length=600)
    status: ClaimStatus
    source_urls: list[str] = Field(default_factory=list, max_length=6)
    review_note: str = Field(default="", max_length=600)

    @field_validator("claim_id", "claim", "review_note")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


class ClaimVerificationLedger(BaseModel):
    schema_version: str = "1.0"
    article_id: str = Field(min_length=1, max_length=160)
    reviewed_by: str | None = Field(default=None, max_length=160)
    reviewed_at: datetime | None = None
    claims: list[ClaimVerification] = Field(min_length=1, max_length=30)

    @field_validator("article_id")
    @classmethod
    def _strip_article_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("reviewed_by")
    @classmethod
    def _strip_reviewer(cls, value: str | None) -> str | None:
        stripped = value.strip() if value else None
        return stripped or None

    @field_validator("reviewed_at")
    @classmethod
    def _timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _human_review_required_for_verified_claims(self):
        ids = [item.claim_id for item in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim_id values must be unique")
        if any(item.status == "verified" for item in self.claims):
            if not self.reviewed_by or not self.reviewed_at:
                raise ValueError("verified claims require reviewed_by and reviewed_at")
        return self


def is_official_primary_source(url: str) -> bool:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and bool(host) and (host.endswith(".gov") or host == "gov")


def build_needs_review_ledger(article_id: str, claims: list[str]) -> ClaimVerificationLedger:
    return ClaimVerificationLedger(
        article_id=article_id,
        claims=[
            ClaimVerification(
                claim_id=f"claim-{index:03d}",
                claim=claim,
                status="needs_review",
                review_note="Attach an official primary source and record human review before marking verified.",
            )
            for index, claim in enumerate(claims, start=1)
        ],
    )


def validate_claim_verification(
    data: dict,
    *,
    article_id: str,
    allowed_source_urls: set[str],
) -> tuple[ClaimVerificationLedger, dict]:
    ledger = ClaimVerificationLedger.model_validate(data)
    if ledger.article_id != article_id:
        raise ValueError("verification ledger article_id does not match the article")

    for item in ledger.claims:
        unknown = sorted(set(item.source_urls) - allowed_source_urls)
        if unknown:
            raise ValueError(f"claim {item.claim_id} cites source URL(s) outside the article source list: {unknown}")
        if item.status == "verified":
            if not item.source_urls:
                raise ValueError(f"verified claim {item.claim_id} requires at least one source URL")
            if not any(is_official_primary_source(url) for url in item.source_urls):
                raise ValueError(f"verified claim {item.claim_id} requires an official primary-source URL")
            if not item.review_note:
                raise ValueError(f"verified claim {item.claim_id} requires a review note")

    counts = {status: sum(item.status == status for item in ledger.claims) for status in ("verified", "needs_review", "editorial")}
    overall_status = "needs_review" if counts["needs_review"] else ("verified" if counts["verified"] else "editorial")
    summary = {
        "status": overall_status,
        "claim_count": len(ledger.claims),
        "verified_count": counts["verified"],
        "needs_review_count": counts["needs_review"],
        "editorial_count": counts["editorial"],
        "human_reviewed": bool(ledger.reviewed_by and ledger.reviewed_at),
    }
    return ledger, summary
