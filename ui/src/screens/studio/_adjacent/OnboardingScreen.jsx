/**
 * OnboardingScreen — Studio Matte first-run profiling wizard.
 *
 * 2 steps: (1) Experience + Genre, (2) Setting + Modifier.
 * Saves photographer_profile to server preferences.
 * Shown once after first login.
 */
import { useState } from 'react';
import { steel, C, FONT_SMOOTH, SCREEN_BG, CTA_BG, CTA_SHADOW, CTA_BEVEL,
         PANEL_SHADOW, PANEL_BEVEL, KEY_ACCENT } from '../../../theme/studioMatte';
import MatteBackground from '../_shared/MatteBackground';
import { savePreference } from '../../../data/authApi';
import { tapHaptic, navHaptic } from '../../../utils/haptics';
import { softClickSound } from '../../../utils/sounds';
import { useMinWidth } from '../../../utils/useIsDesktop';

const EXPERIENCE = [
  { value: 'beginner',    label: 'Beginner' },
  { value: 'hobbyist',    label: 'Hobbyist' },
  { value: 'semi_pro',    label: 'Semi-pro' },
  { value: 'working_pro', label: 'Working pro' },
  { value: 'educator',    label: 'Educator' },
];

const GENRE = [
  { value: 'portrait',    label: 'Portrait' },
  { value: 'wedding',     label: 'Wedding' },
  { value: 'commercial',  label: 'Commercial' },
  { value: 'headshots',   label: 'Headshots' },
  { value: 'fashion',     label: 'Fashion' },
  { value: 'events',      label: 'Events' },
  { value: 'product',     label: 'Product' },
  { value: 'other',       label: 'Other' },
];

const SETTING = [
  { value: 'studio',   label: 'Studio' },
  { value: 'location', label: 'On-location' },
  { value: 'mixed',    label: 'Both' },
];

const MODIFIER = [
  { value: 'softbox',     label: 'Softbox' },
  { value: 'octobox',     label: 'Octobox' },
  { value: 'beauty_dish', label: 'Beauty dish' },
  { value: 'umbrella',    label: 'Umbrella' },
  { value: 'natural',     label: 'Natural light' },
  { value: 'varies',      label: 'Varies' },
];

const STEPS = [
  {
    title: 'How do you shoot?',
    subtitle: 'Helps us tune guidance to your level',
    sections: [
      { key: 'experience', label: 'EXPERIENCE', options: EXPERIENCE, multi: false },
      { key: 'genre',      label: 'GENRE',      options: GENRE,      multi: true },
    ],
  },
  {
    title: 'Your setup',
    subtitle: 'We\'ll tailor suggestions to your workflow',
    sections: [
      { key: 'setting',  label: 'ENVIRONMENT', options: SETTING,  multi: false },
      { key: 'modifier', label: 'GO-TO MODIFIER', options: MODIFIER, multi: false },
    ],
  },
];

function Chip({ label, selected, onClick, large }) {
  return (
    <button onClick={onClick} style={{
      padding: large ? '12px 26px' : '10px 20px', borderRadius: 10, border: 'none', cursor: 'pointer',
      background: selected
        ? `linear-gradient(141.71deg, #2a2218 0%, #1c1810 100%)`
        : `linear-gradient(141.71deg, #1a1c22 0%, #131518 50%, #0c0d10 100%)`,
      boxShadow: selected
        ? `4px 4px 12px rgba(0,0,0,0.50), 0 0 0 0.5px rgba(200,155,69,0.30), 0 0 8px rgba(200,155,69,0.06), inset 0 1px 0 rgba(200,155,69,0.10)`
        : `4px 4px 12px rgba(0,0,0,0.50), -0.5px -0.5px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07)`,
      WebkitTapHighlightColor: 'transparent',
      transition: 'all 0.15s ease',
    }}>
      <span style={{
        fontSize: large ? 13 : 12, fontWeight: selected ? 700 : 600,
        color: selected ? KEY_ACCENT : steel(0.55),
        letterSpacing: '0.3px', ...FONT_SMOOTH,
      }}>{label}</span>
    </button>
  );
}

export default function OnboardingScreen({ onComplete }) {
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState({ experience: null, genre: [], setting: null, modifier: null });
  const [saving, setSaving] = useState(false);

  const currentStep = STEPS[step];

  function updateField(key, value, multi) {
    tapHaptic();
    setProfile(prev => {
      if (!multi) return { ...prev, [key]: value };
      const cur = Array.isArray(prev[key]) ? prev[key] : [];
      return { ...prev, [key]: cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value] };
    });
  }

  async function handleNext() {
    softClickSound(); navHaptic();
    if (step < STEPS.length - 1) {
      setStep(s => s + 1);
    } else {
      setSaving(true);
      try {
        await savePreference('photographer_profile', profile);
      } catch { /* ignore */ }
      setSaving(false);
      onComplete?.();
    }
  }

  function handleSkip() {
    softClickSound();
    try { localStorage.setItem('ngw_onboarding_skipped', '1'); } catch {}
    onComplete?.();
  }

  const isWide = useMinWidth(820);

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'Inter, system-ui, sans-serif' }}>
      <MatteBackground variant="carbon" />
      <div style={{ position: 'relative', zIndex: 1, width: '100%', maxWidth: isWide ? 600 : 440, padding: isWide ? '0 40px' : '0 24px' }}>
        {/* Step indicator */}
        <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginBottom: 28 }}>
          {STEPS.map((_, i) => (
            <div key={i} style={{
              width: i === step ? 24 : 8, height: 4, borderRadius: 2,
              background: i === step ? KEY_ACCENT : steel(0.15),
              transition: 'all 0.3s ease',
            }} />
          ))}
        </div>

        {/* Title */}
        <h2 style={{ margin: '0 0 8px', fontSize: isWide ? 34 : 28, fontWeight: 800, color: 'rgba(245,247,250,0.95)', letterSpacing: '-0.5px', textAlign: 'center', lineHeight: 1.2, textShadow: '0 1px 3px rgba(0,0,0,0.5)', ...FONT_SMOOTH }}>
          {currentStep.title}
        </h2>
        <p style={{ margin: '0 0 32px', fontSize: isWide ? 15 : 13, fontWeight: 500, color: steel(0.50), textAlign: 'center', letterSpacing: '0.1px', ...FONT_SMOOTH }}>
          {currentStep.subtitle}
        </p>

        {/* Sections */}
        {currentStep.sections.map(section => (
          <div key={section.key} style={{ marginBottom: 24 }}>
            <p style={{ margin: '0 0 10px', fontSize: 9, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.35), ...FONT_SMOOTH }}>
              {section.label}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {section.options.map(opt => (
                <Chip
                  key={opt.value}
                  label={opt.label}
                  large={isWide}
                  selected={section.multi
                    ? (Array.isArray(profile[section.key]) && profile[section.key].includes(opt.value))
                    : profile[section.key] === opt.value}
                  onClick={() => updateField(section.key, opt.value, section.multi)}
                />
              ))}
            </div>
          </div>
        ))}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 12, marginTop: 24, justifyContent: 'center' }}>
          <button onClick={handleSkip} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 12, fontWeight: 600, color: steel(0.30), letterSpacing: '0.3px',
            padding: '12px 20px', ...FONT_SMOOTH,
          }}>Skip</button>
          <button onClick={handleNext} style={{
            padding: '14px 48px', borderRadius: 12, border: 'none', cursor: 'pointer',
            background: CTA_BG, boxShadow: `${CTA_SHADOW}, ${CTA_BEVEL}`,
            WebkitTapHighlightColor: 'transparent',
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.80), ...FONT_SMOOTH }}>
              {saving ? 'Saving…' : step < STEPS.length - 1 ? 'NEXT' : 'START'}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
