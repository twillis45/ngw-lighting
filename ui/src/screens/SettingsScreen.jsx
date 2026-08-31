/**
 * SettingsScreen — Figma-matched layout
 *
 * Three sub-screens via internal state:
 *   main       → Settings (user card + GENERAL / SUPPORT / LEGAL)
 *   preferences → Preferences (ANALYSIS / SHOOT MODE / RECIPES / DISPLAY)
 *   account    → Account & Billing (plan card + ACCOUNT / billing / destructive)
 *
 * Back navigation:
 *   sub-screens → return to main
 *   main        → dispatch GO_BACK (previous app screen)
 */
import { useState, useRef, useCallback } from 'react';
import { useAppState, useDispatch } from '../context/AppContext';
import usePreviewMode from '../hooks/usePreviewMode';
import usePaywall, { resolveUserEmail } from '../hooks/usePaywall';
import usePlan from '../hooks/usePlan';
import { PLAN_LABELS } from '../data/planStore';
import {
  loadSettings, saveSetting, applySettings, resetSettings,
  FONT_SIZES, FONT_FAMILIES, DENSITY_OPTIONS, POWER_DISPLAY_OPTIONS, NAV_STYLE_OPTIONS,
} from '../data/settingsStore';
import { loadTheme, saveTheme, applyTheme, THEMES } from '../data/themeStore';
import { loadMode, saveMode } from '../data/modeStore';
import useMode from '../hooks/useMode';
import { isEnabled, setFlag } from '../modes/featureFlags';
import { excludeCurrentSession } from '../data/analytics';
import { logout as apiLogout } from '../data/authApi';
import Toast from '../components/Toast';
import ConfirmActionModal from '../components/settings/ConfirmActionModal';

const SUPPORT_EMAIL  = 'hello@noguesswork.com';
// Fixed 2026-08-31. All three 404'd. The same three were fixed in the Studio
// settings screen on 2026-08-29 and this LEGACY screen was missed — and the
// gate written that day only read the Studio file, so it passed while these
// shipped. /help does not exist at all, so that row is removed rather than
// repointed; a label promising documentation must not open something else.
const PRIVACY_URL    = 'https://noguessworksystems.com/privacy-policy';
const TERMS_URL      = 'https://noguessworksystems.com/terms-of-service';

const DEV_TAP_COUNT  = 5;
const DEV_TAP_WINDOW = 3000;
const APP_VERSION    = 'v1.4.0';

// ─── Row sub-components ──────────────────────────────────────────────────────

function NavRow({ label, value, onClick, danger, billing, testId }) {
  return (
    <button
      className={`stgx-row stgx-row--nav${danger ? ' stgx-row--danger' : ''}${billing ? ' stgx-row--billing' : ''}`}
      onClick={onClick}
      type="button"
      data-testid={testId}
    >
      <span className="stgx-row__label">{label}</span>
      <span className="stgx-row__right">
        {value && <span className="stgx-row__value">{value}</span>}
        <span className="stgx-row__chevron">›</span>
      </span>
    </button>
  );
}

function ToggleRow({ label, value, onChange, testId }) {
  return (
    <div className="stgx-row stgx-row--toggle" data-testid={testId}>
      <span className="stgx-row__label">{label}</span>
      <button
        className={`stgx-toggle${value ? ' stgx-toggle--on' : ''}`}
        onClick={() => onChange(!value)}
        type="button"
        role="switch"
        aria-checked={value}
      >
        <span className="stgx-toggle__knob" />
      </button>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div className="stgx-row">
      <span className="stgx-row__label">{label}</span>
      <span className="stgx-row__value stgx-row__value--info">{value}</span>
    </div>
  );
}

function SectionHdr({ label }) {
  return <div className="stgx-section-hdr">{label}</div>;
}

function ListCard({ children, className = '' }) {
  return <div className={`stgx-list${className ? ` ${className}` : ''}`}>{children}</div>;
}

function ScreenHeader({ title, backLabel, onBack }) {
  return (
    <div className="stgx-hdr">
      <button className="stgx-hdr__back" onClick={onBack} type="button" data-testid="settings-back">
        ‹ {backLabel}
      </button>
      <h2 className="stgx-hdr__title">{title}</h2>
      <div className="stgx-hdr__spacer" />
    </div>
  );
}

// ─── Role configuration ────────────────────────────────────────────────────────

const ROLE_META = {
  photographer: {
    label:    'Photographer',
    icon:     '📷',
    tagline:  'Full analysis controls — patterns, confidence, and all technical detail.',
  },
  assistant: {
    label:    'Assistant',
    icon:     '🎬',
    tagline:  'Optimised for executing a setup — shoot mode and gear-first workflow.',
  },
  learning: {
    label:    'Learning',
    icon:     '🎓',
    tagline:  'Coaching and explanations — less noise, more guidance.',
  },
};

// showFor('photographer', 'learning') returns true when mode is one of the listed roles.
// Used inline to conditionally render rows in the Preferences sub-screen.
function makeShowFor(mode) {
  return (...roles) => roles.includes(mode);
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SettingsScreen() {
  const { user }  = useAppState();
  const dispatch  = useDispatch();
  const userEmail = resolveUserEmail(user);
  const { isPaid, unlock, isAdmin } = usePaywall(userEmail);
  const { plan, setPlan }           = usePlan(userEmail);

  const [subScreen, setSubScreen] = useState('main');
  const [settings, setSettings]   = useState(loadSettings);
  const [theme, setTheme]         = useState(() => loadTheme() || 'dark');
  const [toast, setToast]         = useState({ message: '', visible: false });
  const [confirm, setConfirm]     = useState(null);
  const [isTestSession, setIsTestSession] = useState(() => {
    try { return sessionStorage.getItem('ngw_test_session') === '1'; } catch { return false; }
  });
  const mode = useMode();

  const tapTimestamps = useRef([]);
  const { access: viewAsAccess, role: viewAsRole,
          setAccess: setViewAsAccess, setRole: setViewAsRole,
          isPreviewing } = usePreviewMode();

  // Derived effective values
  const effectiveIsAdmin = viewAsAccess !== null ? viewAsAccess === 'admin' : isAdmin;
  const effectiveIsPaid  = viewAsAccess !== null
    ? (viewAsAccess === 'paid' || viewAsAccess === 'admin')
    : isPaid;

  // Display helpers
  const rawName     = user?.username || user?.email || '';
  const displayName = rawName.includes('@') ? rawName.split('@')[0] : rawName;
  const displayEmail = user?.email || user?.username || '';
  const planLabel   = effectiveIsAdmin ? 'Admin' : effectiveIsPaid ? 'Pro' : 'Free';
  const unitsLabel  = settings.units === 'metric' ? 'Metric' : 'Imperial';
  const themeLabel  = theme.charAt(0).toUpperCase() + theme.slice(1);
  const modeLabel   = ROLE_META[mode]?.label ?? 'Photographer';
  const showFor     = makeShowFor(mode);
  const fontLabel   = (FONT_FAMILIES.find(f => f.id === settings.fontFamily) || FONT_FAMILIES[0]).label;
  const sizeLabel   = (FONT_SIZES.find(f => f.id === settings.fontSize) || FONT_SIZES[2]).label;
  const densityLabel = (DENSITY_OPTIONS.find(d => d.id === settings.density) || DENSITY_OPTIONS[1]).label;
  const powerLabel  = (POWER_DISPLAY_OPTIONS.find(p => p.id === settings.powerDisplay) || POWER_DISPLAY_OPTIONS[0]).label;
  const navLabel    = (NAV_STYLE_OPTIONS.find(n => n.id === settings.navStyle) || NAV_STYLE_OPTIONS[0]).label;

  function showToast(message) { setToast({ message, visible: true }); }

  function update(key, value) {
    saveSetting(key, value);
    const next = { ...settings, [key]: value };
    setSettings(next);
    applySettings(next);
  }

  function goBack() {
    if (subScreen !== 'main') { setSubScreen('main'); }
    else { dispatch({ type: 'GO_BACK' }); }
  }

  function handleSignOut() {
    setConfirm({
      title: 'Sign Out',
      message: 'You will be signed out of your account.',
      confirmText: 'Sign Out',
      destructive: true,
      onConfirm: () => {
        apiLogout();
        dispatch({ type: 'LOGOUT' });
        setConfirm(null);
      },
    });
  }

  function handleReset() {
    setConfirm({
      title: 'Reset to Defaults',
      message: 'All settings will return to their defaults. This cannot be undone.',
      confirmText: 'Reset',
      destructive: true,
      onConfirm: () => {
        resetSettings();
        setSettings(loadSettings());
        saveTheme('dark'); applyTheme('dark'); setTheme('dark');
        setConfirm(null);
        showToast('Reset to defaults');
      },
    });
  }

  function handleSystemReset() {
    setConfirm({
      title: 'Reset System State',
      message: 'Clears locally stored learning data, session state, and cached results. Your account is not affected.',
      confirmText: 'Reset System',
      destructive: true,
      onConfirm: () => {
        try {
          Object.keys(localStorage).forEach(k => {
            if (k.startsWith('ngw_session_') || k.startsWith('ngw_learn_')) {
              localStorage.removeItem(k);
            }
          });
          sessionStorage.clear();
        } catch (_) {}
        setConfirm(null);
        showToast('System state cleared');
      },
    });
  }

  async function handlePasswordReset() {
    if (!displayEmail) {
      showToast('No email on account — cannot send reset link');
      return;
    }
    try {
      const res = await fetch('/api/auth/password-reset/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: displayEmail }),
      });
      if (res.ok) {
        showToast(`Reset link sent to ${displayEmail}`);
      } else {
        showToast('Could not send reset link — try again');
      }
    } catch {
      showToast('Could not send reset link — check your connection');
    }
  }

  function handleDeleteAccount() {
    setConfirm({
      title: 'Delete Account',
      message: 'This will permanently delete your account and all your data — kits, setups, feedback, and subscription. This cannot be undone.',
      confirmText: 'Delete Forever',
      destructive: true,
      onConfirm: async () => {
        setConfirm(null);
        try {
          const token = localStorage.getItem('ngw_auth_token');
          const res = await fetch('/api/auth/me', {
            method: 'DELETE',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });
          if (res.ok) {
            dispatch({ type: 'LOGOUT' });
          } else {
            const data = await res.json().catch(() => ({}));
            showToast(data.detail || 'Delete failed — try again');
          }
        } catch {
          showToast('Delete failed — check your connection');
        }
      },
    });
  }

  function handleRollback() {
    setConfirm({
      title: 'Rollback Last Adjustment',
      message: 'The most recent autonomous system adjustment will be reversed.',
      confirmText: 'Rollback',
      destructive: true,
      onConfirm: () => {
        setConfirm(null);
        showToast('No recent adjustment to roll back');
      },
    });
  }

  function handleSimulateLowConf() {
    try { sessionStorage.setItem('ngw_sim_low_conf', '1'); } catch (_) {}
    showToast('Low confidence simulation active — reload results to see effect');
  }

  function cycleOption(key, options) {
    const idx = options.findIndex(o => o.id === settings[key]);
    const next = options[(idx + 1) % options.length];
    update(key, next.id);
  }

  function cycleTheme() {
    const idx = THEMES.indexOf(theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    saveTheme(next);
    applyTheme(next);
    setTheme(next);
  }

  function cycleMode() {
    const modes = ['photographer', 'assistant', 'learning'];
    const idx = modes.indexOf(mode);
    const next = modes[(idx + 1) % modes.length];
    saveMode(next);
  }

  async function handleTestSessionToggle(v) {
    const ok = await excludeCurrentSession(v);
    if (ok) {
      try { sessionStorage.setItem('ngw_test_session', v ? '1' : '0'); } catch {}
      setIsTestSession(v);
      showToast(v ? 'Session excluded from analytics' : 'Session restored to analytics');
    } else {
      showToast(user ? 'Could not update — try again' : 'Sign in to exclude sessions');
    }
  }

  const handleVersionTap = useCallback(() => {
    const now  = Date.now();
    const taps = tapTimestamps.current;
    taps.push(now);
    while (taps.length && taps[0] < now - DEV_TAP_WINDOW) taps.shift();
    if (taps.length >= DEV_TAP_COUNT) {
      taps.length = 0;
      const wasEnabled = isEnabled('enable_lab');
      setFlag('enable_lab', !wasEnabled);
      showToast(wasEnabled ? 'Dev mode disabled' : 'Dev mode enabled');
    }
  }, []);

  // ── Modals (shared across all sub-screens) ────────────────────────────────

  const Modals = (
    <>
      <ConfirmActionModal
        open={!!confirm}
        title={confirm?.title}
        message={confirm?.message}
        confirmText={confirm?.confirmText}
        destructive={confirm?.destructive}
        onConfirm={confirm?.onConfirm}
        onCancel={() => setConfirm(null)}
      />
      <Toast
        message={toast.message}
        visible={toast.visible}
        onDone={() => setToast(t => ({ ...t, visible: false }))}
      />
    </>
  );

  // ── PREFERENCES ───────────────────────────────────────────────────────────

  if (subScreen === 'preferences') {
    const isAssistant    = mode === 'assistant';
    const isLearning     = mode === 'learning';
    const isPhotographer = mode === 'photographer';

    return (
      <div className="stgx">
        <ScreenHeader
          title={isAssistant ? 'Shoot Preferences' : isLearning ? 'My Preferences' : 'Preferences'}
          backLabel="Settings"
          onBack={goBack}
        />

        {/* Role context chip */}
        <div className="stgx-role-chip">
          <span className="stgx-role-chip__icon">{ROLE_META[mode]?.icon}</span>
          <span className="stgx-role-chip__label">{ROLE_META[mode]?.label}</span>
          <span className="stgx-role-chip__tagline">{ROLE_META[mode]?.tagline}</span>
        </div>

        {/* ── SHOOT MODE — always first for assistant ─────────────────── */}
        <SectionHdr label="SHOOT MODE" />
        <ListCard>
          <NavRow
            label="Comparison prompts"
            value={settings.comparisonPrompts === 'auto' ? 'Auto' : settings.comparisonPrompts === 'low_conf_only' ? 'Low conf' : 'Off'}
            onClick={() => {
              const opts = ['auto', 'low_conf_only', 'off'];
              const idx = opts.indexOf(settings.comparisonPrompts || 'auto');
              update('comparisonPrompts', opts[(idx + 1) % opts.length]);
            }}
          />
          <NavRow
            label="Shoot mode style"
            value={settings.shootModeStyle === 'checklist' ? 'Checklist' : 'Step-by-step'}
            onClick={() => update('shootModeStyle', settings.shootModeStyle === 'checklist' ? 'step' : 'checklist')}
          />
          {showFor('photographer', 'assistant') && (
            <ToggleRow
              label="Live overlay"
              value={!!settings.uiSelfTuning}
              onChange={v => update('uiSelfTuning', v)}
            />
          )}
          {showFor('photographer', 'assistant') && (
            <NavRow
              label="Power readout"
              value={powerLabel}
              onClick={() => cycleOption('powerDisplay', POWER_DISPLAY_OPTIONS)}
            />
          )}
        </ListCard>

        {/* ── ANALYSIS — hidden for assistant ─────────────────────────── */}
        {showFor('photographer', 'learning') && (
          <>
            <SectionHdr label="ANALYSIS" />
            <ListCard>
              {showFor('photographer', 'learning') && (
                <NavRow
                  label="Primary display"
                  value={settings.viewMode === 'full' ? 'Full' : 'Blueprint'}
                  onClick={() => update('viewMode', settings.viewMode === 'full' ? 'quick' : 'full')}
                />
              )}
              <NavRow
                label="Guidance level"
                value={settings.guidanceLevel === 'minimal' ? 'Minimal' : settings.guidanceLevel === 'full' ? 'Coaching' : 'Guided'}
                onClick={() => {
                  const levels = isLearning ? ['guided', 'full'] : ['minimal', 'guided', 'full'];
                  const idx = levels.indexOf(settings.guidanceLevel || 'guided');
                  update('guidanceLevel', levels[(idx + 1) % levels.length]);
                }}
              />
              {showFor('photographer', 'learning') && (
                <NavRow
                  label="Confidence display"
                  value={settings.confidenceDisplay === 'numeric' ? 'Numeric' : settings.confidenceDisplay === 'detailed' ? 'Detailed' : 'Simple'}
                  onClick={() => {
                    const opts = ['simple', 'numeric', 'detailed'];
                    const idx = opts.indexOf(settings.confidenceDisplay || 'simple');
                    update('confidenceDisplay', opts[(idx + 1) % opts.length]);
                  }}
                />
              )}
              {showFor('photographer', 'learning') && (
                <ToggleRow
                  label="Show confidence score"
                  value={!!settings.showConfidenceScore}
                  onChange={v => update('showConfidenceScore', v)}
                />
              )}
              <NavRow
                label="Explanation depth"
                value={settings.explanationDepth === 'brief' ? 'Brief' : settings.explanationDepth === 'technical' ? 'Technical' : 'Standard'}
                onClick={() => {
                  const opts = isLearning ? ['standard', 'technical'] : ['brief', 'standard', 'technical'];
                  const idx = opts.indexOf(settings.explanationDepth || 'standard');
                  update('explanationDepth', opts[(idx + 1) % opts.length]);
                }}
              />
              {showFor('photographer') && (
                <NavRow
                  label="Pattern sensitivity"
                  value={settings.patternSensitivity === 'strict' ? 'Strict' : settings.patternSensitivity === 'flexible' ? 'Flexible' : 'Balanced'}
                  onClick={() => {
                    const opts = ['strict', 'balanced', 'flexible'];
                    const idx = opts.indexOf(settings.patternSensitivity || 'balanced');
                    update('patternSensitivity', opts[(idx + 1) % opts.length]);
                  }}
                />
              )}
              <NavRow
                label="Session storage"
                value={settings.sessionStorage === 'auto' ? 'Auto' : settings.sessionStorage === 'off' ? 'Off' : 'Manual'}
                onClick={() => {
                  const opts = ['auto', 'manual', 'off'];
                  const idx = opts.indexOf(settings.sessionStorage || 'auto');
                  update('sessionStorage', opts[(idx + 1) % opts.length]);
                }}
              />
            </ListCard>
          </>
        )}

        {/* ── RECIPES ─────────────────────────────────────────────────── */}
        <SectionHdr label="RECIPES" />
        <ListCard>
          <ToggleRow
            label="Show descriptions"
            value={isLearning ? true : settings.allowLearning !== false}
            onChange={isLearning ? undefined : v => update('allowLearning', v)}
          />
          <NavRow label="Default sort" value={settings.recipeSort === 'alpha' ? 'A–Z' : 'Recent'} onClick={() => update('recipeSort', settings.recipeSort === 'alpha' ? 'recent' : 'alpha')} />
        </ListCard>

        {/* ── APPEARANCE ──────────────────────────────────────────────── */}
        <SectionHdr label="APPEARANCE" />
        <ListCard>
          <NavRow label="Theme" value={themeLabel} onClick={cycleTheme} />
          {showFor('photographer', 'learning') && (
            <NavRow label="Typeface" value={fontLabel} onClick={() => cycleOption('fontFamily', FONT_FAMILIES)} />
          )}
          <NavRow label="Font size" value={sizeLabel} onClick={() => cycleOption('fontSize', FONT_SIZES)} />
          {showFor('photographer') && (
            <NavRow label="Density" value={densityLabel} onClick={() => cycleOption('density', DENSITY_OPTIONS)} />
          )}
          {showFor('photographer', 'assistant') && (
            <NavRow
              label="Diagram style"
              value={settings.diagramStyle === 'minimal' ? 'Minimal' : 'Blueprint'}
              onClick={() => update('diagramStyle', settings.diagramStyle === 'minimal' ? 'blueprint' : 'minimal')}
            />
          )}
          <NavRow
            label="Unit system"
            value={unitsLabel}
            onClick={() => update('units', settings.units === 'metric' ? 'imperial' : 'metric')}
          />
          <ToggleRow label="Reduce motion" value={!!settings.reduceMotion} onChange={v => update('reduceMotion', v)} />
          <ToggleRow label="Haptic feedback" value={settings.hapticFeedback !== false} onChange={v => update('hapticFeedback', v)} />
          {showFor('photographer') && (
            <NavRow label="Navigation bar" value={navLabel} onClick={() => cycleOption('navStyle', NAV_STYLE_OPTIONS)} />
          )}
        </ListCard>

        {/* ── INTELLIGENCE ────────────────────────────────────────────── */}
        <SectionHdr label="INTELLIGENCE" />
        <ListCard>
          {showFor('photographer') && (
            <NavRow
              label="Autonomy level"
              value={settings.autonomyLevel === 'manual' ? 'Manual' : settings.autonomyLevel === 'adaptive' ? 'Adaptive' : 'Assisted'}
              onClick={() => {
                const opts = ['manual', 'assisted', 'adaptive'];
                const idx = opts.indexOf(settings.autonomyLevel || 'assisted');
                update('autonomyLevel', opts[(idx + 1) % opts.length]);
              }}
            />
          )}
          <NavRow
            label="Fix guidance"
            value={settings.fixGuidance === 'quick' ? 'Quick' : settings.fixGuidance === 'detailed' ? 'Detailed' : 'Balanced'}
            onClick={() => {
              const opts = isLearning ? ['balanced', 'detailed'] : ['quick', 'balanced', 'detailed'];
              const idx = opts.indexOf(settings.fixGuidance || 'balanced');
              update('fixGuidance', opts[(idx + 1) % opts.length]);
            }}
          />
          {showFor('photographer') && (
            <ToggleRow label="Stability mode" value={!!settings.stabilityMode} onChange={v => update('stabilityMode', v)} />
          )}
        </ListCard>

        {/* ── PRIVACY ─────────────────────────────────────────────────── */}
        <SectionHdr label="PRIVACY" />
        <ListCard>
          <ToggleRow label="Allow analytics" value={settings.allowAnalytics !== false} onChange={v => update('allowAnalytics', v)} />
          {showFor('photographer', 'assistant') && (
            <NavRow
              label="Image handling"
              value={settings.imageHandling === 'delete' ? 'Delete after' : 'Store'}
              onClick={() => update('imageHandling', settings.imageHandling === 'delete' ? 'store' : 'delete')}
            />
          )}
        </ListCard>

        <ListCard className="stgx-list--destructive">
          <NavRow label="Reset to Defaults" danger onClick={handleReset} />
        </ListCard>

        {Modals}
      </div>
    );
  }

  // ── ACCOUNT & BILLING ─────────────────────────────────────────────────────

  if (subScreen === 'account') {
    const planName = effectiveIsAdmin ? 'Enterprise Plan' : effectiveIsPaid ? 'Pro Plan' : 'Free Plan';
    const planSub  = effectiveIsPaid ? 'Active subscription' : 'Limited access — 5 analyses/mo';

    return (
      <div className="stgx">
        <ScreenHeader title="Account & Billing" backLabel="Settings" onBack={goBack} />

        {/* Plan card */}
        <div className={`stgx-plan-card${effectiveIsPaid ? ' stgx-plan-card--paid' : ''}`}>
          <div className="stgx-plan-card__body">
            <div className="stgx-plan-card__name">{planName}</div>
            <div className="stgx-plan-card__sub">{planSub}</div>
            {effectiveIsPaid && (
              <div className="stgx-plan-card__renew">Renews April 28, 2026</div>
            )}
          </div>
          <span className={`stgx-plan-badge${effectiveIsPaid ? ' stgx-plan-badge--active' : ''}`}>
            {effectiveIsPaid ? 'Active' : 'Free'}
          </span>
        </div>

        {/* ACCOUNT */}
        <SectionHdr label="ACCOUNT" />
        <ListCard>
          <InfoRow label="Email" value={displayEmail || '—'} />
          <NavRow label="Password" onClick={handlePasswordReset} />
          <NavRow
            label="Connected kit"
            onClick={() => dispatch({ type: 'NAVIGATE', screen: 'my_kit' })}
          />
        </ListCard>

        {/* Billing row */}
        <ListCard className="stgx-list--billing">
          {effectiveIsPaid ? (
            <NavRow label="Manage billing & invoices" billing onClick={() => window.open(`mailto:${SUPPORT_EMAIL}?subject=Billing%20%26%20Invoices`, '_blank')} />
          ) : (
            <NavRow label="Upgrade to Pro" billing onClick={unlock} />
          )}
        </ListCard>

        {/* PROFILE & ANALYTICS */}
        <SectionHdr label="PROFILE" />
        <ListCard>
          <NavRow
            label="Edit photographer profile"
            onClick={() => dispatch({ type: 'NAVIGATE', screen: 'onboarding' })}
          />
          <NavRow
            label="View analytics"
            onClick={() => dispatch({ type: 'NAVIGATE', screen: 'analytics' })}
          />
          {effectiveIsAdmin && (
            <NavRow
              label="Exec dashboard"
              onClick={() => dispatch({ type: 'NAVIGATE', screen: 'analytics' })}
            />
          )}
        </ListCard>

        {/* CONTROLS */}
        <SectionHdr label="CONTROLS" />
        <ListCard>
          <ToggleRow
            label="Experiment participation"
            value={settings.experimentParticipation !== false}
            onChange={v => update('experimentParticipation', v)}
          />
        </ListCard>

        {/* Destructive actions */}
        <ListCard className="stgx-list--destructive">
          <NavRow label="Delete account" danger onClick={handleDeleteAccount} />
          <NavRow label="Sign out" danger onClick={handleSignOut} />
        </ListCard>

        {/* Dev tools — lab enabled, admin or dev mode */}
        {isEnabled('enable_lab') && (
          <>
            <SectionHdr label="DEV TOOLS" />
            <ListCard>
              {effectiveIsAdmin && (
                <NavRow
                  label="Preview As"
                  value={viewAsAccess ? `${viewAsAccess}` : 'Actual'}
                  onClick={() => {
                    const opts = [null, 'free', 'paid', 'admin'];
                    const idx = opts.indexOf(viewAsAccess);
                    setViewAsAccess(opts[(idx + 1) % opts.length]);
                  }}
                />
              )}
              <ToggleRow
                label="Show debug signals"
                value={!!settings.showDebugSignals}
                onChange={v => update('showDebugSignals', v)}
              />
              <NavRow
                label="Simulate low confidence"
                onClick={handleSimulateLowConf}
              />
              <NavRow
                label="View event logs"
                onClick={() => {
                  try {
                    const logs = JSON.parse(localStorage.getItem('ngw_event_log') || '[]');
                    showToast(`${logs.length} events logged`);
                  } catch { showToast('No event logs found'); }
                }}
              />
              <ToggleRow
                label="Test session"
                value={isTestSession}
                onChange={handleTestSessionToggle}
              />
              <NavRow label="Reset system state" danger onClick={handleSystemReset} />
              <NavRow label="Rollback last adjustment" danger onClick={handleRollback} />
            </ListCard>
          </>
        )}

        {Modals}
      </div>
    );
  }

  // ── MAIN SETTINGS ─────────────────────────────────────────────────────────

  return (
    <div className="stgx">
      <ScreenHeader title="Settings" backLabel="Back" onBack={goBack} />

      {/* User card — taps to Account & Billing */}
      <button
        className="stgx-user-card"
        onClick={() => setSubScreen('account')}
        type="button"
        data-testid="settings-account-card"
      >
        <div className="stgx-user-card__avatar">
          {(displayName || 'G').charAt(0).toUpperCase()}
        </div>
        <div className="stgx-user-card__info">
          <div className="stgx-user-card__name">
            {displayName || 'Guest'}
          </div>
          {displayEmail && (
            <div className="stgx-user-card__email">{displayEmail}</div>
          )}
        </div>
        <span className={`stgx-user-badge${effectiveIsPaid ? ' stgx-user-badge--paid' : ''}`}>
          {planLabel}
        </span>
      </button>

      {/* Role callout — shows current role context */}
      <button
        className="stgx-role-banner"
        onClick={cycleMode}
        type="button"
        aria-label="Change role"
      >
        <span className="stgx-role-banner__icon">{ROLE_META[mode]?.icon}</span>
        <div className="stgx-role-banner__text">
          <span className="stgx-role-banner__label">{ROLE_META[mode]?.label} mode</span>
          <span className="stgx-role-banner__tagline">{ROLE_META[mode]?.tagline}</span>
        </div>
        <span className="stgx-role-banner__tap">Tap to change ›</span>
      </button>

      {/* GENERAL */}
      <SectionHdr label="GENERAL" />
      <ListCard>
        <NavRow
          label="Units"
          value={unitsLabel}
          onClick={() => update('units', settings.units === 'metric' ? 'imperial' : 'metric')}
          testId="settings-units"
        />
        <ToggleRow
          label="Analysis auto-save"
          value={settings.sessionStorage === 'auto'}
          onChange={v => update('sessionStorage', v ? 'auto' : 'manual')}
          testId="settings-auto-save"
        />
        {mode !== 'assistant' && (
          <NavRow
            label="Default kit view"
            value={settings.viewMode === 'full' ? 'Full' : 'Lights first'}
            onClick={() => update('viewMode', settings.viewMode === 'full' ? 'quick' : 'full')}
          />
        )}
        <NavRow
          label={mode === 'assistant' ? 'Shoot Preferences' : mode === 'learning' ? 'My Preferences' : 'Preferences'}
          onClick={() => setSubScreen('preferences')}
          testId="settings-preferences"
        />
      </ListCard>

      {/* SUPPORT */}
      <SectionHdr label="SUPPORT" />
      <ListCard>
        <NavRow label="Contact support" onClick={() => window.open(`mailto:${SUPPORT_EMAIL}?subject=NGW%20Support`, '_blank')} />
        <NavRow label="Rate NGW" onClick={() => showToast('Rating coming soon — thanks for your support!')} />
      </ListCard>

      {/* LEGAL */}
      <SectionHdr label="LEGAL" />
      <ListCard>
        <NavRow label="Privacy Policy" onClick={() => window.open(PRIVACY_URL, '_blank')} />
        <NavRow label="Terms of Service" onClick={() => window.open(TERMS_URL, '_blank')} />
      </ListCard>

      {/* Sign out */}
      {user && (
        <ListCard className="stgx-list--destructive">
          <NavRow label="Sign out" danger onClick={handleSignOut} />
        </ListCard>
      )}

      {/* Hidden version tap — 5× to toggle dev mode */}
      <div className="stgx-about" onClick={handleVersionTap} role="presentation">
        <span className="stgx-about__app">No Guesswork Lighting</span>
        <span className="stgx-about__ver">{APP_VERSION}</span>
      </div>

      {Modals}
    </div>
  );
}
