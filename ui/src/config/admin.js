/**
 * Admin identity — single source of truth for the frontend.
 *
 * Mirrors config/admin.py on the backend. Reads VITE_NGW_ADMIN_EMAILS
 * (comma-separated) and falls back to DEFAULT_ADMIN_EMAILS when unset, so an
 * unconfigured build keeps the prior behavior.
 *
 * NOTE: this is a convenience gate, not a security boundary. Anything shipped
 * to the browser is readable and editable by the user; every privileged action
 * is authorized server-side. Keep it that way.
 */

/** Fallback when VITE_NGW_ADMIN_EMAILS is unset.
 *
 * EMPTY, deliberately, changed 2026-08-31. This was
 * ['todd@toddwillisphoto.com'], and that address was retired from
 * NGW_ADMIN_EMAILS the same day — so the fallback had become a stale grant:
 * an unconfigured build would show admin UI to an account the backend no
 * longer treats as admin.
 *
 * An unconfigured allowlist is an absence of permission, never a grant of it.
 * That is the same rule applied to auth/dev_guard.py today, where the Lab
 * image route was failing OPEN on an empty allowlist.
 *
 * The cost of failing closed here is visible and cheap — admin UI hidden until
 * VITE_NGW_ADMIN_EMAILS is set at build time — whereas the cost of failing
 * open is a name silently baked into every bundle forever.
 */
export const DEFAULT_ADMIN_EMAILS = [];

/** The dev-mode identity minted by auth/dev_guard.py — always unlocked. */
export const DEV_MODE_EMAIL = 'dev@localhost';

function parseEnvEmails(raw) {
  if (!raw || !raw.trim()) return null;
  const list = raw
    .split(',')
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  return list.length ? list : null;
}

/** Admin addresses from env, or the default if unset/blank. */
export function getAdminEmails() {
  const env = import.meta.env?.VITE_NGW_ADMIN_EMAILS;
  return parseEnvEmails(env) || DEFAULT_ADMIN_EMAILS;
}

/** True if `email` is an admin account. Tolerates null/empty. */
export function isAdminEmail(email) {
  if (!email) return false;
  return getAdminEmails().includes(email.trim().toLowerCase());
}

/** Seed identity for dev-mode and demo routes — not an admin gate. */
export function primaryAdminEmail() {
  return getAdminEmails()[0];
}
