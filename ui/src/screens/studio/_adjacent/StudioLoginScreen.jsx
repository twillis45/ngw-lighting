/**
 * StudioLoginScreen — Studio Matte design
 * Login / Register gate for Day1DemoApp.
 * Design language: exact match to SetupScreen / ResultScreen token palette.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { tapHaptic, successHaptic, warnHaptic, grainHaptic } from '../../../utils/haptics';
import { softClickSound, navSlideSound } from '../../../utils/sounds';
import { login, register } from '../../../data/authApi';
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
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ctaPressed, setCtaPressed] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);

  // ── Field-level validation — runs every render off live state ──
  // Empty fields don't surface errors until the user has touched the input
  // (handled inside InsetField via the `touched` flag), so we always return
  // the full validation result here and the field decides when to show.
  const trimmedEmail = email.trim();
  const trimmedUsername = username.trim();
  const emailError = !trimmedEmail
    ? 'Email is required.'
    : !isValidEmail(trimmedEmail) ? 'Enter a valid email address.' : null;
  const passwordError = !password
    ? 'Password is required.'
    : (mode === 'register' && password.length < MIN_PASSWORD_LEN)
      ? `At least ${MIN_PASSWORD_LEN} characters.` : null;
  const usernameError = mode !== 'register' ? null
    : !trimmedUsername ? 'Username is required.'
    : trimmedUsername.length < MIN_USERNAME_LEN ? `At least ${MIN_USERNAME_LEN} characters.`
    : !USERNAME_RE.test(trimmedUsername) ? 'Letters, numbers, . _ - only.'
    : null;
  const formInvalid = !!emailError || !!passwordError || (mode === 'register' && !!usernameError);

  const handleSubmit = useCallback(async () => {
    if (emailError || passwordError || (mode === 'register' && usernameError)) {
      warnHaptic();
      setError(emailError || usernameError || passwordError);
      return;
    }
    setLoading(true);
    setError(null);
    softClickSound();
    try {
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
  }, [mode, email, username, password, onLogin, emailError, passwordError, usernameError, trimmedEmail, trimmedUsername]);

  const switchMode = useCallback(() => {
    navSlideSound();
    tapHaptic();
    setMode(m => m === 'login' ? 'register' : 'login');
    setError(null);
  }, []);

  const handleForgotPassword = useCallback(() => {
    tapHaptic();
    // TODO: route to password reset flow when backend endpoint exists.
  }, []);

  const handleAppleSignIn = useCallback(() => {
    tapHaptic();
    // TODO: wire Apple Sign-In; left as placeholder per safety rules
    // (no automated OAuth flow without explicit user authorization).
  }, []);

  const handleGoogleSignIn = useCallback(() => {
    tapHaptic();
    // TODO: wire Google Sign-In; left as placeholder per safety rules
    // (no automated OAuth flow without explicit user authorization).
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
          }}>{mode === 'login' ? 'Sign In' : 'Create Account'}</p>
          <p style={{
            margin: '0 0 28px',
            fontSize: 13, fontWeight: 400, color: C.textSub, lineHeight: 1.5,
            ...FONT_SMOOTH,
          }}>
            {mode === 'login'
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
            <InsetField
              label="EMAIL" value={email} onChange={setEmail}
              placeholder="you@example.com" type="email" disabled={loading}
              onSubmit={handleSubmit} autoFocus
              fieldError={emailError}
            />
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
            <InsetField
              label="PASSWORD" value={password} onChange={setPassword}
              placeholder="••••••••"
              type={showPassword ? 'text' : 'password'}
              disabled={loading}
              onSubmit={handleSubmit}
              fieldError={passwordError}
              hint={mode === 'register' && !passwordError ? `At least ${MIN_PASSWORD_LEN} characters` : null}
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
          {mode === 'login' && (
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

          {/* CTA */}
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
              {loading ? (mode === 'login' ? 'Signing In…' : 'Creating Account…') : (mode === 'login' ? 'Sign In' : 'Create Account')}
            </span>
          </button>

          {/* OR divider + Apple Sign In (placeholder — wiring deferred) */}
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
          <button
            onClick={handleAppleSignIn}
            style={{
              width: '100%', height: 46, borderRadius: 23,
              background: '#0a0b0d',
              boxShadow: `inset 0 0 0 1px ${steel(0.18)}, 1px 2px 6px rgba(0,0,0,0.5)`,
              border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              gap: 8,
              WebkitTapHighlightColor: 'transparent',
              marginBottom: 10,
              ...FONT_SMOOTH,
            }}
          >
            <svg width="14" height="16" viewBox="0 0 14 16" fill="rgba(245,247,250,0.92)">
              <path d="M11.6 8.5c0-2 1.6-3 1.7-3-0.9-1.4-2.4-1.5-2.9-1.6-1.2-0.1-2.4 0.7-3 0.7-0.6 0-1.6-0.7-2.6-0.7-1.3 0-2.6 0.8-3.3 2-1.4 2.4-0.4 6 1 8 0.7 1 1.5 2 2.6 2 1 0 1.4-0.7 2.7-0.7 1.2 0 1.6 0.7 2.7 0.7 1.1 0 1.8-1 2.5-2 0.8-1.1 1.1-2.2 1.1-2.3-0.1 0-2.5-0.9-2.5-3.1zM9.7 2.6c0.6-0.7 1-1.6 0.9-2.6-0.8 0-1.8 0.5-2.4 1.2-0.5 0.6-1 1.6-0.9 2.5 0.9 0.1 1.8-0.4 2.4-1.1z" />
            </svg>
            <span style={{
              fontSize: 15, fontWeight: 600,
              color: 'rgba(245,247,250,0.9)',
              letterSpacing: '0.2px',
            }}>Continue with Apple</span>
          </button>

          <button
            onClick={handleGoogleSignIn}
            style={{
              width: '100%', height: 46, borderRadius: 23,
              background: '#0a0b0d',
              boxShadow: `inset 0 0 0 1px ${steel(0.18)}, 1px 2px 6px rgba(0,0,0,0.5)`,
              border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              gap: 8,
              WebkitTapHighlightColor: 'transparent',
              marginBottom: 14,
              ...FONT_SMOOTH,
            }}
          >
            {/* Google "G" — official 4-color mark */}
            <svg width="16" height="16" viewBox="0 0 18 18">
              <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>
              <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
              <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>
              <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
            </svg>
            <span style={{
              fontSize: 15, fontWeight: 600,
              color: 'rgba(245,247,250,0.9)',
              letterSpacing: '0.2px',
            }}>Continue with Google</span>
          </button>

          {/* Mode toggle */}
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
