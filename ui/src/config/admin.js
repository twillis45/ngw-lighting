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

/** Fallback when VITE_NGW_ADMIN_EMAILS is unset — preserves prior behavior. */
export const DEFAULT_ADMIN_EMAILS = ['todd@toddwillisphoto.com'];

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
