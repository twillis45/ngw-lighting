/**
 * stripeCheckout — creates a Stripe Checkout Session via the backend
 * and redirects the user to the hosted checkout page.
 *
 * After payment Stripe redirects back to:
 *   <origin>/static/ui/?checkout_success=1&session_id=<id>
 *
 * main.jsx detects that param on load and sets ngw_paid=true before React
 * mounts, so usePaywall initialises with isPaid=true without any extra
 * re-renders or race conditions.
 */

import { authHeaders } from './authApi';

const API_BASE = '/api';

/**
 * Start a Stripe Checkout flow.
 *
 * @param {object} opts
 * @param {'monthly'|'yearly'} opts.billingPeriod
 * @param {'pro'|'studio'}     opts.plan
 * @param {number}            [opts.pricePoint]  the price the user was SHOWN.
 *   Sent so the server can refuse to charge a different amount. Before
 *   2026-09-03 the displayed price and the charged price were unrelated.
 * @returns {Promise<void>}  Redirects on success; throws on error.
 */
export async function startStripeCheckout({ billingPeriod = 'monthly', plan = 'pro', pricePoint = null } = {}) {
  const origin = window.location.origin;
  const base   = `${origin}/static/ui/`;

  const res = await fetch(`${API_BASE}/stripe/create-checkout-session`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      billing_period: billingPeriod,
      plan,
      ...(pricePoint != null ? { price_point: pricePoint } : {}),
      success_url:    `${base}?checkout_success=1`,
      cancel_url:     base,
    }),
  });

  if (!res.ok) {
    let msg = 'Failed to start checkout. Please try again.';
    try {
      const data = await res.json();
      if (data?.detail) msg = data.detail;
    } catch { /* ignore parse error */ }
    throw new Error(msg);
  }

  const { url } = await res.json();
  if (!url) throw new Error('No checkout URL returned from server.');

  window.location.href = url;
}
