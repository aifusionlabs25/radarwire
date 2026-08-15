import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from radar.content_studio import (
    BlogBrief,
    BriefSet,
    ContentStudioError,
    DraftPackage,
    HermesContentRunner,
    VisualBrief,
    generate_content_studio,
    generate_content_studio_drafts,
    normalize_content_studio_data,
)


URLS = [
    "https://example.com/1099-errors",
    "https://example.com/1099-deadlines",
    "https://example.com/w9-checklist",
]


def cfg():
    return SimpleNamespace(
        client=SimpleNamespace(name="1099FIRE"),
        hermes=SimpleNamespace(
            enabled=True,
            command="hermes",
            profile_flag="-p",
            profile="amy-radar",
            skill_flag="-s",
            skill="competitor-content-radar",
            toolsets_flag="-t",
            toolsets="safe",
            one_shot_flag="-z",
            timeout_seconds=30,
        ),
    )


def digest():
    articles = []
    for index, url in enumerate(URLS):
        articles.append(
            {
                "title": f"Article {index}",
                "url": url,
                "summary": "Source-backed summary about information-return readiness.",
                "observed_facts": ["The source discusses filing preparation."],
                "content_opportunities": ["Create a practical filing checklist."],
                "evidence_quotes": ["Short evidence phrase."],
                "client_relevance": 0.95 - index * 0.05,
                "relevance_reason": "Direct information-return fit.",
            }
        )
    return {
        "run_id": "run-1",
        "client": {
            "name": "1099FIRE",
            "audience": "Businesses and tax professionals",
            "offerings": ["Information-return software", "Outsourced filing"],
            "content_priorities": ["1099 readiness", "W-9 collection"],
            "deprioritize_topics": ["Unrelated sales tax"],
        },
        "source_error_count": 0,
        "cross_source_themes": ["1099 and W-9 filing"],
        "opportunity_highlights": [
            {
                "source": "Example",
                "opportunity": "Create a pre-filing readiness checklist.",
                "title": "Article 0",
                "url": URLS[0],
                "client_relevance": 0.95,
            }
        ],
        "articles": articles,
    }


def brief(rank: int, *, source_urls=None):
    return BlogBrief(
        rank=rank,
        working_title=f"Original brief {rank}",
        strategic_angle="Help readers prepare before filing season.",
        target_reader="Busy information-return filer",
        search_intent="Practical preparation guidance",
        primary_keyword="1099 filing checklist",
        secondary_keywords=["W-9", "TIN matching"],
        reader_takeaway="A clear preparation sequence.",
        outline=["Assess data", "Validate records", "Choose a filing path"],
        why_now="Preparation reduces filing-season surprises.",
        client_offer_connection="Connects naturally to software or outsourced filing help.",
        source_urls=source_urls or URLS[:2],
        fact_check_notes=["Verify current filing dates using primary IRS material."],
        visual_concepts=["A clean filing-readiness flowchart."],
        confidence=0.9,
    )


def draft_package(source_urls=None):
    body = "## Start with clean data\n\n" + ("Filing preparation should begin with organized records and a deliberate review process. " * 90)
    return DraftPackage(
        brief_rank=1,
        title="A Practical 1099 Filing Readiness Checklist",
        dek="Prepare the data, people, and workflow before filing pressure arrives.",
        slug="1099-filing-readiness-checklist",
        meta_title="1099 Filing Readiness Checklist for Businesses",
        meta_description="A practical checklist for preparing information-return data, validation, recipient delivery, and filing support.",
        primary_keyword="1099 filing checklist",
        draft_markdown=body,
        suggested_cta="Choose 1099FIRE software or ask about outsourced filing help.",
        source_urls=source_urls or URLS[:2],
        factual_review_checklist=["Verify filing dates.", "Confirm form-specific requirements."],
        visual_briefs=[
            VisualBrief(
                placement="Hero",
                concept="A structured readiness path from source data to accepted filing.",
                alt_text="Information-return filing readiness workflow",
                generation_prompt="Editorial workflow graphic with no logos, brands, or personal data.",
            )
        ],
    )


class FakeRunner:
    def __init__(self, source_urls=None):
        self.calls = []
        self.source_urls = source_urls

    def call(self, instruction, payload, model):
        self.calls.append((instruction, payload, model))
        if model is BriefSet:
            return BriefSet(
                client_name="1099FIRE",
                run_id="run-1",
                briefs=[brief(1, source_urls=self.source_urls), brief(2), brief(3)],
            ), {"duration_ms": 10}
        return draft_package(source_urls=self.source_urls), {"duration_ms": 20}


class CompetitorCtaRunner(FakeRunner):
    def call(self, instruction, payload, model):
        if model is BriefSet:
            return super().call(instruction, payload, model)
        result = draft_package().model_copy(
            update={
                "draft_markdown": draft_package().draft_markdown + "\n\nUse eFileMyForms for help.",
                "suggested_cta": "Use Example for filing support.",
            }
        )
        return result, {"duration_ms": 20}


def test_generate_content_studio_writes_review_artifacts_without_side_effects(tmp_path):
    runner = FakeRunner()
    output = tmp_path / "content-studio"

    result = generate_content_studio(cfg(), "run-1", digest(), output, runner=runner)

    assert result["brief_count"] == 3
    assert result["hermes_calls"] == 2
    assert result["sends_email"] is False
    assert result["publishes"] is False
    assert result["runs_discovery"] is False
    assert result["uses_sqlite"] is False
    assert {path.name for path in output.iterdir()} == {
        "briefs.json",
        "briefs.md",
        "draft.json",
        "draft.md",
        "verification.json",
        "review.html",
        "manifest.json",
    }
    assert "INTERNAL DRAFT - FACT CHECK REQUIRED" in (output / "draft.md").read_text(encoding="utf-8")
    verification = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    assert {item["status"] for item in verification["claims"]} == {"needs_review"}
    assert result["claim_verification"]["verified_count"] == 0
    assert "1099FIRE Content Studio" in (output / "review.html").read_text(encoding="utf-8")
    assert "Do not browse" in runner.calls[0][0]
    assert "Do not browse" in runner.calls[1][0]


def test_content_studio_refuses_existing_output_without_overwrite(tmp_path):
    output = tmp_path / "content-studio"
    output.mkdir()
    (output / "keep.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(ContentStudioError, match="Refusing to overwrite"):
        generate_content_studio(cfg(), "run-1", digest(), output, runner=FakeRunner())

    assert (output / "keep.txt").read_text(encoding="utf-8") == "preserve"


def test_content_studio_expands_selected_existing_briefs_without_side_effects(tmp_path):
    runner = FakeRunner()
    output = tmp_path / "draft-set"
    brief_set = BriefSet(client_name="1099FIRE", run_id="run-1", briefs=[brief(1), brief(2), brief(3)])

    result = generate_content_studio_drafts(
        cfg(),
        "run-1",
        digest(),
        brief_set,
        output,
        ranks=[2, 3],
        runner=runner,
    )

    assert result["draft_ranks"] == [2, 3]
    assert result["draft_count"] == 2
    assert result["hermes_calls"] == 2
    assert result["sends_email"] is False
    assert result["publishes"] is False
    assert result["runs_discovery"] is False
    assert result["uses_sqlite"] is False
    assert {path.name for path in output.iterdir()} == {
        "draft-2.json",
        "draft-2.md",
        "verification-2.json",
        "draft-3.json",
        "draft-3.md",
        "verification-3.json",
        "manifest.json",
    }
    assert all(call[2] is DraftPackage for call in runner.calls)
    assert json.loads((output / "draft-2.json").read_text(encoding="utf-8"))["brief_rank"] == 2
    assert json.loads((output / "draft-3.json").read_text(encoding="utf-8"))["brief_rank"] == 3
    assert all(item["needs_review_count"] == 2 for item in result["claim_verification"])


def test_content_studio_passes_only_bounded_approved_voice_examples_to_hermes(tmp_path):
    runner = FakeRunner()
    output = tmp_path / "voice-draft"
    voice_examples = [
        {
            "article_title": "Approved example",
            "reading_mode": "short",
            "approved_at": "2026-08-14T18:30:00Z",
            "approved_text": "Amy's preferred clear, practical style.",
        }
    ]

    result = generate_content_studio_drafts(
        cfg(),
        "run-1",
        digest(),
        BriefSet(client_name="1099FIRE", run_id="run-1", briefs=[brief(1), brief(2), brief(3)]),
        output,
        ranks=[1],
        runner=runner,
        voice_examples=voice_examples,
    )

    assert result["voice_example_count"] == 1
    assert runner.calls[0][1]["approved_voice_examples"] == voice_examples
    assert "style references only" in runner.calls[0][0]


def test_content_studio_expand_rejects_briefs_from_another_run(tmp_path):
    brief_set = BriefSet(client_name="1099FIRE", run_id="other-run", briefs=[brief(1), brief(2), brief(3)])

    with pytest.raises(ContentStudioError, match="run_id"):
        generate_content_studio_drafts(
            cfg(),
            "run-1",
            digest(),
            brief_set,
            tmp_path / "draft-set",
            ranks=[2],
            runner=FakeRunner(),
        )


def test_content_studio_rejects_unknown_source_urls(tmp_path):
    with pytest.raises(ContentStudioError, match="outside the source digest"):
        generate_content_studio(
            cfg(),
            "run-1",
            digest(),
            tmp_path / "content-studio",
            runner=FakeRunner(source_urls=[URLS[0], "https://unapproved.example/article"]),
        )


def test_content_studio_requires_clean_digest(tmp_path):
    source_digest = digest()
    source_digest["source_error_count"] = 1

    with pytest.raises(ContentStudioError, match="source-clean"):
        generate_content_studio(
            cfg(),
            "run-1",
            source_digest,
            tmp_path / "content-studio",
            runner=FakeRunner(),
        )


def test_content_studio_rejects_competitor_brand_in_draft_prose(tmp_path):
    with pytest.raises(ContentStudioError, match="forbidden competitor brand"):
        generate_content_studio(
            cfg(),
            "run-1",
            digest(),
            tmp_path / "content-studio",
            runner=CompetitorCtaRunner(),
        )


def test_hermes_content_runner_uses_utf8_safe_env_without_smtp(monkeypatch):
    captured = {}
    expected = BriefSet(client_name="1099FIRE", run_id="run-1", briefs=[brief(1), brief(2), brief(3)])

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=expected.model_dump_json(), stderr="")

    monkeypatch.setattr("radar.content_studio.subprocess.run", fake_run)
    monkeypatch.setenv("RADAR_SMTP_PASSWORD", "must-not-leak")

    result, meta = HermesContentRunner(cfg()).call("Return JSON only.", {"run_id": "run-1"}, BriefSet)

    assert result.run_id == "run-1"
    assert meta["exit_code"] == 0
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert "RADAR_SMTP_PASSWORD" not in captured["env"]
    assert "ARTICLE_PAYLOAD_JSON" in captured["command"][-1]
    assert json.loads(captured["input"])["run_id"] == "run-1"


def test_content_studio_normalizes_bounded_model_lists():
    raw = BriefSet(
        client_name="1099FIRE",
        run_id="run-1",
        briefs=[brief(1), brief(2), brief(3)],
    ).model_dump()
    raw["briefs"][0]["secondary_keywords"] = [str(index) for index in range(8)]
    raw["briefs"][0]["outline"] = [str(index) for index in range(10)]

    normalized, notes = normalize_content_studio_data(raw, BriefSet)
    result = BriefSet.model_validate(normalized)

    assert len(result.briefs[0].secondary_keywords) == 6
    assert len(result.briefs[0].outline) == 8
    assert notes == [
        "trimmed briefs[0].secondary_keywords from 8 to 6",
        "trimmed briefs[0].outline from 10 to 8",
    ]


def test_draft_package_accepts_practical_1350_word_ceiling():
    package = draft_package()
    package = package.model_copy(update={"draft_markdown": "word " * 1320})

    validated = DraftPackage.model_validate(package.model_dump())

    assert len(validated.draft_markdown.split()) == 1320


def test_hermes_content_runner_repairs_overlong_draft_with_source_context(monkeypatch):
    calls = []
    invalid = draft_package().model_dump()
    invalid["draft_markdown"] = "word " * 1500
    valid = draft_package().model_dump()

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        payload = invalid if len(calls) == 1 else valid
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("radar.content_studio.subprocess.run", fake_run)
    payload = {
        "selected_brief": brief(1).model_dump(),
        "research_articles": [],
    }

    result, meta = HermesContentRunner(cfg()).call("Return draft JSON.", payload, DraftPackage)

    assert result.brief_rank == 1
    assert len(calls) == 2
    assert meta["call_count"] == 2
    assert meta["repair_used"] is True
    assert "950 to 1050 words" in calls[1][0][-1]
    repair_payload = json.loads(calls[1][1]["input"])
    assert repair_payload["repair_context"]["required_source_urls"] == URLS[:2]
