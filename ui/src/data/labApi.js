/**
 * Lab API client — mirrors authApi.js patterns.
 * All endpoints require dev-level auth (JWT + email whitelist).
 */

import { getToken } from './authApi';
import { apiFetch } from '../lib/apiClient';

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function labFetch(path, options = {}) {
  const headers = { ...authHeaders(), ...options.headers };
  // Don't set Content-Type for FormData (browser sets it with boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await apiFetch(`/api/lab${path}`, { headers, ...options });
  const raw = await res.text().catch(() => '');
  const data = raw ? (() => { try { return JSON.parse(raw); } catch { return null; } })() : null;
  if (!res.ok) {
    // FastAPI validation errors return detail as an array of {loc, msg, type} objects
    let msg;
    if (data && Array.isArray(data.detail)) {
      msg = data.detail.map(e => `${e.loc?.slice(-1)[0] ?? 'field'}: ${e.msg}`).join('; ');
    } else {
      msg = data?.detail || `Lab API error (${res.status})`;
    }
    throw new Error(`[${res.status}] ${msg}`);
  }
  if (data === null) throw new Error(`Server returned empty response (${res.status})`);
  return data;
}

/** Fetch from top-level /api routes (intelligence, paywall, etc — not under /api/lab). */
async function coreFetch(path, options = {}) {
  const headers = { ...authHeaders(), ...options.headers };
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await apiFetch(`/api${path}`, { headers, ...options });
  const raw = await res.text().catch(() => '');
  const data = raw ? (() => { try { return JSON.parse(raw); } catch { return null; } })() : null;
  if (!res.ok) {
    let msg;
    if (data && Array.isArray(data.detail)) {
      msg = data.detail.map(e => `${e.loc?.slice(-1)[0] ?? 'field'}: ${e.msg}`).join('; ');
    } else {
      msg = data?.detail || `API error (${res.status})`;
    }
    throw new Error(`[${res.status}] ${msg}`);
  }
  return data;
}

/**
 * Fetch a binary resource (image) from a lab endpoint with auth headers.
 * Returns a blob URL suitable for use in <img src>.
 * Caller is responsible for revoking the URL via URL.revokeObjectURL when done.
 */
export async function labFetchBlob(path) {
  const headers = authHeaders();
  const res = await apiFetch(`/api/lab${path}`, { headers });
  if (!res.ok) throw new Error(`Lab image fetch failed (${res.status})`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}


// ── Status ───────────────────────────────────────────────

export async function checkLabAccess() {
  return labFetch('/status');
}

/**
 * Probe the server to see if the current user is a whitelisted dev.
 * If so, auto-enable the Lab feature flag — no console needed.
 * Safe to call anytime; silently no-ops if not authorized.
 */
export async function probeAndEnableLab() {
  try {
    const { setFlag } = await import('../modes/featureFlags');
    await labFetch('/status');
    // 200 means user is on the whitelist
    setFlag('enable_lab', true);
    return true;
  } catch (err) {
    // 401/403 or network error — not a dev, leave flag as-is
    console.warn('[Lab] probe failed:', err.message);
    return false;
  }
}


// ── Workbench ────────────────────────────────────────────

/**
 * Fetch a remote image URL server-side to bypass CORS (Dropbox, Google Drive, etc).
 * Returns a Blob the caller can turn into a File for the analyze flow.
 */
export async function fetchImageFromUrl(url) {
  const form = new FormData();
  form.append('url', url);
  const res = await apiFetch('/api/lab/fetch-image-url', {
    method: 'POST',
    body: form,
    headers: authHeaders(),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || `Couldn't fetch image (${res.status})`);
  }
  return res.blob();
}

export async function analyzeImage(file, { debug = false, signal } = {}) {
  const form = new FormData();
  form.append('image', file);
  const params = new URLSearchParams();
  if (debug) params.set('debug', 'true');
  // Respect user settings for analysis behavior
  try {
    const s = JSON.parse(localStorage.getItem('ngw_settings') || '{}');
    if (s.imageHandling === 'delete') params.set('delete_after', 'true');
    if (s.patternSensitivity && s.patternSensitivity !== 'balanced') {
      params.set('sensitivity', s.patternSensitivity);
    }
  } catch { /* proceed without */ }
  const query = params.toString() ? `?${params}` : '';
  // /api/analyze — customer-facing, NOT /api/lab. Same handler, different mount.
  return coreFetch(`/analyze${query}`, { method: 'POST', body: form, signal });
}

/** Cancel an in-flight analysis by id. */
export async function cancelAnalysis(analysisId) {
  return coreFetch(`/analyze/cancel/${analysisId}`, { method: 'POST' });
}


// ── Shoot Match ──────────────────────────────────────────
// Recommend a full lighting setup from wizard inputs (mood, environment, gear,
// gearMode, optional skinTone / masterMode / priorAnalysis).  Returns a
// `cards` dict assembled by engine.services.shoot_match_service._build_cards
// with bestMatch, shootThisSetup, spaceCheck, whyThisWorks, whatToLookFor,
// quickFixes, substitutions, otherSetups, cameraSettings and diagram.
//
// Route is /api/shoot-match (not /api/lab/...) so it goes through coreFetch.

export async function shootMatch(payload, { signal } = {}) {
  return coreFetch('/shoot-match', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

/**
 * Regenerate a debug overlay with a specific subset of layers.
 * @param {string} overlayUrl  - Existing overlay URL, e.g. "/static/debug/overlay_foo_abc.jpg"
 * @param {string[]} layers    - Layer names to include. Empty = all layers.
 *   Valid: shadow, highlights, catchlights, background, pose,
 *          specular, surface, light_roles, summary
 * @returns {Promise<{debug_overlay_url: string}>}
 */
export async function regenerateDebugOverlay(overlayUrl, layers = []) {
  return labFetch('/debug-overlay/regenerate', {
    method: 'POST',
    body: JSON.stringify({ overlay_url: overlayUrl, layers }),
  });
}


// ── Gold Set ─────────────────────────────────────────────

export async function listGoldSet(status = null, limit = 50) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));
  return labFetch(`/gold-set?${params}`);
}

export async function getGoldSetEntry(entryId) {
  return labFetch(`/gold-set/${entryId}`);
}

export async function getGoldSetImageUrl(entryId) {
  return labFetchBlob(`/gold-set/${entryId}/image`);
}

export async function createGoldSetEntry(data) {
  return labFetch('/gold-set', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateGoldSetEntry(entryId, data) {
  return labFetch(`/gold-set/${entryId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteGoldSetEntry(entryId) {
  return labFetch(`/gold-set/${entryId}`, { method: 'DELETE' });
}

export async function evaluateGoldSet(limit = 50) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  return labFetch(`/gold-set/evaluate?${params}`, { method: 'POST' });
}

/**
 * Bulk-seed the Gold Set from reference dataset entries.
 * @param {Object} opts
 * @param {string} [opts.tier='gold']       - dataset_tier to import
 * @param {string} [opts.patternId]         - limit to one pattern (optional)
 * @param {boolean} [opts.dryRun=false]     - preview without writing
 */
export async function seedGoldSetFromReference({ tier = 'gold', patternId = null, imagePaths = null, force = false, dryRun = false } = {}) {
  return labFetch('/learning/gold-set/seed-from-reference', {
    method: 'POST',
    body: JSON.stringify({
      tier,
      pattern_id:  patternId || null,
      image_paths: imagePaths || null,
      force,
      dry_run:     dryRun,
    }),
  });
}


// ── Rule Candidates ──────────────────────────────────────

export async function listCandidates(status = null, limit = 50) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));
  return labFetch(`/candidates?${params}`);
}

export async function getCandidate(candidateId) {
  return labFetch(`/candidates/${candidateId}`);
}

export async function uploadCandidateImage(file) {
  const form = new FormData();
  form.append('file', file);
  return labFetch('/candidates/upload-image', { method: 'POST', body: form });
}

export async function createCandidate(data) {
  return labFetch('/candidates', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateCandidate(candidateId, data) {
  return labFetch(`/candidates/${candidateId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteCandidate(candidateId) {
  return labFetch(`/candidates/${candidateId}`, { method: 'DELETE' });
}


// ── Reference Dataset ───────────────────────────────────

export async function ingestReferenceImage(file, metadata, { runPipeline = true, runVlm = true, overwrite = false } = {}) {
  const form = new FormData();
  form.append('image', file);
  const params = new URLSearchParams();
  params.set('metadata_json', JSON.stringify(metadata));
  if (!runPipeline) params.set('run_pipeline', 'false');
  if (!runVlm) params.set('run_vlm', 'false');
  if (overwrite) params.set('overwrite', 'true');
  return labFetch(`/reference-dataset/ingest?${params}`, { method: 'POST', body: form });
}

export async function listReferenceDataset({ patternId = null, status = null, tier = null } = {}) {
  const params = new URLSearchParams();
  if (patternId) params.set('pattern_id', patternId);
  if (status) params.set('status', status);
  if (tier) params.set('tier', tier);
  return labFetch(`/reference-dataset?${params}`);
}

export async function getReferenceEntry(patternId, referenceId, { includeSignals = true, includeVlm = true } = {}) {
  const params = new URLSearchParams();
  if (!includeSignals) params.set('include_signals', 'false');
  if (!includeVlm) params.set('include_vlm', 'false');
  return labFetch(`/reference-dataset/${patternId}/${referenceId}?${params}`);
}

export function getReferenceImageUrl(patternId, referenceId) {
  return `/api/lab/reference-dataset/${patternId}/${referenceId}/image`;
}

export function getReferenceThumbnailUrl(patternId, referenceId) {
  return `/api/lab/reference-dataset/${patternId}/${referenceId}/thumbnail`;
}

export function getReferenceDebugOverlayUrl(patternId, referenceId) {
  return `/api/lab/reference-dataset/${patternId}/${referenceId}/debug-overlay`;
}

export async function approveReference(patternId, referenceId) {
  return labFetch(`/reference-dataset/${patternId}/${referenceId}/approve`, { method: 'POST' });
}

export async function rejectReference(patternId, referenceId, reason = '') {
  const params = new URLSearchParams();
  if (reason) params.set('reason', reason);
  return labFetch(`/reference-dataset/${patternId}/${referenceId}/reject?${params}`, { method: 'POST' });
}

export async function reprocessReference(patternId, referenceId, { runVlm = true } = {}) {
  const params = new URLSearchParams();
  if (!runVlm) params.set('run_vlm', 'false');
  return labFetch(`/reference-dataset/${patternId}/${referenceId}/reprocess?${params}`, { method: 'POST' });
}

export async function updateReferenceMetadata(patternId, referenceId, updates) {
  return labFetch(`/reference-dataset/${patternId}/${referenceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export async function getDatasetVersion() {
  return labFetch('/reference-dataset/version');
}


// ── Learning Ops ─────────────────────────────────────

export async function getLearningOps() {
  return labFetch('/learning/ops');
}

export async function getSchedulerStatus() {
  return labFetch('/learning/scheduler');
}

export async function startScheduler({ intervalHours, windowDays } = {}) {
  return labFetch('/learning/scheduler/start', {
    method: 'POST',
    body: JSON.stringify({
      interval_hours: intervalHours ?? null,
      window_days:    windowDays    ?? null,
    }),
  });
}

export async function stopScheduler() {
  return labFetch('/learning/scheduler/stop', { method: 'POST' });
}

export async function configureScheduler({ intervalHours, windowDays }) {
  return labFetch('/learning/scheduler', {
    method: 'PATCH',
    body: JSON.stringify({
      interval_hours: intervalHours ?? null,
      window_days:    windowDays    ?? null,
    }),
  });
}

export async function runSchedulerNow() {
  return labFetch('/learning/scheduler/run-now', { method: 'POST' });
}

export async function triggerIngestion(days = 30, mode = 'production') {
  return labFetch('/learning/ingest', {
    method: 'POST',
    body: JSON.stringify({ days, mode }),
  });
}

export async function listFailureClusters({ status, severity, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (severity) params.set('severity', severity);
  params.set('limit', limit);
  return labFetch(`/learning/clusters?${params}`);
}

export async function getFailureCluster(clusterId) {
  return labFetch(`/learning/clusters/${clusterId}`);
}

export async function updateClusterStatus(clusterId, status, notes = '') {
  return labFetch(`/learning/clusters/${clusterId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, notes }),
  });
}

export async function generateCandidateFromCluster(clusterId) {
  return labFetch(`/learning/clusters/${clusterId}/generate-candidate`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function evaluateCandidate(candidateId, { autoReleaseOnSafe = false } = {}) {
  return labFetch(`/learning/candidates/${candidateId}/evaluate`, {
    method: 'POST',
    body: JSON.stringify({ auto_release_on_safe: autoReleaseOnSafe }),
  });
}

export async function getCandidateEvaluations(candidateId) {
  return labFetch(`/learning/candidates/${candidateId}/evaluations`);
}

export async function recordRelease(candidateId, { releaseVersion, expectedLift = {} } = {}) {
  return labFetch(`/learning/candidates/${candidateId}/release`, {
    method: 'POST',
    body: JSON.stringify({ release_version: releaseVersion, expected_lift: expectedLift }),
  });
}

export async function getMonitoringSummary() {
  return labFetch('/learning/monitoring');
}

export async function getSignalHygiene() {
  return labFetch('/signals/hygiene');
}

export async function getMonitoringReport(attributionId) {
  return labFetch(`/learning/monitoring/${attributionId}`);
}

export async function triggerMonitoringSweep(windowDays = 30) {
  return labFetch('/learning/monitoring/sweep', {
    method: 'POST',
    body: JSON.stringify({ window_days: windowDays }),
  });
}

export async function getDatasetManifest() {
  return labFetch('/reference-dataset/manifest');
}

// ── Benchmark System v2 ────────────────────────────────────────────────────

/** List all benchmark cases. */
export async function listBenchmarkCases({ patternId, difficulty, limit = 100 } = {}) {
  const params = new URLSearchParams();
  if (patternId)  params.set('pattern_id', patternId);
  if (difficulty) params.set('difficulty',  difficulty);
  params.set('limit', String(limit));
  return labFetch(`/benchmarks/cases?${params}`);
}

/** Get a single benchmark case by ID. */
export async function getBenchmarkCase(caseId) {
  return labFetch(`/benchmarks/cases/${caseId}`);
}

/** Create a benchmark case. */
export async function createBenchmarkCase(data) {
  return labFetch('/benchmarks/cases', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/** Update a benchmark case. */
export async function updateBenchmarkCase(caseId, data) {
  return labFetch(`/benchmarks/cases/${caseId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

/** Delete a benchmark case. */
export async function deleteBenchmarkCase(caseId) {
  return labFetch(`/benchmarks/cases/${caseId}`, { method: 'DELETE' });
}

/** Promote a gold set entry to a benchmark case. */
export async function promoteGoldSetToBenchmark(entryId, difficulty = 'medium') {
  return labFetch(`/benchmarks/cases/from-gold-set/${entryId}?difficulty=${difficulty}`, {
    method: 'POST',
  });
}

/** Score history for a single case across runs. */
export async function getBenchmarkCaseHistory(caseId, limit = 10) {
  return labFetch(`/benchmarks/cases/${caseId}/history?limit=${limit}`);
}

/** List benchmark runs. */
export async function listBenchmarkRuns(limit = 20) {
  return labFetch(`/benchmarks/runs?limit=${limit}`);
}

/** Get a single benchmark run. */
export async function getBenchmarkRun(runId) {
  return labFetch(`/benchmarks/runs/${runId}`);
}

/** Get all per-case results for a run. */
export async function getBenchmarkRunResults(runId) {
  return labFetch(`/benchmarks/runs/${runId}/results`);
}

/**
 * Trigger a benchmark run.
 * @param {object} opts
 * @param {string} [opts.runType='manual']
 * @param {string} [opts.trigger='manual']
 * @param {number|null} [opts.caseLimit]
 * @param {string|null} [opts.notes]
 */
export async function triggerBenchmarkRun({ runType = 'manual', trigger = 'manual', caseLimit = null, notes = null } = {}) {
  return labFetch('/benchmarks/run', {
    method: 'POST',
    body: JSON.stringify({
      run_type:   runType,
      trigger,
      case_limit: caseLimit,
      notes,
    }),
  });
}

/** Pattern-level performance metrics with delta vs previous run. */
export async function getBenchmarkPatternMetrics(patternId) {
  const params = patternId ? `?pattern_id=${encodeURIComponent(patternId)}` : '';
  return labFetch(`/benchmarks/pattern-metrics${params}`);
}

/** Compact latest-run summary for the dashboard header. */
export async function getBenchmarkSummary() {
  return labFetch('/benchmarks/summary');
}

/** Confusion matrix — expected vs predicted pattern from a benchmark run. */
export async function getConfusionMatrix(runId = null) {
  const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
  return labFetch(`/benchmarks/confusion-matrix${qs}`);
}

/** Trigger a nightly-style drift detection run from the Lab UI. */
export async function triggerDriftCheck() {
  return labFetch('/benchmarks/drift-check', { method: 'POST' });
}

/** Return current drift check schedule and threshold configuration. */
export async function getDriftConfig() {
  return labFetch('/benchmarks/drift-config');
}

// ── Intelligence / Learning Insights ─────────────────────

/** VLM correction summary — which CV fields VLM overrides most. */
export async function getVlmCorrections() {
  return labFetch('/vlm-corrections');
}

/** Gold set suggestions from high-confidence live nailed_it signals. */
export async function getGoldSetSuggestions(days = 90, limit = 20) {
  return labFetch(`/signals/gold-set-suggestions?days=${days}&limit=${limit}`);
}

/** Returns the URL path for a signal's thumbnail image. */
export function getSignalThumbnailUrl(signalId) {
  return `/api/lab/signals/${signalId}/thumbnail`;
}

/** Concrete per-pattern recalibration hints (reduce X by Ypp). */
export async function getRecalibrationHints(days = 30) {
  return labFetch(`/signals/recalibration-hints?days=${days}`);
}

/** Per-(pattern, environment) calibration breakdown. */
export async function getCalibrationByEnvironment(days = 30) {
  return labFetch(`/signals/calibration-env?days=${days}`);
}

/** Sweep monitoring across all three windows (7d, 14d, 30d). */
export async function triggerSweepAll() {
  return labFetch('/learning/monitoring/sweep-all', { method: 'POST' });
}

/** Apply an accepted confidence_recalibration candidate to the engine. */
export async function applyCandidate(candidateId, notes = '') {
  return labFetch(`/learning/candidates/${candidateId}/apply`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  });
}

// ── Knowledge Base ────────────────────────────────────────

/** Full pattern knowledge base — all 27 entries with risk levels and signal thresholds. */
export async function getKnowledgeBase() {
  return labFetch('/learning/knowledge');
}

/** Single pattern knowledge entry with symptoms and fix steps. */
export async function getKnowledgeEntry(patternId) {
  return labFetch(`/learning/knowledge/${patternId}`);
}

/** Aggregate weighted signals for a pattern — returns AggregatedInsight. */
export async function aggregatePatternSignals(patternId, days = 30) {
  return labFetch(`/learning/knowledge/${patternId}/signals`, {
    method: 'POST',
    body: JSON.stringify({ days }),
  });
}

/**
 * Run 3-gate CI evaluation for a pattern.
 * If candidateId is provided, runs the full DB-backed evaluation for that candidate.
 * If omitted, runs a pattern-level readiness check using live production signals.
 */
export async function runCIGate(patternId, candidateId = null) {
  const body = candidateId ? { candidate_id: candidateId } : {};
  return labFetch(`/learning/knowledge/${patternId}/ci-gate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ── Revenue Simulation ────────────────────────────────────

/** Compute revenue impact from a CVR delta for a pattern. */
export async function computeRevenueImpact(patternId, { sessionsPerDay = 500, beforeCvr = 0.035, cvrDelta = 0.003, arpu = 49, days = 30 } = {}) {
  return labFetch('/learning/revenue/impact', {
    method: 'POST',
    body: JSON.stringify({
      pattern_id: patternId,
      sessions_per_day: sessionsPerDay,
      before_cvr: beforeCvr,
      cvr_delta: cvrDelta,
      arpu,
      days,
    }),
  });
}

/** Run 30-day simulation for a list of scenarios. */
export async function simulateRevenue(scenarios) {
  return labFetch('/learning/revenue/simulate', {
    method: 'POST',
    body: JSON.stringify({ scenarios }),
  });
}

/** Fetch simulation run history from the backend (survives logout/cache-clear). */
export async function getSimulationHistory(limit = 20) {
  return labFetch(`/learning/revenue/simulate/history?limit=${limit}`);
}

/** Fetch the latest simulation run from the backend, or null if none. */
export async function getLatestSimulation() {
  try {
    return await labFetch('/learning/revenue/simulate/latest');
  } catch (err) {
    if (err.message?.includes('[404]')) return null;
    throw err;
  }
}

// ── Intelligence & Autonomy API ───────────────────────────────────────────────

/** Get current global intelligence score (cached by default). */
export async function getIntelligenceScore(days = 30, force = false) {
  return coreFetch(`/intelligence/score?days=${days}&force=${force}`);
}

/** Get intelligence score trend history. */
export async function getIntelligenceScoreHistory(days = 30, limit = 30) {
  return coreFetch(`/intelligence/score/history?days=${days}&limit=${limit}`);
}

/** Get per-pattern intelligence scores. */
export async function getIntelligencePatterns(days = 30, force = false) {
  return coreFetch(`/intelligence/patterns?days=${days}&force=${force}`);
}

/** Get intelligence cluster report (failure + success clusters). */
export async function getIntelligenceClusters(days = 30) {
  return coreFetch(`/intelligence/clusters?days=${days}`);
}

/** Force-recompute global + pattern intelligence scores. */
export async function forceComputeIntelligence(days = 30) {
  return coreFetch(`/intelligence/compute?days=${days}`, { method: 'POST' });
}

/** Get nailed-it event stats. */
export async function getNailedItStats(days = 30) {
  return coreFetch(`/intelligence/nailed-it/stats?days=${days}`);
}

/** Get autonomy action queue (pending MEDIUM/HIGH risk actions). */
export async function getAutonomyQueue() {
  return coreFetch('/intelligence/autonomy/queue');
}

/** Get full autonomy audit log. */
export async function getAutonomyLog({ limit = 50, riskTier = null, status = null } = {}) {
  const params = new URLSearchParams({ limit });
  if (riskTier) params.set('risk_tier', riskTier);
  if (status) params.set('status', status);
  return coreFetch(`/intelligence/autonomy/log?${params}`);
}

/** Get autonomy dashboard summary (active actions, rollbacks, guardrail status). */
export async function getAutonomyDashboard(days = 7) {
  return coreFetch(`/intelligence/autonomy/dashboard?days=${days}`);
}

/** Run one pass of the autonomous optimization loop manually. */
export async function runAutonomyLoop(days = 30) {
  return coreFetch(`/intelligence/autonomy/run?days=${days}`, { method: 'POST' });
}

/** Approve a queued MEDIUM/HIGH risk autonomy action. */
export async function approveAutonomyAction(actionId, approvedBy) {
  return coreFetch(`/intelligence/autonomy/approve/${actionId}`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

/** Reject a queued autonomy action. */
export async function rejectAutonomyAction(actionId, rejectedBy, reason = '') {
  return coreFetch(`/intelligence/autonomy/reject/${actionId}`, {
    method: 'POST',
    body: JSON.stringify({ rejected_by: rejectedBy, reason }),
  });
}

/** Get intelligence feature flags (thresholds, guardrails). */
export async function getIntelligenceFlags() {
  return coreFetch('/intelligence/flags');
}

/** Fetch API key health status (admin only). */
export async function getApiKeyHealth() {
  return coreFetch('/health/api-keys');
}

/** Force a live API key probe (admin only). */
export async function probeApiKey() {
  return coreFetch('/health/api-keys/probe', { method: 'POST' });
}

/** Send a test capture_message to Sentry (admin only). */
export async function sentryTest() {
  return coreFetch('/health/sentry/test', { method: 'POST' });
}

/** Return aggregated VLM call metrics for the last N hours. */
export async function getApiMetrics(hours = 24) {
  return labFetch(`/api-metrics?hours=${hours}`);
}


// ── Gold Set QC ─────────────────────────────────────────────────────────────

/** Fetch gold set quality-control buckets — read-only inspection. */
export async function fetchGoldSetQC() {
  return labFetch('/gold-set/qc');
}

// ── Coverage Map (Build 4) ──────────────────────────────────────────────────

/** Fetch per-pattern coverage summary — read-only. */
export async function fetchCoverageMap() {
  return labFetch('/coverage-map');
}

// ── Failure Triage (LAB Build 2) ─────────────────────────────────────────────

/**
 * Fetch VLM cases where VLM was confident but disagreed with CV resolver.
 * DATA NOTE: ground_truth_pattern = CV-resolved value, NOT human-labeled ground truth.
 */
export async function fetchOverconfidentFailures(threshold = 0.65, limit = 20) {
  const params = new URLSearchParams({ threshold: String(threshold), limit: String(limit) });
  return labFetch(`/failure-triage/overconfident?${params}`);
}

/**
 * Fetch VLM cases where VLM agreed with CV but at low confidence.
 * DATA NOTE: These are boundary/uncertain cases, not confirmed failures.
 */
export async function fetchUnderconfidentHits(threshold = 0.45, limit = 20) {
  const params = new URLSearchParams({ threshold: String(threshold), limit: String(limit) });
  return labFetch(`/failure-triage/underconfident?${params}`);
}

/**
 * Send a triage item to the gold set as a DRAFT (pending_review).
 * Never auto-approves — requires explicit review in the Gold Set panel.
 * @param {object} item - { image_path, predicted_pattern, ground_truth_pattern, confidence, analysis_id?, notes? }
 */
export async function sendToGoldSetReview(item) {
  return labFetch('/failure-triage/send-to-gold-set', {
    method: 'POST',
    body: JSON.stringify(item),
  });
}

/**
 * Dismiss a triage item.
 * NOTE: No dismissed column exists in vlm_disagreements schema (v1).
 * This function is intentionally null — dismiss is implemented as frontend-only state.
 * Returns a resolved promise so callers can treat it uniformly.
 */
export async function dismissTriageItem(_disagreementId) {
  // Backend dismiss not implemented in v1 — no dismissed/status column in vlm_disagreements.
  // Frontend removes the item from local state. No server call.
  return Promise.resolve({ dismissed: true, local_only: true });
}

export async function getMonitoringStats(hours = 24) {
  return labFetch(`/monitoring-stats?hours=${hours}`);
}

/** Fetch recent L1 analysis telemetry records (Logs → L1 Stream).
 *  @param {number} limit  max rows
 *  @param {object} filters  { userEmail, search, pattern, flags }
 */
export async function getL1Stream(limit = 100, filters = {}) {
  const qs = new URLSearchParams({ limit });
  if (filters.userEmail) qs.set('user_email', filters.userEmail);
  if (filters.search)    qs.set('search',     filters.search);
  if (filters.pattern)   qs.set('pattern',    filters.pattern);
  if (filters.flags)     qs.set('flags',      filters.flags);
  return labFetch(`/l1-stream?${qs}`);
}

/** Fetch recent in-process server log records from the memory buffer. */
export async function getServerLogs({ limit = 200, level = '', search = '', user_email = '', session_id = '', logger = '', since = '', until = '' } = {}) {
  const qs = new URLSearchParams({ limit });
  if (level)        qs.set('level',      level);
  if (search)       qs.set('search',     search);
  if (user_email)   qs.set('user_email', user_email);
  if (session_id)   qs.set('session_id', session_id);
  if (logger)       qs.set('logger',     logger);
  if (since)        qs.set('since',      since);
  if (until)        qs.set('until',      until);
  return labFetch(`/server-logs?${qs}`);
}

/** Export full server log buffer as downloadable JSON. */
export async function exportServerLogs() {
  return labFetch('/server-logs/export');
}

/** Clear all L1 stream analysis records. */
export async function clearL1Stream() {
  return labFetch('/l1-stream', { method: 'DELETE' });
}

/** Clear the in-memory server log buffer. */
export async function clearServerLogs() {
  return labFetch('/server-logs', { method: 'DELETE' });
}

/** Fetch all diagnostic failure entries, optionally filtered by pattern. */
export async function getDiagnostics(pattern = null) {
  const qs = pattern ? `?pattern=${encodeURIComponent(pattern)}` : '';
  return coreFetch(`/diagnostics${qs}`);
}

/** Run server-side alert check — evaluates all production rules + persists transitions. */
export async function checkAlerts(hours = 24) {
  return labFetch(`/alert-check?hours=${hours}`);
}

/** Fetch persisted alert event history from backend. */
export async function getAlertHistory(limit = 50) {
  return labFetch(`/alert-history?limit=${limit}`);
}

/** Fetch unified audit log — all admin actions. */
export async function getAuditLog({ limit = 100, entityType = null } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (entityType) params.set('entity_type', entityType);
  return labFetch(`/audit-log?${params}`);
}


// ── Case Replay (Build 3A) ────────────────────────────────────────────────────

/**
 * Fetch stored replay data for a past analysis run (Build 3A).
 * Returns { analysis_id, found, result, vlm_disagreements, user_feedback, corrections, data_notes }
 * result is null for analyses run before Build 3A deployment.
 */
export async function fetchAnalysisReplay(analysisId) {
  return labFetch(`/analysis/${encodeURIComponent(analysisId)}`);
}


// ── Distillation Candidate Reviews ───────────────────────────────────────────

/** List distillation candidate review rows. All filters are optional. */
export async function listDistillationReviews({
  review_status = null,
  path_type     = null,
  entry_type    = null,
  limit         = 100,
} = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (review_status) params.set('review_status', review_status);
  if (path_type)     params.set('path_type',     path_type);
  if (entry_type)    params.set('entry_type',     entry_type);
  return coreFetch(`/admin/distillation-reviews?${params}`);
}

/** Get a single distillation candidate review row by id. */
export async function getDistillationReview(reviewId) {
  return coreFetch(`/admin/distillation-reviews/${reviewId}`);
}

/** Update review decision for one distillation candidate. */
export async function patchDistillationReview(reviewId, { review_status, rationale = '', notes = '' }) {
  return coreFetch(`/admin/distillation-reviews/${reviewId}`, {
    method: 'PATCH',
    body: JSON.stringify({ review_status, rationale, notes }),
  });
}

/**
 * Submit a teach label from the Workbench.
 * correctness: 'correct' | 'incorrect'
 * When incorrect, expected_pattern should be the corrected pattern.
 */
export async function submitTeachLabel({
  image_path,
  predicted_pattern,
  expected_pattern,
  confidence = 0,
  path_type = 'primary',
  correctness,
  notes = '',
}) {
  return coreFetch('/admin/distillation-reviews/from-workbench', {
    method: 'POST',
    body: JSON.stringify({ image_path, predicted_pattern, expected_pattern, confidence, path_type, correctness, notes }),
  });
}

/** Fetch the image for a distillation review entry (returns object URL). */
export async function getDistillationReviewImageUrl(reviewId) {
  const res = await apiFetch(`/api/admin/distillation-reviews/${reviewId}/image`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Review image fetch failed (${res.status})`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}


// ── Review Ops Dashboard ─────────────────────────────────────────────────────

/**
 * Fetch counts for all 6 Review Ops queues in a single parallel batch.
 * Returns an object with a count (number) and optional error per queue.
 * Never throws — each queue degrades independently.
 */
export async function fetchReviewOpsCounts() {
  const settle = async (fn) => {
    try { return { count: await fn(), error: null }; }
    catch (err) { return { count: null, error: err.message || 'Error' }; }
  };

  const [goldSet, distillation, vlmCorrections, referenceBacklog, correctionLog, groundTruth] =
    await Promise.all([
      // 1. Pending Gold Set Reviews — status=draft means awaiting review
      settle(async () => {
        const d = await labFetch('/gold-set?status=draft&limit=500');
        return d.count ?? 0;
      }),
      // 2. Distillation Reviews Pending
      settle(async () => {
        const d = await coreFetch('/admin/distillation-reviews?review_status=pending_review&limit=500');
        return d.total ?? 0;
      }),
      // 3. VLM Corrections — total corrections logged
      settle(async () => {
        const d = await labFetch('/vlm-corrections');
        // vlm-corrections returns a summary; use total_corrections or record count
        return d.total_corrections ?? d.total ?? (Array.isArray(d.corrections) ? d.corrections.length : 0);
      }),
      // 4. Reference Dataset: needs reprocessing
      settle(async () => {
        const d = await labFetch('/reference-dataset?status=needs_reprocessing');
        return d.total ?? (Array.isArray(d.entries) ? d.entries.length : 0);
      }),
      // 5. Correction Log — total entries (no flagged filter in current API)
      settle(async () => {
        const d = await coreFetch('/admin/correction-log?limit=500');
        return d.total ?? 0;
      }),
      // 6. Ground Truth — total image labels (no verified field in current schema)
      settle(async () => {
        const d = await coreFetch('/admin/image-labels?limit=500');
        return d.total ?? 0;
      }),
    ]);

  return { goldSet, distillation, vlmCorrections, referenceBacklog, correctionLog, groundTruth };
}

// ── Build 3.1: Replay image URL ───────────────────────────────────────────────

/**
 * Return the authenticated URL for a replay image.
 * Does NOT fetch — just builds the URL for use in <img src>.
 * The token is passed as a query param for img tag compat.
 * @param {string} analysisId
 * @returns {string|null}
 */
export function replayImageUrl(analysisId) {
  if (!analysisId) return null;
  const token = getToken();
  const base = `/api/lab/analysis/${encodeURIComponent(analysisId)}/image`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

// ── Layer 4: Calibration surface ──────────────────────────────────────────────

/**
 * Fetch per-pattern recalibration suggestions from signal history.
 * @param {number} [days=30] — lookback window in days
 */
export async function fetchCalibrationSuggestions(days = 30) {
  return labFetch(`/calibration/suggestions?days=${days}`);
}

/**
 * Fetch current confidence_overrides.json (active floors).
 */
export async function fetchCalibrationCurrent() {
  return labFetch('/calibration/current');
}

/**
 * Apply reviewed confidence floors.
 * @param {Object.<string, number>} floors — pattern_id → floor value
 * @param {string} [notes=''] — optional reviewer notes
 */
export async function applyCalibrationFloors(floors, notes = '') {
  return labFetch('/calibration/apply', {
    method: 'POST',
    body: JSON.stringify({ floors, notes }),
  });
}
