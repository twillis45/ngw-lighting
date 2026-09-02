"""Performance regression baselines.

Run with: .venv/bin/python -m pytest -m benchmark -v -s
"""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.diagram import build_diagram
from engine.scoring import score_system
from engine.selector import select_best_system
from main import app

SYSTEMS_PATH = Path("data/lighting_systems.json")

pytestmark = pytest.mark.benchmark


def _load_real_systems():
    with open(SYSTEMS_PATH, encoding="utf-8") as f:
        return json.load(f)["systems"]


def _strip_to_engine(systems):
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "criteria": s["criteria"],
            "features": s["features"],
            "taxonomy_refs": s.get("taxonomy_refs", {}),
            "modifier": s.get("modifier"),
        }
        for s in systems
    ]


# ── Scoring Throughput ────────────────────────────────────

class TestScoringThroughput:
    def test_score_30_systems(self):
        systems = _strip_to_engine(_load_real_systems())
        iterations = 100

        t0 = time.perf_counter()
        for _ in range(iterations):
            for s in systems:
                score_system(s)
        elapsed = time.perf_counter() - t0

        total_ops = iterations * len(systems)
        ops_per_sec = total_ops / elapsed
        per_op_us = (elapsed / total_ops) * 1_000_000

        print(f"\n  Scoring throughput: {ops_per_sec:.0f} ops/sec ({per_op_us:.1f} us/op)")
        print(f"    {total_ops} scores in {elapsed:.3f}s")
        assert per_op_us < 1000, f"Scoring too slow: {per_op_us:.1f} us/op"


# ── Selection Throughput ──────────────────────────────────

class TestSelectionThroughput:
    def test_select_30_systems(self):
        systems = _strip_to_engine(_load_real_systems())
        iterations = 50

        t0 = time.perf_counter()
        for _ in range(iterations):
            select_best_system(systems)
        elapsed = time.perf_counter() - t0

        per_call_ms = (elapsed / iterations) * 1000
        print(f"\n  Selection (30 systems): {per_call_ms:.1f}ms/call ({iterations} iterations)")
        assert per_call_ms < 100, f"Selection too slow: {per_call_ms:.1f}ms"


# ── API Round-Trip ────────────────────────────────────────

class TestAPIRoundTrip:
    def test_recommend_roundtrip(self):
        client = TestClient(app)
        payload = {
            "systems": [
                {
                    "id": f"bench-{i}",
                    "name": f"Benchmark System {i}",
                    "criteria": {"brightness": 5000 + i * 500, "color_accuracy": 90 + i},
                    "features": {"dimmable": True},
                }
                for i in range(5)
            ],
            # session_id has been REQUIRED since 2026-03-25 (SESSION_ID_REQUIRED,
            # commit d9afd90). This test was last touched 2026-03-13, twelve days
            # earlier, and has returned 400 ever since — five months of a red
            # test nobody saw, because the suite was never run clean.
            "metadata": {"session_id": "pytest-benchmark-session"},  # replaced per call below
        }
        iterations = 20

        # A FRESH session_id per call. This measures round-trip latency, not
        # the free-tier quota — and since 2026-09-02 /recommend counts
        # server-side, so 21 calls on one session legitimately hit the paywall
        # at the 4th. Rotating the id keeps the test measuring what it is for.
        import uuid as _uuid

        def _fresh():
            p = dict(payload)
            p["metadata"] = {"session_id": f"bench-{_uuid.uuid4().hex}"}
            return p

        # Warmup
        client.post("/recommend", json=_fresh())

        t0 = time.perf_counter()
        for _ in range(iterations):
            resp = client.post("/recommend", json=_fresh())
            assert resp.status_code == 200
        elapsed = time.perf_counter() - t0

        per_call_ms = (elapsed / iterations) * 1000
        print(f"\n  /recommend round-trip (5 systems): {per_call_ms:.1f}ms/call")
        assert per_call_ms < 200, f"API too slow: {per_call_ms:.1f}ms"

    def test_shoot_match_roundtrip(self):
        client = TestClient(app)
        payload = {
            "subject": "headshot",
            "mood": "Clean & Classic",
            "environment": "Medium Studio",
            "ceiling": "normal",
            "gearMode": "anyGear",
            "gear": [],
        }
        iterations = 20

        # Warmup
        client.post("/api/shoot-match", json=payload)

        t0 = time.perf_counter()
        for _ in range(iterations):
            resp = client.post("/api/shoot-match", json=payload)
            assert resp.status_code == 200
        elapsed = time.perf_counter() - t0

        per_call_ms = (elapsed / iterations) * 1000
        print(f"\n  /api/shoot-match round-trip: {per_call_ms:.1f}ms/call")
        assert per_call_ms < 500, f"Shoot-match too slow: {per_call_ms:.1f}ms"


# ── System Loading ────────────────────────────────────────

class TestSystemLoading:
    def test_cold_load(self):
        iterations = 50

        t0 = time.perf_counter()
        for _ in range(iterations):
            with open(SYSTEMS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data["systems"]) >= 30
        elapsed = time.perf_counter() - t0

        per_load_ms = (elapsed / iterations) * 1000
        print(f"\n  System file load: {per_load_ms:.2f}ms/load ({iterations} iterations)")
        assert per_load_ms < 50, f"Loading too slow: {per_load_ms:.2f}ms"


# ── Diagram Generation ───────────────────────────────────

class TestDiagramGeneration:
    def test_diagram_10_systems(self):
        systems = _load_real_systems()[:10]

        t0 = time.perf_counter()
        for s in systems:
            build_diagram(s)
        elapsed = time.perf_counter() - t0

        per_diagram_ms = (elapsed / len(systems)) * 1000
        print(f"\n  Diagram generation: {per_diagram_ms:.2f}ms/diagram (10 systems)")
        assert per_diagram_ms < 50, f"Diagram gen too slow: {per_diagram_ms:.2f}ms"

    def test_diagram_all_systems(self):
        systems = _load_real_systems()

        t0 = time.perf_counter()
        for s in systems:
            build_diagram(s)
        elapsed = time.perf_counter() - t0

        per_diagram_ms = (elapsed / len(systems)) * 1000
        total_ms = elapsed * 1000
        print(f"\n  All {len(systems)} diagrams: {total_ms:.1f}ms total, {per_diagram_ms:.2f}ms/diagram")
        assert per_diagram_ms < 100, f"Diagram gen too slow: {per_diagram_ms:.2f}ms"
