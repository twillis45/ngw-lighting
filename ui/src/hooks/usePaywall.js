/**
 * usePaywall — localStorage-backed paid/free tier state.
 *
 * isPaid         — true if user has unlocked the full product
 * unlock()       — simulate upgrade (sets localStorage; production wires to payment)
 * lock()         — revert to free tier (dev/testing only)
 * isAdmin        — true for admin emails (always paid, cannot be locked)
 *
 * Admin emails always have isPaid = true regardless of localStorage,
 * UNLESS ?qa_free=1 was passed — which forces free-tier for QA testing.
 * QA mode is stored in sessionStorage and resets on tab close.
 */

import { useState, useCallback, useEffect } from 'react';
import { trackEvent, getSessionId } from '../data/analytics';
import { getPaywallConfig } from '../data/pricingStore';
import { authHeaders } from '../data/authApi';
import { savePlan } from '../data/planStore';
import { isAdminEmail as isAdmin, DEV_MODE_EMAIL } from '../config/admin';

const STORAGE_KEY = 'ngw_paid';
const COUNT_KEY = 'ngw_analysis_count';
const QA_FREE_KEY = 'ngw_qa_free';

function readCount() {
  try { return parseInt(sessionStorage.getItem(COUNT_KEY) || '0', 10); } catch { return 0; }
}
function writeCount(n) {
  try { sessionStorage.setItem(COUNT_KEY, String(n)); } catch {}
}

/** Returns true if QA free-mode is active (?qa_free=1 was used this session).
 *  Requires an admin email — non-admin users cannot activate QA free mode. */
function isQaFreeMode(email) {
  if (!isAdminEmail(email)) return false;
  try { return sessionStorage.getItem(QA_FREE_KEY) === '1'; } catch { return false; }
}

/** These accounts always have full access — no paywall, no prompts. */
function isAdminEmail(email) {
  if (!email) return false;
  const e = email.trim().toLowerCase();
  return e === DEV_MODE_EMAIL || isAdmin(e);
}

/**
 * Resolve the best email from a user object.
 * Falls back through email → username (if it looks like an email) → null.
 * This prevents stale localStorage objects (missing `email` field) from
 * bypassing admin checks by falling through to a display name.
 */
export function resolveUserEmail(user) {
  if (!user) return null;
  if (user.email) return user.email;
  // Only use username if it looks like an email address
  if (user.username && user.username.includes('@')) return user.username;
  return null;
}

function readPaid() {
  try { return localStorage.getItem(STORAGE_KEY) === 'true'; } catch { return false; }
}

/** Read the subscription plan tier stored after server verification ('pro' | 'studio' | null). */
function readPlanTier() {
  try { return localStorage.getItem('ngw_subscription_plan') || null; } catch { return null; }
}

export default function usePaywall(userEmail) {
  const qaFree = isQaFreeMode(userEmail); // admin-only QA override

  // QA free-mode overrides both admin and localStorage paid state so paywall
  // flows can be tested without clearing storage after every session.
  const [isPaid, setIsPaid] = useState(() =>
    qaFree ? false : (isAdminEmail(userEmail) || readPaid())
  );
  const [analysisCount, setAnalysisCount] = useState(readCount);
  // planTier is set after server verification: 'pro' | 'studio' | null
  const [planTier, setPlanTier] = useState(() => qaFree ? null : readPlanTier());
  const paywallCfg = getPaywallConfig();
  const threshold = paywallCfg.threshold ?? 3;
  // In QA free-mode: treat admin as a regular free user so all paywall triggers fire.
  // isAdmin still returns true (informational) but doesn't suppress limit or paywall.
  const effectiveAdmin = !qaFree && isAdminEmail(userEmail);
  const isAtLimit = !effectiveAdmin && !isPaid && analysisCount >= threshold;

  // When userEmail changes to an admin address, sync isPaid — unless QA free-mode
  // is active, in which case keep the free-tier state so testing is uninterrupted.
  useEffect(() => {
    if (!qaFree && isAdminEmail(userEmail)) setIsPaid(true);
  }, [userEmail, qaFree]);

  // Server verification — runs once on mount.
  // Two paths:
  //   A) Pending Stripe session in localStorage → post-checkout confirmation.
  //   B) localStorage says paid but no Stripe session → silent re-verify to prevent
  //      localStorage tampering (e.g. DevTools hack). Clears paid flag if server
  //      does not confirm. Network failures leave the flag intact (benefit of doubt).
  useEffect(() => {
    if (qaFree) return;
    if (effectiveAdmin) return; // admin emails always trusted — no server round-trip needed

    let stripeSession = null;
    try { stripeSession = localStorage.getItem('ngw_stripe_session'); } catch { /* ignore */ }

    // Path B: localStorage says paid but no Stripe session pending — re-verify silently.
    // Must include the JWT (authHeaders) so the server can validate the email param;
    // without it the server now rejects cross-user email lookups and returns is_paid=false.
    if (!stripeSession && readPaid() && userEmail) {
      let cancelled = false;
      (async () => {
        try {
          const res = await fetch(
            `/api/auth/subscription-status?email=${encodeURIComponent(userEmail)}`,
            { credentials: 'include', headers: { ...authHeaders() } },
          );
          if (!res.ok) return; // network/server error — leave paid state as-is
          const data = await res.json();
          if (!cancelled && !data.is_paid) {
            // Server says not paid — localStorage was tampered or subscription lapsed.
            try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
            try { localStorage.removeItem('ngw_subscription_plan'); } catch { /* ignore */ }
            setIsPaid(false);
            setPlanTier(null);
          }
        } catch { /* network error — leave paid state as-is */ }
      })();
      return () => { cancelled = true; };
    }

    // Path A: Post-checkout Stripe session present — confirm with server.
    if (!stripeSession) return;

    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams({ stripe_session: stripeSession });
        if (userEmail) params.set('email', userEmail);
        const res = await fetch(`/api/auth/subscription-status?${params}`, {
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          credentials: 'include',
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data.is_paid) {
          try { localStorage.setItem(STORAGE_KEY, 'true'); } catch { /* ignore */ }
          if (data.plan) {
            try { localStorage.setItem('ngw_subscription_plan', data.plan); } catch { /* ignore */ }
            setPlanTier(data.plan);
            // Sync to planStore so usePlan hook picks up the confirmed tier
            savePlan(data.plan);
            window.dispatchEvent(new Event('ngw_plan_change'));
          }
          setIsPaid(true);
          // Session ID consumed — remove so we don't re-verify on every mount
          try { localStorage.removeItem('ngw_stripe_session'); } catch { /* ignore */ }
        }
      } catch { /* network error — localStorage paid state stands as fallback */ }
    })();

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userEmail]); // re-run when email becomes known (async auth resolution)

  const unlock = useCallback(() => {
    try { localStorage.setItem(STORAGE_KEY, 'true'); } catch {}
    setIsPaid(true);
    trackEvent('UPGRADE_COMPLETED', { email: userEmail });
  }, [userEmail]);

  const lock = useCallback(() => {
    // In QA free-mode allow lock even on admin accounts (so full reset is possible).
    if (!qaFree && isAdminEmail(userEmail)) return;
    try { localStorage.removeItem(STORAGE_KEY); } catch {}
    setIsPaid(false);
  }, [userEmail, qaFree]);

  const incrementCount = useCallback(() => {
    setAnalysisCount(prev => {
      const next = prev + 1;
      writeCount(next);
      trackEvent('ANALYSIS_COUNT_HIT', { count: next, threshold });

      // HIGH-1 fix: also sync count to the server so /recommend paywall gate
      // fires correctly. Fire-and-forget — never blocks the UI.
      const sessionId = getSessionId();
      if (sessionId) {
        fetch('/api/usage/increment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ session_id: sessionId, event: 'analysis_complete' }),
        }).catch(() => { /* network error — sessionStorage count is the fallback */ });
      }

      return next;
    });
  }, [threshold]);

  const isStudio = !qaFree && isPaid && planTier === 'studio';

  return {
    isPaid, unlock, lock,
    isAdmin: isAdminEmail(userEmail),
    analysisCount, threshold, isAtLimit, incrementCount,
    planTier,    // 'pro' | 'studio' | null — set after server verification
    isStudio,    // true only when subscription plan is 'studio'
  };
}
