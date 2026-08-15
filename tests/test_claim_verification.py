from datetime import datetime, timezone

import pytest

from radar.claim_verification import (
    ClaimVerification,
    ClaimVerificationLedger,
    build_needs_review_ledger,
    is_official_primary_source,
    validate_claim_verification,
)


IRS_URL = "https://www.irs.gov/forms-pubs/about-form-w-9"
CLIENT_URL = "https://www.1099fire.com/"


def test_generated_ledger_defaults_every_model_claim_to_needs_review():
    ledger = build_needs_review_ledger("article-1", ["Confirm the filing threshold.", "Confirm the deadline."])
    _, summary = validate_claim_verification(
        ledger.model_dump(mode="json"),
        article_id="article-1",
        allowed_source_urls=set(),
    )

    assert [item.status for item in ledger.claims] == ["needs_review", "needs_review"]
    assert summary == {
        "status": "needs_review",
        "claim_count": 2,
        "verified_count": 0,
        "needs_review_count": 2,
        "editorial_count": 0,
        "human_reviewed": False,
    }


def test_verified_claim_requires_named_timestamped_human_review():
    with pytest.raises(ValueError, match="reviewed_by and reviewed_at"):
        ClaimVerificationLedger(
            article_id="article-1",
            claims=[
                ClaimVerification(
                    claim_id="claim-001",
                    claim="The IRS publishes Form W-9 guidance.",
                    status="verified",
                    source_urls=[IRS_URL],
                    review_note="Matched to the official IRS page.",
                )
            ],
        )


def test_verified_claim_requires_allowed_official_primary_source():
    ledger = ClaimVerificationLedger(
        article_id="article-1",
        reviewed_by="Human reviewer",
        reviewed_at=datetime.now(timezone.utc),
        claims=[
            ClaimVerification(
                claim_id="claim-001",
                claim="The company offers filing support.",
                status="verified",
                source_urls=[CLIENT_URL],
                review_note="Checked the company website.",
            )
        ],
    )

    with pytest.raises(ValueError, match="official primary-source"):
        validate_claim_verification(
            ledger.model_dump(mode="json"),
            article_id="article-1",
            allowed_source_urls={CLIENT_URL},
        )


def test_human_reviewed_claim_with_allowed_government_source_is_verified():
    ledger = ClaimVerificationLedger(
        article_id="article-1",
        reviewed_by="Human reviewer",
        reviewed_at=datetime.now(timezone.utc),
        claims=[
            ClaimVerification(
                claim_id="claim-001",
                claim="The IRS publishes Form W-9 guidance.",
                status="verified",
                source_urls=[IRS_URL],
                review_note="Matched to the official IRS page.",
            ),
            ClaimVerification(
                claim_id="claim-002",
                claim="Use a calm explanatory opening.",
                status="editorial",
                review_note="Editorial direction, not a factual claim.",
            ),
        ],
    )

    _, summary = validate_claim_verification(
        ledger.model_dump(mode="json"),
        article_id="article-1",
        allowed_source_urls={IRS_URL},
    )

    assert summary["status"] == "verified"
    assert summary["verified_count"] == 1
    assert summary["editorial_count"] == 1
    assert summary["human_reviewed"] is True
    assert is_official_primary_source(IRS_URL) is True
    assert is_official_primary_source(CLIENT_URL) is False


def test_verification_rejects_source_not_attached_to_article():
    ledger = build_needs_review_ledger("article-1", ["Confirm the filing threshold."])
    ledger.claims[0].source_urls = [IRS_URL]

    with pytest.raises(ValueError, match="outside the article source list"):
        validate_claim_verification(
            ledger.model_dump(mode="json"),
            article_id="article-1",
            allowed_source_urls=set(),
        )
