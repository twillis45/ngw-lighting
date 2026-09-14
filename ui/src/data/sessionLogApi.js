/**
 * Session Log API — fetches user's analysis history.
 */
import { authHeaders } from './authApi';

const API_BASE = '/api';

/**
 * Fetch paginated list of user's past analyses.
 * @param {object} opts
 * @param {number} opts.page
 * @param {number} opts.perPage
 * @param {string} [opts.pattern]
 * @param {number} [opts.dateFrom] — unix timestamp
 * @param {number} [opts.dateTo]   — unix timestamp
 */
export async function fetchAnalyses({ page = 1, perPage = 20, pattern, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (pattern) params.set('pattern', pattern);
  if (dateFrom) params.set('date_from', String(dateFrom));
  if (dateTo) params.set('date_to', String(dateTo));

  const res = await fetch(`${API_BASE}/user/analyses?${params}`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to load analyses (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch full analysis detail for re-rendering.
 * @param {string} analysisId
 */
export async function fetchAnalysisDetail(analysisId) {
  const res = await fetch(`${API_BASE}/user/analyses/${encodeURIComponent(analysisId)}`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to load analysis (${res.status})`);
  }
  return res.json();
}

/**
 * Get the image URL for one of the signed-in user's own analyses.
 *
 * This used to point at `/lab/analysis/{id}/image`, which gates on the
 * developer allowlist and fails closed: with NGW_DEV_EMAILS unset nobody is
 * authorized, so every Journal thumbnail returned 403 and the cards rendered
 * blank — for customers and for the account that created the analyses alike.
 * The customer route authorizes by ownership instead.
 *
 * @param {string} analysisId
 * @returns {string}
 */
export function getAnalysisImageUrl(analysisId) {
  const token = localStorage.getItem('ngw_auth_token') || '';
  return `${API_BASE}/analysis/${encodeURIComponent(analysisId)}/image?token=${encodeURIComponent(token)}`;
}
