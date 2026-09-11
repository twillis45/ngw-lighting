/**
 * Studio Matte — shared design tokens for Day1DemoApp screens.
 *
 * Single source of truth for all inline-style values.
 * CSS-variable equivalents live in tokens.css under "Studio Matte" block.
 *
 * Figma source: YQgGd8KZyZoXzZwJV7p4b6 / Studio Matte Theme
 */

// ─── Steel-blue tint helper ───────────────────────────────────────────────────
// Base RGB: 132, 158, 184 — brighter steel blue (bumped 2026-04-10 for
// calibrated-display legibility; was 95, 124, 150 which read washed-out).
// CSS equivalent: var(--sm-steel-r/g/b) in tokens.css
export const steel = (a) => `rgba(132, 158, 184,${a})`;

// ─── Key accent tint helper ──────────────────────────────────────────────────
// Base RGB: 200, 155, 69 — amber gold accent.
// Mirrors the steel() helper for KEY_ACCENT alpha tints.
export const accent = (a) => `rgba(200,155,69,${a})`;

// ─── Warm / Dusty Bronze tokens (Figma canonical Tier 1 attention) ──────────
// Figma palette 1318:2 section "ACCENT — WARM". Dusty Bronze replaces pure gold
// for cinematic teal-and-orange grading. Use for KEY arrows, modifier silhouettes,
// hero CTA gradients, ACTIVE chips, readout numerals — anywhere Tier 1 attention
// is needed.  The existing `accent()` amber gold remains for backward compat;
// new work should prefer `warm()` and WARM_* constants.
//
// Migration: screens will transition from `accent()`/KEY_ACCENT to `warm()`/
// WARM_PRIMARY over successive passes. Both coexist safely.
// ─── RULED 2026-09-11: bronze is a NON-TEXT family ──────────────────────────
// Review board, on measured contrast against the Studio Matte surfaces. The
// numbers, WCAG ratio then APCA Lc, on canvas #141518 / panel #242b31:
//
//   WARM_PRIMARY #A06D4A   4.16 / -30.5   3.26 / -27.5   fails AA, below headline
//   WARM_HOVER   #7F5536   2.83 / -19.2   2.22 / -16.1   near the absolute floor
//   WARM_TEXT    #C88A63   6.32 / -46.0   4.96 / -42.9   AA passes, APCA does not on panel
//   amber        #ef962e   7.89 / -56.0   6.19 / -52.9   clears headline everywhere
//
// No member of this family clears APCA's headline threshold on PANEL, which is
// the surface most text sits on. So:
//
//   USE bronze for   fills, key arrows, modifier silhouettes, hero CTA gradients
//   NEVER for        readout numerals, chip labels, body, meta — any text
//
// The readout case is the one that matters. A readout IS the data; an
// unreadable one is a broken instrument rather than a styled one. Text roles
// stay on amber #ef962e, ruled canonical 2026-09-10.
//
// WARM_TEXT is misnamed for what it can do — it fails the text threshold on
// panel. Restrict it to canvas and screen backgrounds, or rename it.
// Full record: ngw-os/docs/superpowers/specs/2026-09-09-visual-system-design.md (b11)
export const WARM_PRIMARY = '#A06D4A';  // key arrows, active chip FILL, hero CTA — never text
export const WARM_HOVER   = '#7F5536';
export const WARM_TEXT    = '#C88A63';   // canvas/screen only — fails APCA headline on PANEL (Lc -42.9). See the ruling above.
export const warm = (a) => `rgba(160,109,74,${a})`;

// Canonical KEY_ACCENT — single export so screens stop hardcoding the hex.
// Currently amber gold; will migrate to WARM_PRIMARY in a future pass.
export const KEY_ACCENT = '#c89b45';

// ─── Screen background ──────────────────────────────────────────────────────
// All Studio Matte full-screen roots use this Carbon Black instead of C.bg
// which is pure black. Provides a softer, warmer near-black.
// Figma canonical: #0B0B0C (Carbon Black, node 1318:2).
export const SCREEN_BG = '#0B0B0C';

// ─── Color palette ────────────────────────────────────────────────────────────
export const C = {
  // ── Surface ──
  bg:          '#000000',           // --sm-bg — Deep Black
  slotBg:      '#08080a',           // --sm-surface-slot
  wellBg:      '#050507',           // --sm-surface-well (ring tracks, deep insets)
  trackBg:     '#08090c',           // --sm-surface-track (scroll tracks, secondary wells)
  panelBg:     '#121316',           // --sm-surface  (Figma: Soft Black)
  pillBg:      '#070709',           // --sm-surface-pill
  ctaFrom:     '#3d404d',           // --sm-surface-cta-from
  ctaMid:      '#292b36',
  ctaTo:       '#1c1d24',           // --sm-surface-cta-to

  // ── Text ──
  textPrimary: 'rgba(245,247,250,0.95)',  // --sm-text-primary
  textSub:     'rgba(184,191,199,0.65)',  // --sm-text-sub
  textSubBold: 'rgba(184,191,199,0.85)',  // --sm-text-sub-bold
  textMeta:    '#a7adb7',                 // --sm-text-meta
  textDim:     'rgba(184,191,199,0.5)',   // --sm-text-dim
  textWarn:    'rgba(245,190,71,0.65)',

  // ── Confidence ──
  confHigh:    'rgba(72,186,136,0.95)',   // --sm-conf-high  (= --color-success)
  confHighBar: 'rgba(72,186,136,0.8)',
  confLow:     'rgba(245,190,72,0.9)',    // --sm-conf-low
  confLowBar:  'rgba(245,190,71,0.8)',
  confLowScore:'rgba(245,190,71,0.9)',

  // ── Structural ──
  homeBar:     'rgba(245,247,250,0.06)',
  divider:     'rgba(255,255,255,0.04)',  // --sm-divider
  barTrack:    'rgba(184,191,199,0.08)',  // --sm-bar-track
  barAlt:      'rgba(184,191,199,0.25)',

  // ── Danger ──
  textDanger:  'rgba(200,70,70,0.82)',
};

// ─── Typography ───────────────────────────────────────────────────────────────
export const FONT_SMOOTH = {
  WebkitFontSmoothing: 'antialiased',
  MozOsxFontSmoothing: 'grayscale',
  textRendering:       'geometricPrecision',
};

// ─── Relational type scale ───────────────────────────────────────────────────
// Floor-anchored scale: change FLOOR and everything adjusts proportionally.
// Ratio ~1.2 (minor third) between tiers — comfortable for instrument UI.
//
//   FLOOR (T6) = smallest readable text on high-DPI mobile (Galaxy S25, iPhone 15)
//   T5 = labels, section headings, chips
//   T4 = body text, spec values, drawer items
//   T3 = card titles, secondary headings
//   T2 = section titles, modifier names
//   T1 = hero leads, pattern names, big numbers
//   T0 = display / splash (used sparingly)
//
// To bump the whole scale: change FLOOR. Everything else follows.
const FLOOR = 14;
const R = 1.2; // minor third ratio
export const TYPE = {
  T0: Math.round(FLOOR * R * R * R * R * R),  // 35 — display
  T1: Math.round(FLOOR * R * R * R * R),       // 29 — hero
  T2: Math.round(FLOOR * R * R * R),            // 24 — section title
  T3: Math.round(FLOOR * R * R),                // 20 — card title
  T4: Math.round(FLOOR * R),                    // 17 — body
  T5: FLOOR + 1,                                // 15 — labels
  T6: FLOOR,                                    // 14 — floor (smallest)
  FLOOR,
};
export const TYPE_DK = {
  T0: Math.round(FLOOR * R * R * R * R * R) + 6, // 41
  T1: Math.round(FLOOR * R * R * R * R) + 4,     // 33
  T2: Math.round(FLOOR * R * R * R) + 2,          // 26
  T3: Math.round(FLOOR * R * R) + 2,              // 22
  T4: Math.round(FLOOR * R) + 1,                  // 18
  T5: FLOOR + 1,                                  // 15
  T6: FLOOR,                                      // 14
  FLOOR,
};

// ─── Focus-visible ring ──────────────────────────────────────────────────────
// Steel-blue ring that shows ONLY on keyboard navigation (:focus-visible).
// Since inline styles can't target :focus-visible, inject as a <style> tag or
// apply via onFocus/onBlur + a state flag.  The constant is the boxShadow value
// to merge into a component's existing boxShadow when focused.
export const FOCUS_RING = `0 0 0 2px ${steel(0.55)}, 0 0 8px ${steel(0.20)}`;

// ─── Panel shadow + bevel (Figma 1515:2) ─────────────────────────────────────
export const PANEL_SHADOW = '1px 2px 4px 0px rgba(0,0,0,0.2), 2px 4px 12px 0px rgba(0,0,0,0.4)';
export const PANEL_BEVEL  = 'inset -1px -1px 2px 0px rgba(0,0,0,0.12), inset 1px 1px 0px 0px rgba(255,255,255,0.05)';

// ─── Numeric readout tokens ──────────────────────────────────────────────────
// Canonical foreground for any "instrument" numeric readout (angle dials,
// density %, distance counters, etc.).  Always reach for these instead of
// C.textSub when a number is the SUBJECT of the widget — textSub is meant
// for secondary copy and reads as washed-out grey on calibrated displays.
//
// READOUT_FG    — bright primary readout colour (warm pearl)
// READOUT_GLOW  — engraved text shadow that lifts the digits off the well
// READOUT_LABEL — small letter-spaced label colour above/below the readout
export const READOUT_FG    = 'rgba(245,210,140,0.95)';
export const READOUT_GLOW  = '0 1px 0 rgba(0,0,0,0.7), 0 0 6px rgba(245,190,72,0.18)';
export const READOUT_LABEL = 'rgba(150,158,170,0.78)';

// ─── Pull-tab drawer tokens ──────────────────────────────────────────────────
// Single source of truth for the tactile pullout used across SetupScreen and
// ResultScreen.  The handle pill is a tiny inset slot machined into the panel
// surface; the open-state foreground glows amber so closed/open state is
// instantly readable.  Mirrors PullTabDrawer.jsx in screens/studio/_shared.
export const DRAWER_HANDLE_SHADOW = 'inset 0px 1px 3px 0px rgba(0,0,0,0.6), inset 0px 0px 6px 0px rgba(0,0,0,0.3)';
export const DRAWER_HANDLE_BG     = '#0a0b0d';
export const DRAWER_RADIUS        = 14;
export const DRAWER_LABEL_FG_OPEN   = 'rgba(245,210,140,0.92)';
export const DRAWER_LABEL_FG_CLOSED = steel(0.75);

// ─── Engraved label text shadow ───────────────────────────────────────────────
// Dark top-edge shadow (light source above) + faint bottom reflection = pressed
// into surface. Use on LIGHTING, ANALYZE, ANALYZING, and any all-caps engraved label.
// CSS-variable equivalent: --sm-text-shadow-engraved in tokens.css
export const TEXT_SHADOW_ENGRAVED = '0 -1px 1px rgba(0,0,0,0.75), 0 1px 0 rgba(255,255,255,0.05), 0 0 2px rgba(0,0,0,0.35)';

// ─── CTA button (Figma 1494:12) ───────────────────────────────────────────────
export const CTA_BG     = `linear-gradient(141.71deg, ${C.ctaFrom} 0%, ${C.ctaMid} 50%, ${C.ctaTo} 100%)`;
export const CTA_SHADOW = `0px 0px 6px 1px ${steel(0.08)}, 1px 2px 4px 0px rgba(0,0,0,0.45), 2px 5px 12px 0px rgba(0,0,0,0.7)`;
export const CTA_BEVEL  = 'inset -1px -1px 2px 0px rgba(0,0,0,0.3), inset 1px 1px 0px 0px rgba(255,255,255,0.2)';

// ─── Viewfinder layers (shared HomeScreen ↔ ResultScreen) ────────────────────
// Directional inset — light comes from 141.71° (upper-left), so the near rim
// (upper-left) casts a hard dark shadow into the well while the far rim
// (lower-right) picks up a faint steel-blue bounce. Reads as a recessed well
// machined into the matte metal surface.
export const VIEWFINDER_INNER_SHADOW = [
  'inset 5px 6px 16px 0px rgba(0,0,0,0.88)',
  'inset 3px 4px 9px 0px rgba(0,0,0,0.70)',
  'inset 2px 2px 4px 0px rgba(0,0,0,0.55)',
  'inset 1px 1px 2px 0px rgba(0,0,0,0.50)',
  'inset -1px -1px 1px 0px rgba(255,255,255,0.05)',
  'inset -2px -2px 5px 0px rgba(132, 158, 184,0.07)',
  'inset 0px 0px 24px 0px rgba(132, 158, 184,0.05)',
  'inset 0px 0px 12px 0px rgba(132, 158, 184,0.07)',
].join(', ');

export const GLASS_REFLECTION = [
  'linear-gradient(141.71deg,',
  'rgba(255,255,255,0.14) 0%,',
  'rgba(255,255,255,0.12) 2%,',
  'rgba(255,255,255,0.09) 4%,',
  'rgba(255,255,255,0.07) 6.5%,',
  'rgba(255,255,255,0.058) 9%,',
  'rgba(255,255,255,0.047) 12%,',
  'rgba(255,255,255,0.037) 16%,',
  'rgba(255,255,255,0.029) 20%,',
  'rgba(255,255,255,0.022) 25%,',
  'rgba(255,255,255,0.017) 30%,',
  'rgba(255,255,255,0.013) 36%,',
  'rgba(255,255,255,0.010) 42%,',
  'rgba(255,255,255,0.007) 48%,',
  'rgba(255,255,255,0.005) 54%,',
  'rgba(255,255,255,0.006) 62%,',
  'rgba(255,255,255,0.008) 68%,',
  'rgba(255,255,255,0.006) 74%,',
  'rgba(255,255,255,0.002) 80%,',
  'rgba(255,255,255,0) 86%)',
].join(' ');

// Lens vignette — ultra-smooth falloff with 8 stops to prevent visible edge.
// The transition zone spans 40–100% so there's no sharp ring.
// Lens vignette — 16 stops for zero banding on mobile OLED
export const LENS_VIGNETTE = 'radial-gradient(ellipse 110% 95% at center, transparent 35%, rgba(0,0,0,0.003) 40%, rgba(0,0,0,0.006) 44%, rgba(0,0,0,0.01) 48%, rgba(0,0,0,0.016) 52%, rgba(0,0,0,0.024) 56%, rgba(0,0,0,0.035) 60%, rgba(0,0,0,0.05) 64%, rgba(0,0,0,0.07) 68%, rgba(0,0,0,0.09) 72%, rgba(0,0,0,0.12) 76%, rgba(0,0,0,0.15) 80%, rgba(0,0,0,0.18) 85%, rgba(0,0,0,0.21) 90%, rgba(0,0,0,0.24) 95%, rgba(0,0,0,0.25) 100%)';

// ─── VF dither noise layer ──────────────────────────────────────────────────
// Subtle high-frequency noise breaks up gradient banding in LENS_VIGNETTE and
// GLASS_REFLECTION. The SVG encodes a 200×200 feTurbulence tile that repeats
// seamlessly. Tiny footprint (~250 bytes), zero network requests.
export const VF_DITHER_NOISE = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E")`;

// ─── Dither style — apply to a sibling div alongside any vignette/gradient ──
// Usage: <div style={DITHER_STYLE} />  placed right after the vignette div.
// This is the single source of truth for anti-banding across all screens.
// Dither confined to vignette edges — transparent center, noise only where
// gradient banding is visible (outer 40%). Uses a radial mask so the hero
// photo center stays clean.
export const DITHER_STYLE = {
  position: 'absolute', inset: 0,
  backgroundImage: VF_DITHER_NOISE, backgroundSize: '200px 200px',
  opacity: 0.28, mixBlendMode: 'overlay',
  pointerEvents: 'none',
  maskImage: 'radial-gradient(ellipse 110% 95% at center, transparent 45%, black 75%)',
  WebkitMaskImage: 'radial-gradient(ellipse 110% 95% at center, transparent 45%, black 75%)',
};

// ─── Metallic chevron (glossy embossed icon treatment) ────────────────────────
export const METALLIC_CHEVRON = {
  backgroundImage: 'linear-gradient(141.71deg, rgba(40,44,52,0.95) 0%, rgba(70,78,90,0.90) 30%, rgba(25,28,34,0.85) 55%, rgba(55,62,72,0.80) 75%, rgba(20,22,28,0.90) 100%)',
  WebkitBackgroundClip: 'text',
  backgroundClip: 'text',
  color: 'transparent',
  ...FONT_SMOOTH,
  filter: 'drop-shadow(0px 1px 1px rgba(0,0,0,0.6)) drop-shadow(0px -1px 0px rgba(255,255,255,0.10)) drop-shadow(0px 0px 2px rgba(132, 158, 184,0.12))',
};

// ─── Neumorphic button states ─────────────────────────────────────────────────
// Raised tile — primary action (New Photo / Retake). Use on the dominant button
// in a bottom-actions trough. Two variants: neutral steel and amber-warm tint.
export const BTN_RAISED_UP = [
  '0px 6px 16px 0px rgba(0,0,0,0.8)',
  '0px 3px 6px 0px rgba(0,0,0,0.6)',
  '0px 1px 2px 0px rgba(0,0,0,0.4)',
  `inset 0px 1.5px 0px 0px rgba(255,255,255,0.18)`,
  'inset 0px -1.5px 0px 0px rgba(0,0,0,0.45)',
  `inset 0px 0px 16px 0px rgba(132, 158, 184,0.07)`,
  '0px 0px 0px 0.5px rgba(0,0,0,0.5)',
].join(', ');

export const BTN_RAISED_DOWN = [
  '0px 0px 2px 0px rgba(0,0,0,0.5)',
  'inset 0px 2px 4px 0px rgba(0,0,0,0.6)',
  'inset 0px 1px 2px 0px rgba(0,0,0,0.4)',
  'inset 0px -0.5px 0px 0px rgba(255,255,255,0.04)',
].join(', ');

// Recessed tile — secondary action (Save / Set up anyway). Resting state must
// show visible inset shadow so it reads as "sunk" next to the raised button.
export const BTN_RECESSED_UP = [
  'inset 0px 2px 5px 0px rgba(0,0,0,0.55)',
  'inset 0px 1px 2px 0px rgba(0,0,0,0.35)',
  'inset 0px -0.5px 0px 0px rgba(255,255,255,0.03)',
].join(', ');

export const BTN_RECESSED_DOWN = [
  'inset 0px 3px 7px 0px rgba(0,0,0,0.7)',
  'inset 0px 1px 3px 0px rgba(0,0,0,0.5)',
].join(', ');

// ─── Nav / Dock tokens ──────────────────────────────────────────────────────
// Ghost nav links — recede until hover. Used for desktop dock on Home,
// secondary nav on Settings, and any discoverable-on-hover navigation.
export const NAV_GHOST = {
  color: steel(0.35),
  hoverColor: steel(0.65),
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.1em',
};

// Machined nav button — raised dome for settings/gear buttons.
// Consistent across Home top-bar, Settings header, Lab Exit.
export const NAV_BTN = {
  bg: 'linear-gradient(141.71deg, #1e2028 0%, #151720 50%, #0e0f14 100%)',
  borderRadius: 10,
  padding: '8px 16px',
  shadow: '5px 5px 14px rgba(0,0,0,0.55), 2px 2px 6px rgba(0,0,0,0.40), -1px -1px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07), inset -1px -1px 0 rgba(0,0,0,0.25)',
  iconSize: 13,
  iconColor: steel(0.45),
  labelSize: 11.5,
  labelColor: steel(0.50),
};

// Identity badge — inset well showing username. Used on Home desktop header.
export const IDENTITY_BADGE = {
  bg: 'linear-gradient(141.71deg, #0e1014 0%, #0a0b0e 100%)',
  shadow: 'inset 2px 2px 5px rgba(0,0,0,0.55), inset -0.5px -0.5px 1px rgba(255,255,255,0.015), 1px 1px 3px rgba(0,0,0,0.30)',
  padding: '5px 12px',
  borderRadius: 6,
  fontSize: 9,
  fontWeight: 700,
  letterSpacing: '1.5px',
  color: steel(0.28),
};

// Dot separator for ghost nav
export const NAV_DOT = { color: steel(0.12), fontSize: 10 };

// ─── Machined surface gradients ──────────────────────────────────────────────
// 141.71° directional gradient — the signature Studio Matte depth direction.
// Used on buttons, chips, panels, docks, and any raised surface.
export const MACHINED_BG = 'linear-gradient(141.71deg, #1a1c22 0%, #131518 50%, #0c0d10 100%)';
export const MACHINED_PANEL_BG = 'linear-gradient(141.71deg, #12141a 0%, #0c0d12 100%)';
export const MACHINED_SHADOW = [
  '4px 4px 12px rgba(0,0,0,0.55)',
  '2px 2px 5px rgba(0,0,0,0.40)',
  '-0.5px -0.5px 1px rgba(255,255,255,0.04)',
  'inset 0 1px 0 rgba(255,255,255,0.07)',
  'inset -1px -1px 0 rgba(0,0,0,0.25)',
].join(', ');

// ─── Green toggle (settings toggles) ─────────────────────────────────────────
export const GREEN        = 'rgba(72,186,136,0.9)';
export const GREEN_DIM    = 'rgba(72,186,136,0.18)';
export const GREEN_BORDER = 'rgba(72,186,136,0.2)';
