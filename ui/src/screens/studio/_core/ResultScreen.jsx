/**
 * ResultScreen — Studio Matte design
 * Pixel-exact match to Figma:
 *   Confident:  YQgGd8KZyZoXzZwJV7p4b6 / 1493:2
 *   Uncertain:  YQgGd8KZyZoXzZwJV7p4b6 / 1498:2
 *
 * Layout: absolute-positioned top section (hero, pattern, pills, CTA)
 *         + flow analytical panel that expands in-place
 * All data from props — no hardcoded sample values.
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { startStripeCheckout } from '../../../data/stripeCheckout';
import { saveSetup } from '../../../data/setupStore';
import { postSignal } from '../../../data/signalsApi';
import { getToken } from '../../../data/authApi';
import { createPortal } from 'react-dom';
import CorrectionSheet from './components/CorrectionSheet';
import { tapHaptic, selectHaptic, successHaptic, navHaptic } from '../../../utils/haptics';
import { getFaceCropPosition } from '../../../utils/faceCrop';
import { useIsDesktop, useViewportWidth, TABLET_MIN_WIDTH } from '../../../utils/useIsDesktop';
import { useDeviceTilt, glassReflectionTransform } from '../../../utils/useDeviceTilt';
import prettify from '../../../utils/prettify';
import { formatSetupText } from '../../../utils/formatSetupText';
import useStableViewport from '../../../utils/useStableViewport';
import { resultRevealSound, segmentPressSound, navSlideSound, softClickSound } from '../../../utils/sounds';
import { loadSettings } from '../../../data/settingsStore';
import EvidenceReadout from '../_shared/EvidenceReadout';
import { scoreIsMeaningful, isDecline } from '../_shared/lightingEvidence';
import { steel, C, FONT_SMOOTH, VIEWFINDER_INNER_SHADOW, GLASS_REFLECTION, LENS_VIGNETTE, DITHER_STYLE,
         CTA_BG, CTA_SHADOW, CTA_BEVEL, PANEL_SHADOW, PANEL_BEVEL,
         TEXT_SHADOW_ENGRAVED,
         READOUT_FG, READOUT_GLOW, READOUT_LABEL,
         DRAWER_RADIUS,
         BTN_RAISED_UP, BTN_RAISED_DOWN, BTN_RECESSED_UP, BTN_RECESSED_DOWN,
         MACHINED_BG, MACHINED_PANEL_BG, MACHINED_SHADOW, SCREEN_BG,
          } from '../../../theme/studioMatte';
import MatteBackground from '../_shared/MatteBackground';
import ViewfinderHUD from '../_shared/ViewfinderHUD';
import LightingDiagram from './components/LightingDiagram';
import SocialExportPanel from '../../../cards/SocialExportPanel';
import { svgToCanvasElement } from '../../../utils/exportSvg';
import ExifStrip from '../_shared/ExifStrip';
import { Component } from 'react';

// Error boundary — prevents SocialExportPanel crashes from killing the result page
class SafeRender extends Component {
  constructor(props) { super(props); this.state = { error: false }; }
  static getDerivedStateFromError() { return { error: true }; }
  componentDidCatch(err) { console.warn('[SafeRender]', err.message); }
  render() { return this.state.error ? null : this.props.children; }
}
import SideViewDiagram from './components/SideViewDiagram';
import Chip, { sevToVariant } from '../_shared/Chip';
import PullTabDrawer from '../_shared/PullTabDrawer';
import ModifierSilhouette from '../_shared/ModifierSilhouette';
import ModifierEmission from '../_shared/ModifierEmission';

// Pill inset shadow — exact from Figma pill nodes
const PILL_SHADOW = 'inset 1px 1px 2px 0px rgba(0,0,0,0.2), inset 1px 2px 4px 0px rgba(0,0,0,0.4)';

// prettify imported from utils/prettify.js — single canonical location.

// ─── SubLabel ───────────────────────────────────────────────────────────────
// 9px engraved uppercase label used to demarcate sub-sections inside a pull-
// out drawer. Sits flush-left with a hairline of letter-spacing so multiple
// blocks of content (signal · components · direction · read) read as
// discrete groups instead of a soup of widgets stacked together.
function SubLabel({ children }) {
  return (
    <p style={{
      margin: '14px 0 6px',
      fontSize: 12, fontWeight: 700,
      color: 'rgba(132, 158, 184,0.62)',
      letterSpacing: '1.2px',
      textTransform: 'uppercase',
      ...FONT_SMOOTH,
    }}>
      {children}
    </p>
  );
}

// ─── DiagnosticsDisclosure ─────────────────────────────────────────────────
// Collapsed-by-default sub-section for engine diagnostics inside the DETAIL
// drawer. Keeps raw signals, pass reliability, supporting/contradicting
// evidence out of the photographer's face while still accessible.
function DiagnosticsDisclosure({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <div
        role="button"
        tabIndex={0}
        onClick={() => { setOpen(v => !v); tapHaptic(); }}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(v => !v); tapHaptic(); } }}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 0',
          cursor: 'pointer',
          WebkitTapHighlightColor: 'transparent',
        }}
      >
        <span style={{
          fontSize: 11, fontWeight: 700,
          color: steel(0.50),
          letterSpacing: '1px',
          padding: '3px 8px',
          borderRadius: 4,
          backgroundColor: 'rgba(255,255,255,0.02)',
          ...FONT_SMOOTH,
        }}>
          {open ? '▾' : '▸'} ENGINE DIAGNOSTICS
        </span>
      </div>
      {open && (
        <div style={{ paddingTop: 4 }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ─── SectionPanel ──────────────────────────────────────────────────────────
// Always-visible analytical panel — same visual chrome as PullTabDrawer
// (panel bg, bevel, shadow, radius) but no toggle, no collapse.  A quiet
// engraved section header sits at the top so the information hierarchy reads
// like a professional spec sheet:  THE LIGHT  |  THE SETUP  |  DETAIL ▸
function SectionPanel({ label, children }) {
  return (
    <div style={{
      borderRadius: DRAWER_RADIUS,
      backgroundColor: C.panelBg,
      boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
      overflow: 'hidden',
      position: 'relative',
    }}>
      {/* Bevel overlay */}
      <div style={{
        position: 'absolute', inset: 0,
        borderRadius: DRAWER_RADIUS,
        pointerEvents: 'none',
        boxShadow: PANEL_BEVEL,
        zIndex: 10,
      }} />
      {/* Section header — authoritative left-aligned label with hairline rule */}
      <div style={{
        padding: '10px 16px 0',
      }}>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: steel(0.62),
          letterSpacing: '1.2px',
          textShadow: '0 1px 0 rgba(0,0,0,0.5)',
          ...FONT_SMOOTH,
        }}>
          {label}
        </span>
        <div style={{
          marginTop: 8,
          height: 1,
          background: 'linear-gradient(to right, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.03) 60%, transparent 100%)',
          boxShadow: '0 0.5px 0 rgba(0,0,0,0.4)',
        }} />
      </div>
      {/* Content */}
      <div style={{ padding: '10px 16px 12px' }}>
        {children}
      </div>
    </div>
  );
}

// ─── BlownHighlightsCanvas ──────────────────────────────────────────────────
// Client-side luminance scanner. When the Blown Highlights chip is tapped,
// this canvas overlays the hero photo and tints any pixel whose RGB exceeds
// the clipping threshold so the user can see exactly WHERE the engine flagged
// the blown regions. No engine roundtrip required — the analysis runs on the
// already-loaded image bitmap. We process at display resolution (bounded by
// the canvas element size, NOT the source image) and render two passes: a hot
// red core for fully-clipped pixels and a softer
// orange wash for near-clipped (warning) pixels. The canvas mirrors the same
// objectFit / objectPosition the hero <img> uses so the overlay tracks the
// visible photo area exactly.
function BlownHighlightsCanvas({ src, objectFit, objectPosition }) {
  const canvasRef = useRef(null);
  const [stats, setStats] = useState(null); // { clippedPct, warnPct } | null

  useEffect(() => {
    if (!src) return;
    let cancelled = false;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      if (cancelled) return;
      const cvs = canvasRef.current;
      if (!cvs) return;
      const rect = cvs.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cvs.width  = Math.max(1, Math.floor(rect.width  * dpr));
      cvs.height = Math.max(1, Math.floor(rect.height * dpr));
      const ctx = cvs.getContext('2d');
      ctx.scale(dpr, dpr);
      // Mirror objectFit math: object-fit:contain → letterbox; cover → crop.
      const cw = rect.width, ch = rect.height;
      const ir = img.naturalWidth / img.naturalHeight;
      const cr = cw / ch;
      let dx, dy, dw, dh;
      if (objectFit === 'contain') {
        if (ir > cr) { dw = cw; dh = cw / ir; dx = 0; dy = (ch - dh) / 2; }
        else         { dh = ch; dw = ch * ir; dx = (cw - dw) / 2; dy = 0; }
      } else { // cover
        if (ir > cr) { dh = ch; dw = ch * ir; dx = (cw - dw) / 2; dy = 0; }
        else         { dw = cw; dh = cw / ir; dx = 0; dy = (ch - dh) / 2; }
        // Honor objectPosition string like "50% 30%" for cover mode.
        if (typeof objectPosition === 'string') {
          const m = objectPosition.match(/(-?\d+(?:\.\d+)?)%\s+(-?\d+(?:\.\d+)?)%/);
          if (m) {
            const px = parseFloat(m[1]) / 100;
            const py = parseFloat(m[2]) / 100;
            dx = (cw - dw) * px;
            dy = (ch - dh) * py;
          }
        }
      }
      ctx.drawImage(img, dx, dy, dw, dh);
      // Read back, threshold, paint highlight tint.
      try {
        const data = ctx.getImageData(0, 0, Math.floor(cw), Math.floor(ch));
        const px = data.data;
        let clipped = 0, warn = 0, total = 0;
        const HOT  = [255, 64, 64, 200];
        const WARN = [255, 180, 60, 130];
        for (let i = 0; i < px.length; i += 4) {
          const r = px[i], g = px[i+1], b = px[i+2], a = px[i+3];
          if (a < 8) continue;
          total++;
          const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
          if (r >= 252 && g >= 252 && b >= 252) {
            px[i]=HOT[0]; px[i+1]=HOT[1]; px[i+2]=HOT[2]; px[i+3]=HOT[3];
            clipped++;
          } else if (lum >= 240) {
            px[i]=WARN[0]; px[i+1]=WARN[1]; px[i+2]=WARN[2]; px[i+3]=WARN[3];
            warn++;
          } else {
            px[i+3] = 0;
          }
        }
        ctx.putImageData(data, 0, 0);
        setStats({
          clippedPct: total ? (clipped / total) * 100 : 0,
          warnPct:    total ? (warn    / total) * 100 : 0,
        });
      } catch (e) {
        // Likely a tainted canvas (CORS) — give a soft fallback message.
        console.warn('BlownHighlightsCanvas: unable to read pixels', e);
        setStats({ error: true });
      }
    };
    img.src = src;
    return () => { cancelled = true; };
  }, [src, objectFit, objectPosition]);

  return (
    <div style={{
      position: 'absolute', inset: 0, pointerEvents: 'none',
      mixBlendMode: 'screen',
    }}>
      <canvas
        ref={canvasRef}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      />
      {stats && !stats.error && (
        <div style={{
          position: 'absolute', top: 10, left: 10,
          padding: '6px 10px', borderRadius: 8,
          backgroundColor: 'rgba(8,9,12,0.78)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.5), inset 0 0 0 0.5px rgba(255,255,255,0.06)',
          fontSize: 12, fontWeight: 700,
          color: 'rgba(245,180,90,0.95)',
          letterSpacing: '0.6px',
          mixBlendMode: 'normal',
          ...FONT_SMOOTH,
        }}>
          {stats.clippedPct.toFixed(1)}% CLIPPED · {stats.warnPct.toFixed(1)}% NEAR
        </div>
      )}
    </div>
  );
}

// PullTabDrawer is now imported from `_shared/PullTabDrawer` so any future
// styling tweak (handle, glow, animation) lands in both ResultScreen and
// SetupScreen at the same time.

// ─── ShadowSignature ─────────────────────────────────────────────────────────
// Tiny dashboard sitting inside the SHADOW ANALYSIS drawer on desktop. Turns
// the two raw engine values (nose_shadow_angle_deg, shadow_density) into a
// readable-at-a-glance graphic so the narrative below doesn't feel stranded
// after the full LightingDiagram was moved up to the hero column.
//
//   • Angle dial  — vertical reference + needle rotating from 0° (straight
//                   down) through ±60°. Reads as "which side is the light
//                   coming from" in a single image.
//   • Density bar — horizontal gradient (light → deep shadow) with a tick
//                   marker at the current density ratio.
//
// Both widgets live in engraved inset cards so they feel built into the
// Studio Matte surface rather than stamped on top. If neither signal is
// present the component renders null.
function ShadowSignature({ angleDeg, density }) {
  const [zoomed, setZoomed] = useState(false);
  if (angleDeg == null && density == null) return null;

  // Engine convention: 0°=up, 90°=right, 180°=straight down, 270°=left.
  // The dial reads as a "how far does the shadow swing from straight down"
  // bias, so we subtract 180° to re-center on down, then normalize into
  // (-180, 180] and clamp to the visible ±60° sweep.
  let bias = null;
  if (angleDeg != null) {
    let b = angleDeg - 180;
    if (b > 180) b -= 360;
    if (b < -180) b += 360;
    bias = Math.max(-60, Math.min(60, b));
  }
  const rad = bias != null ? (bias * Math.PI) / 180 : 0;
  // Needle tail pivots at (50, 14) — just above face/nose — and extends 46px
  // down and sideways. Positive bias → needle swings right (shadow leans to
  // subject's right → key light from subject's upper-left).
  const needleX = 50 + 46 * Math.sin(rad);
  const needleY = 14 + 46 * Math.cos(rad);

  return (
    <div style={{
      display: 'flex', gap: 10, marginBottom: 14, alignItems: 'stretch',
    }}>
      {/* Angle dial card — click anywhere on the well to zoom into a
          fullscreen overlay (portaled to document.body so it escapes
          FitToViewport's transform ancestor on desktop). */}
      {angleDeg != null && (
        <div
          role="button"
          aria-label="Zoom shadow angle dial"
          tabIndex={0}
          onClick={() => { tapHaptic(); setZoomed(true); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapHaptic(); setZoomed(true); } }}
          title="Tap to zoom"
          style={{
            flex: '0 0 auto', width: 140,
            padding: '10px 10px 8px',
            borderRadius: 10,
            backgroundColor: C.pillBg,
            boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
            cursor: 'zoom-in',
          }}
        >
          <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: READOUT_LABEL, letterSpacing: '0.9px', ...FONT_SMOOTH }}>
            NOSE SHADOW
          </p>
          <svg viewBox="0 0 100 72" width="120" height="86" style={{ display: 'block', margin: '2px auto 0' }}>
            {/* ±60° arc */}
            <path
              d={`M ${50 - 50 * Math.sin(Math.PI / 3)} ${14 + 50 * Math.cos(Math.PI / 3)} A 50 50 0 0 1 ${50 + 50 * Math.sin(Math.PI / 3)} ${14 + 50 * Math.cos(Math.PI / 3)}`}
              fill="none" stroke="rgba(184,191,199,0.12)" strokeWidth="1"
            />
            {/* tick marks at -60, -30, 0, 30, 60 */}
            {[-60, -30, 0, 30, 60].map((deg) => {
              const r = (deg * Math.PI) / 180;
              const x1 = 50 + 46 * Math.sin(r);
              const y1 = 14 + 46 * Math.cos(r);
              const x2 = 50 + 50 * Math.sin(r);
              const y2 = 14 + 50 * Math.cos(r);
              return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(184,191,199,0.25)" strokeWidth="1" />;
            })}
            {/* pivot dot (nose tip) */}
            <circle cx={50} cy={14} r={2.2} fill="rgba(184,191,199,0.55)" />
            {/* needle */}
            <line
              x1={50} y1={14} x2={needleX} y2={needleY}
              stroke="rgba(245,190,72,0.95)" strokeWidth="2" strokeLinecap="round"
            />
            <circle cx={needleX} cy={needleY} r={1.8} fill="rgba(245,190,72,1)" />
          </svg>
          <p style={{
            margin: '2px 0 0',
            fontSize: 18,
            fontWeight: 800,
            color: READOUT_FG,
            textAlign: 'center',
            letterSpacing: '0.4px',
            textShadow: READOUT_GLOW,
            ...FONT_SMOOTH,
          }}>
            {angleDeg > 0 ? '+' : ''}{angleDeg.toFixed(0)}°
          </p>
        </div>
      )}

      {/* Density bar card */}
      {density != null && (
        <div style={{
          flex: 1, minWidth: 0,
          padding: '10px 14px 10px',
          borderRadius: 10,
          backgroundColor: C.pillBg,
          boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
          display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: READOUT_LABEL, letterSpacing: '0.9px', ...FONT_SMOOTH }}>
              SHADOW DENSITY
            </p>
            <p style={{
              margin: 0,
              fontSize: 18,
              fontWeight: 800,
              color: READOUT_FG,
              letterSpacing: '0.4px',
              textShadow: READOUT_GLOW,
              ...FONT_SMOOTH,
            }}>
              {(density * 100).toFixed(0)}%
            </p>
          </div>
          <div style={{ position: 'relative', marginTop: 14 }}>
            {/* Gradient track — midtone steel → deep black */}
            <div style={{
              height: 6, borderRadius: 3,
              background: 'linear-gradient(90deg, rgba(184,191,199,0.35) 0%, rgba(184,191,199,0.18) 40%, rgba(0,0,0,0.9) 100%)',
              boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.6), inset 0 -0.5px 0 rgba(255,255,255,0.03)',
            }} />
            {/* Marker */}
            <div style={{
              position: 'absolute', top: -3, left: `calc(${Math.max(0, Math.min(1, density)) * 100}% - 4px)`,
              width: 8, height: 12, borderRadius: 2,
              backgroundColor: 'rgba(245,190,72,0.95)',
              boxShadow: '0 0 6px rgba(245,190,72,0.6), inset 0 1px 0 rgba(255,255,255,0.35), inset 0 -1px 1px rgba(0,0,0,0.4)',
            }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: steel(0.58), letterSpacing: '0.5px', ...FONT_SMOOTH }}>OPEN</span>
            <span style={{ fontSize: 10, fontWeight: 600, color: steel(0.58), letterSpacing: '0.5px', ...FONT_SMOOTH }}>DEEP</span>
          </div>
        </div>
      )}

      {/* Fullscreen NOSE SHADOW overlay — portaled to document.body so it
          escapes FitToViewport's transform ancestor on desktop. The dial
          here is rendered at viewport scale so the angle reads at a glance
          and the numeric label is enormous. */}
      {zoomed && angleDeg != null && createPortal(
        <div
          onClick={() => setZoomed(false)}
          style={{
            position: 'fixed', inset: 0,
            backgroundColor: 'rgba(0,0,0,0.92)',
            zIndex: 99,
            cursor: 'zoom-out',
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            padding: 24,
          }}
        >
          <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.55), letterSpacing: '1.4px', ...FONT_SMOOTH }}>
            NOSE SHADOW ANGLE
          </p>
          <svg viewBox="0 0 100 72" width="min(80vw, 540px)" height="min(60vh, 380px)" style={{ display: 'block', margin: '12px auto' }}>
            {/* arc */}
            <path
              d={`M ${50 - 50 * Math.sin(Math.PI / 3)} ${14 + 50 * Math.cos(Math.PI / 3)} A 50 50 0 0 1 ${50 + 50 * Math.sin(Math.PI / 3)} ${14 + 50 * Math.cos(Math.PI / 3)}`}
              fill="none" stroke="rgba(184,191,199,0.22)" strokeWidth="0.8"
            />
            {/* ticks */}
            {[-60, -30, 0, 30, 60].map((deg) => {
              const r = (deg * Math.PI) / 180;
              const x1 = 50 + 44 * Math.sin(r);
              const y1 = 14 + 44 * Math.cos(r);
              const x2 = 50 + 50 * Math.sin(r);
              const y2 = 14 + 50 * Math.cos(r);
              return (
                <g key={deg}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(184,191,199,0.5)" strokeWidth="0.8" />
                  <text x={50 + 56 * Math.sin(r)} y={14 + 56 * Math.cos(r) + 2} textAnchor="middle"
                    fontSize="4.2" fill="rgba(184,191,199,0.65)" fontFamily="Inter, system-ui, sans-serif">
                    {deg > 0 ? `+${deg}°` : `${deg}°`}
                  </text>
                </g>
              );
            })}
            {/* pivot */}
            <circle cx={50} cy={14} r={2.6} fill="rgba(184,191,199,0.7)" />
            {/* needle */}
            <line x1={50} y1={14} x2={needleX} y2={needleY}
              stroke="rgba(245,190,72,1)" strokeWidth="1.8" strokeLinecap="round" />
            <circle cx={needleX} cy={needleY} r={2.4} fill="rgba(245,190,72,1)" />
          </svg>
          <p style={{
            margin: '8px 0 0',
            fontSize: 56,
            fontWeight: 800,
            color: 'rgba(245,210,140,0.95)',
            letterSpacing: '1px',
            textShadow: '0 1px 0 rgba(0,0,0,0.7)',
            ...FONT_SMOOTH,
          }}>
            {angleDeg > 0 ? '+' : ''}{angleDeg.toFixed(0)}°
          </p>
          <p style={{ margin: '4px 0 0', fontSize: 11, color: steel(0.55), letterSpacing: '0.8px', ...FONT_SMOOTH }}>
            TAP TO CLOSE
          </p>
        </div>,
        document.body
      )}
    </div>
  );
}

// ─── SceneField ─────────────────────────────────────────────────────────────
// Engraved inset tile for VLM narrative fields (Lighting, Mood, Framing,
// Pose, Expression, Style reference). Used by the SCENE drawer — swaps the
// previous flat label/value list for proper chip-card personality so the
// drawer has rhythm and doesn't read like a debug dump.
function SceneField({ label, value }) {
  return (
    <div style={{
      padding: '10px 12px',
      borderRadius: 10,
      backgroundColor: C.trackBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
      minWidth: 0,
    }}>
      <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.55), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
        {prettify(label, { upper: true })}
      </p>
      <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 500, color: C.textSubBold, lineHeight: '18px', textShadow: '0 1px 0 rgba(0,0,0,0.45)', ...FONT_SMOOTH }}>
        {prettify(value, { title: true })}
      </p>
    </div>
  );
}

// ─── SignalGauge ────────────────────────────────────────────────────────────
// One row of the CONFIDENCE drawer's RAW SIGNALS readout. Replaces the old
// flat numeric pill with: label, big value, and a tactile mini bar that
// shows the value's position within an expected range. For percentage
// signals the bar grows from the left; for the signed nose-shadow angle the
// bar is center-anchored so positive/negative is visually obvious.
function SignalGauge({ label, value, display, mode, accentColor }) {
  // mode: 'pct'   → 0..1 normalized, bar grows left→right
  //       'signed'→ value in degrees, range -60..+60, bar center-anchored
  let leftPct = 0, widthPct = 0;
  if (mode === 'pct') {
    const v = Math.max(0, Math.min(1, value));
    leftPct = 0;
    widthPct = v * 100;
  } else if (mode === 'signed') {
    const v = Math.max(-60, Math.min(60, value));
    if (v >= 0) {
      leftPct = 50;
      widthPct = (v / 60) * 50;
    } else {
      leftPct = 50 + (v / 60) * 50;
      widthPct = -(v / 60) * 50;
    }
  }
  return (
    <div style={{
      flex: '1 1 calc(50% - 5px)', minWidth: 130,
      padding: '10px 12px',
      borderRadius: 10,
      backgroundColor: C.pillBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.55), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
          {label}
        </p>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: C.textSub, ...FONT_SMOOTH }}>
          {display}
        </p>
      </div>
      <div style={{
        position: 'relative', marginTop: 9, height: 5, borderRadius: 2.5,
        backgroundColor: 'rgba(184,191,199,0.08)',
        boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.5)',
      }}>
        {/* Center tick for signed mode so the zero line is visible */}
        {mode === 'signed' && (
          <div style={{ position: 'absolute', left: '50%', top: -1, width: 1, height: 7, backgroundColor: steel(0.35) }} />
        )}
        <div style={{
          position: 'absolute', top: 0, height: '100%', borderRadius: 2.5,
          left: `${leftPct}%`, width: `${widthPct}%`,
          backgroundColor: accentColor || 'rgba(245,190,72,0.85)',
          boxShadow: `0 0 4px ${accentColor || 'rgba(245,190,72,0.6)'}, inset 0 0.5px 0 rgba(255,255,255,0.4)`,
          transition: 'width 0.4s ease, left 0.4s ease',
        }} />
      </div>
    </div>
  );
}

// ModifierSilhouette is now imported from `_shared/ModifierSilhouette`. The
// shared component supports an optional `dimensions` engraving so the
// silhouette doubles as the size readout — used by both Result + Setup.


// ─── CatchlightEye ──────────────────────────────────────────────────────────
// Stylized eye outline with one or more catchlight dots positioned at clock
// hours.  Accepts either `clockHours` (array of clock-hour strings/ints — one
// per detected catchlight, used when the engine reports multi-light setups)
// OR a single `clockHour` for backward-compat, OR falls back to mapping the
// nose-shadow angle.  Clock convention is from the VIEWER's perspective:
// 12=top, 3=right (subject's LEFT cheek), 6=bottom, 9=left (subject's RIGHT).
function parseClockHour(str) {
  if (str == null) return null;
  if (typeof str === 'number') {
    if (isNaN(str) || str < 1 || str > 12) return null;
    return Math.round(str);
  }
  const s = String(str).trim();
  // "N o'clock" / "N oclock" format (engine narrative output)
  const mOclock = s.match(/(\d+)\s*o.?clock/i);
  if (mOclock) {
    const h = parseInt(mOclock[1], 10);
    if (!isNaN(h) && h >= 1 && h <= 12) return h;
  }
  // Bare integer string "10" or "10.0" (parseCatchlightObs / array format)
  const hBare = parseInt(s, 10);
  if (!isNaN(hBare) && hBare >= 1 && hBare <= 12 && String(hBare) === s.replace(/\.0$/, '')) return hBare;
  return null;
}
function CatchlightEye({ clockHour, clockHours, angleDeg, compact = false, side = 'auto' }) {
  // Resolve the dot-list:  clockHours[] → array, else clockHour → [hour], else
  // angleDeg fallback → synthetic single entry.
  let hours = null;
  if (Array.isArray(clockHours) && clockHours.length > 0) {
    hours = clockHours.map(parseClockHour).filter(h => h != null);
  } else if (clockHour != null) {
    const h = parseClockHour(clockHour);
    if (h != null) hours = [h];
  }

  // Deduplicate and count so repeated positions read as a brighter/larger dot.
  const counts = new Map();
  if (hours && hours.length > 0) {
    for (const h of hours) counts.set(h, (counts.get(h) || 0) + 1);
  }

  // Angle fallback — only when we have no clock data at all.
  let fallbackPos = null;
  if ((!hours || hours.length === 0) && angleDeg != null) {
    const clamped = Math.max(-60, Math.min(60, angleDeg));
    const clockDeg = -clamped;
    fallbackPos = {
      cx: 50 + 18 * Math.sin((clockDeg * Math.PI) / 180),
      cy: 50 - 18 * Math.cos((clockDeg * Math.PI) / 180),
    };
  }

  const stroke = steel(0.65);
  const maxCount = Math.max(1, ...Array.from(counts.values()));

  // No mirror — catchlight dots are positioned absolutely on the clock face.
  // Mirroring the SVG would reverse their positions which is incorrect.

  // Resolve a primary hour for the readout label so the user sees the
  // engine's clock position spelled out (e.g. "10 o'clock") in addition to
  // the dot. The most-frequent hour wins; ties prefer the smaller hour so
  // the readout is deterministic.
  let primaryHour = null;
  if (counts.size > 0) {
    let bestN = -1;
    for (const [h, n] of counts.entries()) {
      if (n > bestN) { bestN = n; primaryHour = h; }
    }
  }

  // Tick mark geometry — 12 spokes around the iris ring so the clock face
  // is implied without overpowering the catchlight dots.  The hour-marks at
  // 12 / 3 / 6 / 9 are drawn slightly longer.
  const ticks = Array.from({ length: 12 }, (_, i) => {
    const deg = i * 30;
    const r = (deg * Math.PI) / 180;
    const inner = (i % 3 === 0) ? 22 : 22.5;
    const outer = (i % 3 === 0) ? 26 : 24.5;
    return {
      hour: i === 0 ? 12 : i,
      x1: 50 + inner * Math.sin(r),
      y1: 50 - inner * Math.cos(r),
      x2: 50 + outer * Math.sin(r),
      y2: 50 - outer * Math.cos(r),
    };
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, minWidth: 48, minHeight: 48 }}>
      <svg viewBox="0 0 100 100" width="80" height="80" style={{ display: 'block' }}>
        <defs>
          {/* Iris radial gradient — darker limbal ring fading to lighter mid-iris */}
          <radialGradient id="irisGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="rgba(80,100,130,0.55)" />
            <stop offset="62%" stopColor="rgba(55,72,95,0.75)" />
            <stop offset="88%" stopColor="rgba(40,55,75,0.88)" />
            <stop offset="100%" stopColor="rgba(30,42,58,0.95)" />
          </radialGradient>
          {/* Sclera fill — subtle off-white gradient for depth */}
          <radialGradient id="scleraGrad" cx="50%" cy="46%" r="55%">
            <stop offset="0%"  stopColor="rgba(210,215,220,0.12)" />
            <stop offset="100%" stopColor="rgba(160,170,180,0.04)" />
          </radialGradient>
          {/* Pupil reflection gradient */}
          <radialGradient id="pupilGrad" cx="42%" cy="38%" r="60%">
            <stop offset="0%"  stopColor="rgba(15,18,25,0.90)" />
            <stop offset="100%" stopColor="rgba(4,5,10,1)" />
          </radialGradient>
        </defs>

        {/* Almond eye shape — asymmetric: tight medial (inner) canthus,
            rounder lateral (outer) canthus. More anatomically natural. */}
        <path d="M8 50 C14 42 28 26 50 26 C72 26 86 42 92 50 C86 58 72 74 50 74 C28 74 14 58 8 50 Z"
          fill="url(#scleraGrad)" stroke={stroke} strokeWidth={1.4} />

        {/* Subtle sclera vasculature — faint lines near corners for realism */}
        <line x1={16} y1={49} x2={28} y2={47} stroke={stroke} strokeWidth={0.3} opacity={0.15} />
        <line x1={17} y1={51} x2={27} y2={52} stroke={stroke} strokeWidth={0.3} opacity={0.12} />
        <line x1={72} y1={47} x2={84} y2={49} stroke={stroke} strokeWidth={0.3} opacity={0.15} />
        <line x1={73} y1={52} x2={83} y2={51} stroke={stroke} strokeWidth={0.3} opacity={0.12} />

        {/* Clock-face tick ring — faint spokes around the iris */}
        {ticks.map((t) => (
          <line
            key={t.hour}
            x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
            stroke={stroke}
            strokeWidth={t.hour % 3 === 0 ? 1.2 : 0.7}
            opacity={t.hour % 3 === 0 ? 0.90 : 0.55}
            strokeLinecap="round"
          />
        ))}

        {/* Limbal ring — the dark outer edge that defines the iris boundary.
            This is the single strongest cue for a realistic eye. */}
        <circle cx={50} cy={50} r={21} fill="none" stroke="rgba(25,35,50,0.80)" strokeWidth={2} />

        {/* Iris — radial gradient from lighter center to dark limbal edge */}
        <circle cx={50} cy={50} r={20} fill="url(#irisGrad)" stroke="none" />

        {/* Iris fibers — radial striations that give the iris its organic texture.
            Real irises have collagen fibers radiating from the pupil outward. */}
        {Array.from({ length: 24 }, (_, i) => {
          const deg = i * 15;
          const r = (deg * Math.PI) / 180;
          const innerR = 9;
          const outerR = 18.5;
          return (
            <line key={`fiber${i}`}
              x1={50 + innerR * Math.sin(r)} y1={50 - innerR * Math.cos(r)}
              x2={50 + outerR * Math.sin(r)} y2={50 - outerR * Math.cos(r)}
              stroke="rgba(90,115,145,0.35)" strokeWidth={0.4} />
          );
        })}

        {/* Collarette ring — the wavy boundary between pupillary and ciliary
            zones, roughly 60% out from pupil edge to iris edge */}
        <circle cx={50} cy={50} r={13.5} fill="none" stroke="rgba(70,90,115,0.25)" strokeWidth={0.5}
          strokeDasharray="1.5,2" />

        {/* Pupil — subtle gradient for depth, not flat black */}
        <circle cx={50} cy={50} r={8} fill="url(#pupilGrad)" />

        {/* Multi-dot catchlights — one per reported clock hour.  Dots on the
            same clock position stack into a single brighter dot whose radius
            grows with the count, so repeated hits read as "strongest light". */}
        {Array.from(counts.entries()).map(([h, n]) => {
          const clockDeg = (h % 12) * 30;
          const cx = 50 + 16 * Math.sin((clockDeg * Math.PI) / 180);
          const cy = 50 - 16 * Math.cos((clockDeg * Math.PI) / 180);
          const r = 3.4 + 1.5 * (n / maxCount);
          const alpha = 0.6 + 0.4 * (n / maxCount);
          const isPrimary = h === primaryHour;
          return (
            <g key={`${h}-${n}`}>
              {/* outer halo — bigger + warmer for the primary dot */}
              <circle cx={cx} cy={cy} r={r + (isPrimary ? 4 : 2)}
                fill={isPrimary ? 'rgba(245,210,140,0.22)' : 'rgba(245,210,140,0.08)'} />
              <circle cx={cx} cy={cy} r={r + (isPrimary ? 2 : 1)}
                fill={isPrimary ? 'rgba(245,210,140,0.40)' : 'rgba(245,210,140,0.16)'} />
              <circle cx={cx} cy={cy} r={r} fill={`rgba(245,210,140,${alpha})`} />
              {/* Specular highlight — offset toward upper-left for realistic refraction */}
              <circle cx={cx - 0.9} cy={cy - 0.9} r={Math.max(0.8, r * 0.4)} fill="rgba(255,240,210,0.95)" />
            </g>
          );
        })}
        {/* Fallback single dot from nose-shadow angle */}
        {fallbackPos && (
          <>
            <circle cx={fallbackPos.cx} cy={fallbackPos.cy} r={6.5} fill="rgba(245,210,140,0.22)" />
            <circle cx={fallbackPos.cx} cy={fallbackPos.cy} r={4.5} fill="rgba(245,210,140,0.92)" />
            <circle cx={fallbackPos.cx - 1.2} cy={fallbackPos.cy - 1.2} r={1.8} fill="rgba(255,240,210,0.95)" />
          </>
        )}

        {/* Upper eyelid — thicker lash line with natural taper at corners.
            Anatomically the upper lid is always more prominent than the lower. */}
        <path d="M12 50 C12 50 26 22 50 22 C74 22 88 50 88 50"
          fill="none" stroke={stroke} strokeWidth={2} opacity={0.65}
          strokeLinecap="round" />
        {/* Lash fringe — tiny strokes along the upper lid for eyelash texture */}
        {[20, 30, 40, 50, 60, 70, 80].map((pct, i) => {
          // Points along the upper lid curve, approximated
          const t = pct / 100;
          const lx = 12 + t * 76;
          const rawY = 50 - 28 * Math.sin(t * Math.PI);
          const ly = Math.max(22, rawY);
          const lashLen = (i === 2 || i === 3 || i === 4) ? 3.5 : 2.5;
          const lashAngle = -0.3 + t * 0.6; // fan outward slightly
          return (
            <line key={`lash${i}`}
              x1={lx} y1={ly}
              x2={lx + lashLen * Math.sin(lashAngle)} y2={ly - lashLen * Math.cos(lashAngle)}
              stroke={stroke} strokeWidth={0.8} opacity={0.45}
              strokeLinecap="round" />
          );
        })}
        {/* Lower eyelid — thinner, subtler line */}
        <path d="M14 52 C14 52 28 76 50 76 C72 76 86 52 86 52"
          fill="none" stroke={stroke} strokeWidth={0.8} opacity={0.35}
          strokeLinecap="round" />
        {/* Waterline — the inner rim of the lower lid, very faint */}
        <path d="M16 51 C16 51 30 73 50 73 C70 73 84 51 84 51"
          fill="none" stroke="rgba(190,200,210,0.12)" strokeWidth={0.6} />
      </svg>
      {/* Position readout — explicit "10 O'CLOCK" label so the dot's clock
          hour is spelled out in copy as well as plotted in the eye.
          Suppressed in compact mode (twin instruments) — position is in the spec cell. */}
      {!compact && primaryHour != null && (
        <span style={{
          fontSize: 12, fontWeight: 700,
          color: 'rgba(245,210,140,0.92)',
          letterSpacing: '1px',
          ...FONT_SMOOTH,
        }}>
          {primaryHour} O&apos;CLOCK
        </span>
      )}
    </div>
  );
}

// ─── LightComponentChips ────────────────────────────────────────────────────
// Key / Fill / Rim / Source quality presented as a tactile 3-4 cell strip
// so the components — which previously lived as raw "subtle fill. subtle rim
// light." prose inside the shadow narrative — get a proper visual anchor.
// Each cell shows a colored dot whose opacity encodes presence strength.
function LightComponentChips({ components }) {
  if (!components) return null;
  const { source, fill, rim } = components;
  if (!source && !fill && !rim) return null;

  const strengthAlpha = (s) => {
    const v = String(s || '').toLowerCase();
    if (v === 'strong' || v === 'heavy' || v === 'dominant') return 0.95;
    if (v === 'moderate' || v === 'medium') return 0.75;
    if (v === 'subtle' || v === 'soft' || v === 'light') return 0.5;
    return 0.8;
  };

  // Match the diagram's presence gate (LightingDiagram presenceAlpha):
  // subtle/soft/none/unknown are NOT plotted as fill/rim markers, so they
  // shouldn't show up as cells here either — otherwise the panel claims
  // contributors the diagram silently dropped.
  const qualifies = (p) => {
    const v = String(p || '').toLowerCase();
    if (!v || v === 'none' || v === 'unknown' || v === 'subtle' || v === 'soft' || v === 'light') return false;
    return true;
  };
  const fillQualifies = qualifies(fill);
  const rimQualifies  = qualifies(rim);
  // If neither secondary contributor qualifies, suppress the entire row —
  // SOURCE alone (always "key") is redundant with the rest of the panel.
  if (!fillQualifies && !rimQualifies) return null;

  const Cell = ({ label, value, color }) => (
    <div style={{
      flex: 1, minWidth: 0,
      padding: '8px 10px',
      borderRadius: 10,
      backgroundColor: C.pillBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{
          width: 6, height: 6, borderRadius: 3,
          backgroundColor: color,
          boxShadow: `0 0 5px ${color}`,
          flexShrink: 0,
        }} />
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.58), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
          {label}
        </p>
      </div>
      <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 700, color: C.textSubBold, textTransform: 'capitalize', lineHeight: 1.2, ...FONT_SMOOTH }}>
        {value || '—'}
      </p>
    </div>
  );

  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
      {source && (
        <Cell label="SOURCE" value={source} color={`rgba(245,190,72,${strengthAlpha(source)})`} />
      )}
      <Cell label="FILL" value={fill || 'None'} color={`rgba(130,170,220,${fill ? strengthAlpha(fill) : 0.2})`} />
      <Cell label="RIM" value={rim || 'None'} color={`rgba(200,160,240,${rim ? strengthAlpha(rim) : 0.2})`} />
    </div>
  );
}

// ─── DirectionalCompass ─────────────────────────────────────────────────────
// Pull "Shadow falls upper_left → key light at upper_right (0.90)" out of the
// narrative and render it as a 3×3 compass grid with glowing cells for the
// key-light quadrant and the shadow quadrant.  The intensity number renders
// as a sub-line below the grid so the directional relationship is instantly
// readable without parsing prose.
function DirectionalCompass({ direction }) {
  if (!direction) return null;
  const { shadowQuadrant, keyQuadrant, keyIntensity } = direction;
  if (!shadowQuadrant && !keyQuadrant) return null;

  // Map a quadrant label ("upper left", "right", etc.) onto a 3×3 grid index.
  const quadToCell = (q) => {
    if (!q) return null;
    const s = String(q).toLowerCase();
    const row = s.includes('upper') || s.includes('top') || s.includes('above') ? 0
              : s.includes('lower') || s.includes('bottom') || s.includes('below') ? 2
              : 1;
    const col = s.includes('left') ? 0
              : s.includes('right') ? 2
              : 1;
    return row * 3 + col;
  };

  const keyCell    = quadToCell(keyQuadrant);
  const shadowCell = quadToCell(shadowQuadrant);

  const cells = Array.from({ length: 9 }, (_, i) => {
    const isKey    = i === keyCell;
    const isShadow = i === shadowCell;
    return (
      <div key={i} style={{
        aspectRatio: '1 / 1',
        borderRadius: 4,
        backgroundColor: isKey
          ? 'rgba(245,190,72,0.85)'
          : isShadow
            ? 'rgba(60,70,85,0.85)'
            : 'rgba(255,255,255,0.03)',
        boxShadow: isKey
          ? '0 0 8px rgba(245,190,72,0.55), inset 0 1px 0 rgba(255,255,255,0.25)'
          : isShadow
            ? 'inset 0 1px 2px rgba(0,0,0,0.7)'
            : 'inset 0 0.5px 1px rgba(0,0,0,0.4)',
      }} />
    );
  });

  const title = (s) => String(s || '').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '10px 12px',
      borderRadius: 10,
      backgroundColor: C.pillBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
      marginBottom: 12,
    }}>
      <div style={{
        width: 62, height: 62,
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
        gap: 3, flexShrink: 0,
      }}>
        {cells}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.58), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
          LIGHT DIRECTION
        </p>
        {keyQuadrant && (
          <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 600, color: C.textSubBold, lineHeight: 1.3, ...FONT_SMOOTH }}>
            <span style={{ color: 'rgba(245,190,72,0.95)' }}>Key</span> {title(keyQuadrant)}
            {keyIntensity != null && (
              <span style={{ color: steel(0.62), fontWeight: 500 }}> · {(keyIntensity * 100).toFixed(0)}%</span>
            )}
          </p>
        )}
        {shadowQuadrant && (
          <p style={{ margin: '2px 0 0', fontSize: 11, fontWeight: 500, color: steel(0.62), lineHeight: 1.3, ...FONT_SMOOTH }}>
            Shadow falls {title(shadowQuadrant)}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── CCTAxis ────────────────────────────────────────────────────────────────
// Horizontal Kelvin axis for the COLOR PALETTE drawer. Maps a 2500K–8500K
// range onto a tungsten→daylight→shade gradient and plants a glowing marker
// at the parsed key CCT and a smaller marker at the shadow CCT, so the
// palette's color story has a graphic anchor instead of two abstract
// "5400K" rows.
function parseKelvin(str) {
  if (!str) return null;
  const m = String(str).match(/(\d{3,5})/);
  if (!m) return null;
  const k = parseInt(m[1], 10);
  if (isNaN(k) || k < 1500 || k > 12000) return null;
  return k;
}
function CCTAxis({ keyKStr, shadowKStr }) {
  const keyK = parseKelvin(keyKStr);
  const shadowK = parseKelvin(shadowKStr);
  if (keyK == null && shadowK == null) return null;

  const MIN = 2500, MAX = 8500;
  const pct = (k) => `${Math.max(0, Math.min(1, (k - MIN) / (MAX - MIN))) * 100}%`;

  return (
    <div style={{
      marginTop: 6, marginBottom: 14,
      padding: '12px 14px 10px',
      borderRadius: 10,
      backgroundColor: C.pillBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.55), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
          COLOR TEMPERATURE
        </p>
        <span style={{ fontSize: 11, fontWeight: 600, color: steel(0.58), letterSpacing: '0.3px', ...FONT_SMOOTH }}>
          KELVIN
        </span>
      </div>
      <div style={{ position: 'relative', height: 22 }}>
        {/* Gradient track */}
        <div style={{
          position: 'absolute', left: 0, right: 0, top: 8, height: 8,
          borderRadius: 4,
          background: 'linear-gradient(90deg, #ff9c3a 0%, #ffb56a 18%, #fff0d8 38%, #ffffff 50%, #d8ecff 62%, #a8c8f0 82%, #6f9bd6 100%)',
          boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.6), inset 0 -0.5px 0 rgba(255,255,255,0.1)',
        }} />
        {/* Key marker with Kelvin label above */}
        {keyK != null && (
          <div style={{
            position: 'absolute', top: 0, left: pct(keyK), transform: 'translateX(-50%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
          }}>
            <div style={{
              width: 11, height: 22, borderRadius: 3,
              backgroundColor: 'rgba(245,190,72,0.95)',
              boxShadow: '0 0 8px rgba(245,190,72,0.65), inset 0 1px 0 rgba(255,255,255,0.4), inset 0 -1px 1px rgba(0,0,0,0.4)',
            }} />
            <span style={{
              position: 'absolute', top: -13, fontSize: 10, fontWeight: 700,
              color: 'rgba(245,190,72,0.95)', letterSpacing: '0.2px',
              textShadow: '0 0 4px rgba(0,0,0,0.8)',
              whiteSpace: 'nowrap', ...FONT_SMOOTH,
            }}>{keyK}K</span>
          </div>
        )}
        {/* Shadow marker with Kelvin label below */}
        {shadowK != null && (
          <div style={{
            position: 'absolute', top: 4, left: pct(shadowK), transform: 'translateX(-50%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
          }}>
            <div style={{
              width: 7, height: 14, borderRadius: 2,
              backgroundColor: 'rgba(168,200,240,0.9)',
              boxShadow: '0 0 4px rgba(168,200,240,0.55), inset 0 1px 0 rgba(255,255,255,0.5), inset 0 -1px 1px rgba(0,0,0,0.4)',
            }} />
            <span style={{
              position: 'absolute', top: 15, fontSize: 10, fontWeight: 700,
              color: 'rgba(168,200,240,0.95)', letterSpacing: '0.2px',
              textShadow: '0 0 4px rgba(0,0,0,0.8)',
              whiteSpace: 'nowrap', ...FONT_SMOOTH,
            }}>{shadowK}K</span>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        <span style={{ fontSize: 9, fontWeight: 600, color: steel(0.58), letterSpacing: '0.3px', ...FONT_SMOOTH }}>2500K · TUNGSTEN</span>
        <span style={{ fontSize: 9, fontWeight: 600, color: steel(0.58), letterSpacing: '0.3px', ...FONT_SMOOTH }}>5500K · DAYLIGHT</span>
        <span style={{ fontSize: 9, fontWeight: 600, color: steel(0.58), letterSpacing: '0.3px', ...FONT_SMOOTH }}>8500K · SHADE</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 8 }}>
        {keyK != null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 7, height: 10, borderRadius: 2, backgroundColor: 'rgba(245,190,72,0.95)', boxShadow: '0 0 4px rgba(245,190,72,0.5)' }} />
            <span style={{ fontSize: 13, fontWeight: 700, color: C.textSub, ...FONT_SMOOTH }}>KEY {keyK}K</span>
          </div>
        )}
        {shadowK != null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 5, height: 8, borderRadius: 2, backgroundColor: 'rgba(168,200,240,0.9)', boxShadow: '0 0 4px rgba(168,200,240,0.5)' }} />
            <span style={{ fontSize: 13, fontWeight: 700, color: C.textSub, ...FONT_SMOOTH }}>SHADOW {shadowK}K</span>
          </div>
        )}
      </div>
    </div>
  );
}

function Pill({ label }) {
  return (
    <div style={{
      height: 28,
      paddingLeft: 10, paddingRight: 10,
      backgroundColor: C.pillBg,
      borderRadius: 6,
      display: 'flex', alignItems: 'center',
      boxShadow: PILL_SHADOW,
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: C.textMeta, whiteSpace: 'nowrap', WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision' }}>{label}</span>
    </div>
  );
}

// ─── Pattern definitions + face silhouettes ─────────────────────────────────
// One-line shadow definitions for each canonical portrait pattern.  These are
// pure presentation (no engine plumbing required) so the pattern candidate
// rows give the user the *what* alongside the score.
const PATTERN_DEFINITIONS = {
  loop:       'Small triangular shadow off the nose, just touching the cheek.',
  rembrandt:  'Triangle of light on the shadow-side cheek, isolated under the eye.',
  butterfly:  'Symmetric shadow under the nose — light dead-center, slightly above.',
  paramount:  'Symmetric shadow under the nose — light dead-center, slightly above.',
  split:      'Vertical hard split — half the face fully lit, half in shadow.',
  broad:      'Lit side of the face is the side turned toward camera.',
  short:      'Lit side of the face is the side turned away from camera.',
  rim:        'Backlight wraps the contour, separating subject from background.',
  flat:       'Even, near-shadowless illumination across the whole face.',
};

// Stylized portrait silhouette per pattern.  Drawn at viewBox 100×100 so the
// shading geometry has room to read at small sizes without going mushy.  The
// face oval is the same in every variant; the SHADING path is what changes —
// that's the visual cue for the pattern shape.
function PatternFaceIcon({ name, size = 64, lit, shadowSide }) {
  const key = String(name || '').toLowerCase().split(/\s+/)[0]; // "loop" from "Loop"
  const skin    = lit ? 'rgba(245,210,140,0.26)' : 'rgba(184,191,199,0.14)';
  const stroke  = lit ? 'rgba(245,210,140,0.95)' : 'rgba(184,191,199,0.55)';
  const shadow  = 'rgba(0,0,0,0.88)';
  const hi      = lit ? 'rgba(245,210,140,0.70)' : 'rgba(184,191,199,0.40)';
  const noseCol = lit ? 'rgba(245,210,140,0.85)' : 'rgba(184,191,199,0.50)';

  // Default artwork has the shadow on the RIGHT side of the face for loop,
  // rembrandt, broad; on the LEFT for split, short. When the caller tells us
  // which side the shadow actually falls in THIS photo, we flip the whole
  // glyph horizontally so every candidate mirrors the real result.
  // `shadowSide` = 'left' | 'right' | undefined (undefined = no flip).
  const defaultRightSide = new Set(['loop', 'rembrandt', 'broad']);
  const defaultLeftSide  = new Set(['split', 'short']);
  let flip = false;
  if (shadowSide === 'left'  && defaultRightSide.has(key)) flip = true;
  if (shadowSide === 'right' && defaultLeftSide.has(key))  flip = true;

  return (
    <svg viewBox="0 0 100 100" width={size} height={size} style={{ display: 'block', flexShrink: 0 }}>
      <g transform={flip ? 'translate(100,0) scale(-1,1)' : undefined}>
      {/* Face oval — anchor for every pattern */}
      <ellipse cx={50} cy={52} rx={28} ry={34} fill={skin} stroke={stroke} strokeWidth={2} />

      {/* Shading per pattern */}
      {key === 'loop' && (
        // small triangular nose-shadow cast from the nose toward the shadow cheek
        <path d="M50 52 L62 58 L60 66 L52 60 Z" fill={shadow} />
      )}
      {key === 'rembrandt' && (
        <>
          {/* shadow-side cheek fills dark, leaving a small triangle of light isolated under the eye */}
          <path d="M50 18 Q78 22 80 52 Q78 82 50 86 L50 18 Z" fill={shadow} opacity={0.68} />
          <polygon points="54,42 64,46 58,54" fill={hi} />
        </>
      )}
      {(key === 'butterfly' || key === 'paramount') && (
        // symmetric ellipse shadow directly under the nose
        <ellipse cx={50} cy={62} rx={8} ry={4} fill={shadow} />
      )}
      {key === 'split' && (
        // hard vertical split — half the face in total shadow
        <path d="M50 18 Q22 22 22 52 Q22 82 50 86 L50 18 Z" fill={shadow} opacity={0.82} />
      )}
      {key === 'broad' && (
        // shadow on the FAR (turned-away) side — face turned camera-right
        <path d="M68 26 Q84 52 68 78 Q60 82 56 76 L56 30 Q60 22 68 26 Z" fill={shadow} opacity={0.68} />
      )}
      {key === 'short' && (
        // shadow on the NEAR (turned-toward) side — face turned camera-right
        <path d="M32 26 Q16 52 32 78 Q40 82 44 76 L44 30 Q40 22 32 26 Z" fill={shadow} opacity={0.68} />
      )}
      {key === 'rim' && (
        // face fully dark, bright outline wraps the contour
        <>
          <ellipse cx={50} cy={52} rx={28} ry={34} fill="rgba(0,0,0,0.72)" />
          <ellipse cx={50} cy={52} rx={28} ry={34} fill="none" stroke={hi} strokeWidth={4} />
        </>
      )}
      {/* 'flat' draws nothing extra — even illumination */}

      {/* Nose dot for orientation (omit on rim/flat where it adds clutter) */}
      {key !== 'rim' && key !== 'flat' && (
        <circle cx={50} cy={56} r={2} fill={noseCol} />
      )}
      </g>
    </svg>
  );
}

function PatternBars({ candidates, isHighConf, shadowSide, onSelectSetup }) {
  const scoreColor  = isHighConf ? C.confHigh     : C.confLowScore;
  const barFill     = isHighConf ? C.confHighBar  : C.confLowBar;

  // Tapping a pattern silhouette portals a fullscreen overlay showing the
  // same drawing at ~240px along with the pattern name + definition, so the
  // photographer can actually READ the shape (36-px inline icon is too small
  // to resolve the loop triangle / rembrandt cheek).
  const [zoomedPattern, setZoomedPattern] = useState(null); // { name, score, def, lit } | null
  // Apple simplicity: show only the winning pattern by default.
  // Runner-up candidates are available behind a toggle for the curious.
  const [showRunners, setShowRunners] = useState(false);

  // `shadowSide` is 'left' or 'right' meaning "which side of the face the
  // shadow actually falls on in THIS photo".  We mirror asymmetric pattern
  // glyphs (loop, rembrandt, broad, short, split) so the candidate drawings
  // match the real DirectionalCompass read instead of defaulting to a
  // cast-right nose shadow on every photo.

  const defFor = (name) => {
    const key = String(name || '').toLowerCase().split(/\s+/)[0];
    return PATTERN_DEFINITIONS[key] || null;
  };

  const runners = candidates.slice(1);

  return (
    <div>
      {candidates.slice(0, 1).map((c) => {
        const def = defFor(c.name);
        return (
          <div key={c.name} style={{
            marginTop: 6,
            display: 'grid',
            gridTemplateColumns: 'auto minmax(0, 1fr) auto',
            columnGap: 12,
            alignItems: 'center',
          }}>
            {/* Silhouette card — clickable; opens fullscreen portal */}
            <div
              role="button"
              aria-label={`Zoom ${c.name} pattern`}
              tabIndex={0}
              onClick={() => { tapHaptic(); setZoomedPattern({ name: c.name, score: c.score, def, lit: true }); }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapHaptic(); setZoomedPattern({ name: c.name, score: c.score, def, lit: true }); } }}
              title="Tap to zoom"
              style={{
                width: 56, height: 56,
                borderRadius: 10,
                backgroundColor: C.pillBg,
                boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'zoom-in',
                WebkitTapHighlightColor: 'transparent',
                flexShrink: 0,
              }}
            >
              <PatternFaceIcon name={c.name} size={46} lit shadowSide={shadowSide} />
            </div>

            {/* Name + definition + bar */}
            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: C.textSubBold,
                  letterSpacing: '0px',
                  ...FONT_SMOOTH,
                }}>{c.name}</span>
              </div>
              {def && (
                <p style={{
                  margin: '2px 0 6px', fontSize: 13, lineHeight: 1.35,
                  color: steel(0.68),
                  fontWeight: 400,
                  ...FONT_SMOOTH,
                }}>{def}</p>
              )}
              {/* Bar track + fill */}
              <div style={{
                width: '100%', height: 4, borderRadius: 2,
                backgroundColor: C.barTrack,
                position: 'relative',
              }}>
                <div style={{
                  position: 'absolute', left: 0, top: 0,
                  width: `${c.score}%`, height: '100%',
                  borderRadius: 2,
                  backgroundColor: barFill,
                  boxShadow: `0 0 6px ${barFill}`,
                  transition: 'width 0.4s ease',
                }} />
              </div>
            </div>

            {/* Score */}
            <span style={{
              fontSize: 22, fontWeight: 800,
              color: scoreColor,
              alignSelf: 'center',
              letterSpacing: '-0.5px',
              lineHeight: 1,
              ...FONT_SMOOTH,
            }}>{c.score}%</span>
          </div>
        );
      })}

      {/* Runner-up candidates — collapsed by default (Apple simplicity).
          The photographer got THE answer above. These are for the curious. */}
      {runners.length > 0 && (
        <>
          {showRunners && runners.map((c) => {
            const def = defFor(c.name);
            return (
              <div key={c.name} style={{
                marginTop: 14,
                display: 'grid',
                gridTemplateColumns: 'auto minmax(0, 1fr) auto',
                columnGap: 12,
                alignItems: 'center',
              }}>
                <div
                  role="button"
                  aria-label={`Zoom ${c.name} pattern`}
                  tabIndex={0}
                  onClick={() => { tapHaptic(); setZoomedPattern({ name: c.name, score: c.score, def, lit: false }); }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapHaptic(); setZoomedPattern({ name: c.name, score: c.score, def, lit: false }); } }}
                  title="Tap to zoom"
                  style={{
                    width: 56, height: 56,
                    borderRadius: 10,
                    backgroundColor: C.pillBg,
                    boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    cursor: 'zoom-in',
                    WebkitTapHighlightColor: 'transparent',
                    flexShrink: 0,
                  }}
                >
                  <PatternFaceIcon name={c.name} size={46} lit={false} shadowSide={shadowSide} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{
                      fontSize: 14, fontWeight: 500,
                      color: C.textSub,
                      ...FONT_SMOOTH,
                    }}>{c.name}</span>
                  </div>
                  {def && (
                    <p style={{
                      margin: '2px 0 6px', fontSize: 13, lineHeight: 1.4,
                      color: steel(0.60), fontWeight: 400,
                      ...FONT_SMOOTH,
                    }}>{def}</p>
                  )}
                  <div style={{
                    width: '100%', height: 3, borderRadius: 1.5,
                    backgroundColor: C.barTrack, position: 'relative',
                  }}>
                    <div style={{
                      position: 'absolute', left: 0, top: 0,
                      width: `${c.score}%`, height: '100%',
                      borderRadius: 1.5, backgroundColor: C.barAlt,
                      transition: 'width 0.4s ease',
                    }} />
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, alignSelf: 'center' }}>
                  <span style={{
                    fontSize: 14, fontWeight: 700,
                    color: C.textSub,
                    ...FONT_SMOOTH,
                  }}>{c.score}%</span>
                  {onSelectSetup && (
                    <button
                      onClick={(e) => { e.stopPropagation(); tapHaptic(); onSelectSetup(c.name); }}
                      style={{
                        padding: '3px 10px', borderRadius: 6,
                        border: `1px solid ${steel(0.2)}`,
                        background: 'rgba(255,255,255,0.03)',
                        color: steel(0.7), fontSize: 11, fontWeight: 600,
                        letterSpacing: '0.6px', cursor: 'pointer',
                        WebkitTapHighlightColor: 'transparent',
                        ...FONT_SMOOTH,
                      }}
                    >BUILD</button>
                  )}
                </div>
              </div>
            );
          })}
          <div
            role="button"
            tabIndex={0}
            onClick={() => { setShowRunners(v => !v); tapHaptic(); }}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowRunners(v => !v); tapHaptic(); } }}
            style={{
              display: 'flex', justifyContent: 'center', alignItems: 'center',
              padding: '8px 0 0',
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <span style={{
              fontSize: 11, fontWeight: 700,
              color: steel(0.48),
              letterSpacing: '0.8px',
              ...FONT_SMOOTH,
            }}>
              {showRunners ? 'HIDE CANDIDATES' : `${runners.length} OTHER CANDIDATE${runners.length > 1 ? 'S' : ''}`}
            </span>
          </div>
        </>
      )}

      {!isHighConf && (
        <p style={{
          margin: '14px 0 0', fontSize: 13,
          color: C.textWarn, lineHeight: 1.4,
          ...FONT_SMOOTH,
        }}>Possible match — a brighter or sharper photo may improve results</p>
      )}

      {/* Fullscreen zoom portal — large silhouette + name + score + definition.
          Click anywhere to dismiss (matches the diagram zoom convention).
          PORTALED to document.body so it escapes the FitToViewport scale. */}
      {zoomedPattern && createPortal(
        <div
          onClick={() => setZoomedPattern(null)}
          style={{
            position: 'fixed', inset: 0,
            backgroundColor: 'rgba(11,11,12,0.94)',
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            zIndex: 100,
            cursor: 'zoom-out',
            padding: 32,
            gap: 18,
          }}
        >
          <p style={{
            margin: 0, fontSize: 11, fontWeight: 700,
            letterSpacing: '2px', color: steel(0.6), ...FONT_SMOOTH,
          }}>PATTERN · {zoomedPattern.score}% MATCH</p>

          {/* Large silhouette in a viewfinder-style well */}
          <div style={{
            width: 'min(72vw, 320px)', height: 'min(72vw, 320px)',
            borderRadius: 24,
            backgroundColor: C.pillBg,
            boxShadow: 'inset 0px 3px 10px 0px rgba(0,0,0,0.7), inset 0px 1px 3px 0px rgba(0,0,0,0.5), 0 18px 60px rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 24,
          }}>
            <PatternFaceIcon name={zoomedPattern.name} size={260} lit={zoomedPattern.lit} shadowSide={shadowSide} />
          </div>

          <p style={{
            margin: 0, fontSize: 24, fontWeight: 800,
            color: 'rgba(245,247,250,0.95)', letterSpacing: '0.5px',
            ...FONT_SMOOTH,
          }}>{zoomedPattern.name}</p>

          {zoomedPattern.def && (
            <p style={{
              margin: 0, maxWidth: 420,
              fontSize: 15, lineHeight: 1.5,
              color: steel(0.78), textAlign: 'center',
              ...FONT_SMOOTH,
            }}>{zoomedPattern.def}</p>
          )}

          <p style={{
            margin: '6px 0 0', fontSize: 10, fontWeight: 700,
            letterSpacing: '1.5px', color: steel(0.55), ...FONT_SMOOTH,
          }}>TAP TO CLOSE</p>
        </div>,
        document.body
      )}
    </div>
  );
}

// LCBottomActions + BottomActions removed — dead code. The low-confidence
// "New Photo | Build It Anyway" row is now rendered inline at the bottom of
// the analytical panel (see ~line 3058).

// FONT_SMOOTH imported from studioMatte

// ─── Spec cell — matches SetupScreen Studio Matte spec card style ─────────
const SPEC_CELL_BG     = 'rgba(0,0,0,0.08)';
const SPEC_CELL_SHADOW = 'inset 0px 1px 2px 0px rgba(0,0,0,0.45), inset 0px 0px 4px 0px rgba(0,0,0,0.25)';

function SpecCell({ label, value, secondary, secondaryColor }) {
  return (
    <div style={{
      flex: 1, minWidth: 0, borderRadius: 8,
      padding: '8px 10px',
      backgroundColor: SPEC_CELL_BG,
      boxShadow: SPEC_CELL_SHADOW,
    }}>
      <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.50), letterSpacing: '1.1px', ...FONT_SMOOTH }}>{label}</p>
      <p style={{ margin: '4px 0 0', fontSize: 15, fontWeight: 700, color: C.textPrimary, lineHeight: 1.15, ...FONT_SMOOTH, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</p>
      {secondary && (
        <p style={{ margin: '3px 0 0', fontSize: 11, fontWeight: 500, color: secondaryColor || C.confHigh, letterSpacing: '0.1px', ...FONT_SMOOTH }}>
          {secondary}
        </p>
      )}
    </div>
  );
}

// ─── Modifier detail card — Studio Matte hero + spec grid ─────────────────
// ─── IrisCoverageScale ──────────────────────────────────────────────────────
// Visual scale showing where the catchlight lands on the small→XL spectrum,
// expressed as % iris diameter (the engine's native unit for catchlight
// size).  Reads as a banded ruler with a glowing marker so the modifier's
// apparent source size has spatial context, not just a raw number.
//
// Bands (Apparent source size relative to iris diameter):
//   < 25%   tiny    (bare bulb / hard light)
//   25–50%  small   (small softbox / strip)
//   50–100% medium  (mid softbox / oct)
//   100–200% large  (large oct / parabolic / window)
//   > 200%  huge    (sky / large diffuser overhead)
function IrisCoverageScale({ catchlightSize, angularArea }) {
  // Parse "12.3% iris" → 12.3
  let pct = null;
  if (catchlightSize) {
    const m = String(catchlightSize).match(/([\d.]+)\s*%/);
    if (m) pct = parseFloat(m[1]);
  }
  if (pct == null) return null;

  // Map % iris (0–250+) to a 0–1 ruler position with a soft compress at top
  const RULER_MAX = 250;
  const ruler = Math.max(0, Math.min(1, pct / RULER_MAX));

  const bands = [
    { label: 'TINY',   start: 0,   end: 25,  color: 'rgba(245,190,72,0.20)' },
    { label: 'SMALL',  start: 25,  end: 50,  color: 'rgba(245,190,72,0.32)' },
    { label: 'MEDIUM', start: 50,  end: 100, color: 'rgba(245,190,72,0.48)' },
    { label: 'LARGE',  start: 100, end: 200, color: 'rgba(245,190,72,0.65)' },
    { label: 'HUGE',   start: 200, end: 250, color: 'rgba(245,190,72,0.82)' },
  ];

  const bandFor = (v) => bands.find((b) => v >= b.start && v < b.end) || bands[bands.length - 1];
  const activeBand = bandFor(pct);

  return (
    <div style={{
      marginTop: 10, marginBottom: 10,
      padding: '10px 12px 8px',
      borderRadius: 10,
      backgroundColor: C.pillBg,
      boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.58), letterSpacing: '0.9px', ...FONT_SMOOTH }}>
          IRIS COVERAGE
        </p>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'rgba(245,210,140,0.85)', letterSpacing: '0.4px', ...FONT_SMOOTH }}>
          {activeBand.label}
        </span>
      </div>

      {/* Banded ruler */}
      <div style={{ position: 'relative', height: 18 }}>
        <div style={{
          position: 'absolute', left: 0, right: 0, top: 6, height: 8,
          borderRadius: 4,
          display: 'flex',
          overflow: 'hidden',
          boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.65), inset 0 -0.5px 0 rgba(255,255,255,0.06)',
        }}>
          {bands.map((b) => (
            <div key={b.label} style={{
              flex: (b.end - b.start),
              backgroundColor: b.color,
              borderRight: '1px solid rgba(0,0,0,0.45)',
            }} />
          ))}
        </div>
        {/* Marker — vertical pin with engraved % readout */}
        <div style={{
          position: 'absolute', top: 0, left: `${ruler * 100}%`,
          transform: 'translateX(-50%)',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
        }}>
          <div style={{
            width: 9, height: 18, borderRadius: 2,
            backgroundColor: 'rgba(245,210,140,0.95)',
            boxShadow: '0 0 6px rgba(245,190,72,0.7), inset 0 1px 0 rgba(255,255,255,0.45), inset 0 -1px 1px rgba(0,0,0,0.45)',
          }} />
        </div>
      </div>

      {/* Band ticks below the ruler */}
      <div style={{ display: 'flex', marginTop: 4 }}>
        {bands.map((b) => (
          <div key={b.label} style={{
            flex: (b.end - b.start),
            fontSize: 9, fontWeight: 700, letterSpacing: '0.3px',
            color: steel(0.55), textAlign: 'center', ...FONT_SMOOTH,
          }}>{b.label}</div>
        ))}
      </div>

      {/* Numeric readout */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 6 }}>
        <span style={{ fontSize: 16, fontWeight: 800, color: READOUT_FG, textShadow: READOUT_GLOW, letterSpacing: '0.4px', ...FONT_SMOOTH }}>
          {pct.toFixed(1)}<span style={{ fontSize: 11, fontWeight: 700, color: steel(0.62), marginLeft: 3 }}>% iris</span>
        </span>
        {angularArea && (
          <span style={{ fontSize: 11, fontWeight: 600, color: steel(0.55), letterSpacing: '0.3px', ...FONT_SMOOTH }}>
            {angularArea}
          </span>
        )}
      </div>
    </div>
  );
}

function ModifierDetail({ modifier }) {
  if (!modifier) return null;

  // Avoid "Large Large Octabox" — skip sizeLabel if family already contains it
  const family = modifier.family || 'Modifier';
  const heroName = modifier.sizeLabel && !family.toLowerCase().startsWith(modifier.sizeLabel.toLowerCase())
    ? `${modifier.sizeLabel} ${family}`
    : (modifier.family || null);

  // Apparent source band — folded into the subtitle line
  let sourceBand = null;
  if (modifier.catchlightSize) {
    const m = String(modifier.catchlightSize).match(/([\d.]+)\s*%/);
    if (m) {
      const pct = parseFloat(m[1]);
      sourceBand = pct < 25 ? 'Tiny source' : pct < 50 ? 'Small source' : pct < 100 ? 'Medium source' : pct < 200 ? 'Large source' : 'Very large source';
    }
  }

  const cells = [
    modifier.distRange && (
      <SpecCell
        key="dist"
        label="DISTANCE"
        value={modifier.distRange}
        secondary={modifier.optDist ? `optimal ${modifier.optDist}` : null}
        secondaryColor={C.confHigh}
      />
    ),
    modifier.position && (
      <SpecCell
        key="pos"
        label="POSITION"
        value={modifier.position}
        secondary={[modifier.positionQuad, modifier.positionIntensity].filter(Boolean).join(' · ') || null}
      />
    ),
    // LIGHTS cell removed — single-light count is obvious from the diagram;
    // multi-light count surfaces in the DETAIL drawer's signal breakdown.
  ].filter(Boolean);

  if (!heroName && !cells.length) return null;

  // Pair cells into rows of 2 for the spec grid layout
  const rows = [];
  for (let i = 0; i < cells.length; i += 2) {
    rows.push(cells.slice(i, i + 2));
  }

  return (
    <div style={{ marginTop: 8 }}>
      {heroName && (
        <div style={{ marginBottom: 8 }}>
          <p style={{ margin: 0, fontSize: 20, fontWeight: 700, color: C.textPrimary, lineHeight: 1.15, letterSpacing: '0.1px', ...FONT_SMOOTH }}>
            {heroName}
          </p>
          {(modifier.sizeRange || sourceBand) && (
            <p style={{ margin: '4px 0 0', fontSize: 11, fontWeight: 500, color: steel(0.60), letterSpacing: '0.2px', ...FONT_SMOOTH }}>
              {[modifier.sizeRange, sourceBand].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
      )}
      {rows.map((row, i) => (
        <div key={i} style={{ display: 'flex', gap: 10, marginTop: i === 0 ? 0 : 8 }}>
          {row}
          {row.length === 1 && <div style={{ flex: 1 }} />}
        </div>
      ))}
    </div>
  );
}

export default function ResultScreen({ result, imagePreview, onSetup, onRetry, onShotMatch, isPaid = false, plan = 'free', isAdmin = false }) {
  const _isDesktopNative = useIsDesktop();
  const _vpW = useViewportWidth();
  // Tablet portrait (768–1023px): treat as two-column layout territory.
  // Day1DemoApp bypasses FitToViewport at TABLET_MIN_WIDTH, so this screen
  // receives full viewport width on tablets and activates the desktop grid.
  const isDesktop = _isDesktopNative || _vpW >= TABLET_MIN_WIDTH;
  const tilt = useDeviceTilt();
  // Admin settings — confidence display mode
  const _settings = loadSettings();
  const confDisplayMode = _settings.confidenceDisplay || 'simple'; // 'simple' | 'numeric' | 'detailed'
  const showConfPct = _settings.showConfidenceScore !== false; // default true
  // Hero column: 430 on mobile, 540 on desktop — the wider column lets the
  // photo breathe (less aggressive face crop) and makes room for a taller
  // hero block alongside the analytical panel. FitToViewport handles the
  // uniform scale on wide screens at the app shell.
  const heroWidth = isDesktop ? 720 : 430;

  // ── VF geometry (identical to HomeScreen) ──────────────────────────────────
  // Compute the same viewfinder height so the result hero matches HomeScreen.
  // Desktop uses the larger button sizes (168/180) from HomeScreen so the VF
  // height matches exactly — prevents the "VF doesn't match" drift.
  // VF sizing always uses mobile button geometry (136/146) so the mobile VF
  // matches HomeScreen exactly. Desktop layout uses its own D_PHOTO_HEIGHT.
  const VF_TOP = 100;
  const VF_GAP = 16;
  const { stableVH, safeBottom } = useStableViewport();
  const M_BTN_D = 136;
  const M_WELL_D = 146;
  const BTN_OFFSET_FROM_BOTTOM = 48;
  const M_BTN_CY = stableVH - safeBottom - BTN_OFFSET_FROM_BOTTOM - Math.round(M_BTN_D / 2);
  const M_WELL_TOP = M_BTN_CY - M_WELL_D / 2;
  const VF_HEIGHT = Math.max(280, M_WELL_TOP - VF_GAP - VF_TOP);
  // Single detail drawer — THE LIGHT and THE SETUP are always visible.
  // Only the DETAIL section (scene + colors + confidence) collapses.
  // Auto-expand DETAIL on high confidence — photographer wants to see the full read
  const [detailOpen, setDetailOpen] = useState(() => (result?.confidence ?? 0) >= 80);
  const [diagramView, setDiagramView] = useState('top');
  const [diagramZoomed, setDiagramZoomed] = useState(false);
  const [socialDiagramCanvas, setSocialDiagramCanvas] = useState(null);
  const socialDiagramRef = useRef(null);
  const [outcomeRecorded, setOutcomeRecorded] = useState(null); // 'nailed_it' | 'close' | 'failed'
  const [correctionSheetOpen, setCorrectionSheetOpen] = useState(false);
  const [correctionFailureId, setCorrectionFailureId] = useState(null);
  const [setupSaved, setSetupSaved] = useState(false);
  const [briefCopied, setBriefCopied] = useState(false);

  // Rasterize the LightingDiagram SVG into a canvas for social card compositing.
  // Runs after render so the SVG ref is populated.
  useEffect(() => {
    if (!socialDiagramRef.current) return;
    const svgEl = socialDiagramRef.current.getSvgElement?.();
    if (!svgEl) return;
    svgToCanvasElement(svgEl, 2).then(setSocialDiagramCanvas).catch(() => {});
  }, [result]);

  // Auto-save setup if setting is enabled — runs once on mount
  useEffect(() => {
    if (!isPaid || setupSaved) return;
    try {
      const s = loadSettings();
      if (s.autoSaveSetups && result) {
        saveSetup({ name: result?.pattern || result?.authoritative_pattern || 'Setup', tag: 'auto', result });
        setSetupSaved(true);
      }
    } catch { /* skip */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Daylight brightness boost — now global via CSS data-daylight attribute.
  // Legacy per-screen filter kept for backward compat but the setting-driven
  // global approach in applySettings() is the primary mechanism.
  const [daylightMode] = useState(() => {
    try { const s = loadSettings(); return !!s.daylightMode; } catch { return false; }
  });
  const [infoVisible, setInfoVisible] = useState(true);
  const [animatedConf, setAnimatedConf] = useState(0);
  const [dragOffset, setDragOffset] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartY = useRef(null);
  const dragThreshold = 40; // px to commit show/hide
  const longPressTimer = useRef(null);
  const longPressFired = useRef(false);
  // Tracks whether the in-flight hero gesture moved enough to count as a
  // drag (info-panel toggle).  Set in moveDrag past the 8px slop, reset on
  // every fresh handleHeroStart.  Used by the hero onClick to distinguish
  // a real tap (→ enter zoom) from the synthesized click that follows a
  // vertical info-panel drag.
  const heroDidDrag = useRef(false);
  // Diagram fullscreen modal — click any LightingDiagram instance to open
  // a viewport-filling overlay with the same graphic.
  const [diagramFullscreen, setDiagramFullscreen] = useState(false);
  useEffect(() => {
    if (!diagramFullscreen) return;
    const onKey = (e) => { if (e.key === 'Escape') setDiagramFullscreen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [diagramFullscreen]);

  // Chip detail overlay — clicking a warning chip opens a translucent card
  // pinned over the hero photo with the chip label, severity, and detail
  // explanation. Tapping the photo or pressing Escape dismisses it.
  const [chipDetail, setChipDetail] = useState(null); // { label, sev, detail } | null
  const [warningsExpanded, setWarningsExpanded] = useState(false);
  useEffect(() => {
    if (!chipDetail) return;
    const onKey = (e) => { if (e.key === 'Escape') setChipDetail(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [chipDetail]);

  // ── Swipe-back gesture — swipe from left edge navigates back ──
  // Detects a touch starting within 24px of the left screen edge, then
  // tracks rightward movement. If horizontal distance > 80px and the
  // angle is shallow (mostly horizontal), fires onRetry() to go back.
  const swipeStartX = useRef(null);
  const swipeStartY = useRef(null);
  const swipeTouchY = useRef(null);
  const [swipeProgress, setSwipeProgress] = useState(0); // 0-1, for visual hint
  const [swipeY, setSwipeY] = useState(0); // finger Y for glow tracking
  const handleSwipeStart = useCallback((e) => {
    if (e.touches.length !== 1) return;
    const t = e.touches[0];
    if (t.clientX < 24) {
      swipeStartX.current = t.clientX;
      swipeStartY.current = t.clientY;
    }
  }, []);
  const handleSwipeMove = useCallback((e) => {
    if (swipeStartX.current == null || e.touches.length !== 1) return;
    const t = e.touches[0];
    const dx = t.clientX - swipeStartX.current;
    const dy = Math.abs(t.clientY - swipeStartY.current);
    if (dy > dx) { swipeStartX.current = null; setSwipeProgress(0); return; }
    setSwipeProgress(Math.min(1, dx / 100));
    setSwipeY(t.clientY);
  }, []);
  const handleSwipeEnd = useCallback(() => {
    if (swipeProgress > 0.8) {
      navHaptic();
      onRetry();
    }
    swipeStartX.current = null;
    swipeStartY.current = null;
    setSwipeProgress(0);
  }, [swipeProgress, onRetry]);

  const [isZoomed, setIsZoomed] = useState(false);

  // ── First-visit teach overlay ─────────────────────────────────────────────
  const [resultTeachStep, setResultTeachStep] = useState(0);
  const [resultTeachVisible, setResultTeachVisible] = useState(() => {
    try { return localStorage.getItem('ngw_result_teach_seen') !== '1'; } catch { return false; }
  });
  const advanceResultTeach = useCallback(() => {
    setResultTeachStep(prev => {
      if (prev >= 3) {
        setResultTeachVisible(false);
        try { localStorage.setItem('ngw_result_teach_seen', '1'); } catch { /* ignore */ }
        return 4;
      }
      return prev + 1;
    });
    tapHaptic();
  }, []);
  const skipResultTeach = useCallback(() => {
    setResultTeachVisible(false);
    setResultTeachStep(4);
    try { localStorage.setItem('ngw_result_teach_seen', '1'); } catch { /* ignore */ }
    tapHaptic();
  }, []);

  // ── Inline hero pinch-zoom + pan state ──
  // These apply directly to the hero <img> inside the VF (not the fullscreen
  // portal).  Two-finger pinch scales the image in place; single-finger drag
  // pans when scale > 1.  The VF's overflow:hidden clips the edges.
  const [heroScale, setHeroScale] = useState(1);
  const [heroPan, setHeroPan]   = useState({ x: 0, y: 0 });
  const heroPinchStartDist  = useRef(null);
  const heroPinchStartScale = useRef(1);
  const heroPanStart        = useRef(null);
  const heroPanStartOffset  = useRef({ x: 0, y: 0 });
  const heroIsPinching      = useRef(false);

  // Fullscreen portal zoom state (separate from inline)
  const [zoomScale, setZoomScale] = useState(1);
  const [zoomPan, setZoomPan] = useState({ x: 0, y: 0 });
  const pinchStartDist = useRef(null);
  const pinchStartScale = useRef(1);
  const panStart = useRef(null);
  const panStartOffset = useRef({ x: 0, y: 0 });
  // Tap-to-exit-zoom: tracks whether the in-flight touch is still tap-eligible
  // (single finger, no significant movement, hasn't pinched).  Cleared as soon
  // as the user pans, pinches, or lifts.
  const zoomTapCandidate = useRef(false);
  const zoomTapStart = useRef({ x: 0, y: 0, t: 0 });
  // Brief lockout after exiting zoom — prevents the synthesized click that
  // fires after touchend from re-triggering long-press logic and bouncing
  // straight back into zoom.  Set true in exitZoom(), cleared after 600ms.
  const recentlyExitedZoom = useRef(false);
  // Double-tap detector for inline hero — resets zoom
  const lastTapTime = useRef(0);

  // Result reveal sound + haptic on mount
  useEffect(() => {
    resultRevealSound();
    successHaptic();
  }, []);

  const startDrag = useCallback((clientY) => {
    dragStartY.current = clientY;
    setIsDragging(true);
  }, []);

  const moveDrag = useCallback((clientY) => {
    if (dragStartY.current === null) return;
    const dy = clientY - dragStartY.current;
    // Cancel long press if user is dragging — and remember that this gesture
    // turned into a real drag so the trailing click doesn't fire fullscreen.
    if (Math.abs(dy) > 8) {
      heroDidDrag.current = true;
      if (longPressTimer.current) {
        clearTimeout(longPressTimer.current);
        longPressTimer.current = null;
      }
    }
    if (infoVisible) {
      setDragOffset(Math.max(0, dy));
    } else {
      setDragOffset(Math.min(0, dy));
    }
  }, [infoVisible]);

  const endDrag = useCallback(() => {
    if (infoVisible && dragOffset > dragThreshold) {
      setInfoVisible(false);
      selectHaptic();
    } else if (!infoVisible && dragOffset < -dragThreshold) {
      setInfoVisible(true);
      selectHaptic();
    }
    setDragOffset(0);
    setIsDragging(false);
    dragStartY.current = null;
  }, [infoVisible, dragOffset]);

  // ── Inline hero touch handlers — pinch-to-zoom + pan ──
  // Two-finger pinch zooms the hero in-place inside the VF (overflow: hidden
  // clips the edges).  Single-finger pan when heroScale > 1.  When scale is 1
  // the single-finger gesture falls through to the existing info-panel drag.

  const handleHeroTouchStart = useCallback((e) => {
    if (recentlyExitedZoom.current) return;
    longPressFired.current = false;
    heroDidDrag.current = false;
    if (e.touches.length === 2) {
      // ── Pinch start — cancel any pending long-press / drag
      heroIsPinching.current = true;
      if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
      setIsDragging(false); dragStartY.current = null; setDragOffset(0);
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      heroPinchStartDist.current = Math.hypot(dx, dy);
      heroPinchStartScale.current = heroScale;
    } else if (e.touches.length === 1) {
      heroIsPinching.current = false;
      if (heroScale > 1.05) {
        // ── Pan start (hero is zoomed in)
        heroPanStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        heroPanStartOffset.current = { ...heroPan };
      } else {
        // ── Normal drag (info-panel toggle) + long-press → fullscreen
        startDrag(e.touches[0].clientY);
        if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
        longPressTimer.current = setTimeout(() => {
          longPressTimer.current = null;
          longPressFired.current = true;
          tapHaptic();
          setIsZoomed(true);
          setIsDragging(false); dragStartY.current = null; setDragOffset(0);
        }, 500);
      }
    }
  }, [heroScale, heroPan, startDrag]);

  const handleHeroTouchMove = useCallback((e) => {
    if (e.touches.length === 2 && heroPinchStartDist.current) {
      // ── Pinch move — scale hero inline
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      const dist = Math.hypot(dx, dy);
      const newScale = Math.max(1, Math.min(5, heroPinchStartScale.current * (dist / heroPinchStartDist.current)));
      setHeroScale(newScale);
    } else if (e.touches.length === 1 && heroPanStart.current && heroScale > 1.05) {
      // ── Pan move
      const dx = e.touches[0].clientX - heroPanStart.current.x;
      const dy = e.touches[0].clientY - heroPanStart.current.y;
      setHeroPan({ x: heroPanStartOffset.current.x + dx, y: heroPanStartOffset.current.y + dy });
      if (Math.hypot(dx, dy) > 8) heroDidDrag.current = true;
    } else if (e.touches.length === 1 && heroScale <= 1.05) {
      // ── Normal info-panel drag
      moveDrag(e.touches[0].clientY);
    }
  }, [heroScale, moveDrag]);

  const handleHeroTouchEnd = useCallback((e) => {
    if (heroIsPinching.current && e.touches.length < 2) {
      heroPinchStartDist.current = null;
      heroIsPinching.current = false;
      // Snap back to 1 if pinch-released below threshold
      if (heroScale < 1.05) {
        setHeroScale(1);
        setHeroPan({ x: 0, y: 0 });
      }
      return;
    }
    if (heroPanStart.current) { heroPanStart.current = null; return; }
    // Normal drag end
    if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
    endDrag();
  }, [heroScale, endDrag]);

  // Exit zoom mode + reset ALL zoom state (both inline and fullscreen).
  // Also restores the info panels — exiting zoom should always bring the
  // analysis cards back into view, regardless of whether the user had toggled
  // them off before zooming.
  const exitZoom = useCallback(() => {
    setIsZoomed(false);
    setZoomScale(1);
    setZoomPan({ x: 0, y: 0 });
    // Also reset inline hero zoom so re-entering results starts fresh
    setHeroScale(1);
    setHeroPan({ x: 0, y: 0 });
    setInfoVisible(true);
    pinchStartDist.current = null;
    panStart.current = null;
    // Cancel any pending long-press timer that could re-zoom us
    if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
    longPressFired.current = false;
    // Suppress synthesized click + next-touch re-arm for 600ms — long enough
    // to swallow the iOS click-after-touchend (~300ms) and any double-tap.
    recentlyExitedZoom.current = true;
    setTimeout(() => { recentlyExitedZoom.current = false; }, 600);
    tapHaptic();
  }, []);

  // Zoomed touch handlers — pan + pinch (and tap-to-exit)
  const handleZoomTouchStart = useCallback((e) => {
    e.stopPropagation();
    if (e.touches.length === 2) {
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      pinchStartDist.current = Math.hypot(dx, dy);
      pinchStartScale.current = zoomScale;
      panStart.current = null;
      // Pinch is not a tap
      zoomTapCandidate.current = false;
    } else if (e.touches.length === 1) {
      panStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      panStartOffset.current = { ...zoomPan };
      // Single touch starts as a tap candidate; cleared on movement/pinch
      zoomTapCandidate.current = true;
      zoomTapStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
    }
  }, [zoomScale, zoomPan]);

  const handleZoomTouchMove = useCallback((e) => {
    e.stopPropagation();
    if (e.touches.length === 2 && pinchStartDist.current) {
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      const dist = Math.hypot(dx, dy);
      const newScale = Math.min(5, Math.max(1, pinchStartScale.current * (dist / pinchStartDist.current)));
      setZoomScale(newScale);
      zoomTapCandidate.current = false;
    } else if (e.touches.length === 1 && panStart.current) {
      const dx = e.touches[0].clientX - panStart.current.x;
      const dy = e.touches[0].clientY - panStart.current.y;
      setZoomPan({ x: panStartOffset.current.x + dx, y: panStartOffset.current.y + dy });
      // Cancel the tap if the finger has moved beyond the slop radius
      if (zoomTapCandidate.current && Math.hypot(dx, dy) > 8) {
        zoomTapCandidate.current = false;
      }
    }
  }, []);

  const handleZoomTouchEnd = useCallback((e) => {
    e.stopPropagation();
    const wasTap = zoomTapCandidate.current && (Date.now() - zoomTapStart.current.t) < 300;
    if (e.touches.length < 2) pinchStartDist.current = null;
    if (e.touches.length === 0) panStart.current = null;
    // Snap scale back to 1 if pinched below 1
    setZoomScale(s => Math.max(1, s));
    zoomTapCandidate.current = false;
    if (wasTap && e.touches.length === 0) {
      // Single tap on the zoomed hero → exit zoom.  preventDefault on the
      // touchend suppresses the synthesized click that would otherwise fire
      // ~300ms later and run the panel-toggle / re-zoom branches.
      if (e.cancelable) e.preventDefault();
      exitZoom();
    }
  }, [exitZoom]);

  // Touch handlers
  const onTouchStart = useCallback((e) => startDrag(e.touches[0].clientY), [startDrag]);
  const onTouchMove = useCallback((e) => moveDrag(e.touches[0].clientY), [moveDrag]);
  const onTouchEnd = useCallback(() => endDrag(), [endDrag]);

  // Mouse handlers (desktop drag)
  const onMouseDown = useCallback((e) => { e.preventDefault(); startDrag(e.clientY); }, [startDrag]);
  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e) => moveDrag(e.clientY);
    const onUp = () => endDrag();
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [isDragging, moveDrag, endDrag]);

  // Confidence count-up — runs from 0 to the real value when the panel
  // reveals. Resets on dismiss so the animation replays on re-reveal.
  useEffect(() => {
    const target = result?.confidence ?? 0;
    if (!infoVisible) { setAnimatedConf(0); return; }
    const DURATION = 700;
    const start = performance.now();
    let raf;
    const tick = (now) => {
      const t = Math.min((now - start) / DURATION, 1);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setAnimatedConf(Math.round(eased * target));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [infoVisible, result?.confidence]);

  if (!result) return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, overflow: 'hidden' }}>
      <div style={{ position: 'relative', width: '100%', height: '100%', backgroundColor: SCREEN_BG, fontFamily: 'Inter, system-ui, sans-serif' }}>
        <MatteBackground variant="carbon" />
        <button
          aria-label="Back"
          onClick={() => { navHaptic(); onRetry(); }}
          style={{ position: 'absolute', top: 52, left: 8, width: 44, height: 44, zIndex: 30, background: 'none', border: 'none', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}
        >
          <span style={{ position: 'absolute', left: 14, top: 8, fontSize: 22, fontWeight: 600, color: '#a7adb7', lineHeight: 1 }}>‹</span>
        </button>
      </div>
    </div>
  );

  const { pattern, geometricBase, confidence = 0, meta, mood, sections: _sections } = result;
  const sections = _sections || {};
  const raw = result?._raw || {};
  const signalDiag = raw.signal_diagnostics || {};
  // Convention conversion — see LightingDiagram.jsx for the long comment.
  // The engine emits `nose_shadow_angle_deg` in CENTROID convention
  //   (0° = shadow centroid below nose, 90° = right, 180° = above, 270° = left)
  // but every UI consumer (ShadowSignature, CatchlightEye, LightingDiagram,
  // raw-signal chips) was written against SHADOW_PASS convention
  //   (0° = up/back-of-head, 90° = right, 180° = down, 270° = left).
  // The two are 180° apart, so we normalize once at the source so every
  // downstream widget shows the physically-correct direction.  When the
  // engine standardizes its convention this is the only line to revert.
  const _rawSignalsRaw = signalDiag.signals || {};
  const rawSignals = _rawSignalsRaw.nose_shadow_angle_deg != null
    ? { ..._rawSignalsRaw, nose_shadow_angle_deg: ((_rawSignalsRaw.nose_shadow_angle_deg + 180) % 360) }
    : _rawSignalsRaw;
  // Catchlight clock position — clock-hour string for the dot in the eye graphic.
  // Priority: parsed clock positions from key_observations > engine CI field.
  // sections.modifier.position is a compass direction ("Upper Left"), not a clock
  // hour — it must NOT be used for catchlightClockHour.
  const catchlightClockStr =
    (sections?.catchlightPositions?.[0])
    || raw.lighting_inference?.catchlight_intelligence?.primary_key?.position
    || null;
  const catchlightClockHour = parseClockHour(catchlightClockStr);
  const hasRawSignals = rawSignals.nose_shadow_angle_deg != null
    || rawSignals.left_right_asymmetry != null
    || rawSignals.shadow_density != null
    || rawSignals.highlight_width_ratio != null;
  const faceCrop = getFaceCropPosition(result?._raw);
  const isHighConf  = confidence >= 70;
  const confColor   = isHighConf ? C.confHigh : C.confLow;
  // Desktop uses a taller hero block so the photo can show its full aspect
  // (object-fit: contain) and a LightingDiagram can sit inline below the CTA.
  // Desktop hero column height — bumped from 920 → 980 so the LightingDiagram
  // well at the bottom has a usable >250px instead of being clipped at 165px.
  // The actions row still fits within the 1040 design viewport (980 + 60 ≈ 1040).
  // Mobile layout flows from VF bottom — pattern/confidence overlay is ON
  // the photo (inside VF), so CTA sits directly below VF with minimal gap.
  // Mobile: CTA moved to the bottom of the scroll content (inside the
  // analytical panel), so the top section only needs to contain the VF.
  // Summary strip + diagram + drawers + CTA flow naturally below.
  const M_TOP_END   = VF_TOP + VF_HEIGHT + 12;
  const leadMargin  = confidence - (sections.patternCandidates?.[1]?.score ?? 0);
  // Evidence string — shows which physical signals drove this verdict.
  // Only includes signals that actually fired; empty string when no data.
  const confEvidence = (() => {
    const parts = [];
    if (catchlightClockHour != null) parts.push('catchlights');
    if (rawSignals.nose_shadow_angle_deg != null) parts.push('shadow geometry');
    return parts.slice(0, 2).join(' + ');
  })();
  // Desktop hero position constants — photo / info / CTA / diagram stacked
  // top-to-bottom inside the hero column. panelTop = D_DIAGRAM_TOP + 300
  // gives the diagram well ~300px of real estate before the analytical
  // panel column begins.
  const D_PHOTO_TOP    = isDesktop ? 16 : 100;
  // Desktop photo: fill the grid row. The `1fr` grid row stretches to
  // viewport minus CTA. The photo fills this, with the pattern overlay
  // sitting at the bottom inside a gradient fade.
  const D_PHOTO_HEIGHT = isDesktop ? Math.max(VF_HEIGHT, stableVH - 100) : VF_HEIGHT;
  const D_PHOTO_BOTTOM = D_PHOTO_TOP + D_PHOTO_HEIGHT;
  const D_INFO_TOP     = D_PHOTO_BOTTOM + 20;   // photo bottom + 20 gap
  const D_CTA_TOP      = D_INFO_TOP + 120;       // info (pattern+pills) ~ 80 tall + 40 gap
  const D_DIAGRAM_TOP  = D_CTA_TOP + 60;         // CTA (48) + 12 gap → diagram well
  // Desktop: hero fills available viewport height (minus CTA area at bottom).
  // The photo + pattern overlay stretch to fill the column naturally.
  // Hero photo fills ~40% of viewport — keeps verdict hero + full diagram
  // above fold on short phones (iPhone SE: 267px photo, 400px remaining).
  const panelTop    = isDesktop ? (stableVH - 150) : Math.round(stableVH * 0.40);

  // Detail drawer toggle — silent.  THE LIGHT and THE SETUP are always
  // visible; only the DETAIL section collapses.
  const toggleDetail = () => setDetailOpen(prev => !prev);

  // ── Outcome capture — feeds the learning pipeline ──────────────────────
  const handleOutcome = useCallback((outcome) => {
    setOutcomeRecorded(outcome);
    tapHaptic();
    const patternId   = result?.pattern || result?.authoritative_pattern || 'unknown';
    const confScore   = result?.confidence ?? result?.match_confidence ?? null;
    const authHdr     = getToken() ? { Authorization: `Bearer ${getToken()}` } : {};
    // Primary signal — recorded for every outcome
    postSignal({ pattern_id: patternId, confidence_score: confScore, outcome, input_method: 'reference_photo' });
    if (outcome === 'nailed_it') {
      fetch('/api/intelligence/nailed-it', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHdr },
        credentials: 'include',
        body: JSON.stringify({ predicted_pattern: patternId, confidence: confScore }),
      }).catch(() => {});
    }
    if (outcome === 'failed') {
      fetch('/api/failures/event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHdr },
        credentials: 'include',
        body: JSON.stringify({ predicted_pattern: patternId, confidence: confScore }),
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data?.id) setCorrectionFailureId(data.id);
          setTimeout(() => setCorrectionSheetOpen(true), 600);
        })
        .catch(() => {});
    }
  }, [result]);

  // Summary for the collapsed DETAIL drawer
  const detailSummary = [
    sections.vlmNarrative?.fields?.[0]?.value || sections.sceneDescription?.split('.')[0],
    sections.colorPalette?.harmony,
    sections.signalQuality?.available != null
      ? `${sections.signalQuality.available}/${sections.signalQuality.total} signals`
      : sections.confidenceLabel,
  ].filter(Boolean).join(' · ');

  // Source + confidence attribution — dim sub-line below pattern/confidence
  const sourceAttribution = (() => {
    const parts = [];
    if (sections.confidenceLabel) parts.push(sections.confidenceLabel);
    if (sections.patternSource)   parts.push(sections.patternSource.toLowerCase());
    return parts.join(' · ');
  })();

  // Warning chip styling now lives in _shared/Chip.jsx.

  return (
    <>
    {correctionSheetOpen && (
      <CorrectionSheet
        failureEventId={correctionFailureId}
        onClose={() => setCorrectionSheetOpen(false)}
      />
    )}
    <div
      onTouchStart={!isDesktop ? handleSwipeStart : undefined}
      onTouchMove={!isDesktop ? handleSwipeMove : undefined}
      onTouchEnd={!isDesktop ? handleSwipeEnd : undefined}
      style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, overflow: 'hidden' }}
    >
    {/* Swipe-back edge hint — left edge glow that follows finger */}
    {swipeProgress > 0 && (
      <div style={{
        position: 'fixed', top: 0, bottom: 0, left: 0,
        width: 24,
        background: `radial-gradient(circle at 0px ${swipeY}px, rgba(245,247,250,${0.22 * swipeProgress}) 0%, rgba(245,247,250,${0.06 * swipeProgress}) 120px, transparent 240px)`,
        zIndex: 200,
        pointerEvents: 'none',
        transition: 'opacity 0.1s ease',
      }} />
    )}
    <div
      style={{
      width: '100%',
      maxWidth: isDesktop ? '100%' : undefined,
      height: '100%',
      margin: '0 auto',
      fontFamily: 'Inter, system-ui, sans-serif',
      overflowX: 'hidden',
      overflowY: isDesktop ? 'hidden' : 'auto',
      position: 'relative',
      paddingBottom: isDesktop ? 0 : 40,
      filter: daylightMode ? 'brightness(1.15)' : undefined,
      transition: 'filter 0.4s ease',
      // Desktop: two-column grid. Left = hero/pattern/CTA (the 430px instrument
      // column, untouched internally). Right = analytical panel, moved
      // alongside the hero so the screen reads native on wide viewports.
      ...(isDesktop ? {
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
        gridTemplateAreas: '"hero panel"',
        columnGap: 0,
        rowGap: 0,
        maxWidth: 1400,
        margin: '0 auto',
        paddingLeft: 0, paddingRight: 0, paddingTop: 0,
        paddingBottom: 0,
        alignItems: 'start',
        justifyContent: 'center',
        overflowY: 'hidden',
        height: '100%',
      } : null),
    }}>
      <MatteBackground variant="carbon" />

      {/* ─── Top section — absolute positioned within fixed-height container ─── */}
      <div style={{
        ...(isDesktop ? {
          gridArea: 'hero',
          display: 'flex',
          flexDirection: 'column',
          position: 'sticky',
          top: 0,
          height: '100vh',
          overflow: 'hidden',
        } : {
          position: 'relative',
          width: '100%',
          height: panelTop,
        }),
      }}>
      <div style={{ position: 'relative', width: '100%', ...(isDesktop ? { flex: 1, overflow: 'hidden' } : { height: '100%' }) }}>

        {/* Back nav */}
        <button
          aria-label="Back"
          onClick={() => { navSlideSound(); navHaptic(); onRetry(); }}
          style={{
            position: 'absolute', top: 52, left: 8,
            width: 44, height: 44,
            zIndex: 30,
            background: 'none', border: 'none', cursor: 'pointer',
            overflow: 'hidden', WebkitTapHighlightColor: 'transparent',
            display: 'flex', alignItems: 'center',
          }}
        >
          <span style={{
            position: 'absolute', left: 14, top: 8,
            fontSize: 22, fontWeight: 600, color: '#a7adb7', lineHeight: 1,
            WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision',
          }}>‹</span>
        </button>

        {/* Wordmark removed — Result screen is about the answer, not brand.
            Back chevron provides navigation; pattern overlay IS the identity. */}

        {/* Hero — user's photo with glass treatment (Figma 1493:5) */}
        {/* Pinch-to-zoom + pan work inline inside the VF.
            Tap = fullscreen overlay.  Double-tap = reset inline zoom.
            Long-press (500ms, only when heroScale ≤ 1) = fullscreen. */}
        <div
          onTouchStart={isZoomed ? handleZoomTouchStart : handleHeroTouchStart}
          onTouchMove={isZoomed ? handleZoomTouchMove : handleHeroTouchMove}
          onTouchEnd={isZoomed ? handleZoomTouchEnd : handleHeroTouchEnd}
          onMouseDown={isZoomed ? undefined : (e) => { e.preventDefault(); startDrag(e.clientY); }}
          onClick={() => {
            // Lockout window after exiting zoom — swallow the synthesized
            // click that fires after the tap-to-exit touch sequence so it
            // can't re-enter zoom or re-arm the long-press timer.
            if (recentlyExitedZoom.current) return;
            if (longPressFired.current) { longPressFired.current = false; return; }
            if (heroIsPinching.current) return;
            // If a chip-detail overlay is showing on the hero, a click should
            // dismiss it instead of toggling fullscreen.
            if (chipDetail) { setChipDetail(null); return; }
            if (isZoomed) {
              exitZoom();
              return;
            }
            // If the gesture turned into a vertical info-panel drag, this
            // trailing click is not a tap — bail out and reset the flag.
            if (heroDidDrag.current) { heroDidDrag.current = false; return; }
            // Double-tap → reset inline hero zoom (if zoomed in)
            const now = Date.now();
            if (heroScale > 1.05 && (now - lastTapTime.current) < 350) {
              setHeroScale(1);
              setHeroPan({ x: 0, y: 0 });
              tapHaptic();
              lastTapTime.current = 0;
              return;
            }
            lastTapTime.current = now;
            // If hero is zoomed inline, single tap is a no-op (user is
            // exploring the image). Only go fullscreen from default scale.
            if (heroScale > 1.05) return;
            // Plain click → fill viewport.  Cancel any pending long-press
            // timer so it doesn't toggle us back out 500ms later.
            if (longPressTimer.current) {
              clearTimeout(longPressTimer.current);
              longPressTimer.current = null;
            }
            tapHaptic();
            setIsZoomed(true);
          }}
          style={{
            // When zoomed we hide the inline hero and let the portaled
            // fullscreen overlay (rendered below, escapes FitToViewport)
            // own the visual.  Keeping the inline node mounted preserves
            // the position/size CSS so exit transitions still feel right.
            // Photo fills the hero section (top ~55% of viewport).
            // Pattern name + answer content visible below.
            // Full-bleed on both desktop and mobile: photo fills the VF edge-to-edge.
            // objectFit: cover handles orientation-agnostic cropping.
            position: 'absolute', top: 0, left: 0, right: 0, height: '100%',
            borderRadius: 0,
            visibility: isZoomed ? 'hidden' : 'visible',
            overflow: 'hidden',
            // Desktop: deep recessed LCD panel — matching ProcessingScreen trough.
            // Mobile: plain black.
            backgroundColor: isDesktop ? undefined : '#000',
            background: isDesktop
              ? 'linear-gradient(180deg, #111113 0%, #0c0c0e 40%, #080808 100%)'
              : '#000',
            borderRadius: 0,
            // boxShadow on the container renders BEHIND the absolutely-positioned
            // photo child and is invisible. Bezel shadow applied as child overlay below.
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
            transition: 'none',
            touchAction: 'none',
            zIndex: 1,
          }}
        >
          {imagePreview && (
            <img key={imagePreview} src={imagePreview} alt="Result" style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              objectFit: 'cover',
              objectPosition: isDesktop ? '50% 20%' : '50% 25%',
              opacity: 1,
              // Inline pinch-zoom + pan — transform applied directly so the
              // image scales inside the VF with overflow: hidden clipping.
              transform: heroScale > 1.01
                ? `translate(${heroPan.x}px, ${heroPan.y}px) scale(${heroScale})`
                : undefined,
              transition: heroScale <= 1.01 ? 'transform 0.15s ease-out' : 'none',
              willChange: heroScale > 1.01 ? 'transform' : undefined,
              animation: heroScale <= 1.01
                ? 'heroRevealLift 1.0s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards, heroZoomInSlow 1.8s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards'
                : 'none',
              transformOrigin: 'center center',
            }} />
          )}
          <ViewfinderHUD />

          {/* ── VF_WARNING_DOTS — compact amber indicators, top-right ──
              Collapsed: small amber dot with count badge. Tap to expand
              into the full chip set. Each chip opens chipDetail on tap. */}
          {sections.edgeCaseWarnings?.length > 0 && (
            <div style={{
              position: 'absolute', top: 10, right: 10,
              zIndex: 8,
              display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5,
            }}>
              {warningsExpanded ? (
                /* Expanded — full chips */
                <>
                  {sections.edgeCaseWarnings.map((w, i) => (
                    <Chip
                      key={i}
                      label={w.label}
                      variant={sevToVariant(w.sev)}
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); tapHaptic(); setChipDetail(w); }}
                      title={w.detail || 'Tap for details'}
                    />
                  ))}
                  <div
                    role="button" aria-label="Close warnings" tabIndex={0}
                    onClick={(e) => { e.stopPropagation(); setWarningsExpanded(false); }}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setWarningsExpanded(false); } }}
                    style={{
                      width: 44, height: 44,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      cursor: 'pointer',
                      WebkitTapHighlightColor: 'transparent',
                      margin: '-13px -13px -13px 0',
                    }}
                  >
                    <div style={{
                      width: 18, height: 18, borderRadius: 9,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      backgroundColor: 'rgba(0,0,0,0.5)',
                    }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: steel(0.60), lineHeight: 1 }}>×</span>
                    </div>
                  </div>
                </>
              ) : (
                /* Collapsed — amber dot with count */
                <div
                  role="button" aria-label="Show warnings" tabIndex={0}
                  onClick={(e) => { e.stopPropagation(); tapHaptic(); setWarningsExpanded(true); }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapHaptic(); setWarningsExpanded(true); } }}
                  style={{
                    width: 44, height: 44,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    cursor: 'pointer',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  <div style={{
                    width: 22, height: 22, borderRadius: 11,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    backgroundColor: 'rgba(245,190,72,0.18)',
                    boxShadow: '0 0 6px rgba(245,190,72,0.25), inset 0 0 0 0.5px rgba(245,190,72,0.30)',
                  }}>
                    <span style={{
                      fontSize: 9, fontWeight: 700,
                      color: 'rgba(250,210,130,0.95)',
                      lineHeight: 1,
                    }}>
                      {sections.edgeCaseWarnings?.length}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Blown-highlights region overlay — appears only when the user
              taps the Blown Highlights warning chip. Sampled client-side from
              the loaded hero bitmap; tints clipped pixels red and near-clipped
              pixels orange so the user can see WHERE the engine flagged. */}
          {imagePreview && chipDetail?.label === 'Blown Highlights' && (
            <BlownHighlightsCanvas
              src={imagePreview}
              objectFit="contain"
              objectPosition="50% 50%"
            />
          )}
          {/* Bottom vignette — fades photo into the result overlay at VF bottom */}
          <div style={{
            position: 'absolute', inset: 0,
            background: 'linear-gradient(to bottom, transparent 45%, rgba(9,9,11,0.35) 75%, rgba(9,9,11,0.65) 100%)',
            pointerEvents: 'none',
          }} />
          {/* Glass panel — lens vignette + key light reflection inside recessed panel */}
          <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 0, zIndex: 2, pointerEvents: 'none' }}>
            <div style={{ position: 'absolute', inset: 0, background: LENS_VIGNETTE }} />
            <div style={DITHER_STYLE} />
            <div style={{ position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0, background: GLASS_REFLECTION, borderRadius: 0, opacity: isDesktop ? 0.72 : 0.62, transform: glassReflectionTransform(tilt), willChange: 'transform' }} />
          </div>
          {/* Chamfer + counter-chamfer — matches Home VF depth */}
          {isDesktop && (<>
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 3, pointerEvents: 'none',
              background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 3, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
            }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 3, pointerEvents: 'none',
              background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 3, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
            }} />
          </>)}
          {/* Bezel recession overlay — child div over the photo.
              box-shadow inset bleeds through bright photo backgrounds, so we use
              a 4-sided gradient vignette: hard opaque black at each edge fading
              to transparent inward. Immune to photo brightness.
              Combined with a box-shadow ring for the hard pixel edge. */}
          {isDesktop && (
            <div style={{
              position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 4,
              boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.85)',
              background: [
                'linear-gradient(to bottom, rgba(0,0,0,0.88) 0%, rgba(0,0,0,0.62) 4%, rgba(0,0,0,0.28) 9%, rgba(0,0,0,0.06) 14%, transparent 20%)',
                'linear-gradient(to right,  rgba(0,0,0,0.88) 0%, rgba(0,0,0,0.62) 3%, rgba(0,0,0,0.28) 7%, rgba(0,0,0,0.06) 11%, transparent 16%)',
                'linear-gradient(to left,   rgba(0,0,0,0.70) 0%, rgba(0,0,0,0.45) 3%, rgba(0,0,0,0.18) 7%, rgba(0,0,0,0.04) 11%, transparent 16%)',
                'linear-gradient(to top,    rgba(0,0,0,0.60) 0%, rgba(0,0,0,0.38) 3%, rgba(0,0,0,0.14) 7%, transparent 14%)',
              ].join(', '),
            }} />
          )}
          {/* ── Result identification overlay — Apple-style metadata on the photo ──
              Pattern name + confidence sit on the lower third of the VF so the
              answer is ON the photo, not below it. The vignette gradient at
              the bottom provides readable contrast. */}
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            padding: isDesktop ? '64px 24px 28px' : '64px 20px 18px',
            background: 'linear-gradient(to bottom, transparent 0%, rgba(6,7,9,0.40) 22%, rgba(6,7,9,0.68) 45%, rgba(6,7,9,0.88) 68%, rgba(6,7,9,0.97) 100%)',
            zIndex: 10, pointerEvents: 'none',
          }}>
            {/* Mobile verdict lives in the VERDICT HERO ZONE panel below the photo.
                Overlay is gradient-only so depth reads without competing text. */}
          </div>

          {result?.cameraSettings && (
            <ExifStrip exifData={result.cameraSettings} style={{
              bottom: 4, zIndex: 8, opacity: 0.75,
            }} />
          )}

          {/* Chip detail overlay — slides up over the hero when a warning chip
              is tapped. Sits above the inner-shadow bevel so the rim still
              reads behind it. */}
          {chipDetail && (
            <div
              onClick={(e) => { e.stopPropagation(); setChipDetail(null); }}
              style={{
                position: 'absolute', inset: 0, zIndex: 4,
                // Blown Highlights leaves the backdrop transparent so the
                // tinted-pixel overlay underneath stays visible.  Other chip
                // details still wash the photo so the explanation reads.
                background: chipDetail.label === 'Blown Highlights'
                  ? 'transparent'
                  : 'linear-gradient(180deg, rgba(11,11,12,0.35) 0%, rgba(11,11,12,0.78) 55%, rgba(11,11,12,0.92) 100%)',
                backdropFilter: chipDetail.label === 'Blown Highlights' ? undefined : 'blur(4px)',
                WebkitBackdropFilter: chipDetail.label === 'Blown Highlights' ? undefined : 'blur(4px)',
                display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                padding: 22,
                cursor: 'pointer',
                animation: 'chipDetailIn 0.28s cubic-bezier(0.4,0,0.2,1)',
              }}
            >
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  width: '100%', maxWidth: 460,
                  borderRadius: 14,
                  backgroundColor: 'rgba(14,16,20,0.92)',
                  boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
                  padding: '16px 18px 14px',
                  cursor: 'default',
                  position: 'relative',
                }}
              >
                <button
                  onClick={() => setChipDetail(null)}
                  aria-label="Close"
                  style={{
                    position: 'absolute', top: -1, right: 1,
                    width: 44, height: 44,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: 'none', border: 'none', padding: 0,
                    cursor: 'pointer',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  <span style={{
                    width: 26, height: 26, borderRadius: 13,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    color: 'rgba(245,247,250,0.7)',
                    fontSize: 16, lineHeight: '22px',
                  }}>×</span>
                </button>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Chip label={chipDetail.label} variant={sevToVariant(chipDetail.sev)} size="md" />
                  <span style={{
                    fontSize: 9, fontWeight: 700, color: steel(0.5),
                    letterSpacing: '1px', textTransform: 'uppercase', ...FONT_SMOOTH,
                  }}>
                    {chipDetail.sev === 'danger' ? 'Critical' : chipDetail.sev === 'warn' ? 'Warning' : 'Note'}
                  </span>
                </div>
                <p style={{
                  margin: 0,
                  fontSize: 14, lineHeight: '20px',
                  color: 'rgba(225,228,234,0.92)',
                  ...FONT_SMOOTH,
                }}>
                  {chipDetail.detail || 'No additional detail available for this flag.'}
                </p>
              </div>
            </div>
          )}
          {/* Bezel depth shadow — body overhangs recessed LCD from all sides (desktop) */}
          {isDesktop && (
          <div style={{
            position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 9,
            background: [
              'linear-gradient(to bottom, rgba(0,0,0,0.80) 0%, rgba(0,0,0,0.45) 7%, rgba(0,0,0,0.14) 18%, transparent 30%)',
              'linear-gradient(to top,   rgba(0,0,0,0.60) 0%, rgba(0,0,0,0.28) 7%, rgba(0,0,0,0.08) 16%, transparent 28%)',
              'linear-gradient(to right, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0.30) 7%, rgba(0,0,0,0.08) 16%, transparent 26%)',
              'linear-gradient(to left,  rgba(0,0,0,0.45) 0%, rgba(0,0,0,0.18) 7%, transparent 20%)',
            ].join(', '),
          }} />
          )}
          {/* Chamfer edge highlights — top-left bezel catch, matches Home ghost VF depth */}
          {isDesktop && (<>
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 11, pointerEvents: 'none',
              background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.025) 35%, rgba(255,255,255,0.008) 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 11, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 35%, transparent 65%)',
            }} />
          </>)}
        </div>

        {/* Desktop diagram moved to panel column — see SETUP DIAGRAM SectionPanel below */}
      </div>

      {/* ─── Desktop verdict strip — pattern name on clean matte surface, evidence attached ─── */}
      {isDesktop && (
        <div style={{
          flexShrink: 0,
          padding: '12px 20px 14px',
          borderTop: '1px solid rgba(132,158,184,0.06)',
          opacity: infoVisible ? 1 : 0,
          transition: isDragging ? 'none' : 'opacity 0.3s ease 0.05s',
        }}>
          <p style={{
            margin: 0,
            fontWeight: 800,
            fontSize: pattern.length > 18 ? 28 : pattern.length > 12 ? 32 : 36,
            lineHeight: 1.1,
            letterSpacing: '-0.4px',
            color: 'rgba(245,247,250,0.97)',
            ...FONT_SMOOTH,
          }}>
            {/* A decline is not a pattern named "Unknown". When the engine
                cannot read the light, say that in words a photographer would
                use — and let the evidence readout below carry what it DID
                see. See isDecline() for why the trigger is still open. */}
            {isDecline(pattern) ? 'No confident read' : prettify(pattern, { title: true })}
          </p>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 6 }}>
            {confDisplayMode !== 'simple' && !isDecline(pattern) && scoreIsMeaningful(confidence) && (
              <span style={{
                fontSize: 20, fontWeight: 700,
                color: confColor,
                letterSpacing: '-0.2px',
                fontVariantNumeric: 'tabular-nums',
                textShadow: `0 0 10px ${confColor}40`,
                ...FONT_SMOOTH,
              }}>{animatedConf}%</span>
            )}
            {/* Only the >=80 band measured as separable (89% correct). Below it the
                grade misled: "Uncertain" reads were right 83% of the time and
                "Tentative" 100%, which teaches photographers to ignore the label.
                Observations are shown instead -- see lightingEvidence.js. */}
            {confDisplayMode !== 'numeric' && !isDecline(pattern) && scoreIsMeaningful(confidence) && (
              <span style={{
                fontSize: confDisplayMode === 'simple' ? 18 : 13,
                fontWeight: 600,
                color: 'rgba(140,218,160,0.80)',
                letterSpacing: '0.4px',
                ...FONT_SMOOTH,
              }}>
                Confident
              </span>
            )}
          </div>
          {result?.evidence?.observations?.length ? (
            <EvidenceReadout evidence={result.evidence} />
          ) : confEvidence ? (
            <p style={{
              margin: '4px 0 0',
              fontSize: 13, fontWeight: 500,
              color: steel(0.68),
              letterSpacing: '0.2px',
              lineHeight: 1.35,
              ...FONT_SMOOTH,
            }}>{confEvidence} agree</p>
          ) : sourceAttribution ? (
            <p style={{
              margin: '4px 0 0',
              fontSize: 12, fontWeight: 500,
              color: steel(0.55),
              letterSpacing: '0.3px',
              ...FONT_SMOOTH,
            }}>{sourceAttribution}</p>
          ) : null}
          {(() => {
            const raw1 = sections.sceneDescription || sections.vlmNarrative?.fields?.[0]?.value;
            const interp = raw1?.split('.')?.[0]?.trim();
            return interp && interp.length > 10 ? (
              <p style={{
                margin: '6px 0 0',
                fontSize: 12, fontWeight: 400,
                color: steel(0.50),
                lineHeight: 1.4,
                ...FONT_SMOOTH,
              }}>
                {interp}.
              </p>
            ) : null;
          })()}
        </div>
      )}

      {/* ─── Desktop CTA — anchored to bottom of sticky hero column ─── */}
      {isDesktop && (
        <div style={{
          flexShrink: 0,
          padding: '16px 20px 20px',
          pointerEvents: 'none',
          opacity: infoVisible ? 1 : 0,
          transition: isDragging ? 'none' : 'opacity 0.3s ease',
        }}>
          <button
            onClick={() => {
              if (isPaid) { segmentPressSound(); tapHaptic(); onSetup(); }
              else { tapHaptic(); startStripeCheckout().catch(e => { console.error('[checkout]', e.message); alert(e.message || 'Checkout failed. Please try again.'); }) }
            }}
            style={{
              display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              width: '100%',
              height: 54,
              borderRadius: 24,
              background: isPaid ? CTA_BG : 'linear-gradient(141.71deg, #3a3020 0%, #2a2218 50%, #1c1810 100%)',
              boxShadow: isPaid
                ? `${CTA_SHADOW}, ${CTA_BEVEL}`
                : '4px 4px 14px rgba(0,0,0,0.55), 0 0 0 0.5px rgba(200,155,69,0.30), 0 0 12px rgba(200,155,69,0.08), inset 0 1px 0 rgba(200,155,69,0.12)',
              border: 'none', cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              overflow: 'hidden',
              pointerEvents: 'auto',
            }}
          >
            <span style={{
              fontSize: 14, fontWeight: 700,
              color: isPaid ? 'rgba(245,247,250,0.95)' : 'rgba(200,155,60,0.95)',
              letterSpacing: '3px',
              textTransform: 'uppercase',
              pointerEvents: 'none',
              textShadow: isPaid ? undefined : '0 0 12px rgba(200,155,60,0.30)',
              ...FONT_SMOOTH,
            }}>
              {isPaid ? 'Build This Light' : 'Upgrade · From $39/mo'}
            </span>
          </button>
        </div>
      )}
      </div>
      {/* ─── end top section ─── */}

      {/* ─── Drag handle — swipe/tap affordance for panel show/hide (mobile) ── */}
      {!isDesktop && (
        <div
          role="button"
          aria-label={infoVisible ? 'Hide details panel' : 'Show details panel'}
          tabIndex={0}
          onClick={() => { setInfoVisible(v => !v); tapHaptic(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setInfoVisible(v => !v); tapHaptic(); } }}
          style={{
            display: 'flex', justifyContent: 'center', alignItems: 'center',
            padding: '8px 0 4px',
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <div style={{
            width: infoVisible ? 40 : 32, height: 4, borderRadius: 2,
            backgroundColor: steel(infoVisible ? 0.35 : 0.50),
            boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.5), 0 0.5px 0 rgba(255,255,255,0.06)',
            transition: 'width 0.3s cubic-bezier(0.4,0,0.2,1), background-color 0.3s ease',
          }} />
        </div>
      )}

      {/* ─── VERDICT HERO ZONE — mobile only ────────────────────────────────
          Clean dark surface below the photo. The authoritative read:
          pattern name dominant, confidence + evidence immediately attached.
          CTA follows YOUR SETUP — action comes after comprehension.
          Reading order: verdict → proof → setup → action → depth. */}
      {!isDesktop && (
        <div style={{
          marginLeft: 25, marginRight: 25,
          marginTop: 10, marginBottom: 4,
          padding: '14px 16px 14px',
          borderRadius: 14,
          backgroundColor: C.panelBg,
          boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
          position: 'relative',
          overflow: 'hidden',
          opacity: infoVisible ? 1 : 0,
          transition: isDragging ? 'none' : 'opacity 0.3s ease 0.05s',
          pointerEvents: infoVisible ? 'auto' : 'none',
        }}>
          {/* Bevel overlay — machined edge, matches other SectionPanels */}
          <div style={{ position: 'absolute', inset: 0, borderRadius: 14, pointerEvents: 'none', boxShadow: PANEL_BEVEL, zIndex: 1 }} />
          {/* Pattern name — dominant, clean surface, no photo texture competing */}
          <p style={{
            margin: 0,
            fontWeight: 800,
            fontSize: pattern.length > 18 ? 28 : pattern.length > 12 ? 32 : 36,
            lineHeight: 1.1,
            letterSpacing: '-0.4px',
            color: 'rgba(245,247,250,0.97)',
            position: 'relative', zIndex: 2,
            ...FONT_SMOOTH,
          }}>
            {/* A decline is not a pattern named "Unknown". When the engine
                cannot read the light, say that in words a photographer would
                use — and let the evidence readout below carry what it DID
                see. See isDecline() for why the trigger is still open. */}
            {isDecline(pattern) ? 'No confident read' : prettify(pattern, { title: true })}
          </p>
          {/* Confidence — respects confDisplayMode: simple=read, numeric=%, detailed=both */}
          <div style={{
            display: 'flex', alignItems: 'baseline', gap: 8,
            marginTop: 6, position: 'relative', zIndex: 2,
          }}>
            {confDisplayMode !== 'simple' && !isDecline(pattern) && scoreIsMeaningful(confidence) && (
              <span style={{
                fontSize: 20, fontWeight: 700,
                color: confColor,
                letterSpacing: '-0.2px',
                fontVariantNumeric: 'tabular-nums',
                textShadow: `0 0 10px ${confColor}40`,
                ...FONT_SMOOTH,
              }}>
                {animatedConf}%
              </span>
            )}
            {/* Only the >=80 band measured as separable (89% correct). Below it the
                grade misled: "Uncertain" reads were right 83% of the time and
                "Tentative" 100%, which teaches photographers to ignore the label.
                Observations are shown instead -- see lightingEvidence.js. */}
            {confDisplayMode !== 'numeric' && !isDecline(pattern) && scoreIsMeaningful(confidence) && (
              <span style={{
                fontSize: confDisplayMode === 'simple' ? 18 : 13,
                fontWeight: 600,
                color: 'rgba(140,218,160,0.80)',
                letterSpacing: '0.4px',
                ...FONT_SMOOTH,
              }}>
                Confident
              </span>
            )}
          </div>
          {/* Evidence source — which physical signals drove this verdict */}
          {result?.evidence?.observations?.length ? (
            <EvidenceReadout evidence={result.evidence} />
          ) : confEvidence ? (
            <p style={{
              margin: '4px 0 0',
              fontSize: 13, fontWeight: 500,
              color: steel(0.68),
              letterSpacing: '0.2px',
              lineHeight: 1.35,
              position: 'relative', zIndex: 2,
              ...FONT_SMOOTH,
            }}>
              {confEvidence} agree
            </p>
          ) : sourceAttribution ? (
            <p style={{
              margin: '4px 0 0',
              fontSize: 12, fontWeight: 500,
              color: steel(0.55),
              letterSpacing: '0.3px',
              position: 'relative', zIndex: 2,
              ...FONT_SMOOTH,
            }}>
              {sourceAttribution}
            </p>
          ) : null}
          {/* Interpretation line — first sentence from scene / VLM if available */}
          {(() => {
            const raw1 = sections.sceneDescription || sections.vlmNarrative?.fields?.[0]?.value;
            const interp = raw1?.split('.')?.[0]?.trim();
            return interp && interp.length > 10 ? (
              <p style={{
                margin: '6px 0 0',
                fontSize: 12, fontWeight: 400,
                color: steel(0.50),
                lineHeight: 1.4,
                position: 'relative', zIndex: 2,
                ...FONT_SMOOTH,
              }}>
                {interp}.
              </p>
            ) : null;
          })()}
        </div>
      )}

      {/* ── DISPATCH — mobile: immediately after verdict, before technical details ── */}
      {!isDesktop && (
        <div style={{
          marginLeft: 25, marginRight: 25,
          opacity: infoVisible ? 1 : 0,
          transition: isDragging ? 'none' : 'opacity 0.3s ease 0.05s',
          pointerEvents: infoVisible ? 'auto' : 'none',
        }}>
          <SafeRender>
            <SocialExportPanel
              result={result}
              imagePreview={imagePreview}
              diagramCanvas={socialDiagramCanvas}
              isStudio={plan === 'studio' || plan === 'enterprise'}
              isAdmin={isAdmin}
              freeMode={!isPaid}
              layout="compact"
            />
          </SafeRender>
        </div>
      )}

      {/* ─── Lighting Diagram (mobile only — always visible, not in a drawer) ───
          The single most valuable visual in the app. Shows where to put the
          lights. On desktop it's inline in the hero column; on mobile it was
          buried in the Shadow Analysis drawer. Now it's always above the fold. */}
      {!isDesktop && (
        <div
          onClick={() => { tapHaptic(); setChipDetail(null); setDiagramFullscreen(true); }}
          style={{
            marginLeft: 25, marginRight: 25, marginTop: 6, marginBottom: 4,
            position: 'relative',
            width: 'calc(100% - 50px)',
            aspectRatio: '300 / 175',
            borderRadius: 12,
            backgroundColor: C.pillBg,
            boxShadow: 'inset 0px 2px 6px 0px rgba(0,0,0,0.55), inset 0px 1px 2px 0px rgba(0,0,0,0.4), inset 1px 0px 2px 0px rgba(0,0,0,0.3), inset -1px 0px 2px 0px rgba(0,0,0,0.3)',
            overflow: 'hidden',
            cursor: 'zoom-in',
            opacity: infoVisible ? 1 : 0,
            transition: isDragging ? 'none' : 'opacity 0.3s ease 0.08s',
          }}
          title="Tap to expand diagram"
        >
          <div style={{
            position: 'absolute', inset: 0,
            padding: '8px 14px 18px',
            display: 'flex', justifyContent: 'center', alignItems: 'stretch',
            zIndex: 1,
          }}>
            <LightingDiagram ref={socialDiagramRef} result={result} fluid compact showExport={isPaid} />
          </div>
          <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 12, pointerEvents: 'none', zIndex: 9 }}>
            <div style={{ position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0, background: GLASS_REFLECTION, borderRadius: 12, opacity: 0.72, transform: glassReflectionTransform(tilt), willChange: 'transform' }} />
          </div>
          <div style={{
            position: 'absolute', inset: 0, borderRadius: 12,
            pointerEvents: 'none', boxShadow: VIEWFINDER_INNER_SHADOW, zIndex: 10,
          }} />
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 11, pointerEvents: 'none', borderRadius: '12px 12px 0 0',
            background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
          }} />
          <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 11, pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
          }} />
          <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 11, pointerEvents: 'none', borderRadius: '0 0 12px 12px',
            background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
          }} />
          <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 11, pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
          }} />
          {/* Label + expand icon — anchored bottom, reads as purposeful */}
          <div style={{
            position: 'absolute', bottom: 6, left: 12, right: 12, zIndex: 11,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            pointerEvents: 'none',
          }}>
            <span style={{
              fontSize: 11, fontWeight: 700,
              color: steel(0.42),
              letterSpacing: '1px',
              ...FONT_SMOOTH,
            }}>LIGHTING DIAGRAM</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: 0.45 }}>
              <span style={{ fontSize: 10, fontWeight: 600, color: steel(0.65), letterSpacing: '0.5px', ...FONT_SMOOTH }}>TAP TO EXPAND</span>
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <path d="M10 2h4v4M6 14H2v-4M14 2L9 7M2 14l5-5" stroke={steel(0.85)} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
        </div>
      )}

      {/* ─── Evidence Signal Band — compact support-signal chips, mobile only ───
          Glanceable key signals: key direction, modifier, catchlight position.
          Positioned between diagram and analytical panels — evidence supporting
          the verdict before deeper instrument panels. */}
      {!isDesktop && (() => {
        const chips = [
          sections.modifier?.position,
          sections.modifier?.family
            ? `${sections.modifier.sizeLabel ? sections.modifier.sizeLabel + ' ' : ''}${sections.modifier.family}`
            : null,
          catchlightClockHour != null ? `${catchlightClockHour}:00 catchlight` : null,
          geometricBase ? `${prettify(geometricBase, { title: true })} geometry` : null,
        ].filter(Boolean);
        return chips.length > 0 ? (
          <div style={{
            marginLeft: 25, marginRight: 25, marginTop: 8, marginBottom: 0,
            display: 'flex', flexWrap: 'wrap', gap: 6,
            opacity: infoVisible ? 1 : 0,
            transition: isDragging ? 'none' : 'opacity 0.3s ease 0.05s',
            pointerEvents: 'none',
          }}>
            {chips.map((chip, i) => (
              <span key={i} style={{
                fontSize: 11, fontWeight: 600,
                color: steel(0.52),
                letterSpacing: '0.5px',
                padding: '4px 9px',
                borderRadius: 6,
                backgroundColor: C.pillBg,
                boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.40), 0 0.5px 0 rgba(255,255,255,0.03)',
                ...FONT_SMOOTH,
              }}>
                {chip}
              </span>
            ))}
          </div>
        ) : null;
      })()}

      {/* ─── Analytical Panel (pull-tab drawers) ───
          Desktop: scroll container fills the right grid column at 100vh.
          Inner wrapper is a plain flex column with no height constraint —
          this is the fix that allows overflowY: auto to actually scroll
          (flex children shrink to fit if the container has height + flex,
          so we separate scroll container from flex layout). */}
      <div style={{
        ...(isDesktop ? {
          gridArea: 'panel',
          height: '100vh',
          overflowY: 'auto',
          overflowX: 'hidden',
          borderLeft: '1px solid rgba(132,158,184,0.05)',
        } : null),
      }}>
      <div style={{
        marginLeft: isDesktop ? 0 : 25,
        marginRight: isDesktop ? 0 : 25,
        marginTop: isDesktop ? 0 : 4,
        display: 'flex',
        flexDirection: 'column',
        gap: isDesktop ? 10 : 12,
        opacity: infoVisible ? 1 : 0,
        transform: infoVisible ? 'translateY(0)' : 'translateY(60px)',
        transition: isDragging ? 'none' : 'opacity 0.3s ease 0.05s, transform 0.4s cubic-bezier(0.4, 0, 0.2, 1) 0.05s',
        pointerEvents: infoVisible ? 'auto' : 'none',
        ...(isDesktop ? {
          paddingLeft: 24,
          paddingRight: 12,
          paddingTop: 20,
          paddingBottom: 40,
        } : {
          marginLeft: 25,
          marginRight: 25,
        }),
      }}>
        {/* Warning chips moved to VF overlay — see VF_WARNING_DOTS below */}

        {/* Pattern name removed from panel header — it's already on the hero
            overlay AND inside THE LIGHT's PatternBars. Three repetitions
            diluted the impact. Now the panel starts immediately with THE LIGHT. */}

        {/* ═══════════════════════════════════════════════════════════════
            THE LIGHT — always visible.  The core answer: what pattern,
            how confident.
            ═══════════════════════════════════════════════════════════════ */}
        {/* ═══════════════════════════════════════════════════════════════
            YOUR SETUP — single section replacing THE LIGHT + THE SETUP.
            Apple simplicity: one answer, not two sections competing.
            Pattern is already shown in the hero overlay (big text).
            This section shows the actionable blueprint: modifier + catchlight.
            PatternBars (alternate candidates) moved to DETAIL drawer.
            ═══════════════════════════════════════════════════════════════ */}
        {/* ── DISPATCH — desktop: first item in right panel, action surface immediately after verdict ── */}
        {isDesktop && (
          <SafeRender>
            <SocialExportPanel
              result={result}
              imagePreview={imagePreview}
              diagramCanvas={socialDiagramCanvas}
              isStudio={plan === 'studio' || plan === 'enterprise'}
              isAdmin={isAdmin}
              freeMode={!isPaid}
              layout="workbench"
            />
          </SafeRender>
        )}

        {/* ── SETUP DIAGRAM — desktop: proof layer below Dispatch ── */}
        {isDesktop && result?._raw && (
          <div
            onClick={() => { tapHaptic(); setChipDetail(null); setDiagramFullscreen(true); }}
            style={{
              position: 'relative', width: '100%',
              height: 'clamp(280px, 44vh, 460px)',
              borderRadius: 12,
              background: 'linear-gradient(180deg, #111113 0%, #0c0c0e 40%, #080808 100%)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.45), 0 1px 6px rgba(0,0,0,0.25)',
              overflow: 'hidden', cursor: 'zoom-in',
            }}
            title="Click to expand diagram"
          >
            <div style={{ position: 'absolute', inset: 0, padding: '12px 14px', display: 'flex', justifyContent: 'center', alignItems: 'stretch', zIndex: 1 }}>
              {diagramView === 'top' ? (
                <LightingDiagram result={result} fluid showExport={isPaid} />
              ) : (
                <SideViewDiagram result={result} fluid />
              )}
            </div>
            {/* View toggle */}
            <div style={{ position: 'absolute', top: 8, right: 10, zIndex: 11, display: 'flex' }}>
              {['top', 'side'].map(v => (
                <button key={v} onClick={(e) => { e.stopPropagation(); setDiagramView(v); }} style={{
                  padding: '3px 8px', border: 'none', cursor: 'pointer',
                  background: diagramView === v
                    ? 'linear-gradient(141.71deg, #2a2218 0%, #1c1810 100%)'
                    : 'linear-gradient(141.71deg, #14161c 0%, #0c0d10 100%)',
                  borderRadius: v === 'top' ? '5px 0 0 5px' : '0 5px 5px 0',
                  boxShadow: diagramView === v
                    ? 'inset 0 1px 0 rgba(200,155,60,0.10), 0 0 0 0.5px rgba(200,155,60,0.20)'
                    : 'inset 0 1px 0 rgba(255,255,255,0.03)',
                  fontSize: 10, fontWeight: 700, letterSpacing: '0.6px',
                  color: diagramView === v ? '#c89b45' : steel(0.30),
                  WebkitTapHighlightColor: 'transparent',
                }}>{v === 'top' ? 'TOP' : 'SIDE'}</button>
              ))}
            </div>
            {/* Label + expand hint */}
            <div style={{
              position: 'absolute', bottom: 8, left: 12, right: 12, zIndex: 9,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              pointerEvents: 'none',
            }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: steel(0.35), letterSpacing: '1px', ...FONT_SMOOTH }}>LIGHTING DIAGRAM</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: 0.40 }}>
                <span style={{ fontSize: 10, fontWeight: 600, color: steel(0.65), letterSpacing: '0.5px', ...FONT_SMOOTH }}>CLICK TO EXPAND</span>
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                  <path d="M10 2h4v4M6 14H2v-4M14 2L9 7M2 14l5-5" stroke={steel(0.85)} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
            {/* Glass treatment — home empty standard */}
            <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 12, zIndex: 6, pointerEvents: 'none' }}>
              <div style={{
                position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0,
                background: GLASS_REFLECTION, opacity: 0.72,
                transform: glassReflectionTransform(tilt), willChange: 'transform',
              }} />
            </div>
            <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 7, borderRadius: 12, boxShadow: VIEWFINDER_INNER_SHADOW }} />
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 8, pointerEvents: 'none', borderRadius: '12px 12px 0 0',
              background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 8, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
            }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 8, pointerEvents: 'none', borderRadius: '0 0 12px 12px',
              background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 8, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
            }} />
          </div>
        )}

        {(sections.modifier?.family || rawSignals.nose_shadow_angle_deg != null || catchlightClockHour != null || sections.catchlightModifier) && (
          <SectionPanel label={isPaid ? 'YOUR SETUP' : 'YOUR SETUP — UPGRADE TO UNLOCK'}>
            {/* Free tier: blurred preview — show what they'd GET, not what they can't see.
                Creates desire through partial reveal, not deprivation through a lock wall. */}
            {!isPaid && (
              <div
                onClick={() => { tapHaptic(); startStripeCheckout().catch(e => { console.error('[checkout]', e.message); alert(e.message || 'Checkout failed. Please try again.'); }) }}
                style={{ position: 'relative', overflow: 'hidden', borderRadius: 10, cursor: 'pointer' }}
              >
                {/* Blurred preview of setup content */}
                <div style={{
                  padding: '16px 10px', filter: 'blur(8px)', opacity: 0.35,
                  pointerEvents: 'none', userSelect: 'none',
                }}>
                  <div style={{
                    display: 'flex', gap: 10, alignItems: 'stretch',
                    padding: '10px', borderRadius: 10, backgroundColor: C.pillBg,
                  }}>
                    <div style={{ flex: 1, height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <CatchlightEye clockHour={catchlightClockHour} clockHours={catchlightClockHour ? [String(catchlightClockHour)] : []} angleDeg={rawSignals.nose_shadow_angle_deg} compact />
                    </div>
                    {sections.modifier?.family && (
                      <div style={{ flex: 1, height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <ModifierEmission family={sections.modifier.family} size={100} />
                      </div>
                    )}
                  </div>
                  {sections.modifier?.family && (
                    <p style={{ margin: '12px 0 0', fontSize: 18, fontWeight: 700, color: C.textPrimary, textAlign: 'center', ...FONT_SMOOTH }}>
                      {sections.modifier.sizeLabel} {sections.modifier.family}
                    </p>
                  )}
                </div>
                {/* Overlay CTA */}
                <div style={{
                  position: 'absolute', inset: 0,
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  gap: 6, background: 'rgba(4,5,8,0.45)',
                }}>
                  {/* Lock + PRO badge */}
                  <span style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase',
                    padding: '3px 10px', borderRadius: 4,
                    background: 'rgba(200,155,60,0.15)', border: '1px solid rgba(200,155,60,0.30)',
                    color: 'rgba(200,155,60,0.90)', ...FONT_SMOOTH,
                  }}>
                    🔒 PRO
                  </span>
                  <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'rgba(200,155,60,0.90)', letterSpacing: '0.3px', ...FONT_SMOOTH }}>
                    Unlock the full blueprint
                  </p>
                  <p style={{ margin: 0, fontSize: 11, color: steel(0.55), ...FONT_SMOOTH }}>
                    Modifier · Distance · Height · Catchlight · Diagram
                  </p>
                  <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 600, color: steel(0.40), ...FONT_SMOOTH }}>
                    From $39/mo
                  </p>
                </div>
              </div>
            )}
            {!isPaid ? null : (<>  {/* paid content below */}
            {/* ── Twin instruments: Catchlight + Modifier side-by-side ──
                Two visual anchors in one shared well so they read as a
                paired instrument panel, not two orphaned widgets. */}
            <div style={{
              display: 'flex', gap: 10, alignItems: 'stretch',
              padding: '10px 10px 8px',
              borderRadius: 10,
              backgroundColor: C.pillBg,
              boxShadow: 'inset 1px 1px 3px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.5px rgba(255,255,255,0.035)',
            }}>
              {/* Catchlight dial — icon container fixed 80px tall so label aligns with modifier label */}
              <div style={{
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
                gap: 6, minWidth: 0,
              }}>
                <div style={{ height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <CatchlightEye
                    clockHour={catchlightClockHour}
                    clockHours={catchlightClockHour ? [String(catchlightClockHour)] : []}
                    angleDeg={rawSignals.nose_shadow_angle_deg}
                    compact
                  />
                </div>
                <span style={{ fontSize: 12, fontWeight: 700, color: steel(0.50), letterSpacing: '1.2px', ...FONT_SMOOTH }}>
                  CATCHLIGHT
                </span>
              </div>
              {sections.modifier?.family && (
                <div style={{
                  width: 1, alignSelf: 'stretch',
                  background: 'linear-gradient(to bottom, transparent 0%, rgba(255,255,255,0.06) 30%, rgba(255,255,255,0.06) 70%, transparent 100%)',
                }} />
              )}
              {sections.modifier?.family && (
                <div style={{
                  flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
                  gap: 6, minWidth: 0,
                }}>
                  <div style={{ height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <ModifierEmission family={sections.modifier.family} size={100} />
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: steel(0.50), letterSpacing: '1.2px', ...FONT_SMOOTH }}>
                    MODIFIER
                  </span>
                </div>
              )}
            </div>

            {/* ── Modifier hero name — the answer to "what created this light" ── */}
            {sections.modifier?.family && (
              <div style={{ marginTop: 10 }}>
                <ModifierDetail modifier={sections.modifier} />
              </div>
            )}

            {/* Iris coverage + physical meaning removed — source size is
                implied by the modifier name/size range, and physical meaning
                was verbose repetition. APPARENT SOURCE band is now folded
                into the modifier subtitle. */}

            {/* Fallback narrative when no modifier family resolved */}
            {sections.catchlightModifier && !sections.modifier?.family && (
              <p style={{
                margin: '6px 0 0',
                fontSize: 14,
                fontWeight: 400,
                lineHeight: '20px',
                color: C.textSub,
                overflowWrap: 'anywhere',
                ...FONT_SMOOTH,
              }}>
                {sections.catchlightModifier}
              </p>
            )}
          </>)}
          </SectionPanel>
        )}

        {/* ─── Primary CTA — mobile only, after SETUP ─────────────────
            Reading order: VERDICT → PROOF → SETUP → CTA → DEPTH.
            Follows setup so the photographer sees what they're building
            before committing to the action. */}
        {!isDesktop && (
          <button
            onClick={() => {
              if (isPaid) { segmentPressSound(); tapHaptic(); onSetup(); }
              else { tapHaptic(); startStripeCheckout().catch(e => { console.error('[checkout]', e.message); alert(e.message || 'Checkout failed. Please try again.'); }); }
            }}
            style={{
              display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              width: '100%', height: 44, marginTop: 4,
              borderRadius: 22,
              background: isPaid ? CTA_BG : 'linear-gradient(141.71deg, #3a3020 0%, #2a2218 50%, #1c1810 100%)',
              boxShadow: isPaid
                ? `${CTA_SHADOW}, ${CTA_BEVEL}`
                : '4px 4px 14px rgba(0,0,0,0.55), 0 0 0 0.5px rgba(200,155,69,0.30), inset 0 1px 0 rgba(200,155,69,0.12)',
              border: 'none', cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <span style={{
              fontSize: 13, fontWeight: 700,
              color: isPaid ? 'rgba(245,247,250,0.95)' : 'rgba(200,155,60,0.95)',
              letterSpacing: '2.5px',
              textTransform: 'uppercase',
              textShadow: isPaid ? undefined : '0 0 10px rgba(200,155,60,0.28)',
              ...FONT_SMOOTH,
            }}>
              {isPaid ? 'Build This Light' : 'Upgrade · From $39/mo'}
            </span>
          </button>
        )}


        {/* ═══════════════════════════════════════════════════════════════
            DETAIL — single collapsible drawer.  Scene context, color
            palette, and confidence signals live here for the curious.
            Most users never need to open this — the answer and the
            rebuild are already visible above.
            ═══════════════════════════════════════════════════════════════ */}
        {(sections.sceneDescription || sections.vlmNarrative || sections.colorPalette || sections.signalQuality) && (
          <PullTabDrawer label="DETAIL" summary={detailSummary} open={detailOpen} onToggle={toggleDetail}>

            {/* ── Pattern Candidates (moved from THE LIGHT) ──────────── */}
            {sections.patternCandidates?.length > 0 && (
              <>
                <SubLabel>Pattern Analysis</SubLabel>
                <PatternBars
                  candidates={sections.patternCandidates}
                  isHighConf={isHighConf}
                  shadowSide={(() => {
                    const q = (sections.shadowDirection && sections.shadowDirection.shadowQuadrant) || '';
                    if (/left$/.test(q)) return 'left';
                    if (/right$/.test(q)) return 'right';
                    return undefined;
                  })()}
                  onSelectSetup={(patternName) => {
                    segmentPressSound(); tapHaptic();
                    onSetup(patternName);
                  }}
                />
              </>
            )}

            {/* ── Shadow Analysis (R-9: moved from THE LIGHT) ─────────── */}
            {(rawSignals.nose_shadow_angle_deg != null || sections.shadowComponents || sections.shadowDirection || sections.shadowAnalysis) && (
              <>
                <SubLabel>Shadow Analysis</SubLabel>
                <ShadowSignature
                  angleDeg={rawSignals.nose_shadow_angle_deg}
                  density={rawSignals.shadow_density}
                />
                {sections.shadowComponents && (
                  <div style={{ marginTop: 10 }}>
                    <LightComponentChips components={sections.shadowComponents} />
                  </div>
                )}
                {sections.shadowDirection && (
                  <div style={{ marginTop: 10 }}>
                    <DirectionalCompass direction={sections.shadowDirection} />
                  </div>
                )}
                {/* sections.shadowAnalysis is engine-internal debug text (e.g.
                    "Vertical angle pass: high (0.75). Round catchlights → …")
                    — suppressed from user-facing UI. O-2. */}
                {sections.shadowEdgeNote && (
                  <p style={{ margin: '8px 0 0', fontSize: 12, fontWeight: 400, lineHeight: '17px', color: steel(0.62), fontStyle: 'italic', ...FONT_SMOOTH }}>
                    {sections.shadowEdgeNote}
                  </p>
                )}
                <div style={{ height: 1, backgroundColor: 'rgba(255,255,255,0.04)', margin: '14px 0' }} />
              </>
            )}

            {/* ── Scene ────────────────────────────────────────────────── */}
            {(sections.sceneDescription || sections.vlmNarrative) && (
              <>
                <SubLabel>Scene</SubLabel>
                {sections.sceneDescription && (
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 400, lineHeight: '21px', color: C.textSub, ...FONT_SMOOTH }}>
                    {sections.sceneDescription}
                  </p>
                )}
                {sections.vlmNarrative?.fields?.length > 0 && (
                  <div style={{
                    marginTop: sections.sceneDescription ? 12 : 0,
                    display: 'grid',
                    gridTemplateColumns: isDesktop ? '1fr 1fr' : '1fr',
                    gap: 8,
                  }}>
                    {sections.vlmNarrative.fields.map(({ label, value }) => (
                      <SceneField key={label} label={label} value={value} />
                    ))}
                  </div>
                )}
              </>
            )}

            {/* ── Color Palette ────────────────────────────────────────── */}
            {sections.colorPalette && (
              <>
                <SubLabel>Color Palette</SubLabel>
                {sections.colorPalette.hexes.length > 0 && (
                  <div style={{ display: 'flex', gap: 10, marginBottom: 4 }}>
                    {sections.colorPalette.hexes.map((hex, i) => (
                      <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, flex: 1 }}>
                        <div style={{
                          width: '100%', maxWidth: 56, aspectRatio: '1 / 1', borderRadius: 10,
                          backgroundColor: hex,
                          boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.18), 0 2px 6px rgba(0,0,0,0.5)',
                        }} />
                        {sections.colorPalette.colors[i] && (
                          <span style={{ fontSize: 9, fontWeight: 600, color: steel(0.55), textAlign: 'center', lineHeight: 1.2, letterSpacing: '0.2px', ...FONT_SMOOTH }}>
                            {sections.colorPalette.colors[i]}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <CCTAxis keyKStr={sections.colorPalette.cctKey} shadowKStr={sections.colorPalette.cctShadows} />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: sections.colorPalette.character ? 8 : 0 }}>
                  {sections.colorPalette.harmony && (
                    <Chip
                      label={`HARMONY · ${prettify(sections.colorPalette.harmony, { upper: true })}${sections.colorPalette.warmCool ? ' · WARM/COOL' : ''}`}
                      variant="accent"
                      size="sm"
                    />
                  )}
                  {sections.colorPalette.cctKey && (
                    <Chip label={`KEY ${prettify(sections.colorPalette.cctKey, { upper: true })}`} variant="warn" size="sm" />
                  )}
                  {sections.colorPalette.cctShadows && (
                    <Chip label={`SHADOW ${prettify(sections.colorPalette.cctShadows, { upper: true })}`} variant="info" size="sm" />
                  )}
                </div>
                {sections.colorPalette.character && (
                  <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 400, lineHeight: '17px', color: steel(0.58), fontStyle: 'italic', ...FONT_SMOOTH }}>
                    {sections.colorPalette.character}
                  </p>
                )}
              </>
            )}

            {/* ── Confidence — photographer-facing summary ─────────────── */}
            {sections.signalQuality && (
              <>
                <SubLabel>Confidence</SubLabel>
                {/* Signal strength bar — the one metric photographers care about */}
                {sections.signalQuality.strength != null && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: steel(0.55), letterSpacing: '0.5px', ...FONT_SMOOTH }}>SIGNAL STRENGTH</span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: isHighConf ? C.confHigh : C.confLow, ...FONT_SMOOTH }}>
                        {sections.signalQuality.available != null
                          ? `${sections.signalQuality.available}/${sections.signalQuality.total}`
                          : `${Math.round(sections.signalQuality.strength * 100)}%`}
                      </span>
                    </div>
                    <div style={{ height: 3, borderRadius: 1.5, backgroundColor: C.barTrack }}>
                      <div style={{
                        height: '100%', borderRadius: 1.5,
                        width: `${Math.round(sections.signalQuality.strength * 100)}%`,
                        backgroundColor: isHighConf ? C.confHighBar : C.confLowBar,
                        transition: 'width 0.4s ease',
                      }} />
                    </div>
                  </div>
                )}
                {/* Reasoning narrative — human-readable confidence explanation */}
                {sections.signalQuality.reasoning && (
                  <p style={{ margin: '4px 0 0', fontSize: 12, fontWeight: 400, lineHeight: '17px', color: steel(0.62), fontStyle: 'italic', ...FONT_SMOOTH }}>
                    {sections.signalQuality.reasoning}
                  </p>
                )}

                {/* ── Engine Diagnostics — collapsed by default ──────────
                    Raw signals, pass reliability, and supporting/contradicting
                    evidence. Useful for debugging or deep analysis, but not
                    what a photographer on set needs. */}
                {(hasRawSignals || (sections.signalQuality.passSummaries && Object.keys(sections.signalQuality.passSummaries).length > 0) || sections.signalQuality.supporting.length > 0) && (
                  <DiagnosticsDisclosure>
                    {hasRawSignals && (
                      <div style={{ marginBottom: 12 }}>
                        <p style={{ margin: '0 0 6px', fontSize: 12, fontWeight: 600, color: steel(0.55), letterSpacing: '0.5px', ...FONT_SMOOTH }}>
                          RAW SIGNALS
                        </p>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                          {rawSignals.nose_shadow_angle_deg != null && (
                            <SignalGauge
                              label="NOSE SHADOW"
                              value={rawSignals.nose_shadow_angle_deg}
                              display={`${rawSignals.nose_shadow_angle_deg > 0 ? '+' : ''}${rawSignals.nose_shadow_angle_deg.toFixed(0)}°`}
                              mode="signed"
                            />
                          )}
                          {rawSignals.left_right_asymmetry != null && (
                            <SignalGauge
                              label="L/R ASYMMETRY"
                              value={Math.abs(rawSignals.left_right_asymmetry)}
                              display={`${(rawSignals.left_right_asymmetry * 100).toFixed(1)}%`}
                              mode="pct"
                              accentColor="rgba(130,170,220,0.85)"
                            />
                          )}
                          {rawSignals.shadow_density != null && (
                            <SignalGauge
                              label="SHADOW DENSITY"
                              value={rawSignals.shadow_density}
                              display={`${(rawSignals.shadow_density * 100).toFixed(1)}%`}
                              mode="pct"
                            />
                          )}
                          {rawSignals.highlight_width_ratio != null && (
                            <SignalGauge
                              label="HIGHLIGHT WIDTH"
                              value={rawSignals.highlight_width_ratio}
                              display={`${(rawSignals.highlight_width_ratio * 100).toFixed(0)}%`}
                              mode="pct"
                              accentColor="rgba(140,225,180,0.85)"
                            />
                          )}
                        </div>
                        {signalDiag.final_pattern && (
                          <div style={{ marginTop: 10 }}>
                            <Chip
                              label={`PATTERN · ${prettify(signalDiag.final_pattern, { upper: true })}`}
                              variant="accent"
                              size="sm"
                            />
                          </div>
                        )}
                      </div>
                    )}
                    {sections.signalQuality.passSummaries && Object.keys(sections.signalQuality.passSummaries).length > 0 && (
                      <div style={{ marginBottom: 12 }}>
                        <p style={{ margin: '0 0 6px', fontSize: 12, fontWeight: 600, color: steel(0.55), letterSpacing: '0.5px', ...FONT_SMOOTH }}>
                          PASS RELIABILITY
                        </p>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {Object.entries(sections.signalQuality.passSummaries).map(([pass, level]) => {
                            const variant = level === 'high' ? 'success' : level === 'moderate' ? 'info' : 'warn';
                            const passLabel = prettify(pass.replace(/_pass$/, ''), { upper: true });
                            return (
                              <Chip
                                key={pass}
                                label={`${passLabel} · ${String(level).toUpperCase()}`}
                                variant={variant}
                                size="sm"
                              />
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {sections.signalQuality.supporting.length > 0 && (
                      <div style={{ marginBottom: sections.signalQuality.contradicting.length > 0 ? 10 : 0 }}>
                        <p style={{ margin: '0 0 6px', fontSize: 11, fontWeight: 600, color: C.confHigh, letterSpacing: '0.5px', ...FONT_SMOOTH }}>
                          SUPPORTING
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {sections.signalQuality.supporting.map((s, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7 }}>
                              <div style={{ width: 3, height: 3, borderRadius: 1.5, backgroundColor: C.confHigh, marginTop: 6, flexShrink: 0 }} />
                              <span style={{ fontSize: 12, fontWeight: 400, color: C.textSub, lineHeight: 1.4, ...FONT_SMOOTH }}>{s}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {sections.signalQuality.contradicting.length > 0 && (
                      <div>
                        <p style={{ margin: '0 0 6px', fontSize: 11, fontWeight: 600, color: C.confLow, letterSpacing: '0.5px', ...FONT_SMOOTH }}>
                          CONTRADICTING
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {sections.signalQuality.contradicting.map((s, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 7 }}>
                              <div style={{ width: 3, height: 3, borderRadius: 1.5, backgroundColor: C.confLow, marginTop: 6, flexShrink: 0 }} />
                              <span style={{ fontSize: 12, fontWeight: 400, color: C.textSub, lineHeight: 1.4, ...FONT_SMOOTH }}>{s}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </DiagnosticsDisclosure>
                )}
              </>
            )}

            {/* ── Admin-only: raw engine data ── */}
            {isAdmin && (
              <div style={{ marginTop: 16, padding: '12px 0', borderTop: `1px solid ${C.divider}` }}>
                <p style={{ margin: '0 0 8px', fontSize: 10, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.35), ...FONT_SMOOTH }}>
                  ENGINE DATA
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 10, fontFamily: 'var(--font-mono, monospace)', color: steel(0.45), ...FONT_SMOOTH }}>
                  {result?.analysis_id && <div><strong style={{ color: steel(0.55) }}>ID:</strong> {result.analysis_id}</div>}
                  {result?.authoritative_pattern && <div><strong style={{ color: steel(0.55) }}>Pattern:</strong> {result.authoritative_pattern}</div>}
                  {result?.authoritative_pattern_source && <div><strong style={{ color: steel(0.55) }}>Source:</strong> {result.authoritative_pattern_source}</div>}
                  {result?.source_context && <div><strong style={{ color: steel(0.55) }}>Context:</strong> {result.source_context}</div>}
                  {result?.geometric_base && <div><strong style={{ color: steel(0.55) }}>Geo base:</strong> {result.geometric_base}</div>}
                  {result?.light_count != null && <div><strong style={{ color: steel(0.55) }}>Lights:</strong> {result.light_count}</div>}
                  {result?.system_version && <div><strong style={{ color: steel(0.55) }}>Version:</strong> {result.system_version}</div>}
                </div>
              </div>
            )}
          </PullTabDrawer>
        )}

        {/* ── Outcome capture — feeds the learning pipeline ── */}
        {isPaid && !outcomeRecorded && (
          <div style={{
            margin: '16px 0 8px', padding: '16px 14px',
            borderRadius: 12,
            background: MACHINED_PANEL_BG,
            boxShadow: PANEL_SHADOW + ', ' + PANEL_BEVEL,
          }}>
            <p style={{ margin: '0 0 10px', fontSize: 11, fontWeight: 700, letterSpacing: '1.5px', textTransform: 'uppercase', color: steel(0.40), textAlign: 'center', ...FONT_SMOOTH }}>
              DID YOU GET THE SHOT?
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              {[
                { id: 'nailed_it', label: 'Nailed It', icon: '✓', color: C.confHigh },
                { id: 'close',     label: 'Almost',    icon: '~', color: C.confLow },
                { id: 'failed',    label: 'Off',       icon: '✕', color: C.textDanger },
              ].map(o => (
                <button key={o.id} onClick={() => handleOutcome(o.id)}
                  className="sm-btn-lift"
                  style={{
                    flex: 1, padding: '12px 8px', border: 'none', borderRadius: 10, cursor: 'pointer',
                    background: MACHINED_BG,
                    boxShadow: '4px 4px 12px rgba(0,0,0,0.55), -0.5px -0.5px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07)',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                    WebkitTapHighlightColor: 'transparent',
                  }}>
                  <span style={{ fontSize: 18, color: o.color, ...FONT_SMOOTH }}>{o.icon}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: steel(0.55), letterSpacing: '0.3px', ...FONT_SMOOTH }}>{o.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {isPaid && outcomeRecorded && (
          <div style={{
            margin: '16px 0 8px', padding: '14px',
            borderRadius: 12, textAlign: 'center',
            background: MACHINED_PANEL_BG,
            boxShadow: PANEL_SHADOW + ', ' + PANEL_BEVEL,
          }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 600, color: outcomeRecorded === 'nailed_it' ? C.confHigh : outcomeRecorded === 'close' ? C.confLow : C.textDanger, ...FONT_SMOOTH }}>
              {outcomeRecorded === 'nailed_it' ? 'Nailed it — your feedback helps us improve.' : outcomeRecorded === 'close' ? 'Almost — we\'ll use this to tune.' : 'Noted — we\'ll use this to improve.'}
            </p>
            <p style={{ margin: '4px 0 0', fontSize: 10, color: steel(0.35), ...FONT_SMOOTH }}>
              This feeds the learning engine
            </p>
          </div>
        )}

        {/* ── Save setup — quick save without navigating to SetupScreen ── */}
        {isPaid && !setupSaved && (
          <button onClick={() => {
            tapHaptic(); softClickSound();
            saveSetup({ name: result?.pattern || result?.authoritative_pattern || 'Setup', tag: 'auto', result });
            setSetupSaved(true);
          }}
            className="sm-btn-lift"
            style={{
              width: '100%', padding: '13px 0', margin: '8px 0',
              borderRadius: 10, border: 'none', cursor: 'pointer',
              background: MACHINED_BG,
              boxShadow: '4px 4px 12px rgba(0,0,0,0.55), -0.5px -0.5px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              WebkitTapHighlightColor: 'transparent',
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={steel(0.50)} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 5v14l7-5 7 5V5" />
            </svg>
            <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.5px', color: steel(0.50), ...FONT_SMOOTH }}>Save This Setup</span>
          </button>
        )}
        {isPaid && setupSaved && (
          <div style={{ margin: '8px 0', padding: '12px', textAlign: 'center', borderRadius: 10, background: 'linear-gradient(141.71deg, #142218 0%, #0e1810 100%)', boxShadow: PANEL_SHADOW }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: C.confHigh, letterSpacing: '0.3px', ...FONT_SMOOTH }}>✓ Saved to your setups</span>
          </div>
        )}

        {/* ── Copy Setup Brief — text-message-ready spec for assistant handoff ── */}
        {isPaid && (
          <button
            onClick={() => {
              tapHaptic();
              const text = formatSetupText(result);
              if (navigator.share && /mobile|android|iphone|ipad/i.test(navigator.userAgent)) {
                navigator.share({ text }).catch(() => {});
              } else {
                navigator.clipboard?.writeText(text).then(() => {
                  setBriefCopied(true);
                  setTimeout(() => setBriefCopied(false), 2200);
                }).catch(() => {
                  // Fallback: create invisible textarea + execCommand
                  const el = document.createElement('textarea');
                  el.value = text; el.style.position = 'fixed'; el.style.opacity = '0';
                  document.body.appendChild(el); el.select();
                  try { document.execCommand('copy'); setBriefCopied(true); setTimeout(() => setBriefCopied(false), 2200); } catch {}
                  document.body.removeChild(el);
                });
              }
            }}
            className="sm-btn-lift"
            style={{
              width: '100%', padding: '13px 0', margin: '8px 0',
              borderRadius: 10, border: 'none', cursor: 'pointer',
              background: briefCopied
                ? 'linear-gradient(141.71deg, #142218 0%, #0e1810 100%)'
                : MACHINED_BG,
              boxShadow: '4px 4px 12px rgba(0,0,0,0.55), -0.5px -0.5px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              WebkitTapHighlightColor: 'transparent',
              transition: 'background 0.25s ease',
            }}>
            {briefCopied ? (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.confHigh} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.5px', color: C.confHigh, ...FONT_SMOOTH }}>Brief Copied</span>
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={steel(0.50)} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.5px', color: steel(0.50), ...FONT_SMOOTH }}>Copy Setup Brief</span>
              </>
            )}
          </button>
        )}

        {isPaid && onShotMatch && (
          <button onClick={() => { tapHaptic(); softClickSound(); onShotMatch(); }}
            className="sm-btn-lift"
            style={{
              width: '100%', padding: '13px 0', margin: '8px 0',
              borderRadius: 10, border: 'none', cursor: 'pointer',
              background: MACHINED_BG,
              boxShadow: '4px 4px 12px rgba(0,0,0,0.55), -0.5px -0.5px 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              WebkitTapHighlightColor: 'transparent',
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={steel(0.50)} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="2" width="9" height="9" rx="1" />
              <rect x="13" y="13" width="9" height="9" rx="1" />
              <path d="M13 6h3M16 3v6M6 13v3M3 16h6" />
            </svg>
            <span style={{ fontSize: 14, fontWeight: 600, letterSpacing: '0.5px', color: steel(0.50), ...FONT_SMOOTH }}>Compare Your Shot</span>
          </button>
        )}

        {/* Mobile CTA spacer — reserves room at bottom of scroll content
            so the floating CTA bar doesn't occlude the last drawer items. */}
        {!isDesktop && <div style={{ height: 72 }} />}
      </div>
      </div>

      {/* ─── Bottom row: single spacer ───
          The BottomActions "New Photo | Save" trough was removed because its
          Save button called the same `onSetup()` as the hero "Build This Light"
          CTA, and New Photo duplicated the top-left back chevron (which already
          fires `onRetry`).  A single flat spacer keeps the grid row reserved so
          the panel column alignment stays put. */}
      {!isDesktop && <div style={{ height: 16 }} />}

      {/* ─── Sticky CTA bar — mobile only (desktop CTA lives in sticky hero column) ─── */}
      {!isDesktop && (
        <div style={{
          position: 'sticky', bottom: 0, left: 0, right: 0,
          zIndex: 40,
          padding: '8px 25px 14px',
          background: `linear-gradient(to top, ${C.bg}f8 60%, ${C.bg}00 100%)`,
          pointerEvents: 'none',
          opacity: infoVisible ? 1 : 0,
          transition: isDragging ? 'none' : 'opacity 0.3s ease',
        }}>
          <button
            onClick={() => {
              if (isPaid) { segmentPressSound(); tapHaptic(); onSetup(); }
              else { tapHaptic(); startStripeCheckout().catch(e => { console.error('[checkout]', e.message); alert(e.message || 'Checkout failed. Please try again.'); }) }
            }}
            style={{
              display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              width: '100%',
              height: 48,
              borderRadius: 24,
              background: isPaid ? CTA_BG : 'linear-gradient(141.71deg, #3a3020 0%, #2a2218 50%, #1c1810 100%)',
              boxShadow: isPaid
                ? `${CTA_SHADOW}, ${CTA_BEVEL}`
                : '4px 4px 14px rgba(0,0,0,0.55), 0 0 0 0.5px rgba(200,155,69,0.30), 0 0 12px rgba(200,155,69,0.08), inset 0 1px 0 rgba(200,155,69,0.12)',
              border: 'none', cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              overflow: 'hidden',
              pointerEvents: 'auto',
            }}
          >
            <span style={{
              fontSize: 14, fontWeight: 700,
              color: isPaid ? 'rgba(245,247,250,0.95)' : 'rgba(200,155,60,0.95)',
              letterSpacing: '2.5px',
              textTransform: 'uppercase',
              pointerEvents: 'none',
              textShadow: isPaid ? undefined : '0 0 12px rgba(200,155,60,0.30)',
              ...FONT_SMOOTH,
            }}>
              {isPaid ? 'Build This Light' : 'Upgrade · From $39/mo'}
            </span>
          </button>
        </div>
      )}

      {/* ── First-visit teach overlay — explains each Result section ──────── */}
      {resultTeachVisible && !isDesktop && (() => {
        // Responsive column width — matches Home teach
        const COL_W = Math.min(430, window.innerWidth);
        const COL_CX = Math.round(COL_W / 2);
        const steps = [
          { // Step 0: Hero photo + pattern — the result
            x: 0, y: VF_TOP + VF_HEIGHT - 80, w: COL_W, h: 80, r: 0,
            title: 'Your lighting — decoded',
            desc: 'Pattern name and confidence — the answer at a glance.',
            tipY: VF_TOP + VF_HEIGHT + 48,
            arrow: 'up',
          },
          { // Step 1: THE LIGHT section
            x: 20, y: M_TOP_END + 60, w: COL_W - 40, h: 120, r: 12,
            title: 'Shadow geometry',
            desc: 'Which pattern, how strong, and what the shadows tell us.',
            tipY: M_TOP_END - 40,
            arrow: 'down',
          },
          { // Step 2: THE SETUP section (different copy for free vs paid)
            x: 20, y: M_TOP_END + 200, w: COL_W - 40, h: 140, r: 12,
            title: isPaid ? 'Your rebuild blueprint' : 'Your rebuild blueprint',
            desc: isPaid
              ? 'Modifier, catchlight, distance, height — everything to recreate it.'
              : 'Modifier, catchlight, anywhere to continue distance, height — upgrade to unlock the full breakdown.',
            tipY: M_TOP_END + 80,
            arrow: 'down',
          },
          { // Step 3: Build This Light CTA
            x: 25, y: stableVH - safeBottom - 68, w: COL_W - 50, h: 48, r: 24,
            title: isPaid ? 'Ready to build it?' : 'Upgrade to unlock',
            desc: isPaid
              ? 'Step-by-step cockpit to match this light in your studio.'
              : 'Get the full blueprint + step-by-step setup cockpit.',
            tipY: stableVH - safeBottom - 186,
            arrow: 'down',
          },
        ];
        const s = steps[resultTeachStep] || steps[0];
        // Clamp tooltip to viewport — prevent clipping on short screens.
        // Card height is ~72px. Ensure tipY + 72 stays within viewport,
        // and tipY stays above the safe area bottom.
        const CARD_H = 80;
        const maxTipY = stableVH - safeBottom - CARD_H - 8;
        const minTipY = safeBottom + 8;
        s.tipY = Math.max(minTipY, Math.min(maxTipY, s.tipY));
        // Also clamp spotlight Y to stay in viewport
        s.y = Math.max(0, Math.min(stableVH - safeBottom - s.h, s.y));

        const cx = s.x + s.w / 2;
        const cy = s.y + s.h / 2;
        const rx = s.w / 2 + 14;
        const ry = s.h / 2 + 14;
        const stepColors = ['rgba(245,210,140,1)', 'rgba(132,158,184,1)', 'rgba(107,148,245,1)', 'rgba(72,186,136,1)'];
        const sc = stepColors[resultTeachStep] || stepColors[0];

        // Arrow geometry — card shifted left for down-arrows, arrow targets spotlight edge
        const cardLeft = 24;
        const cardRight = 24;
        const cardW = COL_W - cardLeft - cardRight;
        const cardCX = cardLeft + cardW / 2;
        const cardEdgeY = s.arrow === 'up' ? s.tipY : s.tipY + 72;
        // Arrow tip lands at spotlight edge (bottom for up-arrows, top for down)
        const tipYA = s.arrow === 'up' ? (s.y + s.h) : s.y;
        const svgTop = Math.min(tipYA, cardEdgeY) - 10;
        const svgBot = Math.max(tipYA, cardEdgeY) + 10;
        const svgH = svgBot - svgTop;
        const startLY = cardEdgeY - svgTop;
        const endLY = tipYA - svgTop;
        // Natural arc: card is left-offset, spotlight centered — modest rightward curve
        const cpOffset = s.arrow === 'up' ? 30 : 20;
        const cpX = (cardCX + cx) / 2 + cpOffset;
        const cpY1 = startLY + (endLY - startLY) * 0.3;
        const cpY2 = startLY + (endLY - startLY) * 0.7;
        const curvePath = `M${cardCX} ${startLY} C${cpX} ${cpY1}, ${cpX} ${cpY2}, ${cx} ${endLY}`;
        const aSize = 8;
        const aDir = s.arrow === 'up' ? -1 : 1;
        // Chevron centered on endpoint: tip extends past, arms behind
        const aHalf = aSize / 2;
        const aPath = `M${cx - aSize} ${endLY - aHalf * aDir} L${cx} ${endLY + aHalf * aDir} L${cx + aSize} ${endLY - aHalf * aDir}`;
        const curveLen = Math.hypot(cx - cardCX, endLY - startLY) * 1.4;

        return (
          <div
            onClick={advanceResultTeach}
            style={{
              position: 'fixed', inset: 0, zIndex: 60,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              animation: resultTeachStep >= 4 ? 'rTeachOut 0.5s ease forwards' : 'rTeachIn 0.6s ease both',
            }}
          >
            {/* Scrim */}
            <div style={{
              position: 'absolute', inset: 0,
              background: `radial-gradient(ellipse ${rx * 2}px ${ry * 2}px at ${cx}px ${cy}px, transparent 0%, transparent 38%, rgba(0,0,0,0.42) 50%, rgba(0,0,0,0.62) 66%, rgba(0,0,0,0.72) 100%)`,
              transition: 'background 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />

            {/* Volumetric bloom */}
            <div style={{
              position: 'absolute',
              left: cx - 100, top: cy - 100,
              width: 200, height: 200,
              borderRadius: '50%',
              background: `radial-gradient(circle, ${sc.replace(/[\d.]+\)$/, '0.06)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.02)')} 40%, transparent 70%)`,
              pointerEvents: 'none',
              animation: 'rTeachBloom 3s ease-in-out infinite',
              transition: 'left 0.55s cubic-bezier(0.4,0,0.2,1), top 0.55s cubic-bezier(0.4,0,0.2,1)',
            }} />

            {/* Outer glow ring — soft halo, step-colored */}
            <div style={{
              position: 'absolute',
              left: s.x - 14, top: s.y - 14,
              width: s.w + 28, height: s.h + 28,
              borderRadius: s.r ? s.r + 14 : 14,
              border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.12)')}`,
              boxShadow: `0 0 44px ${sc.replace(/[\d.]+\)$/, '0.12)')}, 0 0 18px ${sc.replace(/[\d.]+\)$/, '0.06)')}, inset 0 0 20px ${sc.replace(/[\d.]+\)$/, '0.05)')}`,
              pointerEvents: 'none',
              animation: 'rTeachPulse 2.4s ease-in-out infinite',
              transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />
            {/* Inner spotlight ring — crisp border */}
            <div style={{
              position: 'absolute',
              left: s.x - 3, top: s.y - 3,
              width: s.w + 6, height: s.h + 6,
              borderRadius: s.r ? s.r + 3 : 3,
              border: `1.5px solid ${sc.replace(/[\d.]+\)$/, '0.50)')}`,
              boxShadow: `0 0 20px ${sc.replace(/[\d.]+\)$/, '0.22)')}, 0 0 6px ${sc.replace(/[\d.]+\)$/, '0.12)')}, inset 0 0 10px ${sc.replace(/[\d.]+\)$/, '0.08)')}`,
              pointerEvents: 'none',
              animation: 'rTeachPulse 2.4s ease-in-out 0.2s infinite',
              transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />

            {/* Tooltip card */}
            <div key={resultTeachStep} style={{
              position: 'absolute',
              top: s.tipY,
              left: cardLeft, right: cardRight,
              animation: 'rTeachCard 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) both',
            }}>
              {/* Animated border glow */}
              <div style={{
                position: 'absolute', inset: -1,
                borderRadius: 15,
                background: `conic-gradient(from var(--teach-border-angle, 0deg), ${sc.replace(/[\d.]+\)$/, '0.00)')}, ${sc.replace(/[\d.]+\)$/, '0.18)')}, ${sc.replace(/[\d.]+\)$/, '0.00)')}, ${sc.replace(/[\d.]+\)$/, '0.10)')}, ${sc.replace(/[\d.]+\)$/, '0.00)')})`,
                animation: 'rTeachBorder 4s linear infinite',
                opacity: 0.7,
                pointerEvents: 'none',
              }} />
              <div style={{
                position: 'relative',
                padding: '24px 28px 20px',
                borderRadius: 18,
                backgroundColor: 'rgba(10,11,14,0.92)',
                border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.08)')}`,
                boxShadow: [
                  '0 8px 32px rgba(0,0,0,0.55)',
                  '0 2px 8px rgba(0,0,0,0.35)',
                  `0 0 0 0.5px ${sc.replace(/[\d.]+\)$/, '0.06)')}`,
                  'inset 0 1px 0 rgba(255,255,255,0.07)',
                  'inset 0 -1px 0 rgba(0,0,0,0.2)',
                ].join(', '),
                backdropFilter: 'blur(20px) saturate(1.3)',
                WebkitBackdropFilter: 'blur(20px) saturate(1.3)',
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {/* Top: large text */}
                  <div>
                    <p style={{
                      margin: 0, fontSize: 22, fontWeight: 800, lineHeight: '26px',
                      color: 'rgba(245,247,250,0.96)', letterSpacing: '-0.4px',
                      ...FONT_SMOOTH,
                    }}>{s.title}</p>
                    <p style={{
                      margin: '6px 0 0', fontSize: 16, fontWeight: 500, lineHeight: '22px',
                      color: 'rgba(184,191,199,0.72)', ...FONT_SMOOTH,
                    }}>{s.desc}</p>
                  </div>
                  {/* Bottom row: icon + action */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Step icon */}
                  <div style={{
                    width: 52, height: 52, flexShrink: 0,
                    borderRadius: 14,
                    background: `linear-gradient(145deg, ${sc.replace(/[\d.]+\)$/, '0.14)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.03)')} 100%)`,
                    border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.16)')}`,
                    boxShadow: `inset 0 1px 0 ${sc.replace(/[\d.]+\)$/, '0.08)')}, 0 2px 6px rgba(0,0,0,0.25)`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    animation: 'rTeachFloat 3s ease-in-out infinite',
                  }}>
                    {resultTeachStep === 0 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'rTeachGlow 2s ease-in-out infinite' }}>
                        <circle cx="16" cy="16" r="10" stroke={sc.replace(/[\d.]+\)$/, '0.55)')} strokeWidth="1.8" fill="none" />
                        <path d="M12 16l3 3 5-6" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                      </svg>
                    )}
                    {resultTeachStep === 1 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'rTeachGlow 2s ease-in-out infinite' }}>
                        <circle cx="16" cy="16" r="6" stroke={sc.replace(/[\d.]+\)$/, '0.55)')} strokeWidth="1.8" fill="none" />
                        <path d="M16 6v4M16 22v4M6 16h4M22 16h4M9 9l3 3M20 20l3 3M9 23l3-3M20 12l3-3" stroke={sc.replace(/[\d.]+\)$/, '0.50)')} strokeWidth="1.4" strokeLinecap="round" />
                      </svg>
                    )}
                    {resultTeachStep === 2 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'rTeachGlow 2s ease-in-out infinite' }}>
                        <rect x="6" y="8" width="20" height="16" rx="2" stroke={sc.replace(/[\d.]+\)$/, '0.55)')} strokeWidth="1.8" fill="none" />
                        <path d="M10 14h4M10 18h8" stroke={sc.replace(/[\d.]+\)$/, '0.50)')} strokeWidth="1.4" strokeLinecap="round" />
                        <circle cx="22" cy="14" r="2" fill={sc.replace(/[\d.]+\)$/, '0.35)')} />
                      </svg>
                    )}
                    {resultTeachStep === 3 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'rTeachGlow 2s ease-in-out infinite' }}>
                        <path d="M16 6l-3 6h6l-3 6" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                        <path d="M8 22h16" stroke={sc.replace(/[\d.]+\)$/, '0.45)')} strokeWidth="1.6" strokeLinecap="round" />
                        <path d="M10 26h12" stroke={sc.replace(/[\d.]+\)$/, '0.30)')} strokeWidth="1.4" strokeLinecap="round" />
                      </svg>
                    )}
                  </div>

                  <div style={{ flex: 1 }} />
                  <div
                    onClick={(e) => { e.stopPropagation(); advanceResultTeach(); }}
                    style={{
                      flexShrink: 0, padding: '8px 18px', borderRadius: 10,
                      background: `linear-gradient(135deg, ${sc.replace(/[\d.]+\)$/, '0.16)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.06)')} 100%)`,
                      border: `1px solid ${sc.replace(/[\d.]+\)$/, resultTeachStep < 3 ? '0.18)' : '0.26)')}`,
                      boxShadow: `0 2px 8px rgba(0,0,0,0.3), inset 0 1px 0 ${sc.replace(/[\d.]+\)$/, '0.06)')}`,
                      cursor: 'pointer',
                    }}
                  >
                    <p style={{
                      margin: 0, fontSize: 16, fontWeight: 700, letterSpacing: '0.4px',
                      color: sc.replace(/[\d.]+\)$/, resultTeachStep < 3 ? '0.90)' : '0.95)'),
                      ...FONT_SMOOTH, whiteSpace: 'nowrap',
                    }}>{resultTeachStep < 3 ? 'Next →' : 'Got it →'}</p>
                  </div>
                </div>{/* close bottom row */}
                </div>{/* close two-row layout */}

                {/* Progress bar + skip */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  marginTop: 8,
                }}>
                  <div style={{
                    flex: 1, maxWidth: 80, height: 3, borderRadius: 2,
                    backgroundColor: 'rgba(255,255,255,0.05)',
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${((resultTeachStep + 1) / 4) * 100}%`,
                      height: '100%', borderRadius: 2,
                      background: `linear-gradient(90deg, ${sc.replace(/[\d.]+\)$/, '0.35)')}, ${sc.replace(/[\d.]+\)$/, '0.60)')})`,
                      transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1), background 0.5s ease',
                      boxShadow: `0 0 6px ${sc.replace(/[\d.]+\)$/, '0.20)')}`,
                    }} />
                  </div>
                  <span style={{
                    fontSize: 9, fontWeight: 600, letterSpacing: '0.5px',
                    color: sc.replace(/[\d.]+\)$/, '0.35)'),
                    marginLeft: 8, ...FONT_SMOOTH,
                  }}>{resultTeachStep + 1}/4</span>
                  <div style={{ flex: 1 }} />
                  {resultTeachStep < 3 && (
                    <button
                      onClick={(e) => { e.stopPropagation(); skipResultTeach(); }}
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0',
                        fontSize: 10, fontWeight: 600, color: steel(0.24),
                        WebkitTapHighlightColor: 'transparent', ...FONT_SMOOTH,
                      }}
                    >Skip</button>
                  )}
                </div>
              </div>
            </div>

            {/* Draw-on arrow */}
            <svg key={`rarrow-${resultTeachStep}`} style={{
              position: 'absolute', left: 0, top: svgTop,
              width: COL_W, height: svgH,
              pointerEvents: 'none', overflow: 'visible',
              filter: `drop-shadow(0 0 10px ${sc.replace(/[\d.]+\)$/, '0.35)')})`,
            }}>
              <path d={curvePath} stroke={sc.replace(/[\d.]+\)$/, '0.12)')}
                strokeWidth="8" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen} strokeDashoffset={curveLen}
                style={{ animation: 'rTeachDraw 0.7s cubic-bezier(0.4,0,0.2,1) 0.2s forwards' }} />
              <path d={curvePath} stroke={sc.replace(/[\d.]+\)$/, '0.75)')}
                strokeWidth="2.5" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen} strokeDashoffset={curveLen}
                style={{ animation: 'rTeachDraw 0.7s cubic-bezier(0.4,0,0.2,1) 0.25s forwards' }} />
              <path d={curvePath} stroke="rgba(255,255,255,0.12)"
                strokeWidth="1" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen} strokeDashoffset={curveLen}
                style={{ animation: 'rTeachDraw 0.7s cubic-bezier(0.4,0,0.2,1) 0.3s forwards' }} />
              {/* Arrowhead — slides from card base along curve to endpoint */}
              <style>{`
                @keyframes rTeachArrowSlide${resultTeachStep} {
                  0%   { opacity: 0.4; transform: translate(${cardCX - cx}px, ${startLY - endLY}px) scale(0.7); }
                  40%  { opacity: 1; }
                  100% { opacity: 1; transform: translate(0, 0) scale(1); }
                }
              `}</style>
              <g style={{
                opacity: 0,
                animation: `rTeachArrowSlide${resultTeachStep} 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.2s forwards`,
              }}>
                <g style={{ animation: 'rTeachBounce 1.4s ease-in-out 1.1s infinite' }}>
                  <circle cx={cx} cy={endLY} r="12" fill={sc.replace(/[\d.]+\)$/, '0.08)')} />
                  <path d={aPath} stroke={sc.replace(/[\d.]+\)$/, '0.95)')}
                    strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  <path d={aPath} stroke="rgba(255,255,255,0.22)"
                    strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                </g>
              </g>
            </svg>

            {/* Tap anywhere hint */}
            <p style={{
              position: 'absolute', bottom: 14, left: 0, right: 0,
              textAlign: 'center', margin: 0,
              fontSize: 10, fontWeight: 500, letterSpacing: '0.5px',
              color: steel(0.22), ...FONT_SMOOTH,
              animation: 'rTeachFade 0.6s ease 1s both',
              pointerEvents: 'none',
            }}>Tap anywhere to continue</p>
          </div>
        );
      })()}

      {/* Hero reveal — bridges the desaturated ProcessingScreen look to full color */}
      <style>{`
        @keyframes heroRevealLift {
          0%   { filter: brightness(0.82) saturate(0.50) contrast(0.92); opacity: 0.90; }
          100% { filter: brightness(1) saturate(1) contrast(1); opacity: 1; }
        }
      `}</style>

      {/* Result teach keyframes */}
      <style>{`
        @keyframes rTeachIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes rTeachOut { from { opacity: 1; } to { opacity: 0; pointer-events: none; } }
        @keyframes rTeachCard {
          0%   { opacity: 0; transform: translateY(16px) scale(0.96); }
          60%  { opacity: 1; transform: translateY(-3px) scale(1.01); }
          80%  { transform: translateY(1px) scale(1.0); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes rTeachFade { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes rTeachPulse {
          0%   { transform: scale(1); opacity: 0.85; }
          50%  { transform: scale(1.06); opacity: 1; }
          100% { transform: scale(1); opacity: 0.85; }
        }
        @keyframes rTeachBloom {
          0%   { transform: scale(1); opacity: 0.7; }
          50%  { transform: scale(1.15); opacity: 1; }
          100% { transform: scale(1); opacity: 0.7; }
        }
        @keyframes rTeachDraw { to { stroke-dashoffset: 0; } }
        /* rTeachArrowSlideN keyframes are generated inline per step */
        @keyframes rTeachBounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(3px); } }
        @keyframes rTeachFloat {
          0%   { transform: translateY(0) scale(1); filter: brightness(1); }
          50%  { transform: translateY(-5px) scale(1.12); filter: brightness(1.4); }
          100% { transform: translateY(0) scale(1); filter: brightness(1); }
        }
        @keyframes rTeachGlow {
          0%   { filter: drop-shadow(0 0 2px currentColor) brightness(1); }
          50%  { filter: drop-shadow(0 0 8px currentColor) brightness(1.3); }
          100% { filter: drop-shadow(0 0 2px currentColor) brightness(1); }
        }
        @property --teach-border-angle { syntax: '<angle>'; initial-value: 0deg; inherits: false; }
        @keyframes rTeachBorder { to { --teach-border-angle: 360deg; } }
      `}</style>

      {/* Home indicator — mobile only (desktop has no safe area bar) */}
      {!isDesktop && (
        <div style={{
          position: 'fixed', bottom: 8, left: '50%', transform: 'translateX(-50%)',
          width: 134, height: 5, borderRadius: 3,
          backgroundColor: 'rgba(89,94,107,0.55)',
          boxShadow: [
            'inset 0px 1px 1px 0px rgba(255,255,255,0.12)',
            'inset 0px -0.5px 0.5px 0px rgba(0,0,0,0.2)',
            '0px 0.5px 0px 0px rgba(255,255,255,0.03)',
            '0px -0.5px 1px 0px rgba(0,0,0,0.25)',
          ].join(', '),
          zIndex: 50,
        }} />
      )}

      {/* ─── Hero fullscreen overlay ───
          PORTALED to document.body — same reason as the diagram modal: the
          FitToViewport transform creates a new containing block for any
          fixed-position descendant, so without the portal a "fullscreen"
          overlay only fills the design viewport, not the real screen.  This
          overlay owns the zoom/pinch/pan handlers while it's active; the
          inline hero stays mounted but visibility-hidden so info-panel
          state is preserved across the round trip. */}
      {isZoomed && imagePreview && createPortal(
        <div
          onClick={() => exitZoom()}
          onTouchStart={handleZoomTouchStart}
          onTouchMove={handleZoomTouchMove}
          onTouchEnd={handleZoomTouchEnd}
          style={{
            position: 'fixed', inset: 0,
            backgroundColor: '#000',
            zIndex: 99,
            cursor: 'zoom-out',
            touchAction: 'none',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          <img
            src={imagePreview}
            alt="Result fullscreen"
            style={{
              // Fill the device height — portrait photos (majority of
              // portrait/beauty/fashion inputs) should occupy the full
              // screen height.  Width overflows and is pannable.
              height: '100dvh',
              width: 'auto',
              objectFit: 'contain',
              transform: `translate(${zoomPan.x}px, ${zoomPan.y}px) scale(${zoomScale})`,
              transformOrigin: 'center center',
              willChange: 'transform',
              userSelect: 'none',
              pointerEvents: 'none',
            }}
          />
          <button
            onClick={(e) => { e.stopPropagation(); exitZoom(); }}
            aria-label="Close"
            style={{
              position: 'absolute', top: 24, right: 28,
              width: 44, height: 44, borderRadius: 22,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'rgba(245,247,250,0.85)',
              fontSize: 22, fontWeight: 400, lineHeight: 1,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              ...FONT_SMOOTH,
            }}
          >×</button>
        </div>,
        document.body
      )}

      {/* ─── Diagram fullscreen modal ───
          Renders the LightingDiagram filling the viewport with a backdrop.
          Click the backdrop or the × to dismiss; Escape also closes.
          PORTALED to document.body so it escapes the FitToViewport
          `transform: scale()` ancestor — without the portal, `position:
          fixed` resolves to the scaled design viewport (1180-wide), not the
          actual screen, and the modal renders inside the design column
          instead of filling the visual viewport. */}
      {diagramFullscreen && createPortal(
        <div
          onClick={() => setDiagramFullscreen(false)}
          style={{
            position: 'fixed', inset: 0,
            backgroundColor: 'rgba(11,11,12,0.92)',
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 100,
            cursor: 'zoom-out',
          }}
        >
          {/* Close chevron */}
          <button
            onClick={(e) => { e.stopPropagation(); setDiagramFullscreen(false); }}
            style={{
              position: 'absolute', top: 24, right: 28,
              width: 44, height: 44, borderRadius: 22,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'rgba(245,247,250,0.85)',
              fontSize: 22, fontWeight: 400, lineHeight: 1,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              ...FONT_SMOOTH,
            }}
            aria-label="Close diagram"
          >×</button>
          {/* Fluid diagram — claims up to 92vw × 88vh preserving aspect.
              Wrapped in the canonical glass viewfinder layered stack (well +
              vignette + reflection + bevel) so the fullscreen zoom reads as
              the same machined viewport as the inline hero diagram, just at
              max scale.  Clicks on the viewfinder itself dismiss the zoom
              (no stopPropagation) so tapping anywhere minimizes. */}
          <div
            style={{
              position: 'relative',
              width: 'min(92vw, calc(88vh * 300/220))',
              height: 'min(88vh, calc(92vw * 220/300))',
              borderRadius: 20,
              backgroundColor: C.pillBg,
              boxShadow: 'inset 0px 3px 10px 0px rgba(0,0,0,0.7), inset 0px 1px 3px 0px rgba(0,0,0,0.5), inset 1px 0px 3px 0px rgba(0,0,0,0.4), inset -1px 0px 3px 0px rgba(0,0,0,0.4), 0 24px 80px rgba(0,0,0,0.7)',
              overflow: 'hidden',
              cursor: 'zoom-out',
            }}
          >
            <div style={{
              position: 'absolute', inset: 0,
              padding: '32px 36px',
              display: 'flex', justifyContent: 'center', alignItems: 'stretch',
              zIndex: 1,
            }}>
              {diagramView === 'top' ? (
                <LightingDiagram result={result} fluid />
              ) : (
                <SideViewDiagram result={result} fluid />
              )}
            </div>
            {/* View toggle in zoomed overlay */}
            <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 11, display: 'flex' }} onClick={e => e.stopPropagation()}>
              {['top', 'side'].map(v => (
                <button key={v} onClick={() => { setDiagramView(v); tapHaptic(); }} style={{
                  padding: '5px 14px', border: 'none', cursor: 'pointer',
                  background: diagramView === v
                    ? 'linear-gradient(141.71deg, #2a2218 0%, #1c1810 100%)'
                    : 'linear-gradient(141.71deg, #16181e 0%, #0e1014 100%)',
                  borderRadius: v === 'top' ? '7px 0 0 7px' : '0 7px 7px 0',
                  boxShadow: diagramView === v
                    ? `3px 3px 8px rgba(0,0,0,0.45), 0 0 0 0.5px rgba(200,155,60,0.25), inset 0 1px 0 rgba(200,155,60,0.10)`
                    : '2px 2px 5px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.03)',
                  fontSize: 10, fontWeight: 700, letterSpacing: '0.8px',
                  color: diagramView === v ? '#c89b45' : steel(0.35),
                  ...FONT_SMOOTH,
                }}>{v === 'top' ? 'TOP' : 'SIDE'}</button>
              ))}
            </div>
            {/* Glass overlay — home empty standard (no LENS_VIGNETTE on diagram panel) */}
            <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 20, pointerEvents: 'none', zIndex: 9 }}>
              <div style={{ position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0, background: GLASS_REFLECTION, borderRadius: 20, opacity: 0.72, transform: glassReflectionTransform(tilt), willChange: 'transform' }} />
            </div>
            {/* Inner-shadow bevel ring */}
            <div style={{
              position: 'absolute', inset: 0, borderRadius: 20,
              pointerEvents: 'none', boxShadow: VIEWFINDER_INNER_SHADOW, zIndex: 10,
            }} />
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 11, pointerEvents: 'none', borderRadius: '20px 20px 0 0',
              background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 11, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
            }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 11, pointerEvents: 'none', borderRadius: '0 0 20px 20px',
              background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
            }} />
            <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 11, pointerEvents: 'none',
              background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
            }} />
          </div>
        </div>,
        document.body
      )}

    </div>
    </div>
    </>
  );
}
