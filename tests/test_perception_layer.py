"""Tests for the perception & robustness layer.

These tests verify that the diagnostic layer computes correctly and
never modifies pattern classification or scoring outputs.
"""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass

from engine.orchestrator import (
    AnalysisResult,
    FaceValidation,
    SignalReliability,
    PerceptionExplanation,
    EdgeCaseFlags,
    PatternCandidate,
    PatternCandidates,
    _compute_face_validation,
    _compute_signal_reliability,
    _compute_edge_case_flags,
    _compute_perception_explanation,
    _compute_perception_layer,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_result(**overrides) -> AnalysisResult:
    """Create a minimal AnalysisResult for testing."""
    r = AnalysisResult()
    r.authoritative_pattern = overrides.get("pattern", "rembrandt")
    r.authoritative_pattern_source = overrides.get("source", "reference_read")
    r.classification = overrides.get("classification", {"brightness": "medium", "mood": "cinematic"})
    r.debug_data = overrides.get("debug_data", {})
    r.vision_data = overrides.get("vision_data", {})
    r.cue_report = overrides.get("cue_report", None)
    r.pattern_candidates = overrides.get("pattern_candidates", PatternCandidates(
        primary=PatternCandidate(pattern="rembrandt", source="reference_read", confidence=0.9, rank=1),
    ))
    r.lighting_intel = overrides.get("lighting_intel", None)
    return r


def _make_cue(confidence=0.5, **extra):
    """Create a mock cue with confidence and notes."""
    cue = MagicMock()
    cue.confidence = confidence
    cue.notes = []
    for k, v in extra.items():
        setattr(cue, k, v)
    return cue


def _make_cue_report(populated_cues=None, **kwargs):
    """Create a mock VisualCueReport."""
    cr = MagicMock()
    cr.overall_confidence.return_value = kwargs.get("overall_conf", 0.5)

    from engine.orchestrator import _CUE_FIELD_NAMES
    for name in _CUE_FIELD_NAMES:
        if populated_cues and name in populated_cues:
            setattr(cr, name, populated_cues[name])
        else:
            setattr(cr, name, None)

    return cr


# ═══════════════════════════════════════════════════════════════════════════
# Face Validation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFaceValidation:
    def test_face_detected_good_quality(self):
        """Face box present, large area, yaw available → quality=good."""
        r = _make_result(
            debug_data={"face_box": (100, 100, 300, 400)},
            vision_data={
                "catchlights": {"face_yaw": -0.3},
                "region_attribution": {"face_detection_score": 0.95},
            },
        )
        fv = _compute_face_validation(r)
        assert fv.face_detected is True
        assert fv.face_quality == "good"
        assert fv.face_confidence == 0.95
        assert fv.face_yaw == -0.3
        assert fv.face_box_area_ratio > 0

    def test_face_detected_partial_no_yaw(self):
        """Face box present but no yaw → quality=partial."""
        r = _make_result(
            debug_data={"face_box": (100, 100, 300, 400)},
            vision_data={
                "catchlights": {},
                "region_attribution": {"face_detection_score": 0.85},
            },
        )
        fv = _compute_face_validation(r)
        assert fv.face_detected is True
        assert fv.face_quality == "partial"
        assert fv.face_yaw is None

    def test_face_detected_partial_tiny_area(self):
        """Face box present but tiny → quality=partial."""
        r = _make_result(
            debug_data={"face_box": (0, 0, 5, 5)},
            vision_data={
                "catchlights": {"face_yaw": 0.1},
                "region_attribution": {
                    "face_detection_score": 0.6,
                    "_image_h": 800,
                    "_image_w": 600,
                },
            },
        )
        fv = _compute_face_validation(r)
        assert fv.face_detected is True
        assert fv.face_box_area_ratio < 0.02
        assert fv.face_quality == "partial"

    def test_no_face_detected(self):
        """No face box → quality=none, detected=False."""
        r = _make_result(
            debug_data={},
            vision_data={"catchlights": {}, "region_attribution": {}},
        )
        fv = _compute_face_validation(r)
        assert fv.face_detected is False
        assert fv.face_quality == "none"
        assert fv.face_confidence == 0.0
        assert fv.face_yaw is None
        assert fv.face_box_area_ratio == 0.0

    def test_fallback_confidence_when_score_missing(self):
        """No detection score stored → uses 0.8 heuristic."""
        r = _make_result(
            debug_data={"face_box": (10, 10, 200, 300)},
            vision_data={"catchlights": {"face_yaw": 0.0}, "region_attribution": {}},
        )
        fv = _compute_face_validation(r)
        assert fv.face_confidence == 0.8


# ═══════════════════════════════════════════════════════════════════════════
# Signal Reliability Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalReliability:
    def test_full_cue_report(self):
        """All cues populated → high signal count, no missing."""
        from engine.orchestrator import _CUE_FIELD_NAMES
        populated = {name: _make_cue(confidence=0.7) for name in _CUE_FIELD_NAMES}
        cr = _make_cue_report(populated_cues=populated, overall_conf=0.7)
        r = _make_result(cue_report=cr)
        sr = _compute_signal_reliability(r)
        assert sr.signals_available == len(_CUE_FIELD_NAMES)
        assert sr.missing_signals == []
        assert sr.overall_signal_strength == 0.7

    def test_sparse_cue_report(self):
        """Only a few cues populated → low count, many missing."""
        populated = {
            "catchlight_shape": _make_cue(confidence=0.6, dominant_shape="rectangular"),
            "contrast_ratio": _make_cue(confidence=0.8, ratio=3.5),
        }
        cr = _make_cue_report(populated_cues=populated, overall_conf=0.3)
        r = _make_result(cue_report=cr)
        sr = _compute_signal_reliability(r)
        assert sr.signals_available == 2
        assert len(sr.missing_signals) == 22

    def test_weak_signals_detected(self):
        """Low-confidence cues appear in weak_signals."""
        populated = {
            "shadow_edge_hardness": _make_cue(confidence=0.1),
            "catchlight_shape": _make_cue(confidence=0.8),
        }
        cr = _make_cue_report(populated_cues=populated, overall_conf=0.45)
        r = _make_result(cue_report=cr)
        sr = _compute_signal_reliability(r)
        assert "shadow_edge_hardness" in sr.weak_signals
        assert "catchlight_shape" not in sr.weak_signals

    def test_no_cue_report(self):
        """No cue_report → all signals missing."""
        r = _make_result(cue_report=None)
        sr = _compute_signal_reliability(r)
        assert sr.signals_available == 0
        assert len(sr.missing_signals) == 24

    def test_face_dependent_tracking(self):
        """Face-dependent cues with confidence > 0 counted."""
        populated = {
            "primary_shadow_direction": _make_cue(confidence=0.6, direction="upper_left"),
            "vertical_light_angle": _make_cue(confidence=0.0),  # zero conf → not counted
            "catchlight_shape": _make_cue(confidence=0.7),  # not face-dependent
        }
        cr = _make_cue_report(populated_cues=populated, overall_conf=0.4)
        r = _make_result(cue_report=cr)
        sr = _compute_signal_reliability(r)
        assert sr.face_dependent_signals_available == 1  # only primary_shadow_direction


# ═══════════════════════════════════════════════════════════════════════════
# Edge Case Flags Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCaseFlags:
    def test_no_face_flag(self):
        fv = FaceValidation(face_detected=False)
        r = _make_result(cue_report=_make_cue_report())
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.no_face is True

    def test_bw_processing_flag(self):
        tpe = _make_cue(confidence=0.9, is_bw=True)
        cr = _make_cue_report(populated_cues={"tonal_processing_estimation": tpe})
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr)
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.bw_processing is True

    def test_blown_highlights_flag(self):
        """Fires on actual pixel clipping, not on a contrast-ratio proxy.

        The flag used to key on contrast_ratio > 8.0, which false-fired on any
        dramatic Rembrandt or Loop portrait — deep shadows plus bright skin push
        the p95/p5 ratio past 8 without a single clipped pixel. The source of
        truth is now TonalProcessingEstimation.highlights_clipped, set from the
        histogram (p99 pegged at white with p99-p95 < 3).
        """
        tpe = _make_cue(confidence=0.7, highlights_clipped=True)
        cr = _make_cue_report(populated_cues={"tonal_processing_estimation": tpe})
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr)
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.blown_highlights is True

    def test_blown_highlights_does_not_fire_on_contrast_alone(self):
        """Regression guard for the false-positive this flag was fixed to avoid.

        A dramatic portrait with a high contrast ratio and no clipped highlights
        must NOT be flagged. Without this, someone reinstating the old proxy
        would turn the test above green and quietly reintroduce the bug.
        """
        ctr = _make_cue(confidence=0.7, ratio=10.0)
        tpe = _make_cue(confidence=0.7, highlights_clipped=False)
        cr = _make_cue_report(populated_cues={
            "contrast_ratio": ctr,
            "tonal_processing_estimation": tpe,
        })
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr)
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.blown_highlights is False

    def test_outdoor_foliage_flag(self):
        esc = _make_cue(confidence=0.6, environment_hints=["dappled_foliage", "warm_overall"])
        cr = _make_cue_report(populated_cues={"environmental_shadow_continuity": esc})
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr)
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.outdoor_foliage_shadows is True

    def test_extreme_low_key_flag(self):
        ls = _make_cue(confidence=0.8, shadow_density=0.7)
        cr = _make_cue_report(populated_cues={"light_structure": ls})
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr, classification={"brightness": "low"})
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.extreme_low_key is True

    def test_window_light_gradient(self):
        bg = _make_cue(confidence=0.7, pattern="gradient")
        esc = _make_cue(confidence=0.5, has_natural_indicators=True, environment_hints=[])
        cr = _make_cue_report(populated_cues={
            "background_illumination": bg,
            "environmental_shadow_continuity": esc,
        })
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr)
        ecf = _compute_edge_case_flags(r, fv)
        assert ecf.window_light_gradient is True

    def test_no_edge_cases(self):
        """Clean studio shot → no flags set."""
        cr = _make_cue_report()
        fv = FaceValidation(face_detected=True)
        r = _make_result(cue_report=cr, classification={"brightness": "medium"})
        ecf = _compute_edge_case_flags(r, fv)
        assert not ecf.no_face
        assert not ecf.bw_processing
        assert not ecf.blown_highlights
        assert not ecf.extreme_low_key


# ═══════════════════════════════════════════════════════════════════════════
# Perception Explanation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPerceptionExplanation:
    def test_supporting_signals_populated(self):
        ls = _make_cue(confidence=0.8, pattern_name="rembrandt")
        psd = _make_cue(confidence=0.7, direction="upper_left")
        cr = _make_cue_report(populated_cues={
            "light_structure": ls,
            "primary_shadow_direction": psd,
        })
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=15)
        r = _make_result(cue_report=cr, pattern="rembrandt")
        pe = _compute_perception_explanation(r, fv, sr)
        assert len(pe.supporting_signals) > 0
        assert pe.supporting_signals[0]["confidence"] >= pe.supporting_signals[-1]["confidence"]

    def test_no_face_ambiguity_flag(self):
        fv = FaceValidation(face_detected=False)
        sr = SignalReliability(signals_available=5)
        r = _make_result(cue_report=_make_cue_report())
        pe = _compute_perception_explanation(r, fv, sr)
        assert "no_face_detected" in pe.ambiguity_flags

    def test_bw_ambiguity_flag(self):
        tpe = _make_cue(confidence=0.9, is_bw=True)
        cr = _make_cue_report(populated_cues={"tonal_processing_estimation": tpe})
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=15)
        r = _make_result(cue_report=cr)
        pe = _compute_perception_explanation(r, fv, sr)
        assert "bw_limits_color_cues" in pe.ambiguity_flags

    def test_low_signal_count_flag(self):
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=5)
        r = _make_result(cue_report=_make_cue_report())
        pe = _compute_perception_explanation(r, fv, sr)
        assert "low_signal_count" in pe.ambiguity_flags

    def test_close_confidence_flag(self):
        pc = PatternCandidates(
            primary=PatternCandidate("rembrandt", "reference_read", 0.85, 1),
            alternates=[PatternCandidate("loop", "lighting_inference", 0.78, 2)],
        )
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=15)
        r = _make_result(cue_report=_make_cue_report(), pattern_candidates=pc)
        pe = _compute_perception_explanation(r, fv, sr)
        assert "multiple_patterns_close_confidence" in pe.ambiguity_flags

    def test_pattern_reasoning_populated(self):
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=15)
        r = _make_result(cue_report=_make_cue_report(), pattern="rembrandt")
        pe = _compute_perception_explanation(r, fv, sr)
        assert "rembrandt" in pe.pattern_reasoning
        assert "reference_read" in pe.pattern_reasoning

    def test_contradicting_from_light_structure(self):
        ls = _make_cue(confidence=0.6, pattern_name="loop")
        cr = _make_cue_report(populated_cues={"light_structure": ls})
        fv = FaceValidation(face_detected=True)
        sr = SignalReliability(signals_available=15)
        r = _make_result(cue_report=cr, pattern="rembrandt")
        pe = _compute_perception_explanation(r, fv, sr)
        assert any("loop" in str(c.get("value", "")) for c in pe.contradicting_signals)


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPerceptionLayerIntegration:
    def test_all_fields_populated(self):
        """Full perception layer produces all four structures."""
        ls = _make_cue(confidence=0.8, pattern_name="rembrandt", shadow_density=0.3)
        cr = _make_cue_report(populated_cues={"light_structure": ls}, overall_conf=0.5)
        r = _make_result(
            cue_report=cr,
            debug_data={"face_box": (50, 50, 250, 350)},
            vision_data={
                "catchlights": {"face_yaw": -0.15},
                "region_attribution": {"face_detection_score": 0.92},
            },
        )
        _compute_perception_layer(r)
        assert r.face_validation is not None
        assert r.signal_reliability is not None
        assert r.edge_case_flags is not None
        assert r.perception_explanation is not None

    def test_non_regression_pattern_unchanged(self):
        """Perception layer does NOT modify authoritative_pattern."""
        r = _make_result(pattern="rembrandt", cue_report=_make_cue_report())
        original_pattern = r.authoritative_pattern
        original_source = r.authoritative_pattern_source
        _compute_perception_layer(r)
        assert r.authoritative_pattern == original_pattern
        assert r.authoritative_pattern_source == original_source

    def test_non_regression_candidates_unchanged(self):
        """Perception layer does NOT modify pattern_candidates."""
        pc = PatternCandidates(
            primary=PatternCandidate("loop", "reference_read", 0.85, 1),
        )
        r = _make_result(pattern_candidates=pc, cue_report=_make_cue_report())
        _compute_perception_layer(r)
        assert r.pattern_candidates.primary.pattern == "loop"
        assert r.pattern_candidates.primary.confidence == 0.85

    def test_non_regression_lighting_intel_unchanged(self):
        """Perception layer does NOT modify lighting_intel."""
        li = MagicMock()
        li.light_count = 3
        li.pattern = "rembrandt"
        r = _make_result(lighting_intel=li, cue_report=_make_cue_report())
        _compute_perception_layer(r)
        assert r.lighting_intel.light_count == 3
        assert r.lighting_intel.pattern == "rembrandt"

    def test_graceful_with_no_cue_report(self):
        """Perception layer handles None cue_report without crashing."""
        r = _make_result(cue_report=None)
        _compute_perception_layer(r)
        assert r.face_validation is not None
        assert r.signal_reliability is not None
        assert r.signal_reliability.signals_available == 0

    def test_json_serializable(self):
        """All perception outputs can be serialized to JSON."""
        import json
        cr = _make_cue_report(overall_conf=0.4)
        r = _make_result(
            cue_report=cr,
            debug_data={"face_box": (10, 10, 100, 150)},
            vision_data={"catchlights": {"face_yaw": 0.1}, "region_attribution": {}},
        )
        _compute_perception_layer(r)

        # Verify each can be serialized
        fv = r.face_validation
        assert json.dumps({
            "face_detected": fv.face_detected,
            "face_confidence": fv.face_confidence,
            "face_quality": fv.face_quality,
            "face_yaw": fv.face_yaw,
            "face_box_area_ratio": fv.face_box_area_ratio,
        })

        sr = r.signal_reliability
        assert json.dumps({
            "signals_available": sr.signals_available,
            "weak_signals": sr.weak_signals,
            "missing_signals": sr.missing_signals,
        })

        ecf = r.edge_case_flags
        assert json.dumps({
            "no_face": ecf.no_face,
            "bw_processing": ecf.bw_processing,
        })

        pe = r.perception_explanation
        assert json.dumps({
            "supporting_signals": pe.supporting_signals,
            "ambiguity_flags": pe.ambiguity_flags,
            "pattern_reasoning": pe.pattern_reasoning,
        })
