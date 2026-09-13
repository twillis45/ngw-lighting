"""Two defects found 9/13/2026, and the tests that would have caught them.

Both were about a dependency, and neither produced a wrong lighting
recommendation. They are worth a test file anyway, because both made the
engine say something false about the USER'S IMAGE when the fault was ours.

  1. cv2 and mediapipe were imported in one try block, so a missing mediapipe
     set cv2 to None too. Four helpers that use cv2 and never touch mediapipe
     stopped working on a machine that had everything they needed.

  2. _image_detail abstained by returning 0.0 — inside its own output range,
     at the end that means "no structure at all". The decline floor read that
     and logged "no image structure" for a photograph it had never measured.
"""
import importlib
import sys

import pytest


def test_cv2_is_not_disabled_by_a_missing_mediapipe(monkeypatch):
    """Defect 1. cv2 must survive mediapipe failing to import.

    Simulated at the import machinery rather than by uninstalling anything:
    mediapipe is made to raise on import, the module is reloaded, and cv2 must
    still be bound. With the original single try block this fails — cv2 comes
    back None purely because the next line threw.
    """
    real_import = importlib.__import__

    def no_mediapipe(name, *args, **kwargs):
        if name == "mediapipe" or name.startswith("mediapipe."):
            raise ImportError("simulated: mediapipe unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_mediapipe)
    sys.modules.pop("engine.vision_pipeline", None)
    try:
        vp = importlib.import_module("engine.vision_pipeline")
        assert vp.mp is None, "the simulation did not take — mediapipe still imported"
        assert vp.cv2 is not None, (
            "cv2 was set to None because MEDIAPIPE failed to import. They are "
            "separate dependencies and four helpers here use cv2 alone.")
    finally:
        monkeypatch.undo()
        sys.modules.pop("engine.vision_pipeline", None)
        importlib.import_module("engine.vision_pipeline")


def test_image_detail_abstains_outside_its_own_value_range():
    """Defect 2. A failure must not be reportable as a measurement.

    0.0 is a legitimate output of a Laplacian variance — a perfectly flat
    frame. Using it for "could not measure" makes the two indistinguishable,
    and the decline floor downstream cannot tell them apart either.
    """
    from engine.vision_pipeline import _image_detail

    got = _image_detail(None)  # nothing decodable; the metric must abstain
    assert got is None, (
        f"_image_detail abstained with {got!r}. Any number here is a value the "
        f"metric could legitimately measure, so callers cannot distinguish "
        f"a failure from a reading. Return None.")


def test_a_real_frame_still_measures():
    """The abstention must not have swallowed the working path too."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from engine.vision_pipeline import _image_detail

    # Deterministic structure: a checkerboard has plenty of edges.
    img = np.zeros((120, 120, 3), dtype=np.uint8)
    img[::8] = 255
    img[:, ::8] = 255
    got = _image_detail(img)
    assert got is not None and got > 0, (
        f"a frame with obvious structure measured {got!r}")


def test_unmeasurable_detail_declines_with_a_truthful_reason():
    """Defect 2, downstream. The decline is right; the REASON must be true.

    Asserted on the source strings rather than by driving a full analysis,
    which needs mediapipe, a model download and a corpus image. What matters
    is that the two causes are distinguishable in the payload at all — before
    this, an unmeasurable image was reported as `decline:no_structure`, which
    is a claim about the photograph.
    """
    import inspect

    from engine import orchestrator

    src = inspect.getsource(orchestrator)
    assert "decline:detail_unmeasurable" in src, (
        "there is no distinct source for an unmeasurable image; a missing "
        "instrument is being reported as a property of the photograph")
    assert "decline:no_structure" in src, "the real no-structure decline went missing"
