import base64
import json
from pathlib import Path

import pytest

from radar.creative_shadow import (
    CandidateDirection,
    CandidateScore,
    CreativePlan,
    CreativeShadowError,
    CreativeVerdict,
    GeneratedImage,
    HermesCreativeRunner,
    run_creative_shadow,
)


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
