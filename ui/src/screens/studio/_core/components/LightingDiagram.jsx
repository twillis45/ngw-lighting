/**
 * LightingDiagram — Studio Matte top-down setup diagram
 *
 * Combines the compact SVG approach (from ShadowDiagram) with the rich
 * visual vocabulary from DiagramCard (light beams, distance badges, role colors).
 * Renders key light position, beam cone, shadow direction, camera, and
 * modifier/distance annotations — all in Studio Matte aesthetic.
 *
 * Props:
 *   result    — analysis result (needs ._raw.lighting_inference + .sections.modifier)
 *   compact   — boolean, smaller variant for inline use (default false)
 *   fluid     — boolean, render the SVG at 100% of its container so the
 *               diagram zooms with the viewport (default false)
 */
import { forwardRef, useRef, useImperativeHandle } from 'react';
import { steel, FONT_SMOOTH } from '../../../../theme/studioMatte';
import { exportSvgAsPng, exportSvgAsPdf } from '../../../../utils/exportSvg';

// ─── Role colors (from DiagramCard palette — dark theme) ─────────────────────
const KEY_COLOR      = '#c89b45';
const KEY_FAINT      = 'rgba(200,159,69,0.25)';
const KEY_BEAM       = 'rgba(200,159,69,0.22)';  // warm amber cone — must read on dark bg
const SHADOW_COLOR   = steel(0.55);              // lifted from 0.45 — shadow direction is primary signal

// ─── Clock-position → angle mapping ─────────────────────────────────────────
function clockToAngle(position) {
  if (!position) return null;
  const match = position.match(/(\d+)\s*o.?clock/i);
  if (!match) return null;
  const hour = parseInt(match[1], 10);
  // 12=0°, 1=30°, 2=60° … 11=330° (clockwise from top)
  return (hour % 12) * 30;
}

function sideToAngle(side, elevation) {
  const s = String(side).toLowerCase();
  const base = s.includes('right') ? 45 : s.includes('center') || s === 'on_axis' ? 0 : s.includes('left') ? -45 : 0;
  const elevAdj = elevation === 'high' ? -8 : elevation === 'low' ? 12 : 0;
  return base + elevAdj;
}

const LightingDiagram = forwardRef(function LightingDiagram({ result, compact = false, fluid = false, showExport = false, whiteLabel = false }, ref) {
  const svgRef = useRef(null);
  useImperativeHandle(ref, () => ({ getSvgElement: () => svgRef.current }));
  if (!result) return null;

  const raw = result._raw || {};
  const li  = raw.lighting_inference || {};
  const sd  = raw.signal_diagnostics || {};
  const mod = result.sections?.modifier;
  // Detected components from the engine's lighting_read pass — drives the
  // muted secondary fill/rim markers below.  `presence` is one of:
  //   subtle | soft | moderate | medium | strong | heavy | dominant
  // We translate that into an opacity so a "subtle" fill reads as a ghost
  // marker and a "dominant" fill is nearly as solid as the key.
  const components = result.sections?.shadowComponents || {};

  const keySide      = li.key_side || 'left';

  // Reconstruction-derived signals (preferred when available — these come
  // straight from the engine's pose-corrected estimate).
  const recon       = raw.reconstruction || {};

  // Elevation: reconstruction pass is authoritative; li.key_elevation is a fallback
  const keyElevation = recon.key_light_height || li.key_elevation || 'medium';
  // ⚠ Convention conversion — engine bug compensation.
  // The engine's `nose_shadow_angle_deg` is *usually* the centroid-derived
  // angle (vision_passes.py line 2962), measured as
  //   0° = shadow centroid BELOW nose, 90° = right, 180° = above, 270° = left.
  // The diagram below assumes the canonical shadow_pass convention:
  //   0° = up (back of head), 90° = right, 180° = down (toward camera), 270° = left.
  // The two are 180° apart, so a loop standard with the shadow correctly
  // falling lower-right of the nose was rendering as upper-left (e.g. the
  // 310° reading the user flagged).  We add 180° to map centroid → diagram.
  // If the engine ever standardizes to shadow_pass convention this single
  // line is the only place to revert.
  const _rawShadowDeg = sd.nose_shadow_angle_deg ?? sd.signals?.nose_shadow_angle_deg ?? null;
  const shadowDeg    = _rawShadowDeg != null ? ((_rawShadowDeg + 180) % 360) : null;
  // engine convention: 0–180, offset from camera axis (0 = on-axis, 90 = side)
  const reconKeyDeg = (typeof recon.key_light_angle_deg_pose_corrected === 'number'
    ? recon.key_light_angle_deg_pose_corrected
    : (typeof recon.key_light_angle_deg === 'number' ? recon.key_light_angle_deg : null));

  // ═══════════════════════════════════════════════════════════════════════
  // KEY LIGHT ANGLE — DEFINITIVE CONVENTION (DO NOT CHANGE WITHOUT TESTS)
  //
  // TOP-DOWN DIAGRAM LAYOUT:
  //   • Camera at BOTTOM (large Y), subject at CENTER
  //   • Background at TOP (small Y)
  //   • Positive angles = RIGHT of camera-subject axis
  //   • Negative angles = LEFT of camera-subject axis
  //   • 0° = directly behind camera (on-axis)
  //   • ±90° = perpendicular (side light)
  //   • ±180° = behind subject
  //
  // KEY POSITION FORMULA (from angle):
  //   kX = subX + kDist × sin(angle)   → positive angle → right
  //   kY = subY + kDist × cos(angle)   → 0° → below subject (camera side) ✓
  //
  // MODIFIER ORIENTATION (emission face → subject):
  //   _modRotRad = atan2(kX - subX, subY - kY)        ← CURRENT CORRECT FORMULA
  //   After SVG rotate(θ), local +Y maps to (-sin(θ), cos(θ)).
  //   Setting θ = atan2(kX-subX, subY-kY) makes +Y land on the key-to-subject
  //   direction, so the emission face (drawn at +Y) always faces the subject.
  //   DO NOT CHANGE TO atan2(kX-subX, -(subY-kY)) — that is the old BROKEN
  //   formula which points +Y away from the subject for off-axis keys.
  //
  // THREE INPUT SOURCES (priority order):
  //   1. Catchlight clock position (directly observed in iris)
  //   2. Reconstruction angle + key_side (inferred from shadow geometry)
  //   3. key_side coarse fallback
  // ═══════════════════════════════════════════════════════════════════════

  const clockPos    = mod?.position || (li.catchlight_intelligence?.primary_key?.position);
  const clockAngle  = clockToAngle(clockPos);

  const _ks = String(keySide).toLowerCase();
  const sign = _ks.includes('right')
    ? 1
    : _ks.includes('left')
      ? -1
      : (shadowDeg != null && shadowDeg > 180 ? -1 : 1);

  // Clock hour → diagram angle. Extracts the HORIZONTAL component only
  // using sin() — because the clock position encodes both direction AND
  // elevation, and the top-down diagram only shows direction.
  //
  //   sin(clock angle from 12) gives the left-right component:
  //     12 → sin(0°)=0 → 0° on-axis
  //      1 → sin(30°)=0.5 → 30° right
  //      2 → sin(60°)=0.87 → 60° right
  //      3 → sin(90°)=1.0 → 90° right (perpendicular)
  //      4 → sin(120°)=0.87 → 60° right  (NOT behind — same horizontal as 2)
  //      9 → sin(270°)=-1.0 → 90° left
  //     10 → sin(300°)=-0.87 → 60° left
  //
  // Result is always ±90° (camera-side hemisphere) because lights behind
  // the subject don't create catchlights in the iris.
  const clockToDiagram = (clockDeg) => {
    if (clockDeg == null) return null;
    const rad = clockDeg * Math.PI / 180;
    const horiz = Math.sin(rad);
    return Math.asin(Math.max(-1, Math.min(1, horiz))) * 180 / Math.PI;
  };

  let kAngleDeg;
  if (clockAngle != null) {
    kAngleDeg = clockToDiagram(clockAngle);
  } else if (reconKeyDeg != null) {
    // Engine convention: 0°=camera-facing (on-axis), 90°=side, 180°=behind
    // Diagram convention: 0°=camera-side (on-axis), ±90°=side, ±180°=behind
    // Mapping: direct pass-through with key_side sign.
    // Clamp to ±85° for standard portrait patterns — the engine's shadow
    // geometry can over-estimate off-axis angle on extreme low-key or
    // dark-skin images (e.g. 93.9° for what is visually a ~60° key).
    // No standard portrait pattern (loop, rembrandt, split, butterfly,
    // broad, short) places the key behind the subject. Rim/accent lights
    // can go past 90°, but those are rendered as separate markers.
    // Use geometric_base when available — it preserves the key geometry
    // even when a tonal overlay (low_key, high_key) is the authoritative pattern.
    // e.g. auth=low_key + geometric_base=rembrandt → use rembrandt for diagram.
    const _pat = (raw.geometric_base || raw.authoritative_pattern || '').toLowerCase();
    // Clamp by PHYSICS, not by name. This used to be an allow-list of eight
    // pattern names that got the clamp; anything unlisted rendered raw. The
    // enum carries 34 values, so 25 of them — `triangle` among them — fell
    // through and could draw a key BEHIND a front-lit subject. Measured:
    // `triangle` at 0.95 confidence rendered a 110° key, which no Hurley
    // triangle has ever used.
    //
    // Inverted: a key past 90° is only physical when the pattern IS a back,
    // rim or silhouette setup. Everything else is front-lit and clamps. New
    // enum values now default to the safe side instead of the raw side.
    const KEY_MAY_BE_BEHIND = ['rim', 'silhouette', 'backlight', 'negative_fill'];
    const keyMayBeBehind = KEY_MAY_BE_BEHIND.some(p => _pat.includes(p));
    const clamped = keyMayBeBehind ? reconKeyDeg : Math.min(reconKeyDeg, 85);
    kAngleDeg = sign * clamped;
  } else {
    kAngleDeg = sideToAngle(keySide, keyElevation);
  }

  // ─── Canvas dimensions ───────────────────────────────────────────────────
  // Compact mode uses a slightly wider aspect (220×150) so that at fluid
  // sizes the key light + distance annotations reach the canvas edges
  // instead of floating in dead space.  Full mode is unchanged.
  const W = compact ? 240 : 300;
  const H = compact ? 165 : 220;

  // Subject center — pulled up to leave room for the camera at the bottom
  // and the BG strip at the top.  Larger subR fills more of the canvas.
  const subX = W / 2;
  const subY = compact ? 68 : 90;
  const subR = compact ? 18 : 20;  // scaled down — human figure, not oversized

  // Camera — at the bottom of the canvas, looking UP at the subject (top-down
  // POV: camera is "in front of" the subject's face).
  const camY = H - (compact ? 16 : 22);

  // Background indicator — behind the subject (top of canvas).
  const bgY  = compact ? 12 : 16;

  // Key light position — farther from subject so the beam has real sweep.
  const kDist = compact ? 82 : 88;
  const kRad  = (kAngleDeg * Math.PI) / 180;
  const kX    = subX + kDist * Math.sin(kRad);
  const kY    = subY + kDist * Math.cos(kRad);

  // ── Modifier feathering ──────────────────────────────────────────────
  // Photographers feather the modifier so the subject catches the soft
  // EDGE of the light. The emission center aims slightly PAST the face
  // toward the camera side. Computed here so both the beam cone and the
  // modifier shape can share the same feathered orientation.
  const _featherDeg = (() => {
    const mf = (mod?.family || '').toLowerCase();
    const pat = (result?.pattern || '').toLowerCase();
    const isOnAxis = pat.includes('butterfly') || pat.includes('clamshell') || pat.includes('ring');
    if (isOnAxis) return 0;
    const isHardOff = pat.includes('split');
    const isSoftOff = pat.includes('loop') || pat.includes('rembrandt') || pat.includes('short') || pat.includes('broad');
    let f = isSoftOff ? 15 : isHardOff ? 8 : 10;
    // Larger/softer modifiers feather more
    if (mf.includes('oct') || (mf.includes('soft') && !mf.includes('strip') && !mf.includes('oct'))) f += 5;
    else if (mf.includes('strip')) f += 8;
    else if (mf.includes('beauty')) f += 3;
    else if (mf.includes('para') || mf.includes('umbr')) f -= 2;
    return Math.max(0, Math.min(28, f));
  })();
  // Feather swings emission PAST subject toward camera axis.
  // Key right of subject → CCW (negative). Key left → CW (positive).
  const featherSign = kX >= subX ? -1 : 1;
  const featherRad = (featherSign * _featherDeg) * Math.PI / 180;

  // Shadow direction — derived from the RENDERED key position so it always
  // makes physical sense.  The cast shadow falls in the opposite direction
  // from the key (in pixel space) and we bias it slightly toward the camera
  // (down) so it reads as a face-cast shadow rather than a back-cast.
  //
  // We deliberately ignore engine `nose_shadow_angle_deg` here because the
  // engine emits two competing conventions (centroid vs shadow_pass) that
  // collide for many setups; trusting the visual key direction makes the
  // diagram self-consistent regardless of which convention the engine used.
  const noseTipX = subX;
  const noseTipY = subY + subR + 4;
  // Vector pointing FROM key TO nose (i.e. light-travel direction).
  let shVecX = noseTipX - kX;
  let shVecY = noseTipY - kY;
  let shMag  = Math.hypot(shVecX, shVecY) || 1;
  shVecX /= shMag;
  shVecY /= shMag;
  // Camera-side bias — shadow always falls a bit toward the lens so the
  // arrow reads as "where you'll see the chin shadow on the photo".
  shVecY += 0.55;
  shMag = Math.hypot(shVecX, shVecY) || 1;
  shVecX /= shMag;
  shVecY /= shMag;
  // Convert vector → degrees in the local "0°=up, 90°=right" convention so
  // the SHADOW xx° readout below stays meaningful.
  const sDeg = ((Math.atan2(shVecX, -shVecY) * 180) / Math.PI + 360) % 360;
  const sRad = (sDeg * Math.PI) / 180;
  const sLen = compact ? 28 : 36;
  const sTipX = noseTipX + sLen * shVecX;
  const sTipY = noseTipY + sLen * shVecY;

  // Shadow arrowhead — built from the same unit vector so it always points
  // along the shadow line.
  const aLen = compact ? 4 : 5;
  const aWidth = compact ? 2.5 : 3;
  // Perpendicular unit vector for the arrowhead base.
  const perpX = -shVecY;
  const perpY =  shVecX;
  const arrX = sTipX + aLen * shVecX;
  const arrY = sTipY + aLen * shVecY;
  const arrowPts = [
    `${arrX},${arrY}`,
    `${sTipX - aWidth * perpX},${sTipY - aWidth * perpY}`,
    `${sTipX + aWidth * perpX},${sTipY + aWidth * perpY}`,
  ].join(' ');

  // ── Modifier rotation angle ──────────────────────────────────────────
  // Wide face is drawn at +Y in local coords. This angle makes +Y land
  // on the subject-facing side after SVG rotate(). Computed here so both
  // the beam and the modifier shape share the same feathered basis.
  const _modRotRad = Math.atan2(kX - subX, subY - kY);

  // Light beam cone — feathered to match modifier aim. The subject
  // catches the edge of the cone, not the center.
  const beamSpread = compact ? 20 : 26;
  const featheredModRad = _modRotRad + featherRad;
  // Beam base: project from key in the feathered emission direction
  // (+Y in rotated local = toward subject). In SVG the +Y offset after
  // rotation by θ lands at (-sin(θ), cos(θ)), so the beam direction is
  // (-sin(θ), cos(θ)) — which IS the key-to-subject direction.
  const beamDx = -Math.sin(featheredModRad);
  const beamDy =  Math.cos(featheredModRad);
  const beamReach = kDist - subR;
  const bX = kX + beamReach * beamDx;
  const bY = kY + beamReach * beamDy;
  // Perpendicular for beam spread
  const perpDx = -beamDy;
  const perpDy =  beamDx;
  const beamPts = [
    `${kX},${kY}`,
    `${bX + beamSpread * perpDx},${bY + beamSpread * perpDy}`,
    `${bX - beamSpread * perpDx},${bY - beamSpread * perpDy}`,
  ].join(' ');

  // Sun rays around key light
  const innerR = compact ? 10 : 13;
  const outerR = compact ? 16 : 22;
  const rays = [0, 45, 90, 135, 180, 225, 270, 315].map(deg => {
    const r = (deg * Math.PI) / 180;
    return {
      x1: kX + innerR * Math.sin(r), y1: kY - innerR * Math.cos(r),
      x2: kX + outerR * Math.sin(r), y2: kY - outerR * Math.cos(r),
    };
  });

  // Label positioning
  // Key label placement — push away from the modifier and avoid collisions
  // with the subject circle and camera zone.
  const keyLabelSide = kX > subX + 6 ? 'start' : 'end';
  const _keyLabelOffset = compact ? 20 : 26;
  let keyLabelX = kX > subX + 6 ? kX + _keyLabelOffset : kX - _keyLabelOffset;
  // Clamp to canvas bounds
  keyLabelX = Math.max(compact ? 4 : 6, Math.min(W - (compact ? 4 : 6), keyLabelX));
  // Push key label Y away from camera zone and subject
  const _keyLabelBaseY = kY;
  // Full-mode label stack height: KEY + angle + elevation + clock + modifier
  // = up to ~45px.  Compact: KEY + angle + elevation + distance = ~35px.
  const _labelStackH = compact ? 35 : 48;
  const _keyLabelY = (() => {
    let y = _keyLabelBaseY;
    // If label stack bottom overlaps camera zone, push up
    if (y + _labelStackH > camY - 8) y = camY - 8 - _labelStackH;
    // If label overlaps subject, push away vertically
    if (Math.abs(y - subY) < (compact ? 24 : 30) && Math.abs(kX - subX) < (compact ? 40 : 50)) {
      y = kY < subY ? subY - (compact ? 28 : 34) : subY + subR + (compact ? 16 : 20);
    }
    // Clamp to canvas top
    y = Math.max(compact ? 2 : 4, y);
    return y;
  })();

  // Steel alias — every alpha is bumped by ~0.18 with a floor at 0.42 so
  // the diagram reads on bright displays. The original dim 0.15–0.30 stops
  // disappeared on calibrated monitors; lifting them keeps the matte
  // hierarchy intact while making every glyph legible.
  const st = (a) => `rgba(132, 158, 184,${Math.min(1, Math.max(0.42, a + 0.18))})`;

  // Modifier label for full mode
  const modLabel = mod ? `${mod.sizeLabel ? mod.sizeLabel + ' ' : ''}${mod.family || ''}`.trim() : null;

  // Unique gradient ID suffix — prevents collision when compact + expanded diagrams
  // appear on the same page simultaneously (ResultScreen inline + fullscreen modal).
  const sfx = compact ? 'c' : 'f';

  // Lit-side bearing — direction from subject center toward key light.
  // Used for the head glow gradient and is pre-computed here so both the
  // defs block and the arc section can reference the same value.
  const litAngle = Math.atan2(kX - subX, -(kY - subY));

  // ─── Secondary lights (fill / rim / background) ───────────────────────────
  // The engine's lighting_read pass surfaces presence strings for fill and
  // rim; we render them as muted markers in canonical positions so the user
  // can SEE that the engine detected them, without claiming a measured angle
  // we don't actually have.
  // Threshold gate: ONLY render fill/rim markers when the engine reports a
  // moderate-or-stronger presence.  The engine's lighting_read pass is happy
  // to call any faint ambient bounce "subtle fill" — that's noise on a true
  // single-light setup like a loop-standard test image, and the user
  // shouldn't see a FILL marker materialize on a one-strobe portrait.  Faint
  // presences are still surfaced in the LIGHT COMPONENTS chip drawer for
  // engineering transparency, just not on the diagram itself.
  const presenceAlpha = (p) => {
    const v = String(p || '').toLowerCase();
    if (!v || v === 'none' || v === 'unknown' || v === 'subtle' || v === 'soft' || v === 'light') return 0;
    if (v === 'dominant' || v === 'strong' || v === 'heavy') return 0.85;
    if (v === 'moderate' || v === 'medium') return 0.62;
    return 0;
  };

  const FILL_COLOR     = 'rgba(130,170,220,1)';   // accent / cool — additive fill
  const NEG_FILL_COLOR = 'rgba(180,130,100,1)';   // warm muted — absorber/flag (subtractive)
  const RIM_COLOR  = 'rgba(180,205,235,1)';   // pale steel — reads as edge separation
  const BG_COLOR   = 'rgba(140,225,180,1)';   // soft green — matches success palette

  // FILL — gated on reconstruction.fill_present so we don't fabricate a fill
  // marker from the shallow shadowComponents pass alone.  The reconstruction
  // pass is authoritative; shadowComponents is a lower-fidelity hint.
  // fill_present === true  → show marker
  // fill_present === false → suppress entirely (engine says no fill)
  // fill_present === null  → only show if shadowComponents says strong/dominant
  //                          (moderate alone is ambient noise on single-light setups)
  // negative_fill === true → show NEG FILL marker with absorber styling
  const reconFillPresent = recon.fill_present;   // true | false | null
  const isNegFill = recon.negative_fill === true;
  const fillAlpha = (() => {
    if (reconFillPresent === false) return 0;
    if (reconFillPresent === true) return presenceAlpha(components.fill) || 0.62;
    // null: only render on strong/dominant signal, not moderate (avoids ambient noise)
    const p = String(components.fill || '').toLowerCase();
    if (p === 'dominant' || p === 'strong' || p === 'heavy') return 0.72;
    return 0;
  })();
  const fillX = subX - (kX - subX) * 0.80;
  // Fill sits in the camera-adjacent zone (physically correct — fill sources
  // are near the lens axis). This keeps it well below the shadow arrow which
  // always points into the subject/camera zone from the upper half.
  const fillY = camY - (compact ? 36 : 48);

  // RIM — behind the subject (above the head in top-down view), opposite the
  // key side so it reads as a back-rim hairlight.
  const rimAlpha = presenceAlpha(components.rim);
  const rimX = subX - (kX - subX) * 0.55;
  const rimY = subY - subR - (compact ? 14 : 20);

  // BACKGROUND — only when the engine reports a non-trivial background light
  // (not just a BG color cast).  We piggyback off the existing fill/rim
  // detection: if the lighting_inference has a `background_light_present`
  // signal we use it; otherwise we leave the marker off so the diagram
  // doesn't fabricate a light that isn't there.
  const bgAlpha = li.background_light_present || li.bg_light_present
    ? 0.55
    : 0;

  // Elevation is communicated by the HIGH/MED/LOW label in the key stack.
  // A previous iteration added a ⚠ warning glyph for high/low elevation,
  // but high key IS Rembrandt/butterfly and low key IS intentional dramatic —
  // flagging these as warnings contradicts the pattern identification and
  // patronizes working photographers.  Removed.

  // Camera height annotation — sourced from engine vision pass
  // (camera_height_relative_to_eyes: above | at_eye_level | below).
  const _camHeight = (
    raw.camera_height ||
    raw.geometry?.camera_height_relative_to_eyes ||
    raw.geometry_pass?.camera_height ||
    li.camera_height ||
    null
  );
  const camHeightLabel = _camHeight === 'above'        ? 'HIGH ANGLE'
                       : _camHeight === 'below'        ? 'LOW ANGLE'
                       : _camHeight === 'at_eye_level' ? 'EYE LEVEL'
                       : null;

  const pattern = result?.pattern || li.pattern || 'setup';

  return (
    <>
    <svg
      ref={svgRef}
      xmlns="http://www.w3.org/2000/svg"
      {...(fluid
        ? { width: '100%', height: '100%', preserveAspectRatio: 'xMidYMid meet' }
        : { width: W, height: H })}
      viewBox={`0 0 ${W} ${H}`}
      style={{
        display: 'block',
        margin: fluid ? 0 : (compact ? '12px auto 4px' : '0 auto'),
        overflow: 'visible',
        ...(fluid ? { width: '100%', height: '100%' } : null),
      }}
    >
      {/* ─── SVG gradient defs ─────────────────────────────────────────────
          All gradients use userSpaceOnUse so they reference the same pixel
          coordinates as the geometry computed above — no bounding-box math. */}
      <defs>
        {/* Beam cone: amber bloom at key source → fully transparent at subject.
            Replaces the flat KEY_BEAM fill so the cone reads as real photon
            travel rather than a painted shape. */}
        <linearGradient id={`beamGrad_${sfx}`}
          x1={kX} y1={kY} x2={bX} y2={bY} gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stopColor={KEY_COLOR} stopOpacity="0.70" />
          <stop offset="100%" stopColor={KEY_COLOR} stopOpacity="0" />
        </linearGradient>
        {/* Subject head lit-side glow: warm wash on the hemisphere facing
            the key — makes lit vs shadow instantly legible without text. */}
        <radialGradient id={`headLitGrad_${sfx}`}
          cx={subX + subR * 0.55 * Math.sin(litAngle)}
          cy={subY - subR * 0.55 * Math.cos(litAngle)}
          r={subR * 1.15}
          gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stopColor={KEY_COLOR} stopOpacity="0.34" />
          <stop offset="100%" stopColor={KEY_COLOR} stopOpacity="0" />
        </radialGradient>
        {/* Modifier emission: soft white bloom at the center of the modifier
            shape so it reads as a practical light source, not just a symbol. */}
        <radialGradient id={`modEmit_${sfx}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="rgba(255,248,220,1)" stopOpacity="0.60" />
          <stop offset="100%" stopColor="rgba(255,248,220,1)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* ─── Floor plan distance rings ─────────────────────────────────────
          Faint concentric circles centred on the subject reinforce the
          overhead / plan-view perspective — the same language used in pro
          lighting-diagram software and photography textbooks.  Rendered
          at the very bottom of the stack so all fixtures sit on top. */}
      {[0.50, 1.00].map((scale, i) => (
        <circle key={`floorRing${i}`}
          cx={subX} cy={subY}
          r={Math.round(kDist * scale)}
          fill="none"
          stroke={st(0.07 - i * 0.01)}
          strokeWidth={0.5}
          strokeDasharray="3,9"
        />
      ))}

      {/* Background indicator — rendered in both modes so the top-down
          scene reads as subject-between-background-and-camera.  Width is
          a canvas-relative constant so it visually anchors the top edge. */}
      {(() => {
        const bgHalf = compact ? 70 : 60;
        const bgH    = compact ? 8  : 10;
        const fontSz = compact ? 6  : 7;
        const bgDist = recon.background_distance_ft ?? sd.background_distance_ft;
        const bgDistLabel = bgDist != null ? `${bgDist} ft` : null;
        return (
          <>
            <rect
              x={subX - bgHalf} y={bgY - bgH / 2} width={bgHalf * 2} height={bgH} rx={3}
              fill="none" stroke={st(0.22)} strokeWidth={0.75}
            />
            <text x={subX} y={bgY + 2.5} textAnchor="middle"
              fill={st(0.38)} fontSize={fontSz} fontWeight="600" letterSpacing="0.8"
              fontFamily="Inter, system-ui, sans-serif">BG</text>
            {bgDistLabel && (
              <text x={subX + bgHalf - 4} y={bgY + 2.5} textAnchor="end"
                fill={st(0.32)} fontSize={compact ? 5.5 : 6.5} fontWeight="500" letterSpacing="0.3"
                fontFamily="Inter, system-ui, sans-serif">{bgDistLabel}</text>
            )}
          </>
        );
      })()}

      {/* Camera → subject axis (dashed) — lifted opacity so the compositional
          axis reads at all viewport scales without competing with the beam. */}
      <line
        x1={subX} y1={subY + subR + 2} x2={subX} y2={camY - (compact ? 7 : 10)}
        stroke={st(0.22)} strokeWidth={0.75} strokeDasharray="3,3"
      />

      {/* Light beam cone — gradient fill: bright amber source → transparent
          at subject surface so the cone reads as actual light travel. */}
      <polygon points={beamPts} fill={`url(#beamGrad_${sfx})`} />

      {/* Light beam center line — lifted opacity so the principal ray is
          clearly visible even when the beam cone is narrow. */}
      <line x1={kX} y1={kY} x2={bX} y2={bY}
        stroke="rgba(200,155,60,0.65)" strokeWidth={compact ? 1.8 : 2.2} />

      {/* Shadow direction line — dashed, originates from the nose tip so it
          reads as a cast shadow rather than a nose / face-direction arrow.
          Bumped strokeWidth so the shadow has visual weight comparable to
          the beam at expanded scale. */}
      <line x1={noseTipX} y1={noseTipY} x2={sTipX} y2={sTipY}
        stroke={SHADOW_COLOR} strokeWidth={1.8} strokeLinecap="round"
        strokeDasharray="2.5,2" />
      <polygon points={arrowPts} fill={SHADOW_COLOR} />
      {/* SHADOW label — merged with angle readout so the two annotations
          can never overlap or collide with the KEY marker.  The label sits
          past the arrow tip along the shadow direction so it stays clear
          of the subject head and the key light cluster. */}
      {(() => {
        const dx = Math.sin(sRad);
        const dy = -Math.cos(sRad);
        // Base position: past the arrow tip along shadow direction.
        let lx = sTipX + dx * 10;
        let ly = sTipY + dy * 10 + 2;
        // Collision avoidance — if the label would land near the KEY
        // marker or FILL marker, push it perpendicular so annotations
        // never stack on top of one another.
        const _pushAway = (targetX, targetY, threshold) => {
          const dist = Math.hypot(lx - targetX, ly - targetY);
          if (dist < threshold) {
            const px = -dy;
            const py = dx;
            const dot = px * (lx - targetX) + py * (ly - targetY);
            const sign = dot >= 0 ? 1 : -1;
            const off = compact ? 16 : 20;
            lx += sign * px * off;
            ly += sign * py * off;
          }
        };
        _pushAway(kX, kY, compact ? 22 : 28);       // KEY marker
        _pushAway(fillX, fillY, compact ? 18 : 22);  // FILL marker
        _pushAway(rimX, rimY, compact ? 16 : 20);    // RIM marker
        const anchor = dx >= 0.2 ? 'start' : dx <= -0.2 ? 'end' : 'middle';
        // Shadow label — direction is visually conveyed by the arrow itself;
        // the angle number was adding noise and colliding with the FILL marker.
        const labelText = `SHADOW`;
        return (
          <text
            x={lx} y={ly} textAnchor={anchor}
            fill={st(0.42)} fontSize={compact ? 5.5 : 6} fontWeight="600"
            letterSpacing="0.4"
            fontFamily="Inter, system-ui, sans-serif"
          >{labelText}</text>
        );
      })()}

      {/* ─── Secondary lights (rendered BEFORE the key so the key sits on top
              of any visual overlap, and BEFORE the subject so the subject head
              still occludes them at canvas center). ─── */}
      {fillAlpha > 0 && (() => {
        const fc = isNegFill ? NEG_FILL_COLOR : FILL_COLOR;
        const fillLabel = isNegFill ? 'NEG FILL' : 'FILL';
        return (
          <g opacity={fillAlpha}>
            <circle cx={fillX} cy={fillY} r={compact ? 5.5 : 7}
              fill="none" stroke={fc} strokeWidth={1}
              strokeDasharray={isNegFill ? '1,1.5' : '2,1.5'} />
            <circle cx={fillX} cy={fillY} r={compact ? 1.8 : 2.4} fill={fc} />
            <text x={fillX} y={fillY + (compact ? 12 : 14)} textAnchor="middle"
              fill={fc} fontSize={compact ? 5.5 : 6.5} fontWeight="700"
              letterSpacing="0.6" fontFamily="Inter, system-ui, sans-serif"
              opacity={0.85}
            >{fillLabel}</text>
          </g>
        );
      })()}
      {rimAlpha > 0 && (
        <g opacity={rimAlpha}>
          <circle cx={rimX} cy={rimY} r={compact ? 5 : 6.5}
            fill="none" stroke={RIM_COLOR} strokeWidth={1} strokeDasharray="2,1.5" />
          <circle cx={rimX} cy={rimY} r={compact ? 1.6 : 2.2} fill={RIM_COLOR} />
          <text x={rimX} y={rimY - (compact ? 7 : 9)} textAnchor="middle"
            fill={RIM_COLOR} fontSize={compact ? 5.5 : 6.5} fontWeight="700"
            letterSpacing="0.6" fontFamily="Inter, system-ui, sans-serif"
            opacity={0.9}
          >RIM</text>
        </g>
      )}
      {bgAlpha > 0 && (
        <g opacity={bgAlpha}>
          <circle cx={subX + (compact ? 26 : 32)} cy={bgY + (compact ? 12 : 16)}
            r={compact ? 4 : 5}
            fill="none" stroke={BG_COLOR} strokeWidth={1} strokeDasharray="2,1.5" />
          <circle cx={subX + (compact ? 26 : 32)} cy={bgY + (compact ? 12 : 16)}
            r={compact ? 1.4 : 1.8} fill={BG_COLOR} />
          <text x={subX + (compact ? 26 : 32)} y={bgY + (compact ? 23 : 28)}
            textAnchor="middle"
            fill={BG_COLOR} fontSize={compact ? 5.5 : 6.5} fontWeight="700"
            letterSpacing="0.6" fontFamily="Inter, system-ui, sans-serif"
            opacity={0.9}
          >BG LIGHT</text>
        </g>
      )}

      {/* Key light marker — modifier-shape-aware SIDE-VIEW profiles.
          Each shape is the recognisable silhouette a photographer sees
          looking at the modifier from the side: a softbox is a trapezoid
          (narrow mount → wide diffusion face), a beauty dish is a shallow
          concave bowl with a deflector plate, etc.  Rotated via kToSubDeg
          so the emission face always aims at the subject. */}
      {(() => {
        const mf = (mod?.family || '').toLowerCase();
        const isRect  = mf.includes('rect') || (mf.includes('soft') && !mf.includes('oct'));
        const isOct   = mf.includes('oct');
        const isBeauty = mf.includes('beauty');
        const isStrip = mf.includes('strip');
        const isRing  = mf.includes('ring');
        const isPara  = mf.includes('para') || mf.includes('umbr');

        // Modifier shape rotation — wide emission face drawn at +Y in local.
        // _modRotRad = atan2(kX-subX, subY-kY) makes +Y land on the
        // subject-facing side after SVG rotate(). Feathering offsets aim.
        const kToSubDeg = (_modRotRad + featherRad) * 180 / Math.PI;

        // Ambient glow halo (always)
        const halo = (
          <circle cx={kX} cy={kY} r={compact ? 18 : 24}
            fill="rgba(200,155,60,0.06)" stroke="none" />
        );

        // ── Side-view modifier silhouettes ──────────────────────────────
        // Convention: +Y (down in SVG local coords) = TOWARD SUBJECT after
        // kToSubDeg rotation. The emission face (wide end of a trapezoid,
        // open bowl) is drawn at +Y, the mount/back at −Y. This ensures
        // the wide face always renders on the subject-facing side regardless
        // of key angle quadrant.
        let modShape = null;
        if (isRect || isStrip) {
          // Softbox / strip side view: trapezoid
          const backW  = compact ? (isStrip ? 4 : 10) : (isStrip ? 5 : 12);
          const frontW = compact ? (isStrip ? 8 : 24) : (isStrip ? 10 : 32);
          const depth  = compact ? (isStrip ? 14 : 12) : (isStrip ? 18 : 16);
          const hd = depth / 2;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              <path d={`M ${kX - frontW/2} ${kY + hd} L ${kX - backW/2} ${kY - hd} L ${kX + backW/2} ${kY - hd} L ${kX + frontW/2} ${kY + hd} Z`}
                fill="rgba(200,155,60,0.16)" stroke={KEY_COLOR} strokeWidth={1.25} strokeOpacity={0.75} />
              {/* Diffusion face — bright front panel (+Y = toward subject) */}
              <line x1={kX - frontW/2 + 1} y1={kY + hd}
                    x2={kX + frontW/2 - 1} y2={kY + hd}
                stroke={KEY_COLOR} strokeWidth={1} strokeOpacity={0.55} />
              {/* Inner baffle — recessed diffusion layer */}
              <line x1={kX - frontW * 0.32} y1={kY + hd * 0.35}
                    x2={kX + frontW * 0.32} y2={kY + hd * 0.35}
                stroke={KEY_COLOR} strokeWidth={0.5} strokeOpacity={0.25} />
              {/* Mount stem at back (−Y = away from subject) */}
              <line x1={kX} y1={kY - hd}
                    x2={kX} y2={kY - hd - (compact ? 3 : 4)}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.28} />
            </g>
          );
        } else if (isOct) {
          const backW  = compact ? 10 : 13;
          const frontW = compact ? 26 : 34;
          const depth  = compact ? 12 : 16;
          const hd = depth / 2;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              <path d={`M ${kX - frontW/2} ${kY + hd} L ${kX - backW/2} ${kY - hd} L ${kX + backW/2} ${kY - hd} L ${kX + frontW/2} ${kY + hd} Z`}
                fill="rgba(200,155,60,0.16)" stroke={KEY_COLOR} strokeWidth={1.25} strokeOpacity={0.75} />
              {/* Diffusion face (+Y = toward subject) */}
              <line x1={kX - frontW/2 + 1} y1={kY + hd}
                    x2={kX + frontW/2 - 1} y2={kY + hd}
                stroke={KEY_COLOR} strokeWidth={1} strokeOpacity={0.55} />
              {/* Inner baffle */}
              <line x1={kX - frontW * 0.30} y1={kY + hd * 0.30}
                    x2={kX + frontW * 0.30} y2={kY + hd * 0.30}
                stroke={KEY_COLOR} strokeWidth={0.5} strokeOpacity={0.25} />
              {/* Mount stem (−Y = away) */}
              <line x1={kX} y1={kY - hd}
                    x2={kX} y2={kY - hd - (compact ? 3 : 4)}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.28} />
            </g>
          );
        } else if (isBeauty) {
          const dishW = compact ? 22 : 28;
          const dishD = compact ? 7 : 9;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              {/* Concave bowl — control points at −Y so concave faces +Y in local.
                  After kToSubDeg rotation, +Y = toward subject, giving the correct
                  orientation for all key positions. (Was: control at kY+dishD*1.4
                  which put concave at -Y → backwards after rotation.) */}
              <path d={`M ${kX - dishW/2} ${kY} C ${kX - dishW/4} ${kY - dishD * 1.4} ${kX + dishW/4} ${kY - dishD * 1.4} ${kX + dishW/2} ${kY}`}
                fill="rgba(200,155,60,0.12)" stroke={KEY_COLOR} strokeWidth={1.25} strokeOpacity={0.75} />
              {/* Back plate (at center) */}
              <line x1={kX - dishW/2} y1={kY}
                    x2={kX + dishW/2} y2={kY}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.4} />
              {/* Deflector plate inside the bowl */}
              <line x1={kX - (compact ? 3 : 4)} y1={kY + dishD * 0.55}
                    x2={kX + (compact ? 3 : 4)} y2={kY + dishD * 0.55}
                stroke={KEY_COLOR} strokeWidth={1.5} strokeOpacity={0.55} strokeLinecap="round" />
              {/* Mount stem (−Y = away from subject) */}
              <line x1={kX} y1={kY}
                    x2={kX} y2={kY - (compact ? 3 : 4)}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.28} />
            </g>
          );
        } else if (isRing) {
          const ringW = compact ? 24 : 32;
          const ringH = compact ? 3 : 4;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              <rect x={kX - ringW/2} y={kY - ringH/2} width={ringW} height={ringH} rx={1}
                fill="rgba(200,155,60,0.22)" stroke={KEY_COLOR} strokeWidth={1} strokeOpacity={0.6} />
              <rect x={kX - (compact ? 2.5 : 3)} y={kY - ringH/2 - 0.5} width={compact ? 5 : 6} height={ringH + 1}
                fill="#0a0a0d" stroke={KEY_COLOR} strokeWidth={0.5} strokeOpacity={0.3} />
              {/* Glow emission (+Y = toward subject) */}
              <line x1={kX - ringW/2 + 2} y1={kY + ringH/2}
                    x2={kX + ringW/2 - 2} y2={kY + ringH/2}
                stroke="rgba(255,248,220,0.25)" strokeWidth={0.75} />
            </g>
          );
        } else if (isPara) {
          const paraW = compact ? 24 : 32;
          const paraD = compact ? 14 : 18;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              {/* Deep parabolic curve — opens downward (+Y = toward subject) */}
              <path d={`M ${kX - paraW/2} ${kY} C ${kX - paraW/6} ${kY + paraD * 1.2} ${kX + paraW/6} ${kY + paraD * 1.2} ${kX + paraW/2} ${kY}`}
                fill="rgba(200,155,60,0.12)" stroke={KEY_COLOR} strokeWidth={1.25} strokeOpacity={0.65} />
              {/* Back plate */}
              <line x1={kX - paraW/2} y1={kY}
                    x2={kX + paraW/2} y2={kY}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.4} />
              {/* Umbrella shaft — from back plate through focal point */}
              <line x1={kX} y1={kY}
                    x2={kX} y2={kY + paraD * 0.65}
                stroke={KEY_COLOR} strokeWidth={0.5} strokeOpacity={0.3} />
              {/* Strobe head at focal point (inside the bowl) */}
              <rect x={kX - 2} y={kY + paraD * 0.55} width={4} height={3} rx={0.5}
                fill="rgba(200,155,60,0.35)" stroke={KEY_COLOR} strokeWidth={0.5} strokeOpacity={0.35} />
            </g>
          );
        } else {
          // Unknown modifier — generic reflector
          const genBack  = compact ? 6 : 8;
          const genFront = compact ? 16 : 20;
          const genD     = compact ? 8 : 10;
          const hd = genD / 2;
          modShape = (
            <g transform={`rotate(${kToSubDeg}, ${kX}, ${kY})`}>
              <path d={`M ${kX - genFront/2} ${kY + hd} L ${kX - genBack/2} ${kY - hd} L ${kX + genBack/2} ${kY - hd} L ${kX + genFront/2} ${kY + hd} Z`}
                fill="rgba(200,155,60,0.12)" stroke={KEY_COLOR} strokeWidth={1} strokeOpacity={0.5} />
              {/* Mount stem (−Y = away) */}
              <line x1={kX} y1={kY - hd}
                    x2={kX} y2={kY - hd - 3}
                stroke={KEY_COLOR} strokeWidth={0.75} strokeOpacity={0.25} />
            </g>
          );
        }

        return (
          <>
            {halo}
            {modShape}
            {/* Emission bloom — soft white radial over the modifier center so
                every shape reads as a live light source, not a schematic icon. */}
            <circle cx={kX} cy={kY} r={compact ? 8 : 11} fill={`url(#modEmit_${sfx})`} />
            {/* Amber center dot — the bulb / flash tube */}
            <circle cx={kX} cy={kY} r={compact ? 2.5 : 3.5} fill={KEY_COLOR} />
            {/* Inner hot-spot — the brightest point mimics the actual
                emission center / bare bulb of a strobe or LED panel. */}
            <circle cx={kX} cy={kY} r={compact ? 1.1 : 1.5} fill="rgba(255,250,230,0.95)" />
          </>
        );
      })()}

      {/* Elevation warning glyph removed — see comment above. */}

      {/* Subject head */}
      <circle cx={subX} cy={subY} r={subR}
        fill="#0a0a0d" stroke={st(0.60)} strokeWidth={1.5} />
      {/* Lit-side warmth overlay — radial gradient wash from the key-facing
          hemisphere so the head reads as physically illuminated before the
          eye even reaches the arc indicators. */}
      <circle cx={subX} cy={subY} r={subR} fill={`url(#headLitGrad_${sfx})`} />
      {/* Lit/shadow side arcs — amber on key side, cool dark on shadow side.
          Dual-indicator lets a photographer read the face instantly. */}
      {(() => {
        const litAngle = Math.atan2(kX - subX, -(kY - subY));
        const r2 = subR + 0.5;
        const arcSpan = 1.05;
        // Lit arc
        const lx1 = subX + r2 * Math.sin(litAngle - arcSpan);
        const ly1 = subY - r2 * Math.cos(litAngle - arcSpan);
        const lx2 = subX + r2 * Math.sin(litAngle + arcSpan);
        const ly2 = subY - r2 * Math.cos(litAngle + arcSpan);
        // Shadow arc — opposite side
        const shAng = litAngle + Math.PI;
        const sx1 = subX + r2 * Math.sin(shAng - arcSpan);
        const sy1 = subY - r2 * Math.cos(shAng - arcSpan);
        const sx2 = subX + r2 * Math.sin(shAng + arcSpan);
        const sy2 = subY - r2 * Math.cos(shAng + arcSpan);
        return (
          <>
            {/* Shadow arc — cool steel blue, slightly wider stroke so it
                reads as "dark side" against the warm lit arc. */}
            <path d={`M ${sx1} ${sy1} A ${r2} ${r2} 0 0 1 ${sx2} ${sy2}`}
              fill="none" stroke="rgba(60,90,160,0.58)" strokeWidth={2.8} strokeLinecap="round" />
            {/* Lit arc — warm amber; placed on top of shadow arc so the
                bright side always wins visually. */}
            <path d={`M ${lx1} ${ly1} A ${r2} ${r2} 0 0 1 ${lx2} ${ly2}`}
              fill="none" stroke="rgba(200,155,60,0.85)" strokeWidth={2.8} strokeLinecap="round" />
          </>
        );
      })()}
      {/* Nose pointer — orientation anchor in plan view.  Tapered triangle
          toward camera (chin/nose direction) so a photographer instantly
          reads "face pointing at camera".  Slightly larger and brighter
          in full mode for legibility at expanded scale. */}
      <polygon
        points={`${subX - (compact ? 3 : 4)},${subY + subR - (compact ? 5 : 6)} ${subX + (compact ? 3 : 4)},${subY + subR - (compact ? 5 : 6)} ${subX},${subY + subR + (compact ? 5 : 7)}`}
        fill={st(0.65)}
      />
      {/* Hairline centre axis on the head — reinforces plan-view symmetry and
          gives a calibration line for reading the lit-arc positions. */}
      <line
        x1={subX} y1={subY - subR + 4}
        x2={subX} y2={subY + subR - 4}
        stroke={st(0.12)} strokeWidth={0.5}
      />
      {/* SUBJECT label removed — photographers read the human silhouette instantly */}

      {/* Camera icon — body + pentaprism for recognition at compact and fullscreen scales. */}
      <rect x={subX - 9} y={camY - 6} width={18} height={12} rx={2}
        fill="none" stroke={st(0.38)} strokeWidth={1} />
      <rect x={subX - 2.5} y={camY - 10} width={5} height={5} rx={1}
        fill="none" stroke={st(0.30)} strokeWidth={0.75} />

      {/* ─── Labels ─── */}

      {/* KEY label */}
      <text x={keyLabelX} y={_keyLabelY + (compact ? 4 : 5)} textAnchor={keyLabelSide}
        fill={st(0.55)} fontSize={compact ? 7 : 8} fontWeight="700" letterSpacing="0.8"
        fontFamily="Inter, system-ui, sans-serif">KEY</text>
      {reconKeyDeg != null && (
        <text x={keyLabelX} y={_keyLabelY + (compact ? 13 : 15)} textAnchor={keyLabelSide}
          fill={st(0.40)} fontSize={compact ? 6 : 7} fontWeight="600" letterSpacing="0.3"
          fontFamily="Inter, system-ui, sans-serif">{Math.round(180 - reconKeyDeg)}°</text>
      )}
      {(() => {
        const elev = (keyElevation || '').toLowerCase();
        const isMed = elev === 'medium' || elev === 'mid' || !elev || elev === 'unknown';
        const showElev = !isMed || !compact;
        const elevLabel = elev === 'high' ? 'HIGH' : elev === 'low' ? 'LOW' : 'MED';
        const elevColor = elev === 'high' ? 'rgba(245,190,72,0.85)'
                        : elev === 'low'  ? 'rgba(120,170,220,0.80)'
                        : st(0.38);
        const _sp = compact ? 9 : 10;
        const angleRow = reconKeyDeg != null;
        // Stack: KEY (row 0) → angle° (row 1 if present) → elevation (row 2) → distance (row 3 compact only)
        let y = _keyLabelY + (compact ? 4 : 5); // KEY row baseline
        if (angleRow) y += _sp;
        y += _sp; // elevation row
        const distLabel = mod?.distRange;
        return (
          <>
            {showElev && (
              <text x={keyLabelX} y={y} textAnchor={keyLabelSide}
                fill={elevColor} fontSize={compact ? 5.5 : 6.5} fontWeight="700" letterSpacing="0.5"
                fontFamily="Inter, system-ui, sans-serif">{elevLabel}</text>
            )}
            {compact && distLabel && (
              <text x={keyLabelX} y={y + (showElev ? _sp : 0)} textAnchor={keyLabelSide}
                fill={st(0.38)} fontSize={compact ? 5.5 : 6.5} fontWeight="500" letterSpacing="0.3"
                fontFamily="Inter, system-ui, sans-serif">{distLabel}</text>
            )}
          </>
        );
      })()}

      {/* CAM label */}
      <text x={subX} y={camY + (compact ? 11 : 14)} textAnchor="middle"
        fill={st(0.30)} fontSize={compact ? 7 : 8} fontWeight="600" letterSpacing="0.5"
        fontFamily="Inter, system-ui, sans-serif">CAM</text>

      {/* Camera height annotation — derived from analysis */}
      {!compact && camHeightLabel && (
        <text x={subX} y={camY + 23} textAnchor="middle"
          fill={st(0.45)} fontSize={6.5} fontWeight="500" letterSpacing="0.4"
          fontFamily="Inter, system-ui, sans-serif">{camHeightLabel}</text>
      )}

      {/* Angle readout is now merged into the SHADOW label above so the
          two never stack on top of each other. */}

      {/* ─── Full-mode annotations — limited to avoid overlap ─── */}
      {!compact && (
        <>
          {/* Clock position — below elevation stack */}
          {clockPos && (
            <text
              x={keyLabelX}
              y={_keyLabelY + 5 + (reconKeyDeg != null ? 10 : 0) + 10 + 10}
              textAnchor={keyLabelSide}
              fill={st(0.40)} fontSize={7} fontWeight="500"
              fontFamily="Inter, system-ui, sans-serif"
            >{clockPos}</text>
          )}
          {modLabel && (
            <text
              x={keyLabelX}
              y={_keyLabelY + 5 + (reconKeyDeg != null ? 10 : 0) + 10 + (clockPos ? 20 : 10)}
              textAnchor={keyLabelSide}
              fill={st(0.35)} fontSize={6.5} fontWeight="500"
              fontFamily="Inter, system-ui, sans-serif"
            >{modLabel}</text>
          )}

          {/* Distance annotation — dashed line along the margin OPPOSITE
              the key light, so the modifier label and distance never overlap. */}
          {mod?.distRange && (() => {
            const keyOnLeft = kX < subX;
            const distX = keyOnLeft ? W - 20 : 20;
            const topY = subY;
            const botY = camY - 8;
            const midY = (topY + botY) / 2;
            return (
              <>
                <line x1={distX} y1={topY + 10} x2={distX} y2={midY - 8}
                  stroke={st(0.28)} strokeWidth={0.75} strokeDasharray="2,2" />
                <line x1={distX} y1={midY + 8} x2={distX} y2={botY - 4}
                  stroke={st(0.28)} strokeWidth={0.75} strokeDasharray="2,2" />
                {/* Arrowheads */}
                <polygon
                  points={`${distX},${topY + 6} ${distX - 3},${topY + 12} ${distX + 3},${topY + 12}`}
                  fill={st(0.32)} />
                <polygon
                  points={`${distX},${botY - 2} ${distX - 3},${botY - 8} ${distX + 3},${botY - 8}`}
                  fill={st(0.32)} />
                {/* Distance text */}
                <text x={distX} y={midY + 3} textAnchor="middle"
                  fill={st(0.40)} fontSize={7} fontWeight="600"
                  fontFamily="Inter, system-ui, sans-serif"
                >{mod.distRange}</text>
              </>
            );
          })()}

          {/* Subject label removed — the head circle is self-explanatory to photographers */}
        </>
      )}
    </svg>
    {showExport && (
      <div style={{
        display: 'flex', justifyContent: 'flex-end', padding: '4px 8px 0',
      }}>
        <button onClick={() => {
          const d = new Date();
          const date = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
          const name = `NGW_${(pattern || 'diagram').replace(/\s+/g, '_')}_top-down_${date}`;
          exportSvgAsPng(svgRef.current, name, whiteLabel);
        }} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          padding: 6, opacity: 0.35,
          WebkitTapHighlightColor: 'transparent',
          transition: 'opacity 0.15s ease',
        }}
        onMouseEnter={e => e.currentTarget.style.opacity = '0.7'}
        onMouseLeave={e => e.currentTarget.style.opacity = '0.35'}
        title="Download diagram PNG"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={steel(0.65)} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </button>
      </div>
    )}
    </>
  );
});

export default LightingDiagram;
