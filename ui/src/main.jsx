import React from 'react';
import ReactDOM from 'react-dom/client';
import * as Sentry from '@sentry/react';
import App from './App';
import { AppProvider } from './context/AppContext';
import ErrorBoundary from './components/ErrorBoundary';
import { loadTheme, applyTheme } from './data/themeStore';
import { applySettings } from './data/settingsStore';
import { setFlag } from './modes/featureFlags';
import './theme/tokens.css';
import './styles/app.css';
import './components/shared/shared-components.css';
import { primaryAdminEmail } from './config/admin';

/* ── Sentry browser SDK ─────────────────────────────────────────── */
Sentry.init({
  dsn: 'https://df727ad4e9163f9ccb4c9b2f33f14b4f@o4511174955565056.ingest.us.sentry.io/4511174984269824',
  environment: import.meta.env.DEV ? 'development' : 'production',
  integrations: [
    Sentry.browserTracingIntegration(),
    Sentry.replayIntegration({ maskAllText: false, blockAllMedia: false }),
  ],
  tracesSampleRate: import.meta.env.DEV ? 1.0 : 0.3,
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 1.0,
  beforeSend(event) {
    // Attach auth user context if available
    try {
      const raw = localStorage.getItem('ngw_auth_user');
      if (raw) {
        const u = JSON.parse(raw);
        event.user = { id: u.id, email: u.email, username: u.username };
      }
    } catch { /* ignore */ }
    return event;
  },
});

/* Lock phones to portrait via Screen Orientation API (PWA/fullscreen only).
   Falls back silently — the CSS overlay in index.html handles non-PWA. */
try {
  if (screen.orientation?.lock && window.innerWidth < 768) {
    screen.orientation.lock('portrait').catch(() => {});
  }
} catch { /* ignore — API not supported */ }

/* Apply saved theme and settings before first paint.
   Studio Matte flow forces 'studio' theme for the deeper carbon-black palette. */
const _savedTheme = loadTheme();
try {
  if (sessionStorage.getItem('ngw_studio_active') === '1' ||
      localStorage.getItem('ngw_studio_persist') === '1') {
    applyTheme('studio');
  } else {
    applyTheme(_savedTheme);
  }
} catch {
  applyTheme(_savedTheme);
}
applySettings();

/* URL param shortcuts — dev builds only */
let _devModeUser = null;
let _pendingVerifyToken = null;
try {
  const params = new URLSearchParams(window.location.search);
  let dirty = false;
  if (params.get('lab') === '1') {
    setFlag('enable_lab', true);
    params.delete('lab');
    dirty = true;
  }
  const _isLocalhost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  if ((import.meta.env.DEV || _isLocalhost) && params.get('devmode') === '1') {
    setFlag('enable_lab', true);
    _devModeUser = { id: 'dev-mode', email: primaryAdminEmail(), username: 'Dev Mode' };
    localStorage.setItem('ngw_auth_user', JSON.stringify(_devModeUser));
    localStorage.setItem('ngw_paid', 'true');
    params.delete('devmode');
    dirty = true;
  }
  // QA free-mode — forces free-tier regardless of admin email or ngw_paid localStorage.
  // Use ?qa_free=1 to test paywall flows without manually clearing storage each session.
  // Stored in sessionStorage so it resets on tab close — never persists accidentally.
  if (params.get('qa_free') === '1') {
    try { sessionStorage.setItem('ngw_qa_free', '1'); } catch { /* ignore */ }
    params.delete('qa_free');
    dirty = true;
  }
  const vt = params.get('verify_token');
  if (vt) {
    _pendingVerifyToken = vt;
    params.delete('verify_token');
    dirty = true;
  }
  // Magic link return — store token so App.jsx can verify it before first paint
  const mt = params.get('magic_token');
  if (mt) {
    try { sessionStorage.setItem('ngw_magic_token', mt); } catch { /* ignore */ }
    params.delete('magic_token');
    dirty = true;
  }

  // Password reset return — store token so AuthScreen can pick it up on mount
  const rt = params.get('reset_token');
  if (rt) {
    try { sessionStorage.setItem('ngw_reset_token', rt); } catch { /* ignore */ }
    params.delete('reset_token');
    dirty = true;
  }

  // Direct login deep-link — ?login=1 navigates to auth screen on mount.
  // Share this URL to give users a reliable "sign in" link:
  //   https://app.noguessworksystems.com/?login=1
  // Note: /static/ui/ does NOT work (StaticFiles won't serve index.html
  // for directory requests). Use / or /ui instead.
  if (params.get('login') === '1') {
    try { sessionStorage.setItem('ngw_goto_auth', '1'); } catch { /* ignore */ }
    params.delete('login');
    dirty = true;
  }

  // Studio Matte parallel rollout — flag plumbing (Checkpoint 2).
  // Precedence: ?studio=off > ?studio=1 > ?day1=1 (alias) > persisted flag > default.
  // Storage keys:
  //   sessionStorage.ngw_studio_active   — session-scoped "studio shell is live"
  //   sessionStorage.ngw_studio_cockpit  — Bucket B unlock (gating added in Checkpoint 3)
  //   sessionStorage.ngw_goto_day1_demo  — existing trigger consumed by App.jsx to navigate
  //   localStorage.ngw_studio_persist    — persistent tester opt-in across sessions
  const studioParam = params.get('studio');
  if (studioParam === 'off') {
    try {
      sessionStorage.removeItem('ngw_studio_active');
      sessionStorage.removeItem('ngw_studio_cockpit');
      sessionStorage.removeItem('ngw_goto_day1_demo');
      localStorage.removeItem('ngw_studio_persist');
    } catch { /* ignore */ }
    params.delete('studio');
    dirty = true;
  } else if (studioParam === '1') {
    try {
      sessionStorage.setItem('ngw_studio_active', '1');
      sessionStorage.setItem('ngw_goto_day1_demo', '1');
      if (params.get('persist') === '1') {
        localStorage.setItem('ngw_studio_persist', '1');
      }
      if (params.get('cockpit') === '1') {
        sessionStorage.setItem('ngw_studio_cockpit', '1');
      }
    } catch { /* ignore */ }
    params.delete('studio');
    params.delete('persist');
    params.delete('cockpit');
    dirty = true;
  } else {
    // No explicit studio/day1 param — Studio Matte is now the default.
    // Use ?studio=off to revert to legacy shell.
    try {
      sessionStorage.setItem('ngw_studio_active', '1');
      sessionStorage.setItem('ngw_goto_day1_demo', '1');
    } catch { /* ignore */ }
  }

  // Stripe checkout return — set paid flag before React mounts so usePaywall
  // initialises with isPaid=true without needing a re-render or extra state sync.
  // Also stash the session_id so usePaywall can verify server-side on first render.
  if (params.get('checkout_success') === '1') {
    try { localStorage.setItem('ngw_paid', 'true'); } catch { /* ignore */ }
    const sid = params.get('session_id');
    if (sid) {
      try { localStorage.setItem('ngw_stripe_session', sid); } catch { /* ignore */ }
    }
    // Signal App.jsx to redirect into Shoot Mode (post-payment UX).
    // Stored in sessionStorage so it fires once and resets on tab close.
    try { sessionStorage.setItem('ngw_post_payment', '1'); } catch { /* ignore */ }
    params.delete('checkout_success');
    params.delete('session_id');
    dirty = true;
  }
  if (dirty) {
    const clean = params.toString();
    const url = window.location.pathname + (clean ? `?${clean}` : '');
    window.history.replaceState(null, '', url);
  }
} catch { /* ignore */ }

export { _devModeUser, _pendingVerifyToken };

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <AppProvider devModeUser={_devModeUser}>
        <App />
      </AppProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
