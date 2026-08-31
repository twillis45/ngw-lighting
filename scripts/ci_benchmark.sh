#!/usr/bin/env bash
# CI benchmark runner — called by GitHub Actions.
#
# Calls POST /api/lab/benchmarks/ci-run with X-CI-Secret auth,
# writes the JSON result to /tmp/benchmark_result.json,
# and exits with the exit_code returned by the server (0=pass, 1=fail/blocked).
#
# Required env vars:
#   CI_BENCHMARK_SECRET  — must match server-side CI_BENCHMARK_SECRET
#   NGW_BASE_URL         — e.g. https://api.noguesswork.com
#
# Optional env vars:
#   CI_COMMIT_SHA, CI_PR_NUMBER, CI_BRANCH, CI_REPO

set -euo pipefail

BASE_URL="${NGW_BASE_URL:-http://localhost:8000}"
RESULT_FILE="${BENCHMARK_RESULT_FILE:-/tmp/benchmark_result.json}"
ENDPOINT="${BASE_URL}/api/lab/benchmarks/ci-run"

if [[ -z "${CI_BENCHMARK_SECRET:-}" ]]; then
  echo "❌ CI_BENCHMARK_SECRET is not set. Aborting." >&2
  exit 1
fi

# Build JSON payload
PAYLOAD=$(python3 - <<EOF
import json, os
print(json.dumps({
    "commit_sha": os.environ.get("CI_COMMIT_SHA"),
    "pr_number":  int(os.environ["CI_PR_NUMBER"]) if os.environ.get("CI_PR_NUMBER") else None,
    "branch":     os.environ.get("CI_BRANCH"),
    "repo":       os.environ.get("CI_REPO"),
    "notes":      os.environ.get("CI_NOTES"),
}))
EOF
)

echo "▶ Calling ${ENDPOINT} ..."
HTTP_CODE=$(curl -s -o "${RESULT_FILE}" -w "%{http_code}" \
  -X POST "${ENDPOINT}" \
  -H "X-CI-Secret: ${CI_BENCHMARK_SECRET}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")

if [[ "${HTTP_CODE}" -ge 500 ]]; then
  echo "❌ Server error (HTTP ${HTTP_CODE}). Check server logs." >&2
  cat "${RESULT_FILE}" >&2
  exit 1
fi

if [[ "${HTTP_CODE}" -ge 400 ]]; then
  echo "❌ Request error (HTTP ${HTTP_CODE}):" >&2
  cat "${RESULT_FILE}" >&2
  exit 1
fi

# Extract exit_code from JSON response
EXIT_CODE=$(python3 -c "import json,sys; d=json.load(open('${RESULT_FILE}')); print(d.get('exit_code', 0))")

# Pretty-print summary
python3 - "${RESULT_FILE}" <<'SUMMARY'
import json, sys

result_file = sys.argv[1]
with open(result_file) as f:
    r = json.load(f)

status = r.get("status", "unknown")
score  = r.get("overall_score")
ec     = r.get("exit_code", 0)

# A run that measured NOTHING must not print PASSED. Found 2026-08-31, the
# first time this script ever reached a live server: with the secret finally
# configured it authenticated, ran, found zero benchmark cases in production,
# and printed "✅ Benchmark PASSED | status=no_cases". Same disease as the
# green CI on 46 empty runs and the comparator that returned safe_to_merge
# with no baseline — a verdict about work that never happened.
MEASURED_NOTHING = {"no_cases", "no_baseline", "skipped", "unknown"}

if status in MEASURED_NOTHING:
    print(f"⚠️   Benchmark MEASURED NOTHING  |  status={status}")
    print(f"    {r.get('message', '')}")
    print("    This is NOT a pass. Nothing was evaluated.")
elif ec == 0:
    print(f"✅  Benchmark PASSED  |  status={status}  |  score={score:.3f}" if score is not None else f"✅  Benchmark PASSED  |  status={status}")
else:
    print(f"❌  Benchmark BLOCKED  |  status={status}  |  score={score:.3f}" if score is not None else f"❌  Benchmark BLOCKED  |  status={status}")

regressions = r.get("regressions", [])
if regressions:
    print(f"\nRegressions ({len(regressions)}):")
    for reg in regressions[:5]:
        print(f"  • {reg.get('type','?')}: {reg.get('pattern_id','overall')}  Δ{reg.get('delta', 0)*100:+.1f}%")

insights = r.get("insights", [])
if insights:
    print("\nInsights:")
    for ins in insights[:4]:
        print(f"  • {ins}")
SUMMARY

exit "${EXIT_CODE}"
