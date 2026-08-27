"""Tests for the public accuracy gallery.

The gallery exists so a prospective buyer can audit the product's central
claim before paying. Two things must therefore hold: it must be reachable
without an account, and it must not overstate accuracy.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_gallery_is_public():
    """No account required. An oracle nobody can audit is worth nothing."""
    resp = client.get("/api/gallery")
    assert resp.status_code == 200, resp.text


def test_gallery_reports_misses_not_just_hits():
    """A gallery of only hits is indistinguishable from cherry-picking."""
    d = client.get("/api/gallery").json()
    assert "misses" in d and "hits" in d
    assert d["scored"] == d["hits"] + d["misses"]


def test_accuracy_note_carries_its_denominator():
    """A hit count without its total is a marketing number, not a measurement."""
    d = client.get("/api/gallery").json()
    note = d["accuracy_note"]
    if d["scored"]:
        assert str(d["scored"]) in note, "denominator missing from the accuracy note"
        assert str(d["exact"]) in note, "exact count missing — hits alone overstate"


def test_exact_never_exceeds_hits():
    """`exact` is the stricter measure and must be a subset of `hits`."""
    d = client.get("/api/gallery").json()
    assert d["exact"] <= d["hits"]


def test_unscored_entries_are_not_counted_as_passes():
    """An absent result is a hypothesis, not a passing one."""
    d = client.get("/api/gallery").json()
    unscored = [e for e in d["entries"] if e["verdict"]["match"] is None]
    assert d["count"] - d["scored"] == len(unscored)
    for e in unscored:
        assert e["verdict"]["read"] is None


def test_only_approved_entries_are_served():
    """An unreviewed entry is not evidence, and this page exists to be evidence."""
    import json, os, glob
    served = {e["id"] for e in client.get("/api/gallery").json()["entries"]}
    for d in glob.glob("data/reference_dataset/*/*"):
        meta_p = os.path.join(d, "metadata.json")
        if not os.path.exists(meta_p):
            continue
        meta = json.load(open(meta_p))
        if meta.get("approval_status") != "approved":
            assert meta.get("reference_id") not in served, (
                f"unapproved entry {meta.get('reference_id')} is being served"
            )


def test_thumbnail_404s_for_an_unknown_entry():
    assert client.get("/api/gallery/not-a-real-entry/thumbnail").status_code == 404


def test_gallery_scores_the_engines_resolved_read_not_a_single_pass():
    """The gallery is the public accuracy claim. It must score what the engine
    actually answers.

    signals.light_structure.pattern_name is ONE of 30 vision passes. Scoring it
    reported 2/29 exact while the engine resolves 17/34 exact -- understating
    the product by ~7x on the page whose entire job is proving it works.
    """
    from api.routes.gallery import list_gallery

    payload = list_gallery()
    scored = [e for e in payload["entries"] if e["verdict"]["match"] is not None]
    assert scored, "no scored entries -- resolved reads missing"

    # rembrandt_classic: engine resolves 'rembrandt'; the light_structure pass
    # alone says 'loop'. The gallery must report the former.
    entry = next((e for e in payload["entries"]
                  if "rembrandt_classic" in str(e["id"])), None)
    if entry is not None:
        assert entry["verdict"]["read"] == "rembrandt", (
            f"gallery reported {entry['verdict']['read']!r}; the engine resolves "
            "'rembrandt' -- the verdict is reading a single pass, not the answer")

    exact = sum(1 for e in scored if e["verdict"].get("exact"))
    assert exact >= 10, (
        f"only {exact}/{len(scored)} exact; the engine resolves 17/34. "
        "The gallery is scoring the wrong field and understating the product.")
