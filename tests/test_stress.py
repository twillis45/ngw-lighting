"""Stress tests for engine scaling, concurrent API load, and memory profiling.

Run with: .venv/bin/python -m pytest -m stress -v
"""
import copy
import json
import random
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.selector import select_best_system
from main import app

SYSTEMS_PATH = Path("data/lighting_systems.json")

pytestmark = pytest.mark.stress


def _load_real_systems():
    with open(SYSTEMS_PATH, encoding="utf-8") as f:
        return json.load(f)["systems"]


def _make_synthetic_systems(base_systems, target_count):
    """Clone base systems with randomized criteria to reach target_count."""
    synthetic = []
    rng = random.Random(42)
    for i in range(target_count):
        template = base_systems[i % len(base_systems)]
        s = copy.deepcopy(template)
        s["id"] = f"synth_{i:04d}"
        s["name"] = f"Synthetic System {i}"
        # Randomize criteria +-20%
        for key in s.get("criteria", {}):
            original = s["criteria"][key]
            if isinstance(original, (int, float)):
                factor = 0.8 + rng.random() * 0.4  # 0.8 to 1.2
                s["criteria"][key] = round(original * factor, 2)
        synthetic.append(s)
    return synthetic


def _strip_to_engine_fields(systems):
    """Keep only fields the scoring engine needs."""
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


# ── Engine Scaling ────────────────────────────────────────

class TestEngineScaling:
    def test_100_systems(self):
        base = _load_real_systems()
        systems = _strip_to_engine_fields(_make_synthetic_systems(base, 100))
        t0 = time.perf_counter()
        outcome = select_best_system(systems)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  100 systems: {elapsed:.1f}ms")
        assert elapsed < 500
        assert outcome.total_candidates == 100

    def test_500_systems(self):
        base = _load_real_systems()
        systems = _strip_to_engine_fields(_make_synthetic_systems(base, 500))
        t0 = time.perf_counter()
        outcome = select_best_system(systems)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  500 systems: {elapsed:.1f}ms")
        assert elapsed < 1000
        assert outcome.total_candidates == 500

    def test_1000_systems(self):
        base = _load_real_systems()
        systems = _strip_to_engine_fields(_make_synthetic_systems(base, 1000))
        t0 = time.perf_counter()
        outcome = select_best_system(systems)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  1000 systems: {elapsed:.1f}ms")
        assert elapsed < 2000
        assert outcome.total_candidates == 1000

    def test_3000_systems(self):
        base = _load_real_systems()
        systems = _strip_to_engine_fields(_make_synthetic_systems(base, 3000))
        t0 = time.perf_counter()
        outcome = select_best_system(systems)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  3000 systems: {elapsed:.1f}ms")
        assert elapsed < 10000
        assert outcome.total_candidates == 3000


# ── Concurrent API Load ──────────────────────────────────

class TestConcurrentLoad:
    def test_20_concurrent_shoot_match(self):
        client = TestClient(app)
        payload = {
            "subject": "headshot",
            "mood": "Clean & Classic",
            "environment": "Medium Studio",
            "ceiling": "normal",
            "gearMode": "anyGear",
            "gear": [],
        }

        results = []
        errors = []

        def make_request(_):
            t0 = time.perf_counter()
            try:
                resp = client.post("/api/shoot-match", json=payload)
                elapsed = (time.perf_counter() - t0) * 1000
                return {"status": resp.status_code, "elapsed_ms": elapsed}
            except Exception as e:
                return {"status": 500, "elapsed_ms": 0, "error": str(e)}

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(make_request, i) for i in range(20)]
            for f in as_completed(futures):
                results.append(f.result())

        statuses = [r["status"] for r in results]
        times = [r["elapsed_ms"] for r in results]
        times.sort()

        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        max_time = times[-1]

        print(f"\n  20 concurrent requests:")
        print(f"    All 200: {all(s == 200 for s in statuses)}")
        print(f"    p50: {p50:.0f}ms, p95: {p95:.0f}ms, max: {max_time:.0f}ms")

        assert all(s == 200 for s in statuses), f"Some requests failed: {statuses}"
        assert p95 < 2000, f"p95 too slow: {p95:.0f}ms"

    def test_20_concurrent_recommend(self):
        client = TestClient(app)
        payload = {
            "systems": [
                {
                    "id": f"conc-{i}",
                    "name": f"Concurrent System {i}",
                    "criteria": {"brightness": 5000 + i * 100, "color_accuracy": 90},
                    "features": {"dimmable": True},
                }
                for i in range(5)
            ],
            # session_id has been REQUIRED since 2026-03-25 (SESSION_ID_REQUIRED,
            # commit d9afd90). This test was last touched 2026-03-13, twelve days
            # earlier, and has returned 400 ever since — five months of a red
            # test nobody saw, because the suite was never run clean.
            "metadata": {"session_id": "pytest-benchmark-session"},
        }

        results = []

        def make_request(_):
            t0 = time.perf_counter()
            resp = client.post("/recommend", json=payload)
            elapsed = (time.perf_counter() - t0) * 1000
            return {"status": resp.status_code, "elapsed_ms": elapsed}

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(make_request, i) for i in range(20)]
            for f in as_completed(futures):
                results.append(f.result())

        statuses = [r["status"] for r in results]
        times = sorted(r["elapsed_ms"] for r in results)
        p95 = times[int(len(times) * 0.95)]

        print(f"\n  20 concurrent /recommend: p95={p95:.0f}ms")
        assert all(s == 200 for s in statuses)
        assert p95 < 1000


# ── Memory Profiling ──────────────────────────────────────

class TestMemoryProfile:
    def test_memory_1000_systems(self):
        base = _load_real_systems()
        systems = _strip_to_engine_fields(_make_synthetic_systems(base, 1000))

        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        outcome = select_best_system(systems)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        peak_delta_mb = sum(s.size_diff for s in stats) / (1024 * 1024)

        print(f"\n  1000 systems memory delta: {peak_delta_mb:.2f} MB")
        assert peak_delta_mb < 50, f"Memory usage too high: {peak_delta_mb:.2f} MB"
