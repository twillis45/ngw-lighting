/**
 * AuthModal — lightweight inline auth overlay for the upgrade flow.
 *
 * Shows over PricingScreen when user clicks upgrade without being signed in.
 * On successful auth, calls onSuccess() so the caller can proceed to checkout.
 *
 * Supports:
 *   - Sign in (email + password)
 *   - Create account (email + name + password)
 *   - Magic link (email only, passwordless)
 *   - Google One Tap
 */

import { useState, useEffect, useRef } from 'react';
import { useDispatch } from '../context/AppContext';
import { register, login, saveAuth } from '../data/authApi';
import { probeAndEnableLab } from '../data/labApi';

// Was `import.meta.env.VITE_GOOGLE_CLIENT_ID`, read at BUILD time and never
// set — so this resolved to '' in every shipped bundle and the guard at the
// top of GoogleButton returned immediately. The Google button in the UPGRADE
// flow has therefore never rendered, silently, with no error anywhere.
//
// The login screen had the same defect and was fixed on 2026-08-29 by asking
// the SERVER (/api/auth/providers) instead. Doing the same here: one source of
// truth, no build-time coupling, and the button cannot silently vanish because
// someone rebuilt without an env var. If the server says Google is not
// configured, the button is absent rather than inert — which is the rule this
// project keeps relearning: a control that cannot work should not render.

// ── Google One Tap ────────────────────────────────────────────────────────────

function loadGsiScript(callback) {
  if (window.google?.accounts?.id) { callback(); return; }
  const existing = document.getElementById('gsi-script');
  if (existing) { existing.addEventListener('load', callback); return; }
  const s = document.createElement('script');
  s.id = 'gsi-script';
  s.src = 'https://accounts.google.com/gsi/client';
  s.async = true;
  s.defer = true;
  s.onload = callback;
  document.head.appendChild(s);
}

function GoogleButton({ onCredential, disabled, renderDivider }) {
  const ref = useRef(null);
  const [clientId, setClientId] = useState(null);

  // Ask the server which providers are actually usable. Absent, misconfigured
  // and unreachable all resolve the same way — no button. Failing closed is
  // the only safe default for a control whose defect was rendering with
  // nothing behind it.
  useEffect(() => {
    let alive = true;
    fetch('/api/auth/providers')
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (alive && d && d.google && d.google_client_id) setClientId(d.google_client_id);
      })
      .catch(() => { /* no button */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!clientId || !ref.current) return;
    loadGsiScript(() => {
      if (!window.google?.accounts?.id) return;
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: ({ credential }) => onCredential(credential),
        auto_select: false,
        cancel_on_tap_outside: true,
      });
      window.google.accounts.id.renderButton(ref.current, {
        type: 'standard',
        shape: 'rectangular',
        theme: 'filled_black',
        text: 'continue_with',
        size: 'large',
        width: ref.current.offsetWidth || 320,
        logo_alignment: 'left',
      });
    });
  }, [onCredential, clientId]);

  // Nothing until the server confirms Google is configured.
  if (!clientId) return null;
  return (
    <>
      <div
        ref={ref}
        className="auth-modal__google-btn"
        style={{ opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? 'none' : 'auto' }}
      />
      {renderDivider && (
        <div className="auth-modal__divider"><span>or</span></div>
      )}
    </>
  );
}

// ── Magic Link Flow ───────────────────────────────────────────────────────────

function MagicLinkForm({ onClose }) {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await fetch('/api/auth/magic-link/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      }).then(async r => {
        if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed'); }
      });
      setSent(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (sent) {
    return (
      <div className="auth-modal__magic-sent">
        <svg width="40" height="40" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <circle cx="24" cy="24" r="24" fill="rgba(200,169,110,0.15)"/>
          <path d="M6 24l10 10L42 12" stroke="#C8A96E" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
        </svg>
        <p className="auth-modal__magic-sent-title">Check your email</p>
        <p className="auth-modal__magic-sent-sub">We sent a sign-in link to <strong>{email}</strong></p>
        <p className="auth-modal__magic-sent-hint">The link expires in 15 minutes. You can close this window.</p>
        <button className="auth-modal__back-link" type="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="auth-modal__magic-form">
      <p className="auth-modal__magic-desc">Enter your email and we'll send a one-click sign-in link — no password needed.</p>
      {error && <div className="auth-card__error">{error}</div>}
      <div className="auth-form__field">
        <label className="auth-form__label" htmlFor="ml-email">Email</label>
        <input
          id="ml-email"
          className="auth-form__input"
          type="email"
          placeholder="you@example.com"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          autoFocus
          autoComplete="email"
        />
      </div>
      <button className="auth-form__submit" type="submit" disabled={loading}>
        {loading ? 'Sending…' : 'Send magic link'}
      </button>
    </form>
  );
}

// ── Main Modal ────────────────────────────────────────────────────────────────

export default function AuthModal({ onSuccess, onClose, billingPeriod }) {
  const dispatch              = useDispatch();
  const [mode, setMode]       = useState('login');   // 'login' | 'register' | 'magic'
  const [email, setEmail]     = useState('');
  const [name, setName]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]     = useState(null);
  const [loading, setLoading] = useState(false);

  // Persist upgrade intent in sessionStorage so we can restore after
  // a magic-link return or a page navigation
  useEffect(() => {
    try {
      sessionStorage.setItem('ngw_upgrade_intent', JSON.stringify({ billingPeriod }));
    } catch { /* ignore */ }
  }, [billingPeriod]);

  function switchMode(m) { setMode(m); setError(null); }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user = mode === 'register'
        ? await register(email, name, password)
        : await login(email, password);
      dispatch({ type: 'SET_USER', user });
      await probeAndEnableLab().catch(() => {});
      // Clear upgrade intent — we're about to proceed to checkout
      try { sessionStorage.removeItem('ngw_upgrade_intent'); } catch { /* ignore */ }
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleCredential(credential) {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Google sign-in failed');
      saveAuth(data.token, data.user);
      dispatch({ type: 'SET_USER', user: data.user });
      await probeAndEnableLab().catch(() => {});
      try { sessionStorage.removeItem('ngw_upgrade_intent'); } catch { /* ignore */ }
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="auth-modal" role="dialog" aria-modal="true" aria-label="Sign in to continue">

        <button className="auth-modal__close" type="button" onClick={onClose} aria-label="Close">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>

        <div className="auth-modal__header">
          <p className="auth-modal__eyebrow">One more step</p>
          <h2 className="auth-modal__title">
            {mode === 'login'    ? 'Sign in to continue'
            : mode === 'register' ? 'Create your account'
            :                       'Sign in with a link'}
          </h2>
          <p className="auth-modal__sub">
            {mode === 'login'    ? 'Your subscription will be tied to this account.'
            : mode === 'register' ? 'You\'ll be taken to checkout right after.'
            :                       'We\'ll email you a one-click sign-in link.'}
          </p>
        </div>

        {mode === 'magic' ? (
          <MagicLinkForm onClose={onClose} />
        ) : (
          <>
            {/* Google button. The parent no longer decides whether to show
                it — GoogleButton asks the server and returns null when Google
                is not configured, and the divider follows it, so an absent
                provider leaves no orphaned "or" rule floating above nothing. */}
            <GoogleButton
              onCredential={handleGoogleCredential}
              disabled={loading}
              renderDivider
            />

            {error && <div className="auth-card__error">{error}</div>}

            {/* Tab switcher */}
            <div className="auth-modal__tabs">
              <button
                type="button"
                className={`auth-modal__tab${mode === 'login' ? ' auth-modal__tab--active' : ''}`}
                onClick={() => switchMode('login')}
              >Sign In</button>
              <button
                type="button"
                className={`auth-modal__tab${mode === 'register' ? ' auth-modal__tab--active' : ''}`}
                onClick={() => switchMode('register')}
              >Create Account</button>
            </div>

            <form onSubmit={handleSubmit} className="auth-form">
              <div className="auth-form__field">
                <label className="auth-form__label" htmlFor="am-email">Email</label>
                <input
                  id="am-email"
                  className="auth-form__input"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  autoFocus
                  autoComplete="email"
                />
              </div>

              {mode === 'register' && (
                <div className="auth-form__field">
                  <label className="auth-form__label" htmlFor="am-name">Name</label>
                  <input
                    id="am-name"
                    className="auth-form__input"
                    type="text"
                    placeholder="Your name"
                    value={name}
                    onChange={e => setName(e.target.value)}
                    required
                    minLength={2}
                    maxLength={32}
                    autoComplete="name"
                  />
                </div>
              )}

              <div className="auth-form__field">
                <label className="auth-form__label" htmlFor="am-password">Password</label>
                <input
                  id="am-password"
                  className="auth-form__input"
                  type="password"
                  placeholder={mode === 'register' ? 'Create a password' : 'Your password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  minLength={6}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                />
              </div>

              <button className="auth-form__submit" type="submit" disabled={loading}>
                {loading
                  ? 'Please wait…'
                  : mode === 'login'
                    ? 'Sign In & Continue to Checkout'
                    : 'Create Account & Continue'}
              </button>
            </form>

            <button
              className="auth-modal__magic-link-cta"
              type="button"
              onClick={() => switchMode('magic')}
            >
              Use a magic link instead →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
