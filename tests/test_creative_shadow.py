import base64
import json
from pathlib import Path

import pytest

from radar.creative_shadow import (
    CandidateDirection,
    CandidateScore,
    ControlVerdict,
    CreativeBrandBoard,
    CreativePlan,
    CreativeShadowError,
    CreativeVerdict,
    FinalControlVerdict,
    GeneratedImage,
    HermesCreativeRunner,
    RefinementBrief,
    run_creative_shadow,
    run_creative_shadow_v2,
)
from radar.creative_shadow import _final_control_verdict_instruction


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeCreativeRunner:
    def __init__(self, selected="B", reject_selected=False):
        self.calls = 0
        self.selected = selected
        self.reject_selected = reject_selected

    def call(self, instruction, payload, model):
        self.calls += 1
        if model is CreativePlan:
            return CreativePlan(
                art_objective="Make filing readiness visible and credible.",
                candidates=[
                    CandidateDirection(candidate_id="A", name="Paper system", rationale="Tactile", generation_prompt="Paper editorial, no text", intended_strength="Human"),
                    CandidateDirection(candidate_id="B", name="Working desk", rationale="Documentary", generation_prompt="Documentary desk, no text", intended_strength="Credible"),
                    CandidateDirection(candidate_id="C", name="Signal grid", rationale="Structured", generation_prompt="Abstract information grid, no text", intended_strength="Clear"),
                ],
            ), {"duration_ms": 1}
        if model is GeneratedImage:
            return GeneratedImage(image_ref="data:image/png;base64," + base64.b64encode(PNG_1X1).decode()), {"duration_ms": 1}
        scores = []
        for candidate_id in "ABC":
            flags = ["garbled text"] if self.reject_selected and candidate_id == self.selected else []
            scores.append(
                CandidateScore(
                    candidate_id=candidate_id,
                    brand_fit=8,
                    editorial_credibility=8,
                    human_authenticity=8,
                    subject_relevance=8,
                    composition=8,
                    artifact_risk=6 if flags else 2,
                    rejection_flags=flags,
                    critique="Clear and credible.",
                )
            )
        return CreativeVerdict(scores=scores, selected_candidate_id=self.selected, selection_rationale="Best balance."), {"duration_ms": 1}


def score(candidate_id, *, brand=8, editorial=8, human=8, relevance=8, composition=8, risk=2, flags=None):
    return CandidateScore(
        candidate_id=candidate_id,
        brand_fit=brand,
        editorial_credibility=editorial,
        human_authenticity=human,
        subject_relevance=relevance,
        composition=composition,
        artifact_risk=risk,
        rejection_flags=flags or [],
        critique=f"Critique for {candidate_id}.",
    )


class FakeCreativeV2Runner:
    def __init__(self, *, refined_wins=True):
        self.calls = 0
        self.refined_wins = refined_wins

    def call(self, instruction, payload, model):
        self.calls += 1
        if model is ControlVerdict:
            return ControlVerdict(
                scores=[
                    score("CONTROL", brand=8, editorial=8, human=7, relevance=8, composition=9, risk=1),
                    score("A", brand=5, editorial=7, human=6, relevance=7, composition=8, risk=3),
                    score("B", brand=5, editorial=8, human=8, relevance=8, composition=8, risk=2),
                    score("C", brand=7, editorial=8, human=6, relevance=7, composition=9, risk=2),
                ],
                preferred_candidate_id="C",
                refinement_rationale="C has the strongest structure.",
            ), {"duration_ms": 1}
        if model is RefinementBrief:
            return RefinementBrief(
                source_candidate_id="C",
                refinement_name="Branded readiness grid",
                preserve=["modular workflow", "clear composition"],
                change=["add confident green", "increase filing relevance"],
                generation_prompt="Refine the modular grid with confident green and practical filing cues, no text, no logo.",
            ), {"duration_ms": 1}
        if model is GeneratedImage:
            return GeneratedImage(image_ref="data:image/png;base64," + base64.b64encode(PNG_1X1).decode()), {"duration_ms": 1}
        refined = (
            score("R", brand=9, editorial=9, human=8, relevance=9, composition=9, risk=1)
            if self.refined_wins
            else score("R", brand=7, editorial=9, human=8, relevance=9, composition=9, risk=1)
        )
        return FinalControlVerdict(
            scores=[score("CONTROL", brand=8, editorial=8, human=7, relevance=8, composition=9, risk=1), refined],
            jury_preference="R",
            selection_rationale="R is the jury preference.",
        ), {"duration_ms": 1}


def fixture_manifest(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "control.png").write_bytes(PNG_1X1)
    manifest = {
        "client_name": "1099FIRE",
        "articles": [
            {
                "slug": "pre-filing-readiness",
                "title": "Pre-Filing Readiness",
                "dek": "Prepare before filing pressure arrives.",
                "audience": "High-volume filing teams",
                "art_direction": "Tactile editorial collage",
                "hero": "assets/control.png",
                "hero_alt": "Current control",
            }
        ],
    }
    path = tmp_path / "articles.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def fixture_brand_board(tmp_path: Path) -> Path:
    board = CreativeBrandBoard(
        client_name="1099FIRE",
        palette={"primary_green": "#078F24", "navy": "#10233E", "white": "#FFFFFF", "restrained_coral": "#F05A47"},
        personality=["approachable", "capable", "credible"],
        must_show=["green brand signal", "filing relevance"],
        avoid=["fake forms", "garbled text"],
    )
    path = tmp_path / "brand.json"
    path.write_text(board.model_dump_json(), encoding="utf-8")
    return path


def fixture_v1_shadow(tmp_path: Path) -> Path:
    source = tmp_path / "v1"
    source.mkdir()
    candidate_files = {}
    for candidate_id in "ABC":
        name = f"candidate-{candidate_id.lower()}.png"
        (source / name).write_bytes(PNG_1X1)
        candidate_files[candidate_id] = name
    (source / "shadow-result.json").write_text(
        json.dumps({"article_slug": "pre-filing-readiness", "candidate_count": 3, "candidate_files": candidate_files}),
        encoding="utf-8",
    )
    return source


def test_creative_shadow_isolated_run_writes_comparison_without_side_effects(tmp_path):
    output = tmp_path / "shadow"
    result = run_creative_shadow(fixture_manifest(tmp_path), "pre-filing-readiness", output, runner=FakeCreativeRunner())

    assert result["selected_candidate_id"] == "B"
    assert result["hermes_calls"] == 5
    assert result["production_artwork_changed"] is False
    assert result["sends_email"] is False
    assert result["publishes"] is False
    assert result["deploys"] is False
    assert {path.name for path in output.iterdir()} == {
        "candidate-a.png", "candidate-b.png", "candidate-c.png", "control-current.png", "shadow-result.json", "index.html"
    }
    page = (output / "index.html").read_text(encoding="utf-8")
    assert "Hermes selection" in page
    assert "production control has not changed" in page


def test_creative_shadow_falls_back_when_selected_candidate_fails_gate(tmp_path):
    result = run_creative_shadow(
        fixture_manifest(tmp_path),
        "pre-filing-readiness",
        tmp_path / "shadow",
        runner=FakeCreativeRunner(selected="B", reject_selected=True),
    )
    assert result["selected_candidate_id"] is None
    assert "keeps the existing production artwork" in (tmp_path / "shadow" / "index.html").read_text(encoding="utf-8")


def test_creative_shadow_refuses_nonempty_output(tmp_path):
    output = tmp_path / "shadow"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(CreativeShadowError, match="Refusing to overwrite"):
        run_creative_shadow(fixture_manifest(tmp_path), "pre-filing-readiness", output, runner=FakeCreativeRunner())
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_creative_shadow_resolves_assets_beside_content_directory(tmp_path):
    manifest = fixture_manifest(tmp_path)
    content = tmp_path / "content"
    content.mkdir()
    nested_manifest = content / "articles.json"
    nested_manifest.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_creative_shadow(
        nested_manifest,
        "pre-filing-readiness",
        tmp_path / "shadow-nested",
        runner=FakeCreativeRunner(),
    )

    assert result["control_file"] == "control-current.png"


def test_creative_shadow_can_resume_from_reviewed_hermes_plan(tmp_path):
    runner = FakeCreativeRunner()
    approved_plan = runner.call("plan", {}, CreativePlan)[0]
    runner.calls = 0

    result = run_creative_shadow(
        fixture_manifest(tmp_path),
        "pre-filing-readiness",
        tmp_path / "shadow-resumed",
        runner=runner,
        approved_plan=approved_plan,
    )

    assert result["hermes_calls"] == 4
    assert result["call_meta"]["plan"]["source"] == "approved_hermes_plan"


def test_hermes_json_parser_accepts_fenced_json():
    parsed = HermesCreativeRunner._parse_model(
        'Note\n```json\n{"image_ref":"C:/tmp/image\u2014final.png"}\n```',
        GeneratedImage,
    )
    assert "\u2014" not in parsed.image_ref


def test_generated_image_accepts_native_hermes_tool_envelope():
    parsed = HermesCreativeRunner._parse_model(
        '{"success":true,"image":"C:/tmp/candidate.png","provider":"openai-codex"}',
        GeneratedImage,
    )
    assert parsed.image_ref == "C:/tmp/candidate.png"


def test_final_jury_reserves_rejection_flags_for_blocking_defects():
    instruction = _final_control_verdict_instruction()

    assert "Reserve rejection_flags only for blocking visible defects" in instruction
    assert "Do not put ordinary weaknesses" in instruction
    assert "thumbnail concerns" in instruction


def test_creative_shadow_v2_refines_once_and_beats_control(tmp_path):
    output = tmp_path / "v2"
    result = run_creative_shadow_v2(
        fixture_manifest(tmp_path),
        "pre-filing-readiness",
        fixture_v1_shadow(tmp_path),
        fixture_brand_board(tmp_path),
        output,
        runner=FakeCreativeV2Runner(refined_wins=True),
    )

    assert result["recommended_asset"] == "R"
    assert result["replacement_gate_passed"] is True
    assert result["refinement_source_id"] == "C"
    assert result["hermes_calls"] == 4
    assert result["production_artwork_changed"] is False
    assert result["sends_email"] is False
    assert result["publishes"] is False
    assert result["deploys"] is False
    assert result["runs_scheduler"] is False
    assert result["uses_sqlite"] is False
    assert {path.name for path in output.iterdir()} == {
        "candidate-a.png",
        "candidate-b.png",
        "candidate-c.png",
        "candidate-r-refined.png",
        "control-current.png",
        "shadow-v2-result.json",
        "index.html",
    }


def test_creative_shadow_v2_keeps_control_when_brand_gate_fails(tmp_path):
    output = tmp_path / "v2-fallback"
    result = run_creative_shadow_v2(
        fixture_manifest(tmp_path),
        "pre-filing-readiness",
        fixture_v1_shadow(tmp_path),
        fixture_brand_board(tmp_path),
        output,
        runner=FakeCreativeV2Runner(refined_wins=False),
    )

    assert result["recommended_asset"] == "CONTROL"
    assert result["replacement_gate_passed"] is False
    assert "brand fit is below 8" in result["replacement_gate_failures"]
    page = (output / "index.html").read_text(encoding="utf-8")
    assert "Control remains the recommendation" in page
