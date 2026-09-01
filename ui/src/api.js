import { apiFetch } from './lib/apiClient';
import { authHeaders } from './data/authApi';

/** POST /recommend and return the raw API response. */

export async function fetchRecommendation(payload) {
  const resp = await apiFetch('/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    const msg = typeof err.detail === 'string'
      ? err.detail
      : JSON.stringify(err.detail || err, null, 2);
    throw new Error(msg);
  }

  return resp.json();
}

/** Upload a reference image and return { path, analysis }. */

export async function uploadReferenceImage(file) {
  const form = new FormData();
  form.append('file', file);

  const resp = await apiFetch('/api/upload-reference', {
    method: 'POST',
    headers: { ...authHeaders() },  // JWT required — get_current_user gate
    body: form,
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    const msg = typeof err.detail === 'string'
      ? err.detail
      : JSON.stringify(err.detail || err, null, 2);
    throw new Error(msg || 'Failed to upload reference image');
  }

  return resp.json();
}

/* REMOVED 2026-08-31 — mergeAnalyses() called POST /api/merge-analyses, a route
   that does not exist and never has. It was dead three ways at once, which is
   why it survived: the route 404s, both call sites swallowed the failure with
   .catch(() => {}), and the result was stored in a `consensus` state variable
   that nothing ever read — so even a SUCCESSFUL response would have gone
   nowhere. Every multi-image upload in ReferenceEvalScreen fired a doomed
   request whose result would have been discarded.

   Not reimplemented, because nothing consumed it. If multi-image consensus is
   wanted, it needs a server route AND something that renders the answer.
   tests/test_ui_calls_real_routes.py now compares every /api/ path the UI calls
   against the server's route table, so a phantom cannot come back silently. */

/** POST /api/shoot-match and return UI-ready card data. */

export async function fetchShootMatch(wizardState) {
  const resp = await apiFetch('/api/shoot-match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(wizardState),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    const msg = typeof err.detail === 'string'
      ? err.detail
      : JSON.stringify(err.detail || err, null, 2);
    throw new Error(msg);
  }

  return resp.json();
}
