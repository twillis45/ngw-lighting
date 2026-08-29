/**
 * StudioLoginScreen — Studio Matte design
 * Login / Register gate for Day1DemoApp.
 * Design language: exact match to SetupScreen / ResultScreen token palette.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { tapHaptic, successHaptic, warnHaptic, grainHaptic } from '../../../utils/haptics';
import { softClickSound, navSlideSound } from '../../../utils/sounds';
import { login, register, saveAuth } from '../../../data/authApi';
import MatteBackground from '../_shared/MatteBackground';

// ─── Studio Matte Token Palette ──────────────────────────────────────────────
const steel = (a) => `rgba(132, 158, 184,${a})`;

const C = {
  bg:          '#0B0B0C',
  panelBg:     '#0f1013',
  fieldBg:     '#0a0b0d',
  ctaFrom:     '#3d404d',
  ctaMid:      '#292b36',
  ctaTo:       '#1c1d24',
  textPrimary: 'rgba(245,247,250,0.95)',
  textSub:     'rgba(184,191,199,0.65)',
  textMeta:    '#a7adb7',
  textDim:     'rgba(184,191,199,0.5)',
  errorRed:    'rgba(230,85,85,0.9)',
  divider:     'rgba(255,255,255,0.04)',
};

const CTA_BG     = `linear-gradient(141.71deg, ${C.ctaFrom} 0%, ${C.ctaMid} 50%, ${C.ctaTo} 100%)`;
const CTA_SHADOW = `0px 0px 6px 1px ${steel(0.08)}, 1px 2px 4px 0px rgba(0,0,0,0.45), 2px 5px 12px 0px rgba(0,0,0,0.7)`;
const CTA_BEVEL  = 'inset -1px -1px 2px 0px rgba(0,0,0,0.3), inset 1px 1px 0px 0px rgba(255,255,255,0.2)';

const PANEL_SHADOW = '1px 2px 4px 0px rgba(0,0,0,0.2), 2px 4px 12px 0px rgba(0,0,0,0.4)';
const PANEL_BEVEL  = 'inset -1px -1px 2px 0px rgba(0,0,0,0.12), inset 1px 1px 0px 0px rgba(255,255,255,0.05)';

const FIELD_SHADOW       = 'inset 0px 1px 3px 0px rgba(0,0,0,0.6), inset 0px 0px 8px 0px rgba(0,0,0,0.3), inset 1px 1px 2px 0px rgba(0,0,0,0.4)';
const FIELD_SHADOW_FOCUS = `inset 0px 1px 3px 0px rgba(0,0,0,0.6), inset 0px 0px 8px 0px rgba(0,0,0,0.3), inset 1px 1px 2px 0px rgba(0,0,0,0.4), 0px 0px 0px 1px ${steel(0.35)}`;

const FONT_SMOOTH = {
  WebkitFontSmoothing: 'antialiased',
  MozOsxFontSmoothing: 'grayscale',
  textRendering: 'geometricPrecision',
};

// ─── Eye icon — show/hide password ───────────────────────────────────────────
function EyeIcon({ open }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke={steel(0.75)} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {open ? (
        <>
          <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
          <circle cx="12" cy="12" r="3" />
        </>
      ) : (
        <>
          <path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-11-7-11-7a19.6 19.6 0 0 1 5.06-5.94" />
          <path d="M9.9 4.24A10.05 10.05 0 0 1 12 4c7 0 11 7 11 7a19.6 19.6 0 0 1-3.17 4.19" />
          <path d="M14.12 14.12A3 3 0 1 1 9.88 9.88" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </>
      )}
    </svg>
  );
}

// ─── Inline spinner — SVG-native rotation, no CSS keyframes needed ───────────
function Spinner() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" style={{ marginRight: 8, flexShrink: 0 }}>
      <circle cx="12" cy="12" r="9" stroke="rgba(245,247,250,0.22)" strokeWidth="2.4" fill="none" />
      <path d="M21 12 A9 9 0 0 0 12 3" stroke="rgba(245,247,250,0.92)" strokeWidth="2.4" fill="none" strokeLinecap="round">
        <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.85s" repeatCount="indefinite" />
      </path>
    </svg>
  );
}

// ─── Validation primitives ───────────────────────────────────────────────────
// RFC-light email check — pragmatic, not exhaustive. Catches the common typos
// (missing @, missing TLD, trailing space) without rejecting odd-but-valid
// addresses that real photographers actually use.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
function isValidEmail(s) {
  return EMAIL_RE.test((s || '').trim());
}
const MIN_PASSWORD_LEN = 8;
const MIN_USERNAME_LEN = 3;
const USERNAME_RE = /^[a-zA-Z0-9_.-]+$/;

function InsetField({
  label, value, onChange, placeholder, type = 'text', disabled,
  onSubmit, autoFocus, rightAction,
  fieldError, hint, onCapsLockChange,
}) {
  const [focused, setFocused] = useState(false);
  const [touched, setTouched] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (autoFocus && ref.current) {
      // Slight delay so the panel transition doesn't fight the focus.
      const t = setTimeout(() => ref.current && ref.current.focus(), 120);
      return () => clearTimeout(t);
    }
  }, [autoFocus]);
  // Show a field error only after the user has left the field having typed
  // nothing valid — never on first paint. `touched` is set on blur, so
  // `touched || !focused` was true before the input had ever been focused,
  // and every field rendered "required" the moment the form appeared.
  // The `!focused` half still earns its place: it hides the error again
  // while the user is back in the field fixing it.
  const showError = !!fieldError && touched && !focused;
  const errorRing = showError ? `, 0px 0px 0px 1px rgba(230,85,85,0.55)` : '';
  return (
    <div style={{ marginBottom: 16 }}>
      <p style={{ margin: '0 0 8px', fontSize: 12, fontWeight: 600, color: steel(0.65), letterSpacing: '1px', ...FONT_SMOOTH }}>
        {label}
      </p>
      <div style={{ position: 'relative' }}>
        <input
          ref={ref}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); setTouched(true); }}
          onKeyDown={(e) => {
            if (onCapsLockChange && typeof e.getModifierState === 'function') {
              onCapsLockChange(e.getModifierState('CapsLock'));
            }
            if (e.key === 'Enter' && onSubmit) {
              e.preventDefault();
              onSubmit();
            }
          }}
          onKeyUp={(e) => {
            if (onCapsLockChange && typeof e.getModifierState === 'function') {
              onCapsLockChange(e.getModifierState('CapsLock'));
            }
          }}
          autoComplete={type === 'password' ? 'current-password' : type === 'email' ? 'email' : 'username'}
          style={{
            display: 'block',
            width: '100%',
            padding: rightAction ? '12px 42px 12px 14px' : '12px 14px',
            backgroundColor: C.fieldBg,
            border: 'none',
            borderRadius: 10,
            boxShadow: (focused ? FIELD_SHADOW_FOCUS : FIELD_SHADOW) + errorRing,
            color: C.textPrimary,
            fontSize: 15,
            fontWeight: 500,
            fontFamily: 'inherit',
            outline: 'none',
            boxSizing: 'border-box',
            transition: 'box-shadow 0.18s ease',
            opacity: disabled ? 0.5 : 1,
            ...FONT_SMOOTH,
          }}
        />
        {rightAction && (
          <div style={{
            position: 'absolute',
            right: 8, top: '50%', transform: 'translateY(-50%)',
            display: 'flex', alignItems: 'center',
          }}>
            {rightAction}
          </div>
        )}
      </div>
      {(showError || hint) && (
        <p style={{
          margin: '6px 2px 0', fontSize: 13, fontWeight: 500,
          color: showError ? C.errorRed : steel(0.55),
          letterSpacing: '0.1px', lineHeight: 1.35,
          ...FONT_SMOOTH,
        }}>
          {showError ? fieldError : hint}
        </p>
      )}
    </div>
  );
}

export default function StudioLoginScreen({ onLogin, onAccuracy }) {
  const [mode, setMode] = useState('login'); // 'login' | 'register' | 'forgot' | 'reset'
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ctaPressed, setCtaPressed] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);
  //: Password reset (8/29). The endpoints and the URL plumbing already
  //: existed — /api/auth/password-reset/{request,confirm} are implemented,
  //: and main.jsx already stashes ?reset_token into sessionStorage for any
  //: shell to pick up. Only this screen was never wired, so the control
  //: rendered and did nothing.
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetToken, setResetToken] = useState(null);
  const [forgotSent, setForgotSent] = useState(false);
  //: Google Sign-In (8/29). The button renders ONLY once the server says a
  //: client ID is configured. That is deliberate: the control cannot drift
  //: back into rendering with nothing behind it, which is the stage-4 P0.
  const [googleReady, setGoogleReady] = useState(false);
  const googleIdRef = useRef(null);
  const googleBtnRef = useRef(null);

  //: Ask the server which providers are actually usable. Absent, misconfigured
  //: or unreachable all resolve the same way — no button. Failing closed is the
  //: only safe default for a control whose whole defect was existing when its
  //: backend did not.
  useEffect(() => {
    let alive = true;
    fetch('/api/auth/providers')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!alive || !d || !d.google || !d.google_client_id) return;
        googleIdRef.current = d.google_client_id;
        setGoogleReady(true);
      })
      .catch(() => { /* no provider button */ });
    return () => { alive = false; };
  }, []);

  //: Load Google Identity Services and hand it the button element. GIS renders
  //: its own control into the container — Google's branding rules require it,
  //: and it is what carries the One Tap / FedCM behaviour.
  useEffect(() => {
    if (!googleReady || !googleBtnRef.current) return;
    let alive = true;
    const init = () => {
      if (!alive || !window.google?.accounts?.id || !googleBtnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: googleIdRef.current,
        callback: async ({ credential }) => {
          setLoading(true);
          setError(null);
          try {
            const res = await fetch('/api/auth/google', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ credential }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Google sign-in failed.');
            saveAuth(data.token, data.user);
            successHaptic();
            onLogin(data.user);
          } catch (err) {
            warnHaptic();
            setError(err.message || 'Google sign-in failed.');
          } finally {
            setLoading(false);
          }
        },
      });
      googleBtnRef.current.innerHTML = '';
      window.google.accounts.id.renderButton(googleBtnRef.current, {
        theme: 'filled_black', size: 'large', shape: 'pill',
        text: 'continue_with', width: 320,
      });
    };
    if (window.google?.accounts?.id) { init(); return () => { alive = false; }; }
    const existing = document.getElementById('gsi-client');
    if (existing) { existing.addEventListener('load', init); return () => { alive = false; existing.removeEventListener('load', init); }; }
    const sc = document.createElement('script');
    sc.id = 'gsi-client';
    sc.src = 'https://accounts.google.com/gsi/client';
    sc.async = true; sc.defer = true;
    sc.onload = init;
    //: The script failing to load must not leave a dead button behind.
    sc.onerror = () => { if (alive) setGoogleReady(false); };
    document.head.appendChild(sc);
    return () => { alive = false; };
  }, [googleReady, onLogin]);

  //: Returning from the reset email. Same contract AuthScreen uses, so a
  //: link works whichever shell the user lands in.
  useEffect(() => {
    try {
      const t = sessionStorage.getItem('ngw_reset_token');
      if (t) {
        sessionStorage.removeItem('ngw_reset_token');
        setResetToken(t);
        setMode('reset');
      }
    } catch { /* sessionStorage unavailable — stay on login */ }
  }, []);

  // ── Field-level validation — runs every render off live state ──
  // Empty fields don't surface errors until the user has touched the input
  // (handled inside InsetField via the `touched` flag), so we always return
  // the full validation result here and the field decides when to show.
  const trimmedEmail = email.trim();
  const trimmedUsername = username.trim();
  const emailError = !trimmedEmail
    ? 'Email is required.'
    : !isValidEmail(trimmedEmail) ? 'Enter a valid email address.' : null;
  const passwordError = mode === 'forgot' ? null       // email only
    : !password
    ? 'Password is required.'
    : ((mode === 'register' || mode === 'reset') && password.length < MIN_PASSWORD_LEN)
      ? `At least ${MIN_PASSWORD_LEN} characters.` : null;
  const confirmError = mode !== 'reset' ? null
    : !confirmPassword ? 'Confirm your new password.'
    : confirmPassword !== password ? 'Passwords do not match.' : null;
  const emailErrorActive = mode === 'reset' ? null : emailError;
  const usernameError = mode !== 'register' ? null
    : !trimmedUsername ? 'Username is required.'
    : trimmedUsername.length < MIN_USERNAME_LEN ? `At least ${MIN_USERNAME_LEN} characters.`
    : !USERNAME_RE.test(trimmedUsername) ? 'Letters, numbers, . _ - only.'
    : null;
  const formInvalid = !!emailErrorActive || !!passwordError || !!confirmError || (mode === 'register' && !!usernameError);

  const handleSubmit = useCallback(async () => {
    if (emailErrorActive || passwordError || confirmError || (mode === 'register' && usernameError)) {
      warnHaptic();
      setError(emailErrorActive || usernameError || passwordError || confirmError);
      return;
    }
    setLoading(true);
    setError(null);
    softClickSound();
    try {
      //: Ask for a reset link. The endpoint always reports success so it
      //: cannot be used to enumerate accounts — so this screen must not
      //: claim the address was found either.
      if (mode === 'forgot') {
        const res = await fetch('/api/auth/password-reset/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email.trim() }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Could not send the reset link.');
        successHaptic();
        setForgotSent(true);
        return;
      }
      //: Set the new password against the emailed token, then sign in with
      //: the JWT it returns — no second trip through the login form.
      if (mode === 'reset') {
        const res = await fetch('/api/auth/password-reset/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: resetToken, new_password: password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'That reset link is invalid or has expired.');
        saveAuth(data.token, data.user);
        successHaptic();
        onLogin(data.user);
        return;
      }
      let user;
      if (mode === 'login') {
        user = await login(email.trim(), password);
      } else {
        user = await register(email.trim(), username.trim(), password);
      }
      successHaptic();
      onLogin(user);
    } catch (err) {
      warnHaptic();
      setError(err.message || 'Authentication failed.');
    } finally {
      setLoading(false);
    }
  }, [mode, email, username, password, confirmPassword, resetToken, onLogin,
      emailErrorActive, passwordError, confirmError, usernameError, trimmedEmail, trimmedUsername]);

  const switchMode = useCallback(() => {
    navSlideSound();
    tapHaptic();
    setMode(m => m === 'login' ? 'register' : 'login');
    setError(null);
  }, []);

  const handleForgotPassword = useCallback(() => {
    navSlideSound();
    tapHaptic();
    setMode('forgot');
    setError(null);
    setForgotSent(false);
  }, []);

  //: Any exit from forgot/reset returns to a clean login form.
  const backToLogin = useCallback(() => {
    navSlideSound();
    tapHaptic();
    setMode('login');
    setError(null);
    setForgotSent(false);
    setPassword('');
    setConfirmPassword('');
  }, []);

  return (
    <div style={{
      position: 'fixed', inset: 0, backgroundColor: C.bg,
      overflow: 'auto',
      fontFamily: 'Inter, system-ui, sans-serif',
    }}>
      <div
        onTouchStart={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
        onTouchMove={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
        style={{
        width: '100%', maxWidth: 430, height: '100%',
        margin: '0 auto', backgroundColor: C.bg,
        boxShadow: '2px 4px 40px rgba(0,0,0,0.6), -1px -1px 1px rgba(255,255,255,0.02)',
        overflowY: 'auto',
        position: 'relative',
        display: 'flex', flexDirection: 'column',
      }}>
        <MatteBackground variant="carbon" />

        {/* ── Photography DNA — faint modifier silhouette in the background.
             A softbox outline at 3% opacity says "this was made for photographers"
             without competing with the form. Positioned upper-right to balance
             the left-aligned wordmark. ── */}
        <svg viewBox="0 0 200 240" fill="none" style={{
          position: 'fixed', top: '8%', right: '6%', width: 180, height: 220,
          opacity: 0.025, pointerEvents: 'none', zIndex: 0,
        }}>
          {/* Softbox outline — the universal studio photography icon */}
          <rect x="30" y="20" width="140" height="160" rx="12" stroke={steel(1)} strokeWidth="1.5" fill="none" />
          <rect x="50" y="40" width="100" height="120" rx="6" stroke={steel(1)} strokeWidth="0.8" fill="none" />
          {/* Speed ring */}
          <circle cx="100" cy="200" r="18" stroke={steel(1)} strokeWidth="1" fill="none" />
          <line x1="100" y1="180" x2="100" y2="182" stroke={steel(1)} strokeWidth="0.8" />
          {/* Mount stem */}
          <line x1="100" y1="218" x2="100" y2="240" stroke={steel(1)} strokeWidth="1.2" />
        </svg>

        {/* ── Wordmark — original order: "No Guesswork" hero with "LIGHTING"
             small caps directly underneath, plus tagline ── */}
        <div style={{ position: 'relative', zIndex: 1, padding: 'max(28px, 5vh) 28px 0' }}>
          <p style={{
            margin: 0, fontWeight: 800, fontSize: 30, lineHeight: '34px',
            color: 'rgba(245,247,250,0.94)', letterSpacing: '-0.6px',
            ...FONT_SMOOTH,
          }}>No Guesswork</p>
          <p style={{
            margin: '4px 0 0 1px', fontWeight: 800, fontSize: 11.5, lineHeight: '13px',
            color: 'rgba(145,168,190,0.95)', letterSpacing: '4px',
            textShadow: `0 0 4px ${steel(0.18)}`,
            ...FONT_SMOOTH,
          }}>LIGHTING</p>
          <p style={{
            margin: '10px 0 0', fontSize: 14, fontWeight: 400,
            color: steel(0.7), letterSpacing: '0.2px', lineHeight: 1.5,
            ...FONT_SMOOTH,
          }}>Reverse-engineer portrait lighting. See the setup behind the shot.</p>
          {/* Was: "Reverse-engineer any portrait. Nail the shot, every time."
              Claim ledger #5, FALSE: the corpus resolves 18/34 exactly and the
              proof page one tap away publishes its own misses. A buyer needs a
              single miss to disprove "every time", and we hand them two.
              #6: "any portrait" is UNPROVEN — 34 in-house images, 23 of them
              monochrome, nothing external. See docs/CLAIM_LEDGER.md. */}
        </div>

        {/* ── Content ── */}
        <div style={{ flex: 1, padding: 'max(20px, 3vh) 25px 32px', position: 'relative', zIndex: 1 }}>

          {/* Heading */}
          <p style={{
            margin: '0 0 4px',
            fontWeight: 800, fontSize: 26, lineHeight: '32px',
            color: C.textPrimary, letterSpacing: '-0.3px',
            ...FONT_SMOOTH,
          }}>{mode === 'forgot' ? 'Reset Password'
             : mode === 'reset' ? 'Set a New Password'
             : mode === 'login' ? 'Sign In' : 'Create Account'}</p>
          <p style={{
            margin: '0 0 28px',
            fontSize: 13, fontWeight: 400, color: C.textSub, lineHeight: 1.5,
            ...FONT_SMOOTH,
          }}>
            {mode === 'forgot'
              ? 'Enter the email on the account and we will send a reset link.'
              : mode === 'reset'
              ? 'Choose a new password. You will be signed in straight after.'
              : mode === 'login'
              ? 'Pick up where the last shoot left off.'
              : 'Your reference library starts here.'}
          </p>

          {/* Form panel — single bevel layer (deduplicated) */}
          <div style={{
            borderRadius: 14,
            backgroundColor: C.panelBg,
            boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
            padding: '20px 20px 4px',
            position: 'relative', marginBottom: 14,
          }}>
            {mode !== 'reset' && (
              <InsetField
                label="EMAIL" value={email} onChange={setEmail}
                placeholder="you@example.com" type="email" disabled={loading}
                onSubmit={handleSubmit} autoFocus
                fieldError={emailErrorActive}
              />
            )}
            {/* Animated username slot — appears in register mode without snap */}
            <div style={{
              maxHeight: mode === 'register' ? 110 : 0,
              opacity: mode === 'register' ? 1 : 0,
              overflow: 'hidden',
              transition: 'max-height 0.28s ease, opacity 0.22s ease',
            }}>
              <InsetField
                label="USERNAME" value={username} onChange={setUsername}
                placeholder="handle" type="text"
                disabled={loading || mode !== 'register'}
                onSubmit={handleSubmit}
                fieldError={mode === 'register' ? usernameError : null}
                hint={mode === 'register' ? '3+ chars, letters/numbers/._-' : null}
              />
            </div>
            {mode !== 'forgot' && (
            <InsetField
              label={mode === 'reset' ? 'NEW PASSWORD' : 'PASSWORD'} value={password} onChange={setPassword}
              placeholder="••••••••"
              type={showPassword ? 'text' : 'password'}
              disabled={loading}
              onSubmit={handleSubmit}
              fieldError={passwordError}
              hint={(mode === 'register' || mode === 'reset') && !passwordError ? `At least ${MIN_PASSWORD_LEN} characters` : null}
              onCapsLockChange={setCapsLockOn}
              rightAction={
                <button
                  type="button"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  onClick={() => { tapHaptic(); setShowPassword(s => !s); }}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer', padding: 6,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  <EyeIcon open={showPassword} />
                </button>
              }
            />
            )}
            {/* Confirm — reset mode only. The mismatch is caught before the
                request goes out, so a typo never costs a round trip. */}
            {mode === 'reset' && (
              <InsetField
                label="CONFIRM PASSWORD" value={confirmPassword} onChange={setConfirmPassword}
                placeholder="••••••••"
                type={showPassword ? 'text' : 'password'}
                disabled={loading}
                onSubmit={handleSubmit}
                fieldError={confirmError}
              />
            )}
            {/* Caps Lock notice — surfaces only while the user is actively
                typing into the password field with caps lock on */}
            {capsLockOn && (
              <div style={{
                margin: '-6px 2px 14px',
                display: 'flex', alignItems: 'center', gap: 6,
                fontSize: 13, fontWeight: 600,
                color: 'rgba(245,200,120,0.92)',
                letterSpacing: '0.3px',
                ...FONT_SMOOTH,
              }}>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                  stroke="rgba(245,200,120,0.92)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3 4 11h4v6h8v-6h4z" />
                </svg>
                Caps Lock is on
              </div>
            )}
          </div>

          {/* Forgot password — login mode only */}
          {mode === 'login' && !forgotSent && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
              <button
                onClick={handleForgotPassword}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: 14, fontWeight: 500, color: steel(0.7),
                  padding: '4px 2px', letterSpacing: '0.2px',
                  WebkitTapHighlightColor: 'transparent',
                  ...FONT_SMOOTH,
                }}
              >
                Forgot password?
              </button>
            </div>
          )}

          {/* Error */}
          {error && (
            <p style={{
              margin: '0 0 16px', fontSize: 14, fontWeight: 500,
              color: C.errorRed, lineHeight: 1.4,
              ...FONT_SMOOTH,
            }}>{error}</p>
          )}

          {/* Reset link sent. The endpoint always reports success so it cannot
              be used to enumerate accounts; this copy keeps that promise
              instead of confirming the address was found. */}
          {forgotSent && (
            <div style={{
              borderRadius: 14, backgroundColor: C.panelBg,
              boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
              padding: '18px 20px', marginBottom: 14,
            }}>
              <p style={{
                margin: '0 0 6px', fontSize: 14, fontWeight: 600,
                color: C.textPrimary, ...FONT_SMOOTH,
              }}>Check your email</p>
              <p style={{
                margin: 0, fontSize: 13, fontWeight: 400,
                color: C.textSub, lineHeight: 1.5, ...FONT_SMOOTH,
              }}>If <span style={{ color: C.textMeta }}>{email.trim()}</span> has an account, a reset link is on its way. The link expires, so use it soon.</p>
            </div>
          )}

          {/* CTA — hidden once the link is away; there is nothing left to submit */}
          {!forgotSent && (
          <button
            onClick={handleSubmit}
            onPointerDown={() => { if (!loading) { setCtaPressed(true); tapHaptic(); } }}
            onPointerUp={() => setCtaPressed(false)}
            onPointerLeave={() => setCtaPressed(false)}
            disabled={loading}
            style={{
              width: '100%', height: 52, borderRadius: 24,
              background: CTA_BG,
              boxShadow: ctaPressed ? 'inset 0px 2px 4px rgba(0,0,0,0.5)' : `${CTA_SHADOW}, ${CTA_BEVEL}`,
              border: 'none', cursor: loading ? 'default' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              WebkitTapHighlightColor: 'transparent',
              transform: ctaPressed ? 'scale(0.98)' : 'scale(1)',
              transition: 'transform 0.1s ease, box-shadow 0.1s ease',
              opacity: loading ? 0.85 : (formInvalid ? 0.55 : 1),
              marginBottom: 14,
            }}
          >
            {loading && <Spinner />}
            <span style={{
              fontSize: 15, fontWeight: 600,
              color: 'rgba(245,247,250,0.9)',
              letterSpacing: '0.5px',
              pointerEvents: 'none',
              ...FONT_SMOOTH,
            }}>
              {loading
                ? (mode === 'forgot' ? 'Sending…' : mode === 'reset' ? 'Saving…'
                   : mode === 'login' ? 'Signing In…' : 'Creating Account…')
                : (mode === 'forgot' ? 'Send Reset Link' : mode === 'reset' ? 'Set Password'
                   : mode === 'login' ? 'Sign In' : 'Create Account')}
            </span>
          </button>

          )}

          {/* Back out of the reset flow. Without this the only exit from
              forgot/reset is a page reload. */}
          {(mode === 'forgot' || mode === 'reset') && (
            <button
              onClick={backToLogin}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 14, fontWeight: 500, color: C.textMeta,
                padding: '4px 0', display: 'block', width: '100%', textAlign: 'center',
                WebkitTapHighlightColor: 'transparent',
                ...FONT_SMOOTH,
              }}
            >Back to sign in</button>
          )}

          {/* OR divider + Google. Apple was REMOVED 2026-08-29: it had no route,
              no config and no code anywhere, and standing it up needs a paid
              Apple Developer membership. Deferral recorded in
              PROMOTION-DEFERRED.md, due at iOS launch — Apple requires Sign in
              with Apple of App Store apps offering any third-party sign-in.
              The whole block hides when no provider is configured, so the OR
              rule never floats above nothing. */}
          {(mode === 'login' || mode === 'register') && googleReady && (<>
          <div style={{
            display: 'flex', alignItems: 'center',
            margin: '6px 0 12px',
            gap: 10,
          }}>
            <div style={{ flex: 1, height: 1, background: C.divider }} />
            <span style={{
              fontSize: 9, fontWeight: 600, color: steel(0.5),
              letterSpacing: '1.6px',
              ...FONT_SMOOTH,
            }}>OR</span>
            <div style={{ flex: 1, height: 1, background: C.divider }} />
          </div>
          {/* Google Identity Services renders its own button in here. We do
              not draw our own: Google's branding terms require theirs, and a
              hand-drawn one was exactly how this control came to exist with no
              backend behind it. */}
          <div ref={googleBtnRef} style={{
            display: 'flex', justifyContent: 'center', marginBottom: 10, minHeight: 44,
          }} />
          </>)}

          {/* Mode toggle */}
          {(mode === 'login' || mode === 'register') && (
          <button
            onClick={switchMode}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: 500, color: C.textMeta,
              padding: '4px 0', display: 'block', width: '100%', textAlign: 'center',
              WebkitTapHighlightColor: 'transparent',
              ...FONT_SMOOTH,
            }}
          >
            {mode === 'login' ? "Don't have an account? Create one" : 'Already have an account? Sign in'}
          </button>
          )}

          {/* Proof before signup — Gate Zero G0.3. Every scored reference
              read against verified truth, misses included, no account. */}
          {onAccuracy && (
            <button
              type="button"
              // The email field autofocuses. Without this, the first press
              // blurs it, validation renders "Email is required", the layout
              // shifts, and the button moves out from under the pointer
              // before `click` fires -- so the FIRST tap is silently
              // swallowed and only the second works. preventDefault on
              // mousedown stops the focus change, so nothing shifts.
              onMouseDown={e => e.preventDefault()}
              onClick={onAccuracy}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: 500, color: steel(0.5),
                padding: '10px 0 4px', display: 'block', width: '100%', textAlign: 'center',
                WebkitTapHighlightColor: 'transparent',
                ...FONT_SMOOTH,
              }}
            >
              See how accurate it is first &rarr;
            </button>
          )}

          {/* Legal — register mode only */}
          {mode === 'register' && (
            <p style={{
              margin: '14px 16px 0', fontSize: 12, fontWeight: 400,
              color: steel(0.5), lineHeight: 1.5, textAlign: 'center',
              ...FONT_SMOOTH,
            }}>
              By creating an account you agree to our Terms of Service and Privacy Policy.
            </p>
          )}
        </div>

        {/* iOS home indicator */}
        <div style={{ height: 34, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', zIndex: 1 }}>
          <div style={{ width: 134, height: 5, borderRadius: 3, backgroundColor: 'rgba(245,247,250,0.06)' }} />
        </div>
      </div>
    </div>
  );
}
