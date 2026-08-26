"""Tests for VLW reconciliation — VLM hypothesis vs CV evidence comparison.

Tests cover:
- Mapping table completeness
- Per-dimension reconciliation (confirmed / conflicting / vlm_only / cv_only)
- B&W clamshell false positive scenario
- Aggregate reconciliation (overall agreement classification)
- Confidence boost application
- Orchestrator integration (VLW result in ReferencePhotoAnalysis)
"""

import pytest

from engine.image_analysis_models import (
    LightingRead,
    SceneContext,
    VLMDescription,
    VLWDimensionResult,
    VLWReconciliation,
    VisualCueReport,
    TonalProcessingEstimation,
    BackgroundIllumination,
    ContrastRatio,
    ShadowEdgeHardness,
    SubjectBackgroundSeparation,
    SpecularHighlightBehavior,
)
from engine.vlw_reconciliation import (
    VLM_LIGHTING_STYLE_MAP,
    _classify_mood_family,
    _map_vlm_style,
    _reconcile_fill_presence,
    _reconcile_light_count,
    _reconcile_pattern,
    _reconcile_source_quality,
    apply_confirmed_boosts,
    reconcile_vlw,
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_vlm(lighting_style: str = "", mood: str = "", bg: str = "", **kw) -> VLMDescription:
    """Build a minimal VLMDescription for testing."""
    return VLMDescription(
        lighting_style=lighting_style,
        overall_mood=mood,
        background_context=bg,
        ok=True,
        **kw,
    )


def _make_lighting_read(**overrides) -> LightingRead:
    """Build a LightingRead with sensible defaults."""
    defaults = dict(
        source_quality="hard",
        source_direction="45 degrees left",
        shadow_pattern="rembrandt",
        fill_presence="subtle",
        rim_presence="none",
        light_count=1,
        lighting_family="short_light",
        confidence=0.65,
    )
    defaults.update(overrides)
    return LightingRead(**defaults)


def _make_scene_ctx(**overrides) -> SceneContext:
    """Build a SceneContext with sensible defaults."""
    ctx = SceneContext()
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def _make_cue_report(is_bw: bool = False, is_hcg: bool = False) -> VisualCueReport:
    """Build a minimal VisualCueReport."""
    return VisualCueReport(
        tonal_processing_estimation=TonalProcessingEstimation(
            is_bw=is_bw,
            is_high_contrast_grade=is_hcg,
            estimated_processing="bw" if is_bw else "color",
            confidence=0.9,
        ),
        shadow_edge_hardness=ShadowEdgeHardness(classification="hard", confidence=0.7),
        contrast_ratio=ContrastRatio(label="high", confidence=0.8),
        background_illumination=BackgroundIllumination(
            pattern="dark", brightness_relative="darker", confidence=0.7,
        ),
        cues_computed=4,
        ok=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. Mapping Table Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMappingTable:
    """Verify mapping table completeness and normalisation."""

    VLM_PROMPT_STYLES = [
        "rembrandt", "loop", "butterfly/paramount", "split", "broad", "short",
        "clamshell", "flat/beauty", "rim/edge", "natural/ambient",
        "mixed/practical", "dramatic/chiaroscuro", "high-key", "low-key",
    ]

    @pytest.mark.parametrize("style", VLM_PROMPT_STYLES)
    def test_all_prompt_styles_have_mapping(self, style):
        """Every style in the VLM prompt should resolve to a mapping."""
        result = _map_vlm_style(style)
        assert result, f"VLM style '{style}' has no mapping"
        assert "pattern" in result
        assert "light_count_range" in result
        assert "source_quality" in result
        assert "fill_presence" in result

    def test_unknown_style_returns_empty(self):
        result = _map_vlm_style("totally_made_up_style_xyz")
        assert result == {}

    def test_empty_style_returns_empty(self):
        assert _map_vlm_style("") == {}
        assert _map_vlm_style(None) == {}

    def test_case_insensitive(self):
        r1 = _map_vlm_style("Rembrandt")
        r2 = _map_vlm_style("REMBRANDT")
        r3 = _map_vlm_style("rembrandt")
        assert r1 == r2 == r3

    def test_whitespace_normalisation(self):
        result = _map_vlm_style("  clamshell  ")
        assert result.get("light_count_range") == (2, 2)

    def test_substring_match(self):
        """VLM might return 'hard dramatic' which contains 'dramatic'."""
        result = _map_vlm_style("hard dramatic")
        assert result  # Should match "dramatic" entry


# ═══════════════════════════════════════════════════════════════════════════
# 2. Per-Dimension Reconciliation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestReconcilePattern:
    def test_confirmed_exact_match(self):
        vlm = _map_vlm_style("rembrandt")
        result = _reconcile_pattern(vlm, "rembrandt")
        assert result.agreement == "confirmed"
        assert result.confidence_boost > 0

    def test_confirmed_variant_match(self):
        """Exact rembrandt match should be confirmed."""
        vlm = _map_vlm_style("rembrandt")
        result = _reconcile_pattern(vlm, "rembrandt")
        assert result.agreement == "confirmed"

    def test_conflicting(self):
        vlm = _map_vlm_style("dramatic/chiaroscuro")
        result = _reconcile_pattern(vlm, "clamshell")
        assert result.agreement == "conflicting"
        assert result.recommendation_source == "human_review_required"

    def test_cv_only(self):
        result = _reconcile_pattern({}, "butterfly")
        assert result.agreement == "cv_only"
        assert result.recommended_value == "butterfly"

    def test_vlm_only(self):
        vlm = _map_vlm_style("rembrandt")
        result = _reconcile_pattern(vlm, "unknown")
        assert result.agreement == "vlm_only"
        assert result.recommendation_source == "human_review_required"

    def test_both_inconclusive(self):
        result = _reconcile_pattern({}, "unknown")
        assert result.agreement == "both_inconclusive"


class TestReconcileLightCount:
    def test_confirmed_in_range(self):
        vlm = _map_vlm_style("rembrandt")  # 1-2
        result = _reconcile_light_count(vlm, 1)
        assert result.agreement == "confirmed"

    def test_confirmed_at_range_end(self):
        vlm = _map_vlm_style("rembrandt")  # 1-2
        result = _reconcile_light_count(vlm, 2)
        assert result.agreement == "confirmed"

    def test_conflicting_above_range(self):
        vlm = _map_vlm_style("dramatic/chiaroscuro")  # 1-1
        result = _reconcile_light_count(vlm, 2)
        assert result.agreement == "conflicting"

    def test_bw_false_positive_note(self):
        """B&W image + VLM=1 light + CV=2 lights should produce B&W note."""
        vlm = _map_vlm_style("dramatic/chiaroscuro")  # 1-1
        result = _reconcile_light_count(vlm, 2, is_bw=True)
        assert result.agreement == "conflicting"
        assert len(result.notes) > 0
        assert "B&W" in result.notes[0]

    def test_hcg_false_positive_note(self):
        """High contrast grade should also produce the B&W note."""
        vlm = _map_vlm_style("dramatic/chiaroscuro")
        result = _reconcile_light_count(vlm, 2, is_high_contrast_grade=True)
        assert result.agreement == "conflicting"
        assert any("catchlight" in n.lower() for n in result.notes)

    def test_no_bw_note_when_color(self):
        """Color images should NOT produce B&W notes."""
        vlm = _map_vlm_style("dramatic/chiaroscuro")
        result = _reconcile_light_count(vlm, 2, is_bw=False, is_high_contrast_grade=False)
        assert result.agreement == "conflicting"
        assert len(result.notes) == 0


class TestReconcileSourceQuality:
    def test_confirmed(self):
        vlm = _map_vlm_style("rembrandt")  # hard, mixed
        result = _reconcile_source_quality(vlm, "hard")
        assert result.agreement == "confirmed"

    def test_conflicting(self):
        vlm = _map_vlm_style("clamshell")  # soft only
        result = _reconcile_source_quality(vlm, "hard")
        assert result.agreement == "conflicting"

    def test_bw_auto_resolves_to_vlm_override(self):
        # B&W processing inflates apparent shadow hardness in CV.  When VLM
        # expects soft (clamshell) but CV reads hard and image is B&W,
        # the reconciler now auto-resolves to vlm_override rather than flagging
        # conflicting — VLM catchlight analysis is more reliable here.
        vlm = _map_vlm_style("clamshell")  # expects soft
        result = _reconcile_source_quality(vlm, "hard", is_bw=True)
        assert result.agreement == "vlm_override"
        assert result.recommended_value == "soft"
        assert len(result.notes) > 0


class TestReconcileFillPresence:
    def test_confirmed(self):
        vlm = _map_vlm_style("rembrandt")  # none, subtle, moderate
        result = _reconcile_fill_presence(vlm, "subtle")
        assert result.agreement == "confirmed"

    def test_passive_bounce_normalised(self):
        """passive bounce should be treated as equivalent to subtle."""
        vlm = _map_vlm_style("rembrandt")  # none, subtle, moderate
        result = _reconcile_fill_presence(vlm, "passive bounce")
        assert result.agreement == "confirmed"

    def test_conflicting(self):
        vlm = _map_vlm_style("dramatic/chiaroscuro")  # none, subtle
        result = _reconcile_fill_presence(vlm, "strong")
        assert result.agreement == "conflicting"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Mood Classification Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMoodClassification:
    def test_dramatic(self):
        assert _classify_mood_family("dark and moody") == "dramatic"

    def test_beauty(self):
        assert _classify_mood_family("glamorous and polished") == "beauty"

    def test_natural(self):
        assert _classify_mood_family("candid editorial") == "natural"

    def test_bright(self):
        assert _classify_mood_family("airy and bright") == "bright"

    def test_unknown(self):
        assert _classify_mood_family("") == "unknown"
        assert _classify_mood_family("something completely random") == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Aggregate Reconciliation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestReconcileVLW:
    def test_all_confirmed_strong_agreement(self):
        """VLM and CV agree on everything → strong_agreement."""
        vlm = _make_vlm(lighting_style="rembrandt", mood="dramatic", bg="dark studio")
        lr = _make_lighting_read(
            shadow_pattern="rembrandt", light_count=1,
            source_quality="hard", fill_presence="subtle",
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait")
        cue = _make_cue_report()
        classification = {"mood": "dramatic"}

        result = reconcile_vlw(vlm, lr, ctx, cue, classification)

        assert result.overall_agreement == "strong_agreement"
        assert result.conflict_count == 0
        assert result.confirmed_count >= 3
        assert not result.requires_human_review

    def test_significant_conflict(self):
        """VLM says dramatic/chiaroscuro but CV says clamshell → conflicts."""
        vlm = _make_vlm(lighting_style="dramatic/chiaroscuro", mood="dramatic", bg="dark studio")
        lr = _make_lighting_read(
            shadow_pattern="clamshell", light_count=2,
            source_quality="soft", fill_presence="moderate",
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait")
        cue = _make_cue_report(is_bw=True)
        classification = {"mood": "beauty"}

        result = reconcile_vlw(vlm, lr, ctx, cue, classification)

        assert result.conflict_count >= 3
        assert result.requires_human_review
        assert len(result.human_review_reasons) > 0
        assert len(result.proposed_adjustments) > 0

    def test_vlm_unavailable(self):
        """No VLM description → vlm_unavailable."""
        lr = _make_lighting_read()
        ctx = _make_scene_ctx()
        cue = _make_cue_report()

        result = reconcile_vlw(None, lr, ctx, cue)
        assert result.overall_agreement == "vlm_unavailable"

    def test_vlm_not_ok(self):
        """VLM with ok=False → vlm_unavailable."""
        vlm = VLMDescription(ok=False, notes=["VLM call failed"])
        lr = _make_lighting_read()
        ctx = _make_scene_ctx()
        cue = _make_cue_report()

        result = reconcile_vlw(vlm, lr, ctx, cue)
        assert result.overall_agreement == "vlm_unavailable"

    def test_unrecognised_vlm_style(self):
        """VLM returns unrecognised lighting style."""
        vlm = _make_vlm(lighting_style="totally_unknown_style")
        lr = _make_lighting_read()
        ctx = _make_scene_ctx()
        cue = _make_cue_report()

        result = reconcile_vlw(vlm, lr, ctx, cue)
        assert result.overall_agreement == "vlm_unavailable"
        assert "not recognised" in result.notes[0]


# ═══════════════════════════════════════════════════════════════════════════
# 5. B&W Clamshell False Positive Scenario
# ═══════════════════════════════════════════════════════════════════════════


class TestBWClamshellFalsePositive:
    """Reproduce the known bug: B&W editorial image falsely classified as
    clamshell due to contrast-grade amplified floor bounce catchlights."""

    def test_bw_clamshell_conflict_detected(self):
        """VLM says dramatic, CV says clamshell with 2 lights, B&W detected."""
        vlm = _make_vlm(
            lighting_style="dramatic/chiaroscuro",
            mood="dramatic, intense",
            bg="dark, featureless",
        )
        lr = _make_lighting_read(
            shadow_pattern="clamshell",
            light_count=2,
            source_quality="soft",
            fill_presence="moderate",
            confidence=0.6,
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait", has_face_mesh=True)
        cue = _make_cue_report(is_bw=True, is_hcg=True)

        result = reconcile_vlw(vlm, lr, ctx, cue)

        # Should flag significant conflict
        assert result.conflict_count >= 3
        assert result.requires_human_review

        # Should include B&W catchlight note
        all_notes = []
        for d in result.dimensions:
            all_notes.extend(d.notes)
        assert any("B&W" in n or "catchlight" in n.lower() for n in all_notes), \
            f"Expected B&W catchlight note, got: {all_notes}"

        # Should propose adjustments
        assert len(result.proposed_adjustments) > 0

        # Confidence should NOT be boosted (conflicts present)
        assert result.confidence_delta == 0.0 or result.confirmed_count == 0

    def test_bw_clamshell_no_field_values_changed(self):
        """Verify that reconciliation NEVER modifies LightingRead values."""
        vlm = _make_vlm(lighting_style="dramatic/chiaroscuro")
        lr = _make_lighting_read(
            shadow_pattern="clamshell", light_count=2,
            source_quality="soft", fill_presence="moderate",
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait")
        cue = _make_cue_report(is_bw=True)

        # reconcile_vlw should NOT modify lr
        _ = reconcile_vlw(vlm, lr, ctx, cue)

        assert lr.shadow_pattern == "clamshell"
        assert lr.light_count == 2
        assert lr.source_quality == "soft"
        assert lr.fill_presence == "moderate"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Confidence Boost Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfidenceBoost:
    def test_boost_on_confirmed(self):
        """Confidence should increase when VLM and CV agree."""
        vlm = _make_vlm(lighting_style="rembrandt", mood="dramatic", bg="dark studio")
        lr = _make_lighting_read(
            shadow_pattern="rembrandt", light_count=1,
            source_quality="hard", fill_presence="subtle",
            confidence=0.65,
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait")
        cue = _make_cue_report()
        classification = {"mood": "dramatic"}

        result = reconcile_vlw(vlm, lr, ctx, cue, classification)
        boosted = apply_confirmed_boosts(lr, result)

        assert boosted.confidence > lr.confidence
        assert boosted.confidence <= 0.95  # capped

    def test_no_boost_on_conflict(self):
        """Confidence should NOT increase on conflicts."""
        vlm = _make_vlm(lighting_style="dramatic/chiaroscuro")
        lr = _make_lighting_read(
            shadow_pattern="clamshell", light_count=2,
            source_quality="soft", fill_presence="strong",
            confidence=0.65,
        )
        ctx = _make_scene_ctx(scene_type="studio_portrait")
        cue = _make_cue_report()

        result = reconcile_vlw(vlm, lr, ctx, cue)

        # No confirmed dimensions → delta should be 0
        if result.confirmed_count == 0:
            boosted = apply_confirmed_boosts(lr, result)
            assert boosted.confidence == lr.confidence

    def test_confidence_cap_at_095(self):
        """Confidence should never exceed 0.95."""
        lr = _make_lighting_read(confidence=0.93)
        # Create a reconciliation with large boost
        recon = VLWReconciliation(
            confirmed_count=5,
            confidence_delta=0.20,
        )
        boosted = apply_confirmed_boosts(lr, recon)
        assert boosted.confidence == 0.95

    def test_original_not_mutated(self):
        """apply_confirmed_boosts should return a copy, not modify original."""
        lr = _make_lighting_read(confidence=0.65)
        recon = VLWReconciliation(confirmed_count=3, confidence_delta=0.10)
        boosted = apply_confirmed_boosts(lr, recon)

        assert lr.confidence == 0.65  # original unchanged
        assert boosted.confidence > 0.65  # copy boosted


class TestBWOverrideIsNarrow:
    """The B&W override is a documented exception to CV precedence.

    The VL guardrail says the VLM hints and must not silently outrank strong
    physical evidence. These pin the exception to the one configuration where
    the physical evidence is known-degraded, so it cannot widen by accident.
    """

    def test_reverse_conflict_still_goes_to_review(self):
        """CV soft + VLM hard has no B&W explanation — B&W inflates hardness."""
        vlm = _map_vlm_style("split")  # expects hard
        result = _reconcile_source_quality(vlm, "soft", is_bw=True)
        assert result.agreement == "conflicting"
        assert result.recommendation_source == "human_review_required"

    def test_colour_image_still_conflicts(self):
        """Without B&W there is no reason to doubt the CV hardness reading."""
        vlm = _map_vlm_style("clamshell")  # expects soft
        result = _reconcile_source_quality(vlm, "hard", is_bw=False)
        assert result.agreement == "conflicting"

    def test_override_records_its_reason(self):
        """A silent override would breach the guardrail; this one explains itself."""
        vlm = _map_vlm_style("clamshell")
        result = _reconcile_source_quality(vlm, "hard", is_bw=True)
        assert result.agreement == "vlm_override"
        assert "B&W" in result.explanation
        assert any("inflate" in n for n in result.notes)
