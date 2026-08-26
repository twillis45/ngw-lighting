"""VLW Reconciliation — compare VLM hypothesis against CV evidence.

The VLM (vision-language model) produces a high-level ``lighting_style``
assessment.  The CV pipeline produces detailed measurements via 16 optical
cues and catchlight geometry.  This module compares the two across six
lighting dimensions and classifies each as:

- **confirmed**: VLM and CV agree → boost confidence
- **conflicting**: VLM and CV disagree → flag for human review
- **vlm_only**: VLM has opinion, CV inconclusive → present as hypothesis
- **cv_only**: CV measured, VLM silent → keep CV result

CRITICAL SAFETY CONSTRAINT:
    This module NEVER modifies LightingRead field values (pattern,
    light_count, source_quality, etc.).  The only automatic action is
    ``apply_confirmed_boosts()`` which exclusively adjusts the
    ``confidence`` float.  All conflicts produce a ``VLWReconciliation``
    report for human review.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from engine.image_analysis_models import (
    LightingRead,
    SceneContext,
    VLMDescription,
    VLWDimensionResult,
    VLWReconciliation,
    VisualCueReport,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# VLM Lighting Style → Expected CV Dimensions
# ═══════════════════════════════════════════════════════════════════════════

VLM_LIGHTING_STYLE_MAP: Dict[str, Dict[str, Any]] = {
    "rembrandt": {
        "pattern": ["rembrandt"],
        "light_count_range": (1, 2),
        "source_quality": ["hard", "mixed"],
        "fill_presence": ["none", "subtle", "moderate"],
        "mood_family": "dramatic",
    },
    "loop": {
        "pattern": ["loop"],
        "light_count_range": (1, 2),
        "source_quality": ["soft", "mixed"],
        "fill_presence": ["subtle", "moderate"],
        "mood_family": "natural",
    },
    "butterfly/paramount": {
        "pattern": ["butterfly"],
        "light_count_range": (1, 2),
        "source_quality": ["soft", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "glamour",
    },
    "butterfly": {
        "pattern": ["butterfly"],
        "light_count_range": (1, 2),
        "source_quality": ["soft", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "glamour",
    },
    "paramount": {
        "pattern": ["butterfly"],
        "light_count_range": (1, 2),
        "source_quality": ["soft", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "glamour",
    },
    "split": {
        "pattern": ["split"],
        "light_count_range": (1, 1),
        "source_quality": ["hard", "mixed"],
        "fill_presence": ["none"],
        "mood_family": "dramatic",
    },
    "clamshell": {
        "pattern": ["clamshell", "butterfly"],
        "light_count_range": (2, 2),
        "source_quality": ["soft"],
        "fill_presence": ["moderate", "strong"],
        "mood_family": "beauty",
    },
    "flat/beauty": {
        "pattern": ["flat"],
        "light_count_range": (1, 3),
        "source_quality": ["soft"],
        "fill_presence": ["strong"],
        "mood_family": "beauty",
    },
    "flat": {
        "pattern": ["flat"],
        "light_count_range": (1, 3),
        "source_quality": ["soft"],
        "fill_presence": ["strong"],
        "mood_family": "beauty",
    },
    "rim/edge": {
        "pattern": ["unknown"],
        "light_count_range": (2, 3),
        "source_quality": ["hard", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
    "natural/ambient": {
        "pattern": ["unknown", "environmental ambient"],
        "light_count_range": (1, 1),
        "source_quality": ["soft", "ambient"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "natural",
    },
    "natural": {
        "pattern": ["unknown", "environmental ambient"],
        "light_count_range": (1, 1),
        "source_quality": ["soft", "ambient"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "natural",
    },
    "ambient": {
        "pattern": ["unknown", "environmental ambient"],
        "light_count_range": (1, 1),
        "source_quality": ["soft", "ambient"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "natural",
    },
    "mixed/practical": {
        "pattern": ["unknown"],
        "light_count_range": (1, 4),
        "source_quality": ["mixed"],
        "fill_presence": ["subtle", "moderate"],
        "mood_family": "natural",
    },
    "dramatic/chiaroscuro": {
        "pattern": ["rembrandt", "split"],
        "light_count_range": (1, 1),
        "source_quality": ["hard"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
    "chiaroscuro": {
        "pattern": ["rembrandt", "split"],
        "light_count_range": (1, 1),
        "source_quality": ["hard"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
    "dramatic": {
        "pattern": ["rembrandt", "split"],
        "light_count_range": (1, 1),
        "source_quality": ["hard"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
    "high-key": {
        "pattern": ["flat", "butterfly", "clamshell"],
        "light_count_range": (2, 4),
        "source_quality": ["soft"],
        "fill_presence": ["strong"],
        "mood_family": "bright",
    },
    "low-key": {
        "pattern": ["rembrandt", "split"],
        "light_count_range": (1, 2),
        "source_quality": ["hard", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
    "broad": {
        "pattern": ["broad"],
        "light_count_range": (1, 2),
        "source_quality": ["soft", "mixed"],
        "fill_presence": ["subtle", "moderate"],
        "mood_family": "natural",
    },
    "short": {
        "pattern": ["split", "rembrandt"],
        "light_count_range": (1, 2),
        "source_quality": ["hard", "mixed"],
        "fill_presence": ["none", "subtle"],
        "mood_family": "dramatic",
    },
}

# Mood family mapping for mood dimension comparison.
_MOOD_FAMILY_MAP: Dict[str, str] = {
    "dramatic": "dramatic", "edgy": "dramatic", "cinematic": "dramatic",
    "moody": "dramatic", "dark": "dramatic", "intense": "dramatic",
    "mysterious": "dramatic",
    "glamorous": "beauty", "beauty": "beauty", "polished": "beauty",
    "elegant": "beauty", "refined": "beauty",
    "natural": "natural", "candid": "natural", "editorial": "natural",
    "reportage": "natural", "lifestyle": "natural",
    "bright": "bright", "airy": "bright", "high-key": "bright",
    "cheerful": "bright", "optimistic": "bright",
}


# ═══════════════════════════════════════════════════════════════════════════
# Mapping helpers
# ═══════════════════════════════════════════════════════════════════════════


def _map_vlm_style(lighting_style: str) -> Dict[str, Any]:
    """Look up VLM lighting_style in the mapping table.

    Normalises input (lowercase, strip whitespace) and tries exact match
    first, then substring match for compound styles like "dramatic/chiaroscuro".
    Returns empty dict for unrecognised styles.
    """
    if not lighting_style:
        return {}

    key = lighting_style.strip().lower()

    # Exact match
    if key in VLM_LIGHTING_STYLE_MAP:
        return VLM_LIGHTING_STYLE_MAP[key]

    # Substring match (e.g. "hard dramatic" contains "dramatic")
    for map_key, map_val in VLM_LIGHTING_STYLE_MAP.items():
        if map_key in key or key in map_key:
            return map_val

    return {}


def _classify_mood_family(mood_str: str) -> str:
    """Map a free-text mood string to a mood family."""
    if not mood_str:
        return "unknown"
    low = mood_str.lower()
    for token, family in _MOOD_FAMILY_MAP.items():
        if token in low:
            return family
    return "unknown"


def _is_inconclusive(value: str) -> bool:
    """Check if a value is effectively empty/inconclusive."""
    return not value or value.lower() in ("unknown", "none", "", "n/a")


# ═══════════════════════════════════════════════════════════════════════════
# Per-dimension reconciliation
# ═══════════════════════════════════════════════════════════════════════════


def _reconcile_pattern(
    vlm_expected: Dict[str, Any],
    cv_pattern: str,
) -> VLWDimensionResult:
    """Compare lighting pattern."""
    vlm_patterns = vlm_expected.get("pattern", [])
    vlm_str = ", ".join(vlm_patterns) if vlm_patterns else ""

    result = VLWDimensionResult(
        dimension="lighting_pattern",
        vlm_value=vlm_str,
        cv_value=cv_pattern,
    )

    if not vlm_patterns and _is_inconclusive(cv_pattern):
        result.agreement = "both_inconclusive"
        result.recommended_value = cv_pattern
        result.recommendation_source = "cv"
        return result

    if not vlm_patterns:
        result.agreement = "cv_only"
        result.recommended_value = cv_pattern
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(cv_pattern):
        result.agreement = "vlm_only"
        result.recommended_value = vlm_patterns[0]
        result.recommendation_source = "human_review_required"
        result.explanation = f"VLM suggests {vlm_str} but CV pattern is inconclusive."
        return result

    # Normalise for comparison
    cv_lower = cv_pattern.lower().strip()
    vlm_lower = [p.lower().strip() for p in vlm_patterns]

    # Check for match (allow rembrandt-ish to match rembrandt, etc.)
    matched = False
    for vp in vlm_lower:
        if cv_lower == vp:
            matched = True
            break
        if cv_lower.startswith(vp) or vp.startswith(cv_lower):
            matched = True
            break

    if matched:
        result.agreement = "confirmed"
        result.confidence_boost = 0.08
        result.recommended_value = cv_pattern
        result.recommendation_source = "cv"
        result.explanation = f"VLM ({vlm_str}) agrees with CV ({cv_pattern})."
    else:
        result.agreement = "conflicting"
        result.recommended_value = cv_pattern
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM expects {vlm_str} but CV measured {cv_pattern}. "
            f"Keeping CV result; flagged for review."
        )

    return result


def _reconcile_light_count(
    vlm_expected: Dict[str, Any],
    cv_count: int,
    is_bw: bool = False,
    is_high_contrast_grade: bool = False,
) -> VLWDimensionResult:
    """Compare light count with B&W special handling."""
    count_range: Tuple[int, int] = vlm_expected.get("light_count_range", (0, 0))
    vlm_str = f"{count_range[0]}-{count_range[1]}" if count_range[0] != count_range[1] else str(count_range[0])

    result = VLWDimensionResult(
        dimension="light_count",
        vlm_value=vlm_str,
        cv_value=str(cv_count),
    )

    if count_range == (0, 0) and cv_count == 0:
        result.agreement = "both_inconclusive"
        result.recommended_value = str(cv_count)
        result.recommendation_source = "cv"
        return result

    if count_range == (0, 0):
        result.agreement = "cv_only"
        result.recommended_value = str(cv_count)
        result.recommendation_source = "cv"
        return result

    if cv_count == 0:
        result.agreement = "vlm_only"
        result.recommended_value = str(count_range[0])
        result.recommendation_source = "human_review_required"
        result.explanation = f"VLM expects {vlm_str} lights but CV detected none."
        return result

    if count_range[0] <= cv_count <= count_range[1]:
        result.agreement = "confirmed"
        result.confidence_boost = 0.06
        result.recommended_value = str(cv_count)
        result.recommendation_source = "cv"
        result.explanation = f"CV light count ({cv_count}) within VLM range ({vlm_str})."
    else:
        result.agreement = "conflicting"
        result.recommended_value = str(cv_count)
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM expects {vlm_str} lights but CV detected {cv_count}."
        )

        # Special B&W check: VLM says 1 light, CV says 2 — potential floor bounce
        if (is_bw or is_high_contrast_grade) and cv_count > count_range[1]:
            bw_note = (
                "B&W/high-contrast processing detected. Lower catchlight "
                "intensity may be artificially elevated by contrast grading, "
                "causing false clamshell detection. VLM single-source "
                "hypothesis should be investigated."
            )
            result.notes.append(bw_note)
            result.explanation += f" {bw_note}"

    return result


def _reconcile_source_quality(
    vlm_expected: Dict[str, Any],
    cv_quality: str,
    is_bw: bool = False,
    is_high_contrast_grade: bool = False,
) -> VLWDimensionResult:
    """Compare source quality."""
    vlm_qualities = vlm_expected.get("source_quality", [])
    vlm_str = ", ".join(vlm_qualities) if vlm_qualities else ""

    result = VLWDimensionResult(
        dimension="source_quality",
        vlm_value=vlm_str,
        cv_value=cv_quality,
    )

    if not vlm_qualities and _is_inconclusive(cv_quality):
        result.agreement = "both_inconclusive"
        result.recommended_value = cv_quality
        result.recommendation_source = "cv"
        return result

    if not vlm_qualities:
        result.agreement = "cv_only"
        result.recommended_value = cv_quality
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(cv_quality):
        result.agreement = "vlm_only"
        result.recommended_value = vlm_qualities[0]
        result.recommendation_source = "human_review_required"
        result.explanation = f"VLM suggests {vlm_str} quality but CV is inconclusive."
        return result

    cv_lower = cv_quality.lower().strip()
    vlm_lowers = [q.lower() for q in vlm_qualities]

    if cv_lower in vlm_lowers:
        result.agreement = "confirmed"
        result.confidence_boost = 0.05
        result.recommended_value = cv_quality
        result.recommendation_source = "cv"
        result.explanation = f"VLM ({vlm_str}) agrees with CV ({cv_quality})."
    elif is_bw and cv_lower == "hard" and "soft" in vlm_lowers:
        # ── Narrow, documented exception to CV precedence ──────────────
        # The VL guardrail is that the VLM hints and must not silently
        # outrank strong physical evidence. This is neither silent nor
        # strong evidence: B&W processing measurably inflates apparent
        # shadow edge hardness, so the CV reading is known-degraded in
        # exactly this configuration, and the note says so on the record.
        #
        # Deliberately one-directional. B&W inflates hardness, so it only
        # explains CV-hard-vs-VLM-soft. The reverse conflict — CV soft,
        # VLM hard — has no such explanation and still goes to review.
        result.agreement = "vlm_override"
        result.recommended_value = "soft"
        result.recommendation_source = "vlm"
        result.explanation = (
            f"CV measured {cv_quality} but the image is B&W, which inflates "
            f"apparent shadow edge hardness. Resolving to the VLM reading ({vlm_str})."
        )
        result.notes.append(
            "B&W processing can inflate apparent shadow edge hardness, "
            "making soft light appear hard in CV measurements."
        )
    else:
        result.agreement = "conflicting"
        result.recommended_value = cv_quality
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM expects {vlm_str} but CV measured {cv_quality}."
        )

    return result


def _reconcile_fill_presence(
    vlm_expected: Dict[str, Any],
    cv_fill: str,
) -> VLWDimensionResult:
    """Compare fill presence."""
    vlm_fills = vlm_expected.get("fill_presence", [])
    vlm_str = ", ".join(vlm_fills) if vlm_fills else ""

    result = VLWDimensionResult(
        dimension="fill_presence",
        vlm_value=vlm_str,
        cv_value=cv_fill,
    )

    if not vlm_fills and _is_inconclusive(cv_fill):
        result.agreement = "both_inconclusive"
        result.recommended_value = cv_fill
        result.recommendation_source = "cv"
        return result

    if not vlm_fills:
        result.agreement = "cv_only"
        result.recommended_value = cv_fill
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(cv_fill):
        result.agreement = "vlm_only"
        result.recommended_value = vlm_fills[0]
        result.recommendation_source = "human_review_required"
        result.explanation = f"VLM suggests {vlm_str} fill but CV is inconclusive."
        return result

    # Normalise: "passive bounce" is equivalent to "subtle"
    cv_normalised = cv_fill.lower().strip()
    if cv_normalised == "passive bounce":
        cv_normalised = "subtle"

    if cv_normalised in [f.lower() for f in vlm_fills]:
        result.agreement = "confirmed"
        result.confidence_boost = 0.05
        result.recommended_value = cv_fill
        result.recommendation_source = "cv"
        result.explanation = f"VLM ({vlm_str}) agrees with CV ({cv_fill})."
    else:
        result.agreement = "conflicting"
        result.recommended_value = cv_fill
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM expects {vlm_str} fill but CV measured {cv_fill}."
        )

    return result


def _reconcile_scene_type(
    vlm_description: VLMDescription,
    scene_ctx: SceneContext,
) -> VLWDimensionResult:
    """Compare scene type classification."""
    # Parse VLM background context into a scene type
    vlm_bg = (vlm_description.background_context or "").lower()
    vlm_scene = "unknown"
    _outdoor_tokens = {"outdoor", "outside", "street", "sky", "sunset", "beach", "park", "garden"}
    _env_tokens = {"cafe", "restaurant", "bar", "hotel", "room", "interior", "kitchen", "window"}
    _studio_tokens = {"dark studio", "seamless", "backdrop", "studio", "plain background"}

    if any(tok in vlm_bg for tok in _outdoor_tokens):
        vlm_scene = "outdoor"
    elif any(tok in vlm_bg for tok in _env_tokens):
        vlm_scene = "environmental"
    elif any(tok in vlm_bg for tok in _studio_tokens):
        vlm_scene = "studio_portrait"

    result = VLWDimensionResult(
        dimension="scene_type",
        vlm_value=vlm_scene,
        cv_value=scene_ctx.scene_type,
    )

    if _is_inconclusive(vlm_scene) and _is_inconclusive(scene_ctx.scene_type):
        result.agreement = "both_inconclusive"
        result.recommended_value = scene_ctx.scene_type
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(vlm_scene):
        result.agreement = "cv_only"
        result.recommended_value = scene_ctx.scene_type
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(scene_ctx.scene_type):
        result.agreement = "vlm_only"
        result.recommended_value = vlm_scene
        result.recommendation_source = "human_review_required"
        return result

    if vlm_scene == scene_ctx.scene_type:
        result.agreement = "confirmed"
        result.confidence_boost = 0.03
        result.recommended_value = scene_ctx.scene_type
        result.recommendation_source = "cv"
    else:
        result.agreement = "conflicting"
        result.recommended_value = scene_ctx.scene_type
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM sees {vlm_scene} scene but CV classified as {scene_ctx.scene_type}."
        )

    return result


def _reconcile_mood(
    vlm_description: VLMDescription,
    classification: Optional[Dict[str, Any]],
    vlm_expected: Dict[str, Any],
) -> VLWDimensionResult:
    """Compare mood/intent at the family level."""
    vlm_mood_raw = vlm_description.overall_mood or ""
    vlm_mood_family = _classify_mood_family(vlm_mood_raw)
    # Also consider the expected mood family from the lighting style mapping
    expected_mood_family = vlm_expected.get("mood_family", "")

    cv_mood = ""
    if classification and isinstance(classification, dict):
        cv_mood = classification.get("mood", "") or ""
    cv_mood_family = _classify_mood_family(cv_mood)

    result = VLWDimensionResult(
        dimension="mood",
        vlm_value=vlm_mood_raw or expected_mood_family,
        cv_value=cv_mood,
    )

    if _is_inconclusive(vlm_mood_raw) and not expected_mood_family and _is_inconclusive(cv_mood):
        result.agreement = "both_inconclusive"
        result.recommended_value = cv_mood
        result.recommendation_source = "cv"
        return result

    vlm_family = vlm_mood_family if vlm_mood_family != "unknown" else expected_mood_family
    if not vlm_family or vlm_family == "unknown":
        result.agreement = "cv_only"
        result.recommended_value = cv_mood
        result.recommendation_source = "cv"
        return result

    if _is_inconclusive(cv_mood) or cv_mood_family == "unknown":
        result.agreement = "vlm_only"
        result.recommended_value = vlm_mood_raw
        result.recommendation_source = "human_review_required"
        return result

    if vlm_family == cv_mood_family:
        result.agreement = "confirmed"
        result.confidence_boost = 0.03
        result.recommended_value = cv_mood
        result.recommendation_source = "cv"
    else:
        result.agreement = "conflicting"
        result.recommended_value = cv_mood
        result.recommendation_source = "human_review_required"
        result.explanation = (
            f"VLM mood family ({vlm_family}) differs from CV mood family ({cv_mood_family})."
        )

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Main reconciliation
# ═══════════════════════════════════════════════════════════════════════════


def reconcile_vlw(
    vlm_description: Optional[VLMDescription],
    lighting_read: LightingRead,
    scene_ctx: SceneContext,
    cue_report: VisualCueReport,
    classification: Optional[Dict[str, Any]] = None,
) -> VLWReconciliation:
    """Compare VLM hypothesis against CV evidence across all dimensions.

    Returns a ``VLWReconciliation`` showing per-dimension agreement/conflict
    and recommended values.  Does NOT modify ``lighting_read`` — the caller
    decides whether to apply recommended adjustments.
    """
    if vlm_description is None or not getattr(vlm_description, "ok", False):
        return VLWReconciliation(
            overall_agreement="vlm_unavailable",
            notes=["VLM description not available; reconciliation skipped."],
        )

    vlm_style = (vlm_description.lighting_style or "").strip()
    vlm_expected = _map_vlm_style(vlm_style)

    if not vlm_expected:
        return VLWReconciliation(
            overall_agreement="vlm_unavailable",
            notes=[f"VLM lighting_style '{vlm_style}' not recognised in mapping table."],
        )

    # Detect B&W / high-contrast grade from cue report
    is_bw = False
    is_hcg = False
    tpe = cue_report.tonal_processing_estimation if cue_report else None
    if tpe is not None:
        is_bw = getattr(tpe, "is_bw", False) or False
        is_hcg = getattr(tpe, "is_high_contrast_grade", False) or False

    # Reconcile each dimension
    dimensions: List[VLWDimensionResult] = []

    dimensions.append(_reconcile_pattern(vlm_expected, lighting_read.shadow_pattern))
    dimensions.append(_reconcile_light_count(
        vlm_expected, lighting_read.light_count,
        is_bw=is_bw, is_high_contrast_grade=is_hcg,
    ))
    dimensions.append(_reconcile_source_quality(
        vlm_expected, lighting_read.source_quality,
        is_bw=is_bw, is_high_contrast_grade=is_hcg,
    ))
    dimensions.append(_reconcile_fill_presence(vlm_expected, lighting_read.fill_presence))
    dimensions.append(_reconcile_scene_type(vlm_description, scene_ctx))
    dimensions.append(_reconcile_mood(vlm_description, classification, vlm_expected))

    # Aggregate
    conflict_count = sum(1 for d in dimensions if d.agreement == "conflicting")
    confirmed_count = sum(1 for d in dimensions if d.agreement == "confirmed")
    vlm_only_count = sum(1 for d in dimensions if d.agreement == "vlm_only")
    cv_only_count = sum(1 for d in dimensions if d.agreement == "cv_only")

    # Determine overall agreement
    if conflict_count == 0 and confirmed_count >= 3:
        overall = "strong_agreement"
    elif conflict_count == 0:
        overall = "partial_agreement"
    elif conflict_count <= 2:
        overall = "partial_agreement"
    else:
        overall = "significant_conflict"

    # Human review reasons
    human_review_reasons: List[str] = []
    proposed_adjustments: List[str] = []
    requires_review = conflict_count > 0

    for d in dimensions:
        if d.agreement == "conflicting":
            human_review_reasons.append(
                f"{d.dimension}: VLM expects {d.vlm_value} but CV measured {d.cv_value}."
            )
            if d.vlm_value and d.cv_value:
                proposed_adjustments.append(
                    f"{d.dimension}: {d.cv_value} → {d.vlm_value} (if VLM hypothesis accepted)"
                )
        # Collect B&W notes
        for note in d.notes:
            if note not in human_review_reasons:
                human_review_reasons.append(note)

    # Net confidence delta from confirmed dimensions
    confidence_delta = sum(d.confidence_boost for d in dimensions if d.agreement == "confirmed")

    reconciliation = VLWReconciliation(
        dimensions=dimensions,
        overall_agreement=overall,
        conflict_count=conflict_count,
        confirmed_count=confirmed_count,
        vlm_only_count=vlm_only_count,
        cv_only_count=cv_only_count,
        requires_human_review=requires_review,
        human_review_reasons=human_review_reasons,
        proposed_adjustments=proposed_adjustments,
        confidence_delta=confidence_delta,
        notes=[f"VLM style: {vlm_style}"],
    )

    if conflict_count > 0:
        logger.info(
            "VLW reconciliation: %d conflicts, %d confirmed (VLM style: %s)",
            conflict_count, confirmed_count, vlm_style,
        )

    return reconciliation


def apply_vlm_overrides(
    lighting_read: LightingRead,
    reconciliation: VLWReconciliation,
) -> LightingRead:
    """VLM overrides are disabled — VLM is not authoritative over CV measurements.

    CV physics-based signals (shadow edge hardness, gradient falloff) are the
    authoritative source for source_quality.  VLM is enrichment only.
    Returns lighting_read unchanged.
    """
    return lighting_read


def apply_confirmed_boosts(
    lighting_read: LightingRead,
    reconciliation: VLWReconciliation,
) -> LightingRead:
    """Apply ONLY confidence boosts from confirmed dimensions.

    This is the SAFE application path — it never changes field values,
    only increases ``confidence`` when VLM and CV agree.  Conflicting
    dimensions are left untouched.
    """
    if reconciliation.confidence_delta <= 0:
        return lighting_read

    boosted = deepcopy(lighting_read)
    new_conf = min(0.95, boosted.confidence + reconciliation.confidence_delta)
    boosted.confidence = round(new_conf, 3)
    boosted.notes.append(
        f"VLW: confidence boosted +{reconciliation.confidence_delta:.3f} "
        f"({reconciliation.confirmed_count} confirmed dimensions)"
    )
    return boosted
