/**
 * PricingScreen — full-screen 3-tier pricing overlay.
 *
 * Renders as a modal overlay triggered from any paywall upgrade CTA.
 * Tiers: Free (current) / Pro $39/mo / Studio (coming soon)
 *
 * Props:
 *   onClose      — called when user dismisses without upgrading
 *   onUnlock     — called when user completes upgrade (plan passed as arg)
 *   trigger      — string — which gate opened this ('success_moment' | 'shoot_mode' | etc.)
 *   source       — string — component that opened this
 */

import { useState, useEffect, useCallback } from 'react';
import { trackEvent } from '../data/analytics';
import { broadcastConversion } from '../data/experimentTracker';
import { getActivePricing } from '../data/pricingStore';
import { startStripeCheckout } from '../data/stripeCheckout';
import { getToken } from '../data/authApi';
import AuthModal from './AuthModal';

const FREE_FEATURES_INCLUDED = [
  '3 analyses per session',
  'Basic pattern identification',
];

const FREE_FEATURES_GATED = [
  'Full blueprints & distances',
  'Shoot Mode',
];

const PRO_FEATURES = [
  'Unlimited analyses',
  'Full blueprints — positions, ratios, distances',
  'Shoot Mode — compare live, correct on set',
  'Reference image analysis',
  'All 28 lighting patterns',
  'All modifiers + camera settings',
  'Saved setups library',
];

const STUDIO_FEATURES = [
  'Everything in Pro',
  'Team licences',
  'API access',
  'White-label exports',
  'Priority support',
];

function FeatureRow({ text, included }) {
  return (
    <li className={`pricing-tier__feature${included ? '' : ' pricing-tier__feature--missing'}`}>
      {included ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      ) : (
        <span className="pricing-tier__dash">—</span>
      )}
      {text}
    </li>
  );
}

function PricingTierCard({ tier, pricing, billingPeriod, onSelect, isCurrent, loading = false }) {
  const isPro   = tier === 'pro';
  const isFree  = tier === 'free';
  const isStudio = tier === 'studio';

  const monthlyPrice = isPro ? pricing.price_monthly : null;
  const yearlyPrice  = isPro ? pricing.price_yearly  : null;
  // yearlyPrice is the annual total — show per-month equivalent when on yearly tab
  const displayPrice = billingPeriod === 'yearly' && yearlyPrice
    ? Math.round(yearlyPrice / 12)
    : monthlyPrice;

  return (
    <div className={`pricing-tier${isPro ? ' pricing-tier--featured' : ''}${isStudio ? ' pricing-tier--muted' : ''}`}>
      <div className="pricing-tier__header">
        <div className="pricing-tier__name-group">
          <span className="pricing-tier__name">
            {tier === 'free' ? 'Free' : tier === 'pro' ? 'Pro' : 'Studio'}
          </span>
          {isPro && <span className="pricing-tier__cancel-note">cancel anytime</span>}
        </div>
        {isCurrent && <span className="pricing-tier__current-badge">Current plan</span>}
        {isStudio && <span className="pricing-tier__current-badge">Coming soon</span>}
        {isPro && billingPeriod === 'yearly' && pricing.yearly_discount_pct && (
          <span className="pricing-tier__badge">Save {pricing.yearly_discount_pct}%</span>
        )}
      </div>

      <div className="pricing-tier__price">
        {isFree && <span className="pricing-tier__amount">$0</span>}
        {isPro && (
          <>
            <span className="pricing-tier__amount">${displayPrice}</span>
            <span className="pricing-tier__period">/mo</span>
          </>
        )}
        {isStudio && <span className="pricing-tier__amount pricing-tier__amount--muted">Coming soon</span>}
      </div>

      {isPro && billingPeriod === 'yearly' && yearlyPrice && (
        <p className="pricing-tier__billing-note">
          Billed ${yearlyPrice}/yr · ${pricing.price_monthly}/mo monthly
        </p>
      )}

      <ul className="pricing-tier__features">
        {isFree  && FREE_FEATURES_INCLUDED.map((f, i) => <FeatureRow key={i} text={f} included />)}
        {isFree  && FREE_FEATURES_GATED.map((f, i) => <FeatureRow key={`g${i}`} text={f} included={false} />)}
        {isPro   && PRO_FEATURES.map((f, i)  => <FeatureRow key={i} text={f} included />)}
        {isStudio && STUDIO_FEATURES.map((f, i) => <FeatureRow key={i} text={f} included />)}
      </ul>

      <button
        className={`pricing-tier__cta${isPro ? ' pricing-tier__cta--primary' : ''}${isFree || isStudio ? ' pricing-tier__cta--ghost' : ''}`}
        onClick={() => onSelect(tier)}
        type="button"
        disabled={isCurrent || isStudio || loading}
      >
        {isCurrent        ? 'Current plan'
         : isStudio       ? 'Coming soon'
         : isFree         ? 'Stay free'
         : loading        ? 'Redirecting…'
         : `Start Pro — $${displayPrice}/mo  →`}
      </button>
    </div>
  );
}

export default function PricingScreen({ onClose, onUnlock, trigger, source }) {
  const [billingPeriod, setBillingPeriod] = useState('monthly');
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState(null);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const pricing = getActivePricing();

  // Restore upgrade intent — if user returns from magic link or re-opens pricing
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('ngw_upgrade_intent');
      if (raw) {
        const intent = JSON.parse(raw);
        if (intent?.billingPeriod) setBillingPeriod(intent.billingPeriod);
        // If already authenticated and intent exists, fire checkout automatically
        if (getToken()) {
          sessionStorage.removeItem('ngw_upgrade_intent');
          handleCheckout(intent.billingPeriod || 'monthly');
        }
      }
    } catch { /* ignore */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    trackEvent('PRICING_SCREEN_VIEWED', { trigger: trigger || 'direct', source: source || 'unknown' });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handlePeriodToggle(period) {
    if (period === billingPeriod) return;
    trackEvent('PRICING_PLAN_TOGGLED', { from_period: billingPeriod, to_period: period });
    setBillingPeriod(period);
  }

  async function handleSelect(tier) {
    if (tier === 'free') {
      trackEvent('UPGRADE_ABANDONED', { step: 'pricing_screen', plan: 'free' });
      onClose?.();
      return;
    }
    if (tier === 'studio') {
      trackEvent('UPGRADE_CLICKED', { plan: 'studio', trigger });
      return; // waitlist — no action yet
    }

    // Pro — start Stripe Checkout
    const price = billingPeriod === 'yearly' ? pricing.price_yearly : pricing.price_monthly;
    trackEvent('UPGRADE_STARTED', { plan: 'pro', billing_period: billingPeriod, price, trigger });
    broadcastConversion('UPGRADE_CLICKED', { plan: 'pro', billing_period: billingPeriod, price, trigger });

    // Auth guard — show AuthModal instead of surfacing a raw error
    if (!getToken()) {
      setShowAuthModal(true);
      return;
    }

    handleCheckout(billingPeriod);
  }

  async function handleCheckout(period) {
    setCheckoutLoading(true);
    setCheckoutError(null);
    try {
      // Send the price the user is actually looking at. The server refuses to
      // charge a different amount than was displayed (409) rather than falling
      // back to the base ID, which is the defect this replaces.
      await startStripeCheckout({
        billingPeriod: period,
        pricePoint: period === 'yearly' ? pricing?.price_yearly : pricing?.price_monthly,
      });
      // redirects on success — code below only runs on error
    } catch (err) {
      setCheckoutError(err.message || 'Something went wrong. Please try again.');
      setCheckoutLoading(false);
      trackEvent('CHECKOUT_ERROR', { plan: 'pro', billing_period: period, error: err.message });
    }
  }

  function handleClose() {
    trackEvent('UPGRADE_ABANDONED', { step: 'pricing_screen', trigger });
    onClose?.();
  }

  return (
    <>
    {showAuthModal && (
      <AuthModal
        billingPeriod={billingPeriod}
        onSuccess={() => {
          setShowAuthModal(false);
          handleCheckout(billingPeriod);
        }}
        onClose={() => setShowAuthModal(false)}
      />
    )}
    <div className="pricing-screen-overlay" onClick={handleClose}>
      <div className="pricing-screen" onClick={e => e.stopPropagation()}>

        <button className="pricing-screen__close" onClick={handleClose} type="button" aria-label="Close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>

        <p className="pricing-screen__eyebrow">UNLOCK THE FULL SYSTEM</p>
        <h2 className="pricing-screen__title">
          {checkoutLoading ? 'Redirecting to checkout…' : 'Pro plan.\nUnlimited analyses.'}
        </h2>
        <p className="pricing-screen__subtitle">Cancel anytime. No per-use limits.</p>

        {/* Checkout error */}
        {checkoutError && (
          <p className="pricing-screen__error">{checkoutError}</p>
        )}

        {/* Billing toggle */}
        <div className="pricing-screen__toggle">
          <button
            className={`pricing-screen__toggle-btn${billingPeriod === 'monthly' ? ' pricing-screen__toggle-btn--active' : ''}`}
            onClick={() => handlePeriodToggle('monthly')}
            type="button"
          >Monthly</button>
          <button
            className={`pricing-screen__toggle-btn${billingPeriod === 'yearly' ? ' pricing-screen__toggle-btn--active' : ''}`}
            onClick={() => handlePeriodToggle('yearly')}
            type="button"
          >
            Yearly
            {pricing.yearly_discount_pct && (
              <span className="pricing-screen__toggle-badge">Save {pricing.yearly_discount_pct}%</span>
            )}
          </button>
        </div>

        {/* Tier cards — mobile: Pro first */}
        <div className="pricing-screen__grid">
          <PricingTierCard tier="free"   pricing={pricing} billingPeriod={billingPeriod} onSelect={handleSelect} isCurrent loading={checkoutLoading} />
          <PricingTierCard tier="pro"    pricing={pricing} billingPeriod={billingPeriod} onSelect={handleSelect} loading={checkoutLoading} />
          <PricingTierCard tier="studio" pricing={pricing} billingPeriod={billingPeriod} onSelect={handleSelect} loading={checkoutLoading} />
        </div>

        {/* Trust bar */}
        <p className="pricing-screen__trust">
          🔒  Secure checkout via Stripe · Cancel anytime
        </p>

        {/* FAQ */}
        <div className="pricing-screen__faq">
          {[
            ['What counts as an analysis?', 'Each time you run the wizard or upload a reference photo, that\'s one analysis. Free accounts get 3 per session.'],
            ['Does it work with my gear?', 'Yes — you tell NGW what lights and modifiers you own, and it builds setups using only your kit.'],
            ['What\'s Shoot Mode?', 'A live comparison tool: upload your test shot, see exactly what to adjust to match the target setup.'],
            ['Can I cancel?', 'Any time. No questions, no fees. Your saved setups stay accessible for 30 days after cancellation.'],
          ].map(([q, a], i) => (
            <details key={i} className="pricing-screen__faq-item">
              <summary className="pricing-screen__faq-q">{q}</summary>
              <p className="pricing-screen__faq-a">{a}</p>
            </details>
          ))}
        </div>

      </div>
    </div>
    </>
  );
}
