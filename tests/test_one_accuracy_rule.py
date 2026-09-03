"""The number a buyer reads and the number engineering defends use ONE rule.

Review-board condition C5, 2026-09-03. There were two scorers:

    tests/test_corpus_accuracy_gate.py  filtered "unknown" out of
        acceptable_patterns, then tested equality against expected_pattern
        first and UNFILTERED -- defeating its own docstring
    api/routes/gallery.py               applied no "unknown" filter at all

So the engineering floor (17/33) and the public proof page (15/30) came from
different rules over different corpora, and nothing asserted they described the
same engine. The denominators still differ, legitimately -- the gallery shows
approved entries, the gate runs the whole corpus -- so what is asserted here is
that the RULE is one rule, and that both sides exclude the same things.
"""
import re
from pathlib import Path

import pytest

from engine.pattern_scoring import REFUSAL, is_acceptable, is_exact, is_scoreable


class TestBothSidesDelegate:
    """Neither may carry its own scoring logic. This is a source check on
    purpose: a behavioural check would pass while a private copy drifted."""

    @pytest.mark.parametrize("path", [
        "api/routes/gallery.py",
        "tests/test_corpus_accuracy_gate.py",
    ])
    def test_imports_the_shared_scorer(self, path):
        src = Path(path).read_text()
        assert "engine.pattern_scoring" in src, (
            f"{path} does not use the shared scorer; it has its own opinion "
            f"about what counts as a hit"
        )

    @pytest.mark.parametrize("path", [
        "api/routes/gallery.py",
        "tests/test_corpus_accuracy_gate.py",
    ])
    def test_does_not_reimplement_the_unknown_filter(self, path):
        """The exact line that produced two rules: a local list comprehension
        stripping 'unknown' out of acceptable_patterns."""
        src = Path(path).read_text()
        # Only flag a line that ASSIGNS the filtered list -- that is scoring
        # logic. An f-string mentioning the same filter inside an assertion
        # MESSAGE is not, and my first version of this test failed on exactly
        # that line in the corpus gate: a false positive in the detector, not a
        # defect in the code.
        offenders = [
            ln for ln in src.splitlines()
            if 'acceptable_patterns' in ln
            and '!=' in ln and 'unknown' in ln
            and not ln.strip().startswith("#")
            and 'f"' not in ln and "f'" not in ln
            and re.match(r"\s*\w+\s*=\s*\[", ln)
        ]
        assert not offenders, f"{path} filters 'unknown' locally:\n  " + "\n  ".join(offenders)


class TestTheRuleItself:
    def test_a_refusal_never_scores_even_when_truth_is_unknown(self):
        """THE defect. data/reference_dataset/unknown/mixed_light_failure has
        expected_pattern 'unknown', so an engine that declined scored BOTH
        acceptable and exact -- a point for refusing to read the photograph."""
        gt = {"expected_pattern": REFUSAL,
              "acceptable_patterns": [REFUSAL, "flat", "rembrandt", "loop", "split"]}
        assert not is_exact(REFUSAL, gt)
        assert not is_acceptable(REFUSAL, gt)

    def test_a_refusal_never_scores_on_a_normal_entry_either(self):
        gt = {"expected_pattern": "loop", "acceptable_patterns": ["loop", "butterfly"]}
        assert not is_exact(REFUSAL, gt)
        assert not is_acceptable(REFUSAL, gt)

    def test_an_unknown_truth_entry_is_not_scoreable(self):
        """It lists four common patterns as acceptable, so it passes on almost
        any answer. It measures nothing and belongs in neither side."""
        assert not is_scoreable({"expected_pattern": REFUSAL,
                                 "acceptable_patterns": [REFUSAL, "flat", "loop"]})
        assert is_scoreable({"expected_pattern": "loop", "acceptable_patterns": ["loop"]})

    def test_real_answers_still_score_normally(self):
        gt = {"expected_pattern": "loop", "acceptable_patterns": ["loop", "butterfly"]}
        assert is_exact("loop", gt) and is_acceptable("loop", gt)
        assert not is_exact("butterfly", gt) and is_acceptable("butterfly", gt)
        assert not is_acceptable("split", gt)


class TestTheGalleryExcludesWhatTheGateExcludes:
    def test_gallery_reports_a_scoreable_flag(self):
        """Without it the route cannot keep unscoreable entries out of the
        ratio, which is how a free hit reached the public proof page."""
        src = Path("api/routes/gallery.py").read_text()
        assert '"scoreable"' in src
        # Read the whole statement with balanced brackets. Splitting on the
        # first "]" lands inside i["verdict"] and proves nothing -- which is
        # what my first version of this test did.
        after = src.split("scored = [", 1)[1]
        depth, stmt = 1, []
        for ch in after:
            if ch == "[": depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0: break
            stmt.append(ch)
        assert "scoreable" in "".join(stmt), \
            "the scored list does not filter on scoreable, so an entry with no "\
            "correct answer still counts toward the public ratio"
