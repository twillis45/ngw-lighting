"""Integration tests for the central orchestrator.

Verifies that analyze_image(), recommend_system(), and evaluate_test_shot()
produce structured results through the full decision chain.
"""

import pytest

from engine.orchestrator import (
    AnalysisResult,
    analyze_image,
    evaluate_test_shot,
    recommend_system,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _fake_describe(image_path, mode="vision", debug=False, run_vlm=True):
    """Return a plausible describe_image result for testing.

    Mirrors describe_image()'s signature including run_vlm — a double that
    drifts from the real signature fails for the wrong reason.
    """
    return {
        "ok": True,
        "palette": {"overall": [{"hex": "#808080", "pct": 100}]},
        "orientation": "portrait",
        "is_grayscale_like": False,
        "classification": {
            "mood": "corporate",
            "confidence": 0.7,
            "lightQuality": "soft",
            "colorTemperature": "neutral",
            "brightness": "medium",
            "suggestedRecipe": "corporate-loop",
        },
        "vision": {
            "ok": True,
            "catchlights": {
                "ok": True,
                "count": 1,
                "catchlights": [
                    {"eye": "left", "position": "10 o'clock", "shape": "round", "intensity": 0.9},
                ],
                "inferred": {
                    "keyLightPosition": "above, slightly left",
                    "likelyModifier": "beauty dish or round source",
                    "lightCount": 1,
                },
            },
            "skin_tone": {
                "ok": True,
                "skin_tone_guess": "light",
                "confidence": "high",
            },
            "pose": {"ok": True, "pose": "standing", "angle": "front-ish", "visibility": 0.8},
            "region_attribution": {
                "masks": {"person_ratio": 0.5, "background_ratio": 0.4},
                "palettes": {
                    "background_palette": [
                        {"rgb": [80, 80, 80], "hex": "#505050", "name": "gray", "pct": 100},
                    ],
                },
                "face_box": [0.3, 0.1, 0.7, 0.4],
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# analyze_image
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeImage:

    def test_returns_analysis_result(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert isinstance(result, AnalysisResult)
        assert result.ok is True

    def test_populates_vision_data(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.vision_data.get("ok") is True
        assert "catchlights" in result.vision_data

    def test_populates_classification(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.classification.get("mood") == "corporate"

    def test_populates_lighting_intel(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.lighting_intel is not None
        assert hasattr(result.lighting_intel, "pattern")

    def test_populates_reference_analysis(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.reference_analysis is not None

    def test_solver_skipped_when_disabled(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.solver_result is None

    def test_handles_describe_failure_gracefully(self, monkeypatch):
        import engine.image_analysis as ia_mod

        def _failing_describe(*a, **kw):
            return {"ok": False}

        monkeypatch.setattr(ia_mod, "describe_image", _failing_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.ok is False
        assert len(result.notes) > 0

    def test_handles_describe_exception_gracefully(self, monkeypatch):
        import engine.image_analysis as ia_mod

        def _exploding_describe(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(ia_mod, "describe_image", _exploding_describe)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert result.ok is False
        assert any("boom" in n for n in result.notes)

    def test_description_excludes_internal_keys(self, monkeypatch):
        import engine.image_analysis as ia_mod

        def _describe_with_internals(*a, **kw):
            result = _fake_describe(*a, **kw)
            result["_cue_report"] = {"internal": True}
            result["_debug_img_bgr"] = "numpy_array"
            return result

        monkeypatch.setattr(ia_mod, "describe_image", _describe_with_internals)

        result = analyze_image("/fake/image.jpg", run_extended=False, run_solver=False)
        assert "_cue_report" not in result.description
        assert "_debug_img_bgr" not in result.description
        assert "palette" in result.description


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_test_shot
# ═══════════════════════════════════════════════════════════════════════════

class TestEvaluateTestShot:

    def test_returns_dict(self, monkeypatch):
        import engine.image_analysis as ia_mod
        monkeypatch.setattr(ia_mod, "describe_image", _fake_describe)

        result = evaluate_test_shot("/fake/image.jpg")
        assert isinstance(result, dict)
        assert result.get("ok") is True

    def test_excludes_internal_keys(self, monkeypatch):
        import engine.image_analysis as ia_mod

        def _describe_with_internals(*a, **kw):
            result = _fake_describe(*a, **kw)
            result["_cue_report"] = {"internal": True}
            return result

        monkeypatch.setattr(ia_mod, "describe_image", _describe_with_internals)

        result = evaluate_test_shot("/fake/image.jpg")
        assert "_cue_report" not in result


# ═══════════════════════════════════════════════════════════════════════════
# recommend_system
# ═══════════════════════════════════════════════════════════════════════════

class TestRecommendSystem:

    def test_returns_selection_result(self):
        import json
        from pathlib import Path

        systems_path = Path("data/lighting_systems.json")
        if not systems_path.exists():
            pytest.skip("lighting_systems.json not found")

        data = json.loads(systems_path.read_text())
        systems = data.get("systems", [])
        if not systems:
            pytest.skip("No systems in lighting_systems.json")
        result = recommend_system(systems[:3])
        assert hasattr(result, "winner")
        assert hasattr(result, "confidence")

    def test_empty_systems_raises(self):
        with pytest.raises(Exception):
            recommend_system([])
