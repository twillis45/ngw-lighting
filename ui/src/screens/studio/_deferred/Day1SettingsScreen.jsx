/**
 * Day1SettingsScreen — Studio Matte design
 * Three sub-screens: main → preferences | account
 * No AppContext dependency; accepts user/onBack/onLogout props.
 */
import { useState, useRef, useCallback } from 'react';
import { tapHaptic, selectHaptic, navHaptic } from '../../../utils/haptics';
import { softClickSound, navSlideSound, panelToggleSound } from '../../../utils/sounds';
import { saveSetting, loadSettings, resetSettings, applySettings,
         FONT_SIZES, POWER_DISPLAY_OPTIONS } from '../../../data/settingsStore';
import { loadMode, saveMode } from '../../../data/modeStore';
import { isEnabled, setFlag } from '../../../modes/featureFlags';
import useMode from '../../../hooks/useMode';
import { steel, C as SM_C, FONT_SMOOTH, PANEL_SHADOW, PANEL_BEVEL, GREEN, KEY_ACCENT, SCREEN_BG } from '../../../theme/studioMatte';
import { Panel, Divider, SectionLabel, NavRow, ToggleRow, InfoRow, ScreenHeader, HomeIndicator }
  from '../_core/components';
import MatteBackground from '../_shared/MatteBackground';
import usePlan from '../../../hooks/usePlan';
import { PLAN_LABELS } from '../../../data/planStore';

const SUPPORT_EMAIL = 'hello@noguesswork.com';
const PRIVACY_URL   = 'https://noguessworksystems.com/privacy-policy';
const TERMS_URL     = 'https://noguessworksystems.com/terms-of-service';
const APP_VERSION   = 'v1.4.0';
const DEV_TAP_COUNT  = 5;
const DEV_TAP_WINDOW = 3000;

// ─── Screen-local token extensions ───────────────────────────────────────────
const C = { ...SM_C, textDanger: 'rgba(200,70,70,0.82)' };
const FS = FONT_SMOOTH;  // shorthand alias used throughout this file

const ROLE_META = {
  photographer: { label: 'Photographer', initial: 'P', tagline: 'Full analysis — patterns, confidence, all technical detail.' },
  assistant:    { label: 'Assistant',    initial: 'A', tagline: 'Optimised for executing a setup — gear-first workflow.' },
  learning:     { label: 'Learning',     initial: 'L', tagline: 'Coaching and explanations — less noise, more guidance.' },
};

// ─── Preferences sub-screen ───────────────────────────────────────────────────
function PreferencesScreen({ settings, update, onBack, mode, isAdmin }) {
  function cycleOption(key, options) {
    const idx = options.findIndex(o => o.id === settings[key]);
    const next = options[(idx + 1) % options.length];
    update(key, next.id);
  }

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, fontFamily: 'Inter, system-ui, -apple-system, sans-serif', overflow: 'hidden' }}>
      <MatteBackground variant="carbon" />
    <div style={{ position: 'relative', zIndex: 1, height: '100%', overflowY: 'auto', maxWidth: 720, margin: '0 auto' }}>
      <ScreenHeader title="Preferences" onBack={onBack} />
      <div style={{ padding: '8px 20px 48px', position: 'relative', zIndex: 1 }}>

        {/* ── APPEARANCE — all users ────────────────────────────────────── */}
        <SectionLabel label="APPEARANCE" />
        <Panel>
          <ToggleRow label="Daylight mode" value={!!settings.daylightMode} onChange={v => update('daylightMode', v)} tooltip="Brightness boost for bright studios and outdoor use. Makes the UI readable in direct light." />
          <Divider />
          <ToggleRow label="Haptic feedback" value={settings.hapticFeedback !== false} onChange={v => update('hapticFeedback', v)} tooltip="Vibration feedback on taps and interactions." />
          <Divider />
          <ToggleRow label="Reduce motion" value={!!settings.reduceMotion} onChange={v => update('reduceMotion', v)} tooltip="Disables animations for accessibility." />
          <Divider />
          <NavRow
            label="Font size"
            value={(FONT_SIZES.find(f => f.id === settings.fontSize) || FONT_SIZES[2]).label}
            onClick={() => cycleOption('fontSize', FONT_SIZES)}
            tooltip="Adjust text size for readability."
          />
          <Divider />
          <NavRow
            label="Unit system"
            value={settings.units === 'metric' ? 'Metric' : 'Imperial'}
            onClick={() => update('units', settings.units === 'metric' ? 'imperial' : 'metric')}
            tooltip="Feet/inches or meters for distances."
          />
          <Divider />
          <ToggleRow label="Export branding" value={settings.exportBranding !== false} onChange={v => update('exportBranding', v)} tooltip="Show 'No Guesswork Lighting' on diagram PNG/PDF exports. Turn off for clean client deliverables." />
        </Panel>

        {/* ── SHOOT MODE — all users ──────────────────────────────────── */}
        <SectionLabel label="SHOOT MODE" />
        <Panel>
          <NavRow
            label="Power readout"
            value={(POWER_DISPLAY_OPTIONS.find(p => p.id === settings.powerDisplay) || POWER_DISPLAY_OPTIONS[0]).label}
            onClick={() => cycleOption('powerDisplay', POWER_DISPLAY_OPTIONS)}
            tooltip="How strobe power is displayed. Fraction: 1/4, 1/2. Stops: f-stop relative. Percent: 0–100%."
          />
          <Divider />
          <NavRow
            label="Diagram style"
            value={settings.diagramStyle === 'minimal' ? 'Minimal' : 'Standard'}
            onClick={() => update('diagramStyle', settings.diagramStyle === 'minimal' ? 'standard' : 'minimal')}
            tooltip="Standard: full diagram with labels. Minimal: clean positions only."
          />
          <Divider />
          <ToggleRow label="Auto-save setups" value={!!settings.autoSaveSetups} onChange={v => update('autoSaveSetups', v)} tooltip="Automatically save every lighting setup after analysis. Find them in Saved Setups." />
        </Panel>

        {/* ── ADMIN — engine tuning, only shown for admin accounts ──── */}
        {isAdmin && (<>
          <SectionLabel label="ENGINE TUNING (ADMIN)" />
          <Panel>
            <NavRow
              label="Confidence display"
              value={settings.confidenceDisplay === 'numeric' ? 'Numeric' : settings.confidenceDisplay === 'detailed' ? 'Detailed' : 'Simple'}
              onClick={() => {
                const opts = ['simple', 'numeric', 'detailed'];
                const idx = opts.indexOf(settings.confidenceDisplay || 'simple');
                update('confidenceDisplay', opts[(idx + 1) % opts.length]);
              }}
              tooltip="Simple: Confident / Tentative / Uncertain. Numeric: percentage. Detailed: percentage + label together."
            />
            <Divider />
            <NavRow
              label="Pattern sensitivity"
              value={settings.patternSensitivity === 'strict' ? 'Strict' : settings.patternSensitivity === 'flexible' ? 'Flexible' : 'Balanced'}
              onClick={() => {
                const opts = ['strict', 'balanced', 'flexible'];
                const idx = opts.indexOf(settings.patternSensitivity || 'balanced');
                update('patternSensitivity', opts[(idx + 1) % opts.length]);
              }}
              tooltip="How strictly the engine matches patterns."
            />
            <Divider />
            <ToggleRow
              label="Show confidence score"
              value={!!settings.showConfidenceScore}
              onChange={v => update('showConfidenceScore', v)}
              tooltip="Display confidence percentage on results."
            />
            <Divider />
            <NavRow
              label="Explanation depth"
              value={settings.explanationDepth === 'brief' ? 'Brief' : settings.explanationDepth === 'technical' ? 'Technical' : 'Standard'}
              onClick={() => {
                const opts = ['brief', 'standard', 'technical'];
                const idx = opts.indexOf(settings.explanationDepth || 'standard');
                update('explanationDepth', opts[(idx + 1) % opts.length]);
              }}
              tooltip="Cockpit coaching detail level."
            />
            <Divider />
            <NavRow
              label="Comparison prompts"
              value={settings.comparisonPrompts === 'low_conf_only' ? 'Low conf' : settings.comparisonPrompts === 'off' ? 'Off' : 'Auto'}
              onClick={() => {
                const opts = ['auto', 'low_conf_only', 'off'];
                const idx = opts.indexOf(settings.comparisonPrompts || 'auto');
                update('comparisonPrompts', opts[(idx + 1) % opts.length]);
              }}
              tooltip="When to prompt shot comparison."
            />
          </Panel>

          <SectionLabel label="PRIVACY (ADMIN)" />
          <Panel>
            <ToggleRow
              label="Allow analytics"
              value={settings.allowAnalytics !== false}
              onChange={v => update('allowAnalytics', v)}
              tooltip="Anonymous usage data for engine improvement."
            />
            <Divider />
            <NavRow
              label="Image handling"
              value={settings.imageHandling === 'delete' ? 'Delete after' : 'Store'}
              onClick={() => update('imageHandling', settings.imageHandling === 'delete' ? 'store' : 'delete')}
              tooltip="Store photos for history or delete after analysis."
            />
          </Panel>
        </>)}

        <div style={{ height: 1 }} />
        <Panel>
          <NavRow label="Reset to Defaults" danger onClick={() => {
            resetSettings(); applySettings(loadSettings());
            softClickSound();
          }} />
        </Panel>

      </div>
    </div>
    </div>
  );
}

// ─── Account sub-screen ───────────────────────────────────────────────────────
function AccountScreen({ user, onBack, onLogout }) {
  const [resetSent, setResetSent] = useState(false);
  const displayEmail = user?.email || user?.username || '';
  const { plan, setPlan, isPaid, isAdmin } = usePlan(displayEmail);
  const planLabel = PLAN_LABELS[plan] || plan;

  // Plan accent colors
  const planAccent = isPaid
    ? { bg: 'rgba(72,186,136,0.10)', border: 'rgba(72,186,136,0.25)', color: GREEN, label: 'ACTIVE' }
    : { bg: 'rgba(200,155,60,0.08)', border: 'rgba(200,155,60,0.20)', color: KEY_ACCENT, label: 'FREE' };

  async function handlePasswordReset() {
    if (!displayEmail) return;
    try {
      const res = await fetch('/api/auth/password-reset/request', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: displayEmail }),
      });
      setResetSent(res.ok);
    } catch { setResetSent(false); }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, fontFamily: 'Inter, system-ui, -apple-system, sans-serif', overflow: 'hidden' }}>
      <MatteBackground variant="carbon" />
    <div style={{ position: 'relative', zIndex: 1, height: '100%', overflowY: 'auto', maxWidth: 720, margin: '0 auto' }}>
      <ScreenHeader title="Account" onBack={onBack} />
      <div style={{ padding: '8px 20px 48px', position: 'relative', zIndex: 1 }}>

        {/* Plan card — machined instrument panel with LED status indicator */}
        <div style={{
          backgroundColor: '#0c0e14',
          borderRadius: 14, padding: '20px 22px',
          boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
          marginTop: 8,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <p style={{ margin: 0, fontSize: 17, fontWeight: 700, color: C.textPrimary, letterSpacing: '-0.2px', ...FS }}>{planLabel} Plan</p>
              <p style={{ margin: '5px 0 0', fontSize: 12, color: steel(0.50), ...FS }}>
                {isPaid ? 'Active subscription' : 'Free tier — limited analyses'}
              </p>
            </div>
            {/* LED status indicator — machined well with glowing dot */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              {/* Status dot in recessed well */}
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: 'radial-gradient(circle at 50% 44%, #010102 0%, #040508 50%, transparent 80%)',
                boxShadow: [
                  'inset 3px 3px 6px rgba(0,0,0,0.80)',
                  'inset 1px 1px 3px rgba(0,0,0,0.55)',
                  'inset -1px -1px 2px rgba(255,255,255,0.015)',
                  '-0.5px -0.5px 1px rgba(255,255,255,0.03)',
                  '1px 2px 4px rgba(0,0,0,0.40)',
                  // LED glow trapped in well
                  isPaid ? 'inset 0 0 6px rgba(72,186,136,0.12)' : 'inset 0 0 4px rgba(200,155,60,0.08)',
                ].join(', '),
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <div style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: isPaid
                    ? 'radial-gradient(circle at 35% 30%, rgba(180,255,220,0.95) 0%, rgba(72,186,136,0.85) 60%, rgba(40,120,85,0.75) 100%)'
                    : `radial-gradient(circle at 35% 30%, rgba(255,220,160,0.85) 0%, rgba(200,155,60,0.70) 60%, rgba(140,100,30,0.60) 100%)`,
                  boxShadow: isPaid
                    ? '0 0 6px rgba(72,186,136,0.50), 0 0 2px rgba(140,230,190,0.30)'
                    : '0 0 5px rgba(200,155,60,0.40), 0 0 2px rgba(255,200,100,0.20)',
                }} />
              </div>
              <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '1.2px', textTransform: 'uppercase',
                color: isPaid ? 'rgba(140,225,180,0.70)' : 'rgba(200,155,60,0.60)',
                ...FS,
              }}>{planAccent.label}</span>
            </div>
          </div>
        </div>

        {/* Admin — plan switcher for testing free vs paid experience */}
        {isAdmin && (
          <>
            <SectionLabel label="ADMIN — SUBSCRIPTION TESTING" />
            <Panel>
              <p style={{ margin: 0, padding: '10px 20px 6px', fontSize: 11, color: steel(0.38), ...FS }}>
                Switch tiers to test paywall and feature gates.
              </p>
              <div style={{ display: 'flex', gap: 8, padding: '10px 20px 16px', flexWrap: 'nowrap' }}>
                {['free', 'paid', 'pro', 'studio', 'enterprise'].map(tier => {
                  const active = plan === tier;
                  const isFreeTier = tier === 'free';
                  const accentColor = isFreeTier ? 'rgba(200,155,60,' : 'rgba(72,186,136,';
                  return (
                    <div key={tier} style={{ position: 'relative' }}>
                      {/* Well cavity behind each button */}
                      <div style={{
                        position: 'absolute', inset: -1.5, borderRadius: 9,
                        boxShadow: [
                          'inset 4px 4px 10px rgba(0,0,0,0.80)',
                          'inset 2px 2px 5px rgba(0,0,0,0.60)',
                          'inset -1px -1px 2px rgba(255,255,255,0.012)',
                          '-0.5px -0.5px 1px rgba(255,255,255,0.03)',
                          '2px 3px 8px rgba(0,0,0,0.45)',
                          active ? `inset 0 0 6px ${accentColor}0.08)` : '',
                        ].filter(Boolean).join(', '),
                        pointerEvents: 'none',
                      }} />
                      {/* Button face */}
                      <button onClick={() => { setPlan(tier, { force: true }); softClickSound(); selectHaptic(); }}
                        style={{
                          position: 'relative',
                          background: active
                            ? `linear-gradient(141.71deg, ${isFreeTier ? '#2a2218' : '#1a2a22'} 0%, ${isFreeTier ? '#1c1810' : '#122018'} 100%)`
                            : 'linear-gradient(141.71deg, #1a1c22 0%, #131518 50%, #0c0d10 100%)',
                          border: 'none', borderRadius: 7, padding: '5px 10px', cursor: 'pointer',
                          boxShadow: [
                            '6px 6px 16px rgba(0,0,0,0.65)',
                            '3px 3px 7px rgba(0,0,0,0.48)',
                            '1px 1px 3px rgba(0,0,0,0.32)',
                            '-1px -1px 1px rgba(255,255,255,0.05)',
                            'inset 0 1.5px 0 rgba(255,255,255,0.09)',
                            'inset 1px 0 0 rgba(255,255,255,0.04)',
                            'inset -1px -1px 0 rgba(0,0,0,0.30)',
                            active ? `0 0 0 1px ${accentColor}0.30)` : '',
                            active ? `0 0 10px ${accentColor}0.10)` : '',
                          ].filter(Boolean).join(', '),
                          WebkitTapHighlightColor: 'transparent',
                          transition: 'transform 0.15s ease',
                          transform: active ? 'translateY(-1px)' : 'none',
                        }}
                      >
                        {/* Active LED dot */}
                        {active && (
                          <div style={{
                            position: 'absolute', top: -3, right: -3,
                            width: 8, height: 8, borderRadius: '50%',
                            background: isFreeTier
                              ? 'radial-gradient(circle at 35% 30%, rgba(255,220,160,0.95) 0%, rgba(200,155,60,0.80) 100%)'
                              : 'radial-gradient(circle at 35% 30%, rgba(180,255,220,0.95) 0%, rgba(72,186,136,0.80) 100%)',
                            boxShadow: isFreeTier
                              ? '0 0 6px rgba(200,155,60,0.50)'
                              : '0 0 6px rgba(72,186,136,0.50)',
                          }} />
                        )}
                        <span style={{
                          fontSize: 10.5, fontWeight: active ? 700 : 600,
                          letterSpacing: '0.8px', textTransform: 'uppercase',
                          color: active
                            ? `${accentColor}0.88)`
                            : steel(0.45),
                          textShadow: active ? `0 0 8px ${accentColor}0.20)` : 'none',
                          ...FS,
                        }}>{PLAN_LABELS[tier]}</span>
                      </button>
                    </div>
                  );
                })}
              </div>
              <Divider />
              <InfoRow label="Current tier" value={planLabel} />
              <Divider />
              <InfoRow label="Is paid" value={isPaid ? 'Yes' : 'No'} />
            </Panel>
          </>
        )}

        <SectionLabel label="ACCOUNT" />
        <Panel>
          <InfoRow label="Email" value={displayEmail || '—'} />
          <Divider />
          <NavRow
            label={resetSent ? 'Reset link sent ✓' : 'Reset Password'}
            onClick={handlePasswordReset}
          />
        </Panel>

        <SectionLabel label="BILLING" />
        <Panel>
          <NavRow
            label={isPaid ? 'Manage billing & invoices' : 'Upgrade to Pro'}
            onClick={async () => {
              if (isPaid) {
                window.open(`mailto:${SUPPORT_EMAIL}?subject=Billing%20%26%20Invoices`, '_blank');
              } else {
                try {
                  const { startStripeCheckout } = await import('../../../data/stripeCheckout');
                  await startStripeCheckout({ plan: 'pro' });
                } catch (err) {
                  alert(err.message || 'Could not start checkout');
                }
              }
              softClickSound();
            }}
          />
        </Panel>

        <div style={{ height: 16 }} />
        <Panel>
          <NavRow label="Sign Out" danger onClick={onLogout} />
        </Panel>

        <div style={{ height: 8 }} />
        <Panel>
          <NavRow label="Delete Account" danger onClick={async () => {
            if (!confirm('Are you sure you want to permanently delete your account? This cannot be undone.')) return;
            try {
              const { authHeaders } = await import('../../../data/authApi');
              const res = await fetch('/api/auth/me', {
                method: 'DELETE',
                headers: { ...authHeaders() },
              });
              if (!res.ok) throw new Error('Failed to delete account');
              localStorage.clear();
              window.location.href = '/';
            } catch (err) {
              alert(err.message || 'Could not delete account');
            }
          }} />
        </Panel>

      </div>
    </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Day1SettingsScreen({ user, onBack, onLogout, onLab }) {
  const [subScreen, setSubScreen] = useState('main');
  const [settings, setSettings]   = useState(loadSettings);
  const mode = useMode();
  const tapTimestamps = useRef([]);

  function update(key, val) {
    saveSetting(key, val);
    setSettings(prev => ({ ...prev, [key]: val }));
  }

  function cycleMode() {
    const modes = ['photographer', 'assistant', 'learning'];
    const idx = modes.indexOf(mode);
    saveMode(modes[(idx + 1) % modes.length]);
    softClickSound(); tapHaptic();
  }

  const [labEnabled, setLabEnabled] = useState(() => isEnabled('enable_lab'));
  const handleVersionTap = useCallback(() => {
    const now  = Date.now();
    const taps = tapTimestamps.current;
    taps.push(now);
    while (taps.length && taps[0] < now - DEV_TAP_WINDOW) taps.shift();
    if (taps.length >= DEV_TAP_COUNT) {
      taps.length = 0;
      const next = !isEnabled('enable_lab');
      setFlag('enable_lab', next);
      setLabEnabled(next);
      tapHaptic();
    }
  }, []);

  const displayName  = user?.username || user?.email?.split('@')[0] || 'User';
  const displayEmail = user?.email || user?.username || '';
  const { plan: mainPlan, isPaid: mainIsPaid, isAdmin: mainIsAdmin } = usePlan(displayEmail);

  if (subScreen === 'preferences') {
    return (
      <PreferencesScreen
        settings={settings}
        update={update}
        onBack={() => { navSlideSound(); setSubScreen('main'); }}
        mode={mode}
        isAdmin={mainIsAdmin}
      />
    );
  }

  if (subScreen === 'account') {
    return (
      <AccountScreen
        user={user}
        onBack={() => { navSlideSound(); setSubScreen('main'); }}
        onLogout={onLogout}
      />
    );
  }

  // ── MAIN ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, fontFamily: 'Inter, system-ui, -apple-system, sans-serif', overflow: 'hidden' }}>
      <MatteBackground variant="carbon" />
    <div style={{ position: 'relative', zIndex: 1, height: '100%', overflowY: 'auto', maxWidth: 720, margin: '0 auto' }}>

      {/* Ambient gear silhouette — desktop only, photography DNA */}
      <svg viewBox="0 0 200 260" fill="none" style={{
        position: 'fixed', bottom: '10%', right: '8%', width: 160, height: 210,
        opacity: 0.018, pointerEvents: 'none', zIndex: 0,
      }}>
        <circle cx="100" cy="60" r="35" stroke={steel(1)} strokeWidth="1.5" fill="none" />
        <circle cx="100" cy="60" r="15" stroke={steel(1)} strokeWidth="0.8" fill="none" />
        <line x1="100" y1="95" x2="100" y2="220" stroke={steel(1)} strokeWidth="1.2" />
        <line x1="65" y1="220" x2="135" y2="220" stroke={steel(1)} strokeWidth="1" />
        <line x1="75" y1="220" x2="100" y2="195" stroke={steel(1)} strokeWidth="0.8" />
        <line x1="125" y1="220" x2="100" y2="195" stroke={steel(1)} strokeWidth="0.8" />
      </svg>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '16px 20px 8px', position: 'sticky', top: 0, backgroundColor: 'rgba(8,9,12,0.92)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)', zIndex: 10 }}>
        <button
          onClick={() => { navSlideSound(); navHaptic(); onBack?.(); }}
          style={{ backgroundColor: 'transparent', border: 'none', cursor: 'pointer', fontSize: 16, color: steel(0.65), padding: '4px 0', WebkitTapHighlightColor: 'transparent', minWidth: 64, textAlign: 'left', ...FS }}
        >‹ Back</button>
        <h1 style={{ flex: 1, textAlign: 'center', margin: 0, fontSize: 16, fontWeight: 700, color: C.textPrimary, letterSpacing: '-0.2px', ...FS }}>Settings</h1>
        <div style={{ minWidth: 64 }} />
      </div>

      <div style={{ padding: '8px 20px 48px', position: 'relative', zIndex: 1 }}>

        {/* ── User card (taps → account) ── */}
        <button
          onClick={() => { navSlideSound(); tapHaptic(); setSubScreen('account'); }}
          style={{
            width: '100%', backgroundColor: C.panelBg, border: 'none', cursor: 'pointer',
            borderRadius: 14, padding: '16px 20px',
            boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
            display: 'flex', alignItems: 'center', gap: 14,
            WebkitTapHighlightColor: 'transparent', marginTop: 8,
          }}
        >
          {/* Avatar */}
          <div style={{
            width: 44, height: 44, borderRadius: 22, flexShrink: 0,
            backgroundColor: '#161820',
            boxShadow: '0px 2px 6px rgba(0,0,0,0.6), inset 0px 1px 0px rgba(255,255,255,0.05)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 18, color: steel(0.7), fontWeight: 600, ...FS }}>
              {displayName.charAt(0).toUpperCase()}
            </span>
          </div>
          {/* Info */}
          <div style={{ flex: 1, textAlign: 'left' }}>
            <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: C.textPrimary, ...FS }}>{displayName}</p>
            {displayEmail && displayEmail !== displayName && (
              <p style={{ margin: '3px 0 0', fontSize: 12, color: steel(0.5), ...FS }}>{displayEmail}</p>
            )}
          </div>
          {/* Plan badge — dynamic, reads from actual plan tier */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {(() => {
              const isFree = mainPlan === 'free';
              const accentC = isFree ? 'rgba(200,155,60,' : 'rgba(72,186,136,';
              const bgGrad = isFree
                ? 'linear-gradient(141.71deg, #2a2218 0%, #1c1810 100%)'
                : 'linear-gradient(141.71deg, #1a2a22 0%, #122018 100%)';
              return (
                <div style={{
                  background: bgGrad,
                  borderRadius: 8, padding: '5px 12px',
                  boxShadow: [
                    '4px 4px 10px rgba(0,0,0,0.55)',
                    '2px 2px 5px rgba(0,0,0,0.40)',
                    '-0.5px -0.5px 1px rgba(255,255,255,0.04)',
                    `inset 0 1px 0 ${accentC}0.10)`,
                    'inset -1px -1px 0 rgba(0,0,0,0.25)',
                    `0 0 0 0.5px ${accentC}0.20)`,
                    `0 0 8px ${accentC}0.06)`,
                  ].join(', '),
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: isFree
                      ? 'radial-gradient(circle at 35% 30%, rgba(255,220,160,0.95) 0%, rgba(200,155,60,0.80) 100%)'
                      : 'radial-gradient(circle at 35% 30%, rgba(180,255,220,0.95) 0%, rgba(72,186,136,0.80) 100%)',
                    boxShadow: isFree ? '0 0 4px rgba(200,155,60,0.50)' : '0 0 4px rgba(72,186,136,0.50)',
                  }} />
                  <span style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: '1px',
                    color: isFree ? 'rgba(200,155,60,0.80)' : 'rgba(140,225,180,0.80)',
                    ...FS,
                  }}>{PLAN_LABELS[mainPlan]?.toUpperCase() || 'FREE'}</span>
                </div>
              );
            })()}
            <span style={{ fontSize: 16, color: steel(0.40), lineHeight: 1 }}>›</span>
          </div>
        </button>

        {/* ── Role banner (taps to cycle mode) ── */}
        <button
          onClick={cycleMode}
          style={{
            width: '100%', backgroundColor: C.panelBg, border: 'none', cursor: 'pointer',
            borderRadius: 14, padding: '14px 20px', marginTop: 10,
            boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
            display: 'flex', alignItems: 'center', gap: 12,
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <div style={{
            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
            backgroundColor: 'rgba(132, 158, 184,0.12)',
            boxShadow: 'inset 0px 1px 2px rgba(0,0,0,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: steel(0.65), ...FS }}>
              {ROLE_META[mode]?.initial || 'P'}
            </span>
          </div>
          <div style={{ flex: 1, textAlign: 'left' }}>
            <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: C.textPrimary, ...FS }}>
              {ROLE_META[mode]?.label || 'Photographer'} mode
            </p>
            <p style={{ margin: '3px 0 0', fontSize: 11, color: steel(0.5), lineHeight: '14px', ...FS }}>
              {ROLE_META[mode]?.tagline}
            </p>
          </div>
          <span style={{ fontSize: 11, color: steel(0.4), flexShrink: 0, ...FS }}>Tap to change ›</span>
        </button>

        {/* ── GENERAL ── */}
        <SectionLabel label="GENERAL" />
        <Panel>
          <NavRow
            label="Units"
            value={settings.units === 'metric' ? 'Metric' : 'Imperial'}
            onClick={() => update('units', settings.units === 'metric' ? 'imperial' : 'metric')}
            tooltip="Switch between feet/inches and meters for all distance and height measurements."
          />
          <Divider />
          <ToggleRow
            label="Analysis auto-save"
            value={settings.sessionStorage === 'auto'}
            onChange={v => update('sessionStorage', v ? 'auto' : 'manual')}
            tooltip="Automatically save each analysis to your session history. When off, results are only available during the current session."
          />
          <Divider />
          <NavRow
            label="Preferences"
            onClick={() => { navSlideSound(); tapHaptic(); setSubScreen('preferences'); }}
            tooltip="Analysis settings, display options, shoot mode, and privacy controls."
          />
        </Panel>

        {/* ── SUPPORT ── */}
        <SectionLabel label="SUPPORT" />
        <Panel>
          <NavRow label="Contact support" onClick={() => window.open(`mailto:${SUPPORT_EMAIL}?subject=NGW%20Support`, '_blank')} />
          <Divider />
          <NavRow label="Rate NGW" onClick={() => {}} />
        </Panel>

        {/* ── LEGAL ── */}
        <SectionLabel label="LEGAL" />
        <Panel>
          <NavRow label="Privacy Policy" onClick={() => window.open(PRIVACY_URL, '_blank')} />
          <Divider />
          <NavRow label="Terms of Service" onClick={() => window.open(TERMS_URL, '_blank')} />
        </Panel>

        {/* ── Sign out ── */}
        {user && (
          <>
            <div style={{ height: 8 }} />
            <Panel>
              <NavRow label="Sign Out" danger onClick={onLogout} />
            </Panel>
          </>
        )}

        {/* Lab access — visible when dev mode is enabled */}
        {labEnabled && onLab && (
          <div style={{ padding: '12px 0 0' }}>
            <Panel>
              <NavRow label="Open Lab" onClick={() => { onLab(); softClickSound(); tapHaptic(); }} tooltip="Engine workbench — signals, benchmarks, gold set, diagnostics" />
            </Panel>
          </div>
        )}

        {/* ── Version tap (hidden dev mode trigger) ── */}
        <div
          onClick={handleVersionTap}
          style={{ textAlign: 'center', padding: '28px 0 8px', cursor: 'default' }}
        >
          <p style={{ margin: 0, fontSize: 11, color: steel(0.40), ...FS }}>No Guesswork Lighting</p>
          <p style={{ margin: '4px 0 0', fontSize: 10, color: steel(0.35), ...FS }}>{APP_VERSION}</p>
        </div>

      </div>

      <HomeIndicator />
    </div>
    </div>
  );
}
