"""A blocking call inside an `async def` route freezes the whole API.

Found 2026-08-31. Two routes ran full benchmark suites synchronously inside
`async def` handlers, so the work executed ON the event loop and every other
request — health checks, logins, analyses — waited for it.

Measured against a REAL uvicorn server (a TestClient probe does NOT reproduce
this: it gives each request its own portal, so it never exercises the shared
loop, and my first attempt reported a clean 3 ms for the broken version):

    direct call        concurrent /ping took 2.005 s
    run_in_threadpool  concurrent /ping took 0.009 s

A ci-run with ZERO cases already takes 40.7 s — that is the fixed cost of
engine startup. With the 30 gold-set cases it is minutes of total API freeze,
and the drift-check is triggered from the Lab UI, so the person who froze the
service is sitting there watching it not respond.

This test is structural rather than behavioural: spinning up a server per case
is slow and flaky, and the thing that actually matters is whether the heavy
call is awaited off the loop.
"""
import inspect
import re

import pytest

import api.routes.lab_benchmarks as bench

# Functions that run a full benchmark. Each takes tens of seconds at minimum.
HEAVY = ("run_ci_benchmark", "run_nightly_check", "run_benchmark")


def _async_route_bodies(module):
    src = inspect.getsource(module)
    # Each `async def name(...):` up to the next top-level def/@router.
    for m in re.finditer(r"\nasync def (\w+)\(.*?(?=\n(?:@|async def |def ))", src, re.S):
        yield m.group(1), m.group(0)


def test_no_async_route_calls_a_benchmark_synchronously():
    offenders = []
    for name, body in _async_route_bodies(bench):
        code = "\n".join(l.split("#", 1)[0] for l in body.splitlines())
        for fn in HEAVY:
            for call in re.finditer(rf"\b{fn}\s*\(", code):
                before = code[max(0, call.start() - 60):call.start()]
                if "run_in_threadpool" in before or "to_thread" in before:
                    continue
                offenders.append(f"{name}() calls {fn}() directly")
    assert not offenders, (
        "these block the event loop for the whole run, freezing every other "
        f"request: {offenders}")


def test_the_heavy_routes_actually_await_something():
    """Guard the guard: if the route stopped being async, or the call vanished,
    the test above would pass while asserting nothing."""
    src = inspect.getsource(bench)
    assert src.count("run_in_threadpool(") >= 2, (
        "expected both heavy routes to hand off to a threadpool; found "
        f"{src.count('run_in_threadpool(')}")
