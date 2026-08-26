/**
 * socialCanvas.js — Viral-grade social export for No Guesswork Lighting.
 *
 * Design goals: stop the scroll, reward the save, drive the share.
 * Typography is NEVER monotone — every card mixes huge vs micro, colored vs white.
 * Role colors carry real meaning: warm amber = key (strobe warmth), steel = fill, green = rim.
 *
 * Color source of truth: socialTokens.js (mirrored in Figma "Social Card Tokens" variables).
 */
// v2 — ghost clip, logo lockup, right-aligned brand
import { TOKENS } from './socialTokens.js';

export const FORMATS = {
  STORY:     { w: 1080, h: 1920, label: 'Story (9:16)' },
  SQUARE:    { w: 1080, h: 1080, label: 'Square (1:1)' },
  PORTRAIT:  { w: 1080, h: 1350, label: 'Portrait (4:5)' },
  LANDSCAPE: { w: 1920, h: 1080, label: 'Landscape (16:9)' },
};

export const PREVIEW_FORMATS = {
  STORY:    { w: 540, h: 960,  label: 'Story (9:16)' },
  SQUARE:   { w: 540, h: 540,  label: 'Square (1:1)' },
  PORTRAIT: { w: 540, h: 675,  label: 'Portrait (4:5)' },
};

// ── Color system — sourced from socialTokens.js / Figma "Social Card Tokens" ─
const BG       = TOKENS.surface.base;     // '#09090b'
const SURFACE  = TOKENS.surface.elevated; // '#111218'
const SURFACE2 = TOKENS.surface.premium;  // '#191b24'
const TEXT     = 'rgba(248,249,252,0.96)';
const TEXT_MID = 'rgba(248,249,252,0.60)';
const TEXT_DIM = 'rgba(132,158,184,0.45)';
const FONT     = '"Geist", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

// Confidence: green → steel → dim steel (Studio Matte: cool/neutral tiers, no warm amber)
function confColor(c) {
  if (c >= 0.75) return TOKENS.confidence.high;  // '#48ba88' — green, cool
  if (c >= 0.50) return 'rgba(132,158,184,0.90)'; // steel — moderate confidence
  return 'rgba(132,158,184,0.50)';                 // dim steel — low confidence
}

// Role identity colors — semantic, not decorative
function roleColor(r) {
  r = (r || '').toLowerCase();
  if (r === 'key')  return TOKENS.role.key;   // '#d4a054' warm amber
  if (r === 'fill') return TOKENS.role.fill;  // '#7da3c8' steel blue
  if (r === 'rim' || r === 'hair' || r === 'kicker') return TOKENS.role.rim;  // '#48ba88'
  if (r === 'background' || r === 'bg') return TOKENS.role.bg;  // '#d47240'
  return 'rgba(132,158,184,0.55)';
}

function capitalize(str) {
  return String(str || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
function f(sz, S) { return `${Math.round(sz * S)}px`; }
function px(sz, S) { return Math.round(sz * S); }

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawDivider(ctx, y, x1, x2, alpha = 0.10) {
  ctx.strokeStyle = `rgba(132,158,184,${alpha})`;
  ctx.lineWidth   = 1;
  ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
}

// Animation: smoothstep 0→1 for section starting at t0 and ending at t1 (within 0–1 progress)
function sect(progress, t0, t1) {
  const raw = Math.max(0, Math.min(1, (progress - t0) / Math.max(0.001, t1 - t0)));
  return raw * raw * (3 - 2 * raw);
}

// Micro label — tracked uppercase, muted. Used for section headers, sublabels.
function micro(ctx, x, y, text, S, opts = {}) {
  const { color = TEXT_DIM, size = 13, align = 'left', tracking = 2 } = opts;
  ctx.save();
  ctx.font = `700 ${f(size, S)} ${FONT}`;
  ctx.fillStyle = color; ctx.textAlign = align;
  ctx.letterSpacing = `${px(tracking, S)}px`;
  ctx.fillText(text.toUpperCase(), x, y);
  ctx.restore();
}

// Logo mark — reproduces static/www/img/logo.svg in canvas 2D (no async load needed)
function drawLogoMark(ctx, ox, oy, sz, color) {
  const sc = sz / 48;
  ctx.save();
  ctx.translate(ox, oy);
  ctx.scale(sc, sc);
  ctx.strokeStyle = color;
  ctx.fillStyle   = color;
  ctx.lineJoin = 'round';
  ctx.lineCap  = 'round';
  // Rounded rect frame
  ctx.lineWidth = 2;
  roundRect(ctx, 4, 4, 40, 40, 12);
  ctx.stroke();
  // V chevron
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.moveTo(18, 14); ctx.lineTo(24, 34); ctx.lineTo(30, 14);
  ctx.stroke();
  // Apex dot
  ctx.beginPath();
  ctx.arc(24, 14, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawBrand(ctx, w, y, branded, S) {
  if (!branded) return;
  const color   = 'rgba(132,158,184,0.65)';
  const markSz  = px(20, S);
  const gap     = px(7, S);
  const rightPad = px(48, S);
  ctx.save();
  ctx.font = `600 ${f(11, S)} ${FONT}`;
  ctx.letterSpacing = `${px(0.5, S)}px`;
  const tw = ctx.measureText('NO GUESSWORK LIGHTING').width;
  const ox = w - rightPad - markSz - gap - tw;
  const midY = y;
  drawLogoMark(ctx, ox, midY - markSz / 2, markSz, color);
  ctx.fillStyle   = color;
  ctx.textAlign   = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText('NO GUESSWORK LIGHTING', ox + markSz + gap, midY);
  ctx.restore();
}

// Face-biased cover-fill. cropAnchorY: 0=top 0.5=center 1=bottom. 0.18 shows face for portraits.
function drawPhotoCover(ctx, photo, x, y, w, h, cropAnchorY = 0.25) {
  if (!photo) return false;
  const asp = photo.naturalWidth / photo.naturalHeight;
  let dw = w, dh = w / asp;
  if (dh < h) { dh = h; dw = h * asp; }
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.drawImage(photo, x + (w - dw) / 2, y + (h - dh) * cropAnchorY, dw, dh);
  ctx.restore();
  return true;
}

function drawPhotoFade(ctx, bottomY, w, fadeH) {
  const g = ctx.createLinearGradient(0, bottomY - fadeH, 0, bottomY);
  g.addColorStop(0, 'rgba(9,9,11,0)');
  g.addColorStop(1, BG);
  ctx.fillStyle = g; ctx.fillRect(0, bottomY - fadeH, w, fadeH);
}

// Confidence block: large % number + "CONFIDENCE" micro label + bar below.
// Returns height consumed.
function drawConfBlock(ctx, x, y, w, confidence, S, opts = {}) {
  const { align = 'left', compact = false } = opts;
  const pct = Math.round((confidence || 0) * 100);
  const cc  = confColor(confidence);
  const ax  = align === 'center' ? x + w / 2 : x;

  ctx.textAlign = align;

  if (compact) {
    // Inline: "42% confidence" on one line
    ctx.font      = `700 ${f(22, S)} ${FONT}`;
    ctx.fillStyle = cc;
    ctx.fillText(`${pct}%`, ax, y);
    const pctW = ctx.measureText(`${pct}%`).width;
    ctx.save();
    ctx.font = `500 ${f(20, S)} ${FONT}`;
    ctx.fillStyle = TEXT_DIM;
    ctx.textAlign = 'left';
    ctx.fillText(' confidence', (align === 'center' ? ax - pctW / 2 : ax) + pctW, y);
    ctx.restore();
    return px(28, S);
  }

  // Large: big number + micro label + bar
  ctx.save();
  ctx.shadowColor = cc;
  ctx.shadowBlur  = px(12, S);
  ctx.font        = `800 ${f(58, S)} ${FONT}`;
  ctx.fillStyle   = cc;
  ctx.fillText(`${pct}%`, ax, y);
  ctx.restore();

  micro(ctx, ax, y + px(10, S), 'Confidence', S, { color: TEXT_DIM, size: 13, align, tracking: 2 });

  // Thin bar
  const barY = y + px(26, S);
  const barW = align === 'center' ? Math.round(w * 0.55) : w;
  const barX = align === 'center' ? ax - barW / 2 : ax;
  const r = px(2, S);
  roundRect(ctx, barX, barY, barW, px(3, S), r);
  ctx.fillStyle = 'rgba(132,158,184,0.10)'; ctx.fill();
  const fw = Math.max(px(8, S), Math.round(barW * Math.min(confidence, 1)));
  roundRect(ctx, barX, barY, fw, px(3, S), r);
  ctx.fillStyle = cc; ctx.fill();

  return px(46, S);
}

// Light row with colored dot + role label + detail + optional kelvin. Returns height consumed.
function drawLightRow(ctx, x, y, light, S) {
  const rc     = roleColor(light.role);
  const role   = (light.role || 'light').toUpperCase();
  const mod    = light.modifier_label || light.modifier || '';
  const pos    = (light.position_label || light.position || '').replace(/-/g, ' ');
  const dist   = light.distance_m != null ? `${(light.distance_m * 3.281).toFixed(0)} ft` : '';
  const detail = [mod, pos, dist].filter(Boolean).join('  ·  ');

  // Colored dot
  ctx.beginPath();
  ctx.arc(x, y - px(3, S), px(5, S), 0, Math.PI * 2);
  ctx.fillStyle = rc; ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1;

  const tx = x + px(18, S);

  // Role label — colored, tracked
  ctx.save();
  ctx.font = `700 ${f(14, S)} ${FONT}`;
  ctx.fillStyle = rc; ctx.textAlign = 'left';
  ctx.letterSpacing = `${px(1.5, S)}px`;
  ctx.fillText(role, tx, y);

  // Kelvin inline — muted warm tint, after role label
  if (light.kelvin) {
    const roleW = ctx.measureText(role).width;
    ctx.font = `500 ${f(13, S)} ${FONT}`;
    ctx.fillStyle = 'rgba(212,160,84,0.50)';
    ctx.letterSpacing = `${px(0.5, S)}px`;
    ctx.fillText(`${Math.round(light.kelvin)}K`, tx + roleW + px(10, S), y);
  }
  ctx.restore();

  if (detail) {
    ctx.font      = `400 ${f(32, S)} ${FONT}`;
    ctx.fillStyle = TEXT; ctx.textAlign = 'left';
    ctx.fillText(detail, tx, y + px(34, S));

    // Catchlight modifier note — italic, dimmer, only when detected
    if (light.catchlight_modifier && typeof light.catchlight_modifier === 'string') {
      const clLabel = `catchlight: ${light.catchlight_modifier.replace(/_/g, ' ')}`;
      ctx.font      = `400 ${f(22, S)} ${FONT}`;
      ctx.fillStyle = 'rgba(132,158,184,0.45)';
      ctx.fillText(clLabel, tx, y + px(64, S));
      return px(88, S);
    }
    return px(66, S);
  }
  return px(24, S);
}

// Overhead diagram with role-colored lights.
function drawOverheadDiagram(ctx, x, y, w, h, lights, S) {
  const cx = x + w / 2, cy = y + h * 0.50;
  const r  = Math.min(w * 0.38, h * 0.40);

  ctx.strokeStyle = 'rgba(132,158,184,0.10)'; ctx.lineWidth = px(1, S);
  roundRect(ctx, x, y, w, h, px(12, S)); ctx.stroke();

  micro(ctx, w / 2 + x - w / 2, y + px(20, S), 'Overhead View', S,
    { color: 'rgba(132,158,184,0.20)', size: 12, align: 'center', tracking: 2.5 });

  [1, 0.50].forEach(sc => {
    ctx.strokeStyle = `rgba(132,158,184,${sc === 1 ? 0.08 : 0.04})`;
    ctx.lineWidth   = px(1, S);
    ctx.beginPath(); ctx.arc(cx, cy, r * sc, 0, Math.PI * 2); ctx.stroke();
  });

  // Subject
  ctx.beginPath(); ctx.arc(cx, cy, px(5, S), 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(248,249,252,0.55)'; ctx.fill();

  // Camera
  const camY = cy + r * 0.72, cs = px(7, S);
  ctx.beginPath();
  ctx.moveTo(cx, camY - cs); ctx.lineTo(cx - cs, camY + cs * 0.7); ctx.lineTo(cx + cs, camY + cs * 0.7);
  ctx.closePath();
  ctx.fillStyle = 'rgba(132,158,184,0.30)'; ctx.fill();
  micro(ctx, cx, camY + px(17, S), 'cam', S, { color: 'rgba(132,158,184,0.22)', size: 10, align: 'center', tracking: 1 });

  lights.forEach(l => {
    const lc  = roleColor(l.role);
    const pos = (l.position_label || '').toLowerCase();
    let deg;
    if (l.role === 'fill') {
      const key = lights.find(k => k.role === 'key');
      const kp  = (key?.position_label || '').toLowerCase();
      if (key?.angle_deg != null && (kp.includes('right') || kp.includes('left'))) {
        // Mirror the key's angle onto the opposite side for fill placement
        const kMag = Math.min(key.angle_deg, 85);
        deg = kp.includes('right') ? 360 - kMag : kMag;
      } else {
        deg = kp.includes('right') ? 300 : kp.includes('left') ? 60 : 315;
      }
    } else {
      const isRight = pos.includes('right');
      const isLeft  = pos.includes('left');
      if (l.angle_deg != null && (isRight || isLeft)) {
        // Use actual angle from engine: 0°=on-axis(top), 90°=side
        // Right: canvas deg = angle_deg (upper-right quadrant)
        // Left:  canvas deg = 360 - angle_deg (upper-left quadrant)
        const mag = Math.min(l.angle_deg, 85);
        deg = isRight ? mag : 360 - mag;
      } else {
        deg = isRight ? 55 : isLeft ? 305 : 45;
      }
    }
    const rad = ((deg - 90) * Math.PI) / 180;
    const lx  = cx + Math.cos(rad) * r * 0.82;
    const ly  = cy + Math.sin(rad) * r * 0.82;

    // Glow dot
    ctx.save();
    ctx.shadowColor = lc; ctx.shadowBlur = px(8, S);
    ctx.beginPath(); ctx.arc(lx, ly, px(8, S), 0, Math.PI * 2);
    ctx.fillStyle = lc; ctx.globalAlpha = 0.70; ctx.fill();
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = lc; ctx.globalAlpha = 0.18;
    ctx.lineWidth   = px(1, S);
    ctx.setLineDash([px(8, S), px(6, S)]);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(lx, ly); ctx.stroke();
    ctx.restore();

    const above = ly < cy;
    micro(ctx, lx, ly + (above ? -px(16, S) : px(20, S)), l.role || '', S,
      { color: lc, size: 12, align: 'center', tracking: 1.5 });
  });
}

// No-photo fallback zone — ghost pattern name + light-reticle. Never looks placeholder.
function drawNoPhotoZone(ctx, x, y, w, h, pattern, confidence, S) {
  const cc = confColor(confidence);
  // Dark BG — subtle warmth at top-right where key light would live
  const bg = ctx.createRadialGradient(x + w * 0.72, y + h * 0.28, 0, x + w * 0.72, y + h * 0.28, w * 0.90);
  bg.addColorStop(0, '#16171f');
  bg.addColorStop(1, BG);
  ctx.fillStyle = bg; ctx.fillRect(x, y, w, h);

  // Ghost pattern name — enormous, barely legible, reads as graphic texture
  if (pattern) {
    ctx.save();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.font = `900 ${f(140, S)} ${FONT}`;
    ctx.fillStyle = 'rgba(248,249,252,0.032)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(capitalize(pattern), x + w / 2, y + h * 0.52);
    ctx.restore();
  }

  // Light-reticle symbol — minimal crosshair, centered upper third
  const cx = x + w / 2, cy = y + h * 0.36, r = px(22, S);
  const arm = px(14, S);
  ctx.save();
  ctx.strokeStyle = `${cc}28`;
  ctx.lineWidth = px(1.5, S);
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.28, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx - r - arm, cy); ctx.lineTo(cx - r - px(3, S), cy);
  ctx.moveTo(cx + r + px(3, S), cy); ctx.lineTo(cx + r + arm, cy);
  ctx.moveTo(cx, cy - r - arm); ctx.lineTo(cx, cy - r - px(3, S));
  ctx.moveTo(cx, cy + r + px(3, S)); ctx.lineTo(cx, cy + r + arm);
  ctx.stroke();
  ctx.restore();
}

// ── PRIMITIVES ────────────────────────────────────────────────────────────────

// Film grain — OffscreenCanvas tile generated once per session, tiled over canvas.
// Always call as the LAST draw operation in a compositor.
let _grainTile = null;
function ensureGrainTile() {
  if (_grainTile) return _grainTile;
  const size = 256;
  let oc;
  try { oc = new OffscreenCanvas(size, size); }
  catch { oc = document.createElement('canvas'); oc.width = oc.height = size; }
  const oc2 = oc.getContext('2d');
  const id  = oc2.createImageData(size, size);
  const d   = id.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = Math.random() * 255 | 0;
    d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255;
  }
  oc2.putImageData(id, 0, 0);
  _grainTile = oc;
  return oc;
}
export function drawGrain(ctx, w, h, intensity = 0.025) {
  const tile = ensureGrainTile();
  const size = 256;
  ctx.save();
  ctx.globalAlpha = intensity;
  for (let ty = 0; ty < h; ty += size) {
    for (let tx = 0; tx < w; tx += size) {
      ctx.drawImage(tile, tx, ty);
    }
  }
  ctx.restore();
}

// Standalone confidence bar — proportional fill, steel track.
export function drawConfidenceBar(ctx, confidence, barX, barY, trackW, S) {
  const barH = px(3, S);
  const r    = px(2, S);
  roundRect(ctx, barX, barY, trackW, barH, r);
  ctx.fillStyle = 'rgba(132,158,184,0.10)'; ctx.fill();
  const fw = Math.max(px(6, S), Math.round(trackW * Math.min(confidence, 1)));
  roundRect(ctx, barX, barY, fw, barH, r);
  ctx.fillStyle = confColor(confidence); ctx.fill();
}

// Pattern hero — adaptive type scale, centered at (cx, y).
// Returns nominal font height in scaled pixels.
// Pass opts.shadowColor + opts.shadowBlur for glow.
export function drawPatternHero(ctx, pattern, cx, y, maxW, S, opts = {}) {
  const { color = TEXT, shadowColor = null, shadowBlur = 0 } = opts;
  const text = capitalize(pattern || 'Unknown');
  const len  = text.replace(/\s/g, '').length;
  let sz     = len <= 6 ? 140 : len <= 10 ? 112 : 88;
  ctx.save();
  ctx.font = `800 ${f(sz, S)} ${FONT}`;
  while (sz > 48 && ctx.measureText(text).width > maxW) {
    sz -= 4;
    ctx.font = `800 ${f(sz, S)} ${FONT}`;
  }
  ctx.shadowColor  = shadowColor || 'transparent';
  ctx.shadowBlur   = shadowBlur;
  ctx.fillStyle    = color;
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, cx, y);
  ctx.restore();
  return px(sz, S);
}

// Face-aware cover crop. Returns {sx, sy, sw, sh} for drawImage.
// faceBox: {x, y, w, h} in source-image pixels (or null → top-third bias).
export function smartCrop(img, faceBox, targetW, targetH) {
  const iw   = img.naturalWidth  || img.width  || targetW;
  const ih   = img.naturalHeight || img.height || targetH;
  const tAsp = targetW / targetH;
  let sw, sh;
  if (iw / ih > tAsp) { sh = ih; sw = Math.round(ih * tAsp); }
  else                 { sw = iw; sh = Math.round(iw / tAsp); }
  let sx, sy;
  if (faceBox && faceBox.x != null && faceBox.w != null) {
    sx = Math.round(faceBox.x + faceBox.w / 2 - sw / 2);
    sy = Math.round(faceBox.y + faceBox.h / 2 - sh / 2);
  } else {
    sx = Math.round((iw - sw) / 2);
    sy = Math.round((ih - sh) * 0.33);
  }
  sx = Math.max(0, Math.min(iw - sw, sx));
  sy = Math.max(0, Math.min(ih - sh, sy));
  return { sx, sy, sw, sh };
}

// Environment pill badge
function drawEnvBadge(ctx, x, y, env, S) {
  if (!env) return;
  const label = env.replace(/_/g, ' ').toUpperCase();
  ctx.save();
  ctx.font = `700 ${f(13, S)} ${FONT}`;
  const tw = ctx.measureText(label).width;
  const bw = tw + px(20, S), bh = px(26, S);
  roundRect(ctx, x, y, bw, bh, px(6, S));
  ctx.fillStyle = 'rgba(9,9,11,0.65)'; ctx.fill();
  ctx.strokeStyle = 'rgba(132,158,184,0.20)'; ctx.lineWidth = px(1, S); ctx.stroke();
  ctx.fillStyle = 'rgba(132,158,184,0.65)'; ctx.textAlign = 'left';
  ctx.fillText(label, x + px(10, S), y + px(18, S));
  ctx.restore();
}


// ── BTS CARD (4:5) ─────────────────────────────────────────────────────────
// Photo-dominant reveal card. Pattern name is massive — THE statement.
// Typography: 86px pattern, 58px conf%, 14px role label, 26px detail.
export function renderBTSCard(ctx, {
  photo, diagramCanvas, pattern, confidence, lights = [],
  camera, format, branded = true, environment = null, progress = 1,
}) {
  const { w, h } = format;
  const S   = w / 1080;
  const pad = px(44, S);
  const cw  = w - pad * 2;

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  const lc = lights.length;
  const hasCam = !!(camera && (camera.aperture || camera.iso || camera.shutter));
  const photoRatio = lc >= 3 ? 0.52 : lc >= 1 ? 0.60 : 0.65;
  const photoH = Math.round(h * photoRatio);

  // ── PHOTO — fades in first ──
  const photoA = sect(progress, 0, 0.30);
  ctx.save(); ctx.globalAlpha = photoA;
  if (!drawPhotoCover(ctx, photo, 0, 0, w, photoH, 0.18)) {
    drawNoPhotoZone(ctx, 0, 0, w, photoH, pattern, confidence, S);
  }
  drawPhotoFade(ctx, photoH, w, px(110, S));
  if (environment) drawEnvBadge(ctx, pad, px(32, S), environment, S);
  ctx.restore();

  // ── PATTERN NAME — clean fade only ──
  const patA = sect(progress, 0.22, 0.20);
  let y = photoH + px(36, S);
  ctx.save();
  ctx.globalAlpha = patA;
  ctx.shadowColor = confColor(confidence);
  ctx.shadowBlur  = px(40, S);
  ctx.font        = `800 ${f(86, S)} ${FONT}`;
  ctx.fillStyle   = TEXT;
  ctx.textAlign   = 'left';
  ctx.fillText(capitalize(pattern || 'Unknown'), pad, y);
  ctx.shadowBlur = 0;
  // Accent rule — width sweeps in from left (purposeful reveal, not decorative)
  const accentFull = px(240, S);
  const accentW = Math.round(accentFull * sect(progress, 0.30, 0.20));
  if (accentW > 2) {
    const accentG = ctx.createLinearGradient(pad, 0, pad + accentFull, 0);
    accentG.addColorStop(0,   confColor(confidence) + 'dd');
    accentG.addColorStop(0.5, confColor(confidence) + '88');
    accentG.addColorStop(1,   'rgba(0,0,0,0)');
    ctx.fillStyle = accentG;
    ctx.fillRect(pad, y + px(10, S), accentW, px(4, S));
  }
  ctx.restore();
  y += px(76, S);

  // ── CONFIDENCE — counts up ──
  const confA  = sect(progress, 0.40, 0.24);
  const animConf = confidence * confA;
  ctx.save(); ctx.globalAlpha = confA;
  y += drawConfBlock(ctx, pad, y, cw, animConf, S);
  ctx.restore();
  y += px(28, S);

  // ── DIVIDER + LIGHTS ──
  const lightsA = sect(progress, 0.58, 0.16);
  ctx.save(); ctx.globalAlpha = lightsA;
  drawDivider(ctx, y, pad, w - pad);
  ctx.restore();
  y += px(28, S);

  if (lc > 0) {
    ctx.save(); ctx.globalAlpha = lightsA;
    micro(ctx, pad, y, `Lights · ${lc}`, S, { size: 15 });
    ctx.restore();
    y += px(28, S);
    lights.slice(0, 4).forEach((l, i) => {
      const rowA = sect(progress, 0.62 + i * 0.09, 0.15);
      ctx.save(); ctx.globalAlpha = rowA;
      const rowH = drawLightRow(ctx, pad + px(2, S), y, l, S);
      ctx.restore();
      y += rowH + px(18, S);
    });
    y += px(4, S);
  }

  // ── CAMERA ──
  if (hasCam) {
    const camA = sect(progress, 0.82, 0.14);
    ctx.save(); ctx.globalAlpha = camA;
    drawDivider(ctx, y, pad, w - pad);
    y += px(22, S);
    micro(ctx, pad, y, 'Camera', S, { size: 15 });
    y += px(28, S);
    const parts = [
      camera.aperture, camera.shutter,
      camera.iso ? `ISO ${camera.iso}` : null,
      camera.focal_length ? `${camera.focal_length}mm` : null,
    ].filter(Boolean);
    ctx.font = `500 ${f(28, S)} ${FONT}`;
    ctx.fillStyle = TEXT; ctx.textAlign = 'left';
    ctx.fillText(parts.join('  ·  '), pad, y);
    if (camera.model) {
      y += px(36, S);
      ctx.font = `400 ${f(20, S)} ${FONT}`;
      ctx.fillStyle = TEXT_DIM;
      ctx.fillText(camera.model, pad, y);
    }
    ctx.restore();
  }

  ctx.save(); ctx.globalAlpha = sect(progress, 0.94, 0.06);
  drawBrand(ctx, w, h - px(24, S), branded, S);
  ctx.restore();
  drawGrain(ctx, w, h);
}


// ── STORY (9:16) ────────────────────────────────────────────────────────────
// Instagram / TikTok. The SCROLL STOPPER.
// Photo is the emotion. Pattern name is THE MOMENT. Everything else rewards the save.
export function renderStoryTemplate(ctx, {
  photo, diagramCanvas, pattern, confidence, lights = [],
  camera, setupSummary, format, branded = true, environment = null, progress = 1,
}) {
  const { w, h } = format;
  const S   = w / 1080;
  const pad = px(60, S);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  // ── PHOTO + CINEMATIC OVERLAY ──
  if (photo) {
    const crop = smartCrop(photo, null, w, h);
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, w, h); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, h);
    ctx.restore();
    const ov = ctx.createLinearGradient(0, 0, 0, h);
    ov.addColorStop(0,    'rgba(9,9,11,0.22)');  // top vignette — soft
    ov.addColorStop(0.18, 'rgba(9,9,11,0.03)');  // face zone — nearly invisible
    ov.addColorStop(0.38, 'rgba(9,9,11,0.18)');  // widen the clear window
    ov.addColorStop(0.50, 'rgba(9,9,11,0.72)');  // transition below face
    ov.addColorStop(0.60, 'rgba(9,9,11,0.88)');
    ov.addColorStop(0.72, 'rgba(9,9,11,0.93)');
    ov.addColorStop(1,    'rgba(9,9,11,0.97)');
    ctx.fillStyle = ov; ctx.fillRect(0, 0, w, h);
  } else {
    const bg = ctx.createRadialGradient(w * 0.3, h * 0.25, 0, w * 0.5, h * 0.35, w);
    bg.addColorStop(0, '#151820'); bg.addColorStop(1, BG);
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
  }

  // ── TOP BAR — fades in immediately, safe zone at 16% per Instagram spec ──
  const topA  = sect(progress, 0, 0.25);
  const topY  = Math.round(h * 0.160);
  ctx.save(); ctx.globalAlpha = topA;
  micro(ctx, w / 2, topY, 'Lighting Breakdown', S,
    { color: branded ? 'rgba(132,158,184,0.50)' : 'rgba(132,158,184,0.25)', size: 17, align: 'center', tracking: 3.5 });
  if (environment) {
    const label = environment.replace(/_/g, ' ').toUpperCase();
    ctx.font = `700 ${f(13, S)} ${FONT}`;
    const tw  = ctx.measureText(label).width;
    const bw  = tw + px(18, S), bh = px(26, S);
    const bx  = w - pad - bw, by = topY - px(19, S);
    roundRect(ctx, bx, by, bw, bh, px(6, S));
    ctx.fillStyle = 'rgba(9,9,11,0.65)'; ctx.fill();
    ctx.strokeStyle = 'rgba(132,158,184,0.18)'; ctx.lineWidth = px(1, S); ctx.stroke();
    ctx.fillStyle = 'rgba(132,158,184,0.65)'; ctx.textAlign = 'left';
    ctx.fillText(label, bx + px(9, S), by + px(18, S));
  }
  ctx.restore();

  // ── PATTERN HERO — clean fade, glow fades in with it ──
  const patA  = sect(progress, 0.18, 0.24);
  const heroY = Math.round(h * 0.520);
  ctx.save();
  ctx.globalAlpha = patA;
  drawPatternHero(ctx, pattern, w / 2, heroY, w - px(120, S), S, {
    color:       TEXT,
    shadowColor: confColor(confidence),
    shadowBlur:  px(32, S),
  });
  ctx.restore();

  // Thin rule — width animates in from center
  const ruleFullW = px(80, S), ruleH = px(3, S);
  const ruleAnimW = Math.round(ruleFullW * sect(progress, 0.36, 0.18));
  const ruleY     = heroY + px(12, S);
  if (ruleAnimW > 2) {
    const ruleX = (w - ruleAnimW) / 2;
    const ruleG = ctx.createLinearGradient(ruleX, 0, ruleX + ruleAnimW, 0);
    ruleG.addColorStop(0,   'rgba(132,158,184,0)');
    ruleG.addColorStop(0.5, 'rgba(132,158,184,0.50)');
    ruleG.addColorStop(1,   'rgba(132,158,184,0)');
    ctx.fillStyle = ruleG;
    ctx.fillRect(ruleX, ruleY, ruleAnimW, ruleH);
  }

  // ── CONFIDENCE — counts up ──
  const confAnimProg = sect(progress, 0.40, 0.24);
  const animConf = confidence * confAnimProg;
  const pct = Math.round(animConf * 100);
  const cc  = confColor(confidence);
  const confY = ruleY + px(40, S);

  ctx.save();
  ctx.globalAlpha = confAnimProg;
  ctx.shadowColor = cc; ctx.shadowBlur = px(14, S);
  ctx.font        = `800 ${f(64, S)} ${FONT}`;
  ctx.fillStyle   = cc; ctx.textAlign = 'center';
  ctx.fillText(`${pct}%`, w / 2, confY);
  ctx.restore();

  ctx.save(); ctx.globalAlpha = confAnimProg;
  micro(ctx, w / 2, confY + px(14, S), 'Confidence', S,
    { color: TEXT_DIM, size: 15, align: 'center', tracking: 2.5 });
  ctx.restore();

  // Confidence bar
  const barW = Math.round(w * 0.44);
  const barX = (w - barW) / 2, barY = confY + px(32, S);
  ctx.save(); ctx.globalAlpha = confAnimProg;
  drawConfidenceBar(ctx, animConf, barX, barY, barW, S);
  ctx.restore();

  // ── OVERHEAD DIAGRAM — fades in ──
  const diagA = sect(progress, 0.56, 0.20);
  const diagW = Math.round(w * 0.68);
  const diagH = px(200, S);
  const diagX = (w - diagW) / 2;
  const diagY = barY + px(38, S);

  ctx.save(); ctx.globalAlpha = diagA;
  if (diagramCanvas && diagramCanvas.width > 10) {
    const asp = diagramCanvas.width / diagramCanvas.height;
    let dw = diagW, dh = diagW / asp;
    if (dh > diagH) { dh = diagH; dw = diagH * asp; }
    ctx.save(); roundRect(ctx, diagX, diagY, diagW, diagH, px(10, S)); ctx.clip();
    ctx.drawImage(diagramCanvas, diagX + (diagW - dw) / 2, diagY + (diagH - dh) / 2, dw, dh);
    ctx.restore();
  } else if (lights.length > 0) {
    drawOverheadDiagram(ctx, diagX, diagY, diagW, diagH, lights, S);
  }
  ctx.restore();

  // ── LIGHTS — staggered ──
  let y = diagY + diagH + px(32, S);

  if (lights.length > 0) {
    ctx.save(); ctx.globalAlpha = sect(progress, 0.68, 0.14);
    micro(ctx, pad, y, `Lights · ${lights.length}`, S, { size: 15 });
    ctx.restore();
    y += px(28, S);
    lights.slice(0, 3).forEach((l, i) => {
      const rowA = sect(progress, 0.72 + i * 0.08, 0.15);
      ctx.save(); ctx.globalAlpha = rowA;
      y += drawLightRow(ctx, pad + px(2, S), y, l, S) + px(20, S);
      ctx.restore();
    });
  } else if (setupSummary) {
    ctx.font = `400 ${f(28, S)} ${FONT}`;
    ctx.fillStyle = TEXT_DIM; ctx.textAlign = 'center';
    ctx.fillText(setupSummary, w / 2, y);
  }

  ctx.save(); ctx.globalAlpha = sect(progress, 0.92, 0.08);
  drawBrand(ctx, w, h - px(72, S), branded, S);
  ctx.restore();
  drawGrain(ctx, w, h);
}


// ── CAROUSEL SLIDE (1:1) ────────────────────────────────────────────────────
// One light per slide. Role color OWNS this slide — everything keys off it.
// Typography: role = massive 96px; modifier = 40px accent; stats = 64px bold numbers.
export function renderCarouselSlide(ctx, {
  light, index, total, pattern, format, branded = true, progress = 1,
}) {
  const { w, h } = format;
  const S = w / 1080;

  // Gradient BG — subtle, not flat
  const bg = ctx.createLinearGradient(0, 0, w, h);
  bg.addColorStop(0, '#0e0f16');
  bg.addColorStop(1, BG);
  ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

  const rc    = roleColor(light.role || '');
  const role  = capitalize(light.label || light.role || '');
  const mod   = light.modifier_label || light.modifier || '';
  const pos   = (light.position_label || light.position || '').replace(/-/g, ' ');
  const dist  = light.distance_m  != null ? `${(light.distance_m * 3.281).toFixed(0)} ft` : '';
  const angle = light.angle_deg   != null ? `${Math.round(Math.abs(light.angle_deg))}°` : '';
  const ht    = light.height_m    ? `${(light.height_m * 3.281).toFixed(0)} ft` : '';
  const rawStop = light.power_stop != null ? String(light.power_stop) : '';
  const power = rawStop
    ? (rawStop.toLowerCase().startsWith('guide') ? rawStop : `Guide ${rawStop}`)
    : (light.power_hint || '');

  // Thick role-color top strip — sweeps in from left
  const stripH    = px(5, S);
  const stripFill = Math.round(w * sect(progress, 0, 0.22));
  ctx.save();
  ctx.shadowColor = rc; ctx.shadowBlur = px(12, S);
  ctx.fillStyle   = rc;
  ctx.fillRect(0, 0, stripFill, stripH);
  ctx.restore();

  // Subtle role-color glow — pulses in
  const glowA = sect(progress, 0.08, 0.30);
  const glowG = ctx.createRadialGradient(w / 2, h * 0.35, 0, w / 2, h * 0.35, px(280, S));
  glowG.addColorStop(0,   rc + '14');
  glowG.addColorStop(0.7, 'rgba(0,0,0,0)');
  ctx.save(); ctx.globalAlpha = glowA;
  ctx.fillStyle = glowG; ctx.fillRect(0, 0, w, h * 0.70);
  ctx.restore();

  // Counter + pattern label
  const hdrA = sect(progress, 0.05, 0.20);
  ctx.save(); ctx.globalAlpha = hdrA;
  ctx.font = `600 ${f(20, S)} ${FONT}`;
  ctx.fillStyle = TEXT_DIM; ctx.textAlign = 'right';
  ctx.fillText(`${index + 1} / ${total}`, w - px(52, S), px(58, S));
  ctx.fillStyle = `${rc}55`; ctx.textAlign = 'left';
  ctx.fillText(capitalize(pattern || ''), px(52, S), px(58, S));
  ctx.restore();

  // ── ROLE NAME — clean fade with glow ──
  const roleA = sect(progress, 0.18, 0.24);
  const roleY = Math.round(h * 0.40);
  ctx.save();
  ctx.globalAlpha = roleA;
  ctx.shadowColor = rc; ctx.shadowBlur = px(28, S);
  ctx.font        = `800 ${f(112, S)} ${FONT}`;
  ctx.fillStyle   = rc;  // role-colored — key identity signal
  ctx.textAlign   = 'center';
  ctx.fillText(role, w / 2, roleY);
  ctx.restore();

  // Role-colored underline — width grows from center
  const ulFullW = px(100, S);
  const ulAnimW = Math.round(ulFullW * sect(progress, 0.36, 0.18));
  ctx.save();
  ctx.globalAlpha = sect(progress, 0.36, 0.18) * 0.55;
  const ulG = ctx.createLinearGradient(w / 2 - ulAnimW / 2, 0, w / 2 + ulAnimW / 2, 0);
  ulG.addColorStop(0, 'rgba(0,0,0,0)');
  ulG.addColorStop(0.5, rc);
  ulG.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = ulG;
  ctx.fillRect(w / 2 - ulAnimW / 2, roleY + px(12, S), ulAnimW, px(2, S));
  ctx.restore();

  let y = roleY + px(52, S);

  // Position — fades in
  if (pos) {
    ctx.save(); ctx.globalAlpha = sect(progress, 0.42, 0.18);
    ctx.font = `400 ${f(28, S)} ${FONT}`;
    ctx.fillStyle = TEXT_MID; ctx.textAlign = 'center';
    ctx.fillText(pos, w / 2, y);
    ctx.restore();
    y += px(42, S);
  }

  // Modifier — white, role-color glow only. Role color is accent (role label), not hierarchy.
  if (mod) {
    const modA = sect(progress, 0.44, 0.20);
    ctx.save();
    ctx.globalAlpha = modA;
    ctx.shadowColor = rc; ctx.shadowBlur = px(8, S);
    ctx.font        = `600 ${f(52, S)} ${FONT}`;
    ctx.fillStyle   = TEXT_MID; ctx.textAlign = 'center';
    ctx.fillText(mod, w / 2, y);
    ctx.restore();
    y += px(68, S);
  }

  // ── STATS — BIG NUMBERS ──
  const kelvinVal = light.kelvin ? `${Math.round(light.kelvin / 100) * 100}K` : '';
  const catchlightVal = (light.catchlight_modifier && typeof light.catchlight_modifier === 'string')
    ? capitalize(light.catchlight_modifier).replace('Softbox ', '').replace('_', ' ')
    : '';
  const stats = [
    { label: 'DISTANCE', value: dist },
    { label: 'ANGLE',    value: angle },
    { label: 'HEIGHT',   value: ht },
    { label: 'KELVIN',   value: kelvinVal, small: true },
    { label: 'CATCHLIGHT', value: catchlightVal, small: true },
  ].filter(s => s.value);

  if (stats.length > 0) {
    const statsA = sect(progress, 0.60, 0.22);
    y += px(12, S);
    ctx.save(); ctx.globalAlpha = statsA;
    drawDivider(ctx, y, px(80, S), w - px(80, S));
    ctx.restore();
    y += px(28, S);

    // Row 1: primary stats (DISTANCE, ANGLE, HEIGHT) — max 3, big numbers
    const primary = stats.filter(s => !s.small).slice(0, 3);
    // Row 2: secondary stats (KELVIN, CATCHLIGHT) — smaller, below
    const secondary = stats.filter(s => s.small);

    const sw = Math.round((w - px(160, S)) / Math.max(1, primary.length));
    let sx = px(80, S) + sw / 2;

    primary.forEach((s, si) => {
      const sA = sect(progress, 0.64 + si * 0.08, 0.18);
      ctx.save(); ctx.globalAlpha = sA;
      micro(ctx, sx, y, s.label, S, { color: TEXT_DIM, size: 15, align: 'center', tracking: 2 });
      ctx.shadowColor = TEXT; ctx.shadowBlur = px(6, S);
      ctx.font        = `800 ${f(60, S)} ${FONT}`;
      ctx.fillStyle   = TEXT; ctx.textAlign = 'center';
      ctx.fillText(s.value, sx, y + px(62, S));
      ctx.restore();
      sx += sw;
    });

    const primaryH = primary.length > 0 ? px(88, S) : 0;
    y += primaryH;

    if (secondary.length > 0) {
      const ssw = Math.round((w - px(160, S)) / secondary.length);
      let ssx = px(80, S) + ssw / 2;
      secondary.forEach((s, si) => {
        const sA = sect(progress, 0.76 + si * 0.08, 0.16);
        ctx.save(); ctx.globalAlpha = sA;
        micro(ctx, ssx, y, s.label, S, { color: TEXT_DIM, size: 12, align: 'center', tracking: 2 });
        ctx.font      = `700 ${f(34, S)} ${FONT}`;
        ctx.fillStyle = 'rgba(132,158,184,0.75)';
        ctx.textAlign = 'center';
        ctx.fillText(s.value, ssx, y + px(42, S));
        ctx.restore();
        ssx += ssw;
      });
      y += px(60, S);
    } else {
      y += px(22, S);
    }
  }

  if (power) {
    ctx.save(); ctx.globalAlpha = sect(progress, 0.86, 0.12);
    micro(ctx, w / 2, y + px(8, S), power, S,
      { color: 'rgba(132,158,184,0.35)', size: 22, align: 'center', tracking: 0.5 });
    ctx.restore();
  }

  ctx.save(); ctx.globalAlpha = sect(progress, 0.94, 0.06);
  drawBrand(ctx, w, h - px(50, S), branded, S);
  ctx.restore();
  drawGrain(ctx, w, h);
}


// ── SUMMARY CARD (4:5) ─────────────────────────────────────────────────────
// Photo + pattern + overhead diagram + full light breakdown. The "save this" card.
export function renderBTSSummary(ctx, {
  photo, diagramCanvas, pattern, confidence, lights = [],
  camera, format, branded = true, environment = null, progress = 1,
}) {
  const { w, h } = format;
  const S   = w / 1080;
  const pad = px(44, S);
  const cw  = w - pad * 2;

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  const photoH = Math.round(h * 0.46);
  const photoA = sect(progress, 0, 0.28);
  ctx.save(); ctx.globalAlpha = photoA;
  if (!drawPhotoCover(ctx, photo, 0, 0, w, photoH, 0.18)) {
    drawNoPhotoZone(ctx, 0, 0, w, photoH, pattern, confidence, S);
  }
  drawPhotoFade(ctx, photoH, w, px(120, S));
  if (environment) drawEnvBadge(ctx, pad, px(30, S), environment, S);
  ctx.restore();

  let y = photoH + px(36, S);

  // ── PATTERN ──
  const patA = sect(progress, 0.22, 0.20);
  ctx.save();
  ctx.globalAlpha = patA;
  ctx.shadowColor = confColor(confidence); ctx.shadowBlur = px(32, S);
  ctx.font        = `800 ${f(76, S)} ${FONT}`;
  ctx.fillStyle   = TEXT; ctx.textAlign = 'left';
  ctx.fillText(capitalize(pattern || 'Unknown'), pad, y);
  ctx.restore();
  y += px(14, S);

  const confA = sect(progress, 0.36, 0.20);
  ctx.save(); ctx.globalAlpha = confA;
  y += drawConfBlock(ctx, pad, y, cw, confidence * confA, S, { compact: true });
  ctx.restore();
  y += px(22, S);

  const diagA = sect(progress, 0.50, 0.22);
  ctx.save(); ctx.globalAlpha = diagA;
  drawDivider(ctx, y, pad, w - pad);
  ctx.restore();
  y += px(20, S);

  // ── DIAGRAM ──
  const diagH = px(220, S);
  ctx.save(); ctx.globalAlpha = diagA;
  if (diagramCanvas && diagramCanvas.width > 10) {
    const asp = diagramCanvas.width / diagramCanvas.height;
    let dw = cw, dh = cw / asp;
    if (dh > diagH) { dh = diagH; dw = diagH * asp; }
    ctx.save(); roundRect(ctx, pad, y, cw, diagH, px(10, S)); ctx.clip();
    ctx.drawImage(diagramCanvas, pad + (cw - dw) / 2, y + (diagH - dh) / 2, dw, dh);
    ctx.restore();
  } else {
    drawOverheadDiagram(ctx, pad, y, cw, diagH, lights, S);
  }
  ctx.restore();
  y += diagH + px(18, S);

  const lightsA = sect(progress, 0.65, 0.16);
  ctx.save(); ctx.globalAlpha = lightsA;
  drawDivider(ctx, y, pad, w - pad);
  ctx.restore();
  y += px(20, S);

  // ── LIGHTS ──
  if (lights.length > 0) {
    ctx.save(); ctx.globalAlpha = lightsA;
    micro(ctx, pad, y, `Lights · ${lights.length}`, S, { size: 15 });
    ctx.restore();
    y += px(28, S);
    lights.slice(0, 4).forEach((l, i) => {
      const rowA = sect(progress, 0.70 + i * 0.08, 0.15);
      ctx.save(); ctx.globalAlpha = rowA;
      y += drawLightRow(ctx, pad + px(2, S), y, l, S) + px(16, S);
      ctx.restore();
    });
  }

  ctx.save(); ctx.globalAlpha = sect(progress, 0.94, 0.06);
  drawBrand(ctx, w, h - px(22, S), branded, S);
  ctx.restore();
  drawGrain(ctx, w, h);
}


// ── BLUEPRINT CARD (4:5) ──────────────────────────────────────────────────────
// Technical reference. Photo zone (top 36%) + pattern header + diagram + full light list.
// Analytical identity — data-first, pattern centered as header not statement.
// data shape mirrors exportData in SocialExportPanel.jsx.
export function drawBlueprintCard(ctx, data, S) {
  const {
    pattern, confidence = 0, lights = [], imageEl: photo,
    branded = true, environment = null, diagramCanvas = null,
    judgment = null,
    progress = 1, confEvidence = '',
  } = data;

  const w   = ctx.canvas.width;
  const h   = ctx.canvas.height;
  const pad = px(44, S);
  const cw  = w - pad * 2;
  const cc  = confColor(confidence);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  // ── PHOTO — smart crop, top 36% ──
  const photoH = Math.round(h * 0.36);
  const photoA = sect(progress, 0, 0.28);
  ctx.save(); ctx.globalAlpha = photoA;
  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, photoH);
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, w, photoH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, photoH);
    ctx.restore();
    drawPhotoFade(ctx, photoH, w, px(100, S));
  } else {
    drawNoPhotoZone(ctx, 0, 0, w, photoH, pattern, confidence, S);
  }
  if (environment) drawEnvBadge(ctx, pad, px(28, S), environment, S);
  ctx.restore();

  // ── SERIES LABEL — LIGHT READ, small, centered, between photo and pattern ──
  const seriesA = sect(progress, 0.18, 0.22);
  ctx.save();
  ctx.globalAlpha   = seriesA;
  ctx.font          = `500 ${f(11, S)} ${FONT}`;
  ctx.letterSpacing = `${px(2.5, S)}px`;
  ctx.fillStyle     = 'rgba(132,158,184,0.32)';
  ctx.textAlign     = 'center';
  ctx.textBaseline  = 'alphabetic';
  ctx.fillText('LIGHT READ', w / 2, photoH + px(28, S));
  ctx.restore();

  // ── PATTERN — centered header at 44% ──
  const patY = Math.round(h * 0.44);
  const patA = sect(progress, 0.22, 0.20);
  ctx.save(); ctx.globalAlpha = patA;
  drawPatternHero(ctx, pattern, w / 2, patY, cw, S,
    { shadowColor: cc, shadowBlur: px(32, S) });
  ctx.restore();

  // ── CONFIDENCE — left-aligned, compact ──
  const confA = sect(progress, 0.34, 0.18);
  const pct   = Math.round((confidence || 0) * 100);
  let y = patY + px(46, S);

  ctx.save(); ctx.globalAlpha = confA;
  ctx.textBaseline = 'alphabetic';
  ctx.font = `800 ${f(36, S)} ${FONT}`;
  ctx.fillStyle = cc; ctx.textAlign = 'left';
  ctx.fillText(`${pct}%`, pad, y);
  const pctW = ctx.measureText(`${pct}%`).width;
  micro(ctx, pad + pctW + px(10, S), y, 'Confidence', S,
    { color: TEXT_DIM, size: 12, tracking: 2 });
  ctx.restore();

  ctx.save(); ctx.globalAlpha = confA;
  drawConfidenceBar(ctx, confidence, pad, y + px(6, S), cw, S);
  if (confEvidence) {
    ctx.font      = `500 ${f(18, S)} ${FONT}`;
    ctx.fillStyle = 'rgba(132,158,184,0.65)';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(confEvidence, pad, y + px(24, S));
  }
  ctx.restore();

  y += confEvidence ? px(38, S) : px(20, S);

  // ── DIVIDER + DIAGRAM ──
  const diagA = sect(progress, 0.46, 0.20);
  ctx.save(); ctx.globalAlpha = diagA;
  drawDivider(ctx, y, pad, w - pad);
  ctx.restore();
  y += px(14, S);

  const diagH = px(200, S);
  ctx.save(); ctx.globalAlpha = diagA;
  if (diagramCanvas && diagramCanvas.width > 10) {
    const asp = diagramCanvas.width / diagramCanvas.height;
    let dw = cw, dh = cw / asp;
    if (dh > diagH) { dh = diagH; dw = diagH * asp; }
    ctx.save(); roundRect(ctx, pad, y, cw, diagH, px(10, S)); ctx.clip();
    ctx.drawImage(diagramCanvas, pad + (cw - dw) / 2, y + (diagH - dh) / 2, dw, dh);
    ctx.restore();
  } else {
    drawOverheadDiagram(ctx, pad, y, cw, diagH, lights, S);
  }
  ctx.restore();
  y += diagH + px(12, S);

  // ── DIVIDER + LIGHTS — up to 4 rows ──
  const lightsA = sect(progress, 0.62, 0.16);
  ctx.save(); ctx.globalAlpha = lightsA;
  drawDivider(ctx, y, pad, w - pad);
  ctx.restore();
  y += px(16, S);

  if (lights.length > 0) {
    ctx.save(); ctx.globalAlpha = lightsA;
    micro(ctx, pad, y, `Lights · ${lights.length}`, S, { size: 14 });
    ctx.restore();
    y += px(22, S);
    lights.slice(0, 4).forEach((l, i) => {
      const rowA = sect(progress, 0.66 + i * 0.07, 0.14);
      ctx.save(); ctx.globalAlpha = rowA;
      const rowH = drawLightRow(ctx, pad + px(2, S), y, l, S);
      ctx.restore();
      y += rowH + px(12, S);
    });
  }

  {
    const brandA = sect(progress, 0.94, 0.06);
    ctx.save();
    ctx.globalAlpha = brandA;

    if (judgment === 'nailed' || judgment === 'close') {
      const jLabel = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
      const jAlpha = judgment === 'nailed' ? 0.88 : 0.52;
      ctx.font          = `600 ${f(11, S)} ${FONT}`;
      ctx.letterSpacing = `${px(1.5, S)}px`;
      ctx.fillStyle     = `rgba(132,158,184,${jAlpha})`;
      ctx.textAlign     = 'left';
      ctx.textBaseline  = 'alphabetic';
      ctx.fillText(jLabel, pad, h - px(22, S));
    }

    ctx.restore();
  }

  ctx.save(); ctx.globalAlpha = sect(progress, 0.94, 0.06);
  drawBrand(ctx, w, h - px(22, S), branded, S);
  ctx.restore();
  drawGrain(ctx, w, h);
}


// ── SIGNAL CARD (4:5) — The Instrument Read ──────────────────────────────────
// Hard horizontal division: specimen (top 55%) + analysis readout (bottom 45%).
// Authority > lifestyle. Classified, stamped, measured.
// data shape mirrors exportData in SocialExportPanel.jsx.
// progress: 0–1 animation control (default 1 = final frame).
export function drawSignalCard(ctx, data, S) {
  const {
    pattern, confidence = 0, imageEl: photo,
    branded = true,
    judgment = null,
    progress = 1, confEvidence = '',
  } = data;

  const w          = ctx.canvas.width;
  const h          = ctx.canvas.height;
  const pad        = px(20, S);
  const specimenH  = Math.round(h * 0.55);
  const analysisY  = specimenH;

  // ── BASE — analysis zone color covers full canvas ──
  ctx.fillStyle = '#0B0B0C';
  ctx.fillRect(0, 0, w, h);

  // ── SPECIMEN ZONE — image fills top 55%, clipped, no decorative overlay ──
  const photoA = sect(progress, 0, 0.30);
  ctx.save();
  ctx.globalAlpha = photoA;
  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, specimenH);
    ctx.beginPath(); ctx.rect(0, 0, w, specimenH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, specimenH);
  } else {
    drawNoPhotoZone(ctx, 0, 0, w, specimenH, pattern, confidence, S);
  }
  ctx.restore();

  // ── ANALYSIS ZONE — explicit flat refill, no gradient ──
  ctx.fillStyle = '#0B0B0C';
  ctx.fillRect(0, analysisY, w, h - analysisY);

  // ── DIVISION RULE — hard 1px boundary + left calibration notch ──
  const ruleA = sect(progress, 0.26, 0.44);
  ctx.save();
  ctx.globalAlpha = ruleA;
  ctx.strokeStyle = 'rgba(255,255,255,0.14)';
  ctx.lineWidth   = 1;
  ctx.beginPath(); ctx.moveTo(0, specimenH); ctx.lineTo(w, specimenH); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,255,255,0.22)';
  ctx.beginPath(); ctx.moveTo(0, specimenH - px(2, S)); ctx.lineTo(0, specimenH + px(2, S)); ctx.stroke();
  ctx.restore();

  // ── CORNER BRACKETS — L-shaped, 10px arms, structural ──
  const arm      = px(10, S);
  const bracketA = sect(progress, 0.22, 0.42);
  ctx.save();
  ctx.globalAlpha = bracketA;
  ctx.strokeStyle = 'rgba(255,255,255,0.20)';
  ctx.lineWidth   = 1;
  ctx.lineCap     = 'square';
  ctx.beginPath(); ctx.moveTo(0, arm); ctx.lineTo(0, 0); ctx.lineTo(arm, 0); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(w - arm, 0); ctx.lineTo(w, 0); ctx.lineTo(w, arm); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, specimenH - arm); ctx.lineTo(0, specimenH); ctx.lineTo(arm, specimenH); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(w - arm, specimenH); ctx.lineTo(w, specimenH); ctx.lineTo(w, specimenH - arm); ctx.stroke();
  ctx.restore();

  // ── SERIES HEADER — LIGHT READ identifier, small, tracked ──
  const seriesA = sect(progress, 0.28, 0.50);
  ctx.save();
  ctx.globalAlpha   = seriesA;
  ctx.font          = `500 ${f(10, S)} ${FONT}`;
  ctx.letterSpacing = `${px(2.0, S)}px`;
  ctx.fillStyle     = 'rgba(132,158,184,0.35)';
  ctx.textAlign     = 'left';
  ctx.textBaseline  = 'alphabetic';
  ctx.fillText('LIGHT READ', pad, analysisY + px(16, S));
  ctx.restore();

  // ── CLASSIFICATION — uppercase, left-aligned, decisive ──
  const patternUpper = (pattern || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const nameLen      = patternUpper.replace(/\s/g, '').length;
  let   classFontSz  = nameLen <= 7 ? 48 : nameLen <= 11 ? 42 : nameLen <= 15 ? 34 : 28;
  const maxClassW    = w - pad * 2 - px(56, S);

  ctx.save();
  ctx.font          = `700 ${f(classFontSz, S)} ${FONT}`;
  ctx.letterSpacing = `${px(5, S)}px`;
  while (classFontSz > 16 && ctx.measureText(patternUpper).width > maxClassW) {
    classFontSz -= 2;
    ctx.font = `700 ${f(classFontSz, S)} ${FONT}`;
  }
  ctx.restore();

  const classY = analysisY + px(34, S); // shifted down 12px to clear LIGHT READ series header
  const classA = sect(progress, 0.34, 0.56);
  ctx.save();
  ctx.globalAlpha   = classA;
  ctx.font          = `700 ${f(classFontSz, S)} ${FONT}`;
  ctx.letterSpacing = `${px(5, S)}px`;
  ctx.fillStyle     = 'rgba(245,247,250,0.95)';
  ctx.textAlign     = 'left';
  ctx.textBaseline  = 'top';
  ctx.fillText(patternUpper, pad, classY);
  ctx.restore();

  // ── CONFIDENCE — right-aligned, same row, secondary, bare percentage ──
  const pct   = Math.round((confidence || 0) * 100);
  const confA = sect(progress, 0.42, 0.60);
  ctx.save();
  ctx.globalAlpha   = confA;
  ctx.font          = `600 ${f(14, S)} ${FONT}`;
  ctx.letterSpacing = `${px(0.5, S)}px`;
  ctx.fillStyle     = `rgba(200,215,225,${pct >= 60 ? 0.62 : 0.44})`;
  ctx.textAlign     = 'right';
  ctx.textBaseline  = 'top';
  ctx.fillText(`${pct}%`, w - pad, classY + px(2, S));
  ctx.restore();

  // ── EVIDENCE READOUT — instrument log, quiet but legible ──
  if (confEvidence) {
    const evidA = sect(progress, 0.50, 0.66);
    ctx.save();
    ctx.globalAlpha   = evidA;
    ctx.font          = `400 ${f(13, S)} ${FONT}`;
    ctx.letterSpacing = `${px(1.0, S)}px`;
    ctx.fillStyle     = 'rgba(160,175,190,0.55)';
    ctx.textAlign     = 'left';
    ctx.textBaseline  = 'top';
    ctx.fillText(`DERIVED — ${confEvidence.toUpperCase()}`, pad, classY + px(classFontSz + 14, S));
    ctx.restore();
  }

  // ── FOOTER IDENTITY — issued brand mark (left: judgment proof, right: NGW identity) ──
  {
    const footerA = sect(progress, 0.86, 1.0);
    ctx.save();
    ctx.globalAlpha  = footerA;
    ctx.textBaseline = 'alphabetic';

    if (branded) {
      ctx.font          = `500 ${f(10, S)} ${FONT}`;
      ctx.letterSpacing = `${px(1.5, S)}px`;
      ctx.fillStyle     = 'rgba(132,158,184,0.70)';
      ctx.textAlign     = 'right';
      ctx.fillText('LIGHT READ · NGW', w - pad, h - px(16, S));
    }

    if (judgment === 'nailed' || judgment === 'close') {
      const jLabel = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
      const jAlpha = judgment === 'nailed' ? 0.88 : 0.52;
      ctx.font          = `600 ${f(11, S)} ${FONT}`;
      ctx.letterSpacing = `${px(1.5, S)}px`;
      ctx.fillStyle     = `rgba(132,158,184,${jAlpha})`;
      ctx.textAlign     = 'left';
      ctx.fillText(jLabel, pad, h - px(16, S));
    }

    ctx.restore();
  }

  // ── GRAIN — always last ──
  drawGrain(ctx, w, h);
}


// ── EXPORT VARIANT FUNCTIONS (test/real-dispatch-export-variants) ─────────────
// Variants B–E are test-only. Wire via ?lc_variant=b|c|d|e URL param.
// Do not expose in production unless explicitly promoted.

// Variant B — Two-Zone Proof Receipt
// Larger portrait (63%), gradient bridge, setup block with small diagram cue.
export function drawSignalCardB(ctx, data, S) {
  const { pattern, confidence = 0, imageEl: photo, branded = true,
          judgment = null, lights = [], confEvidence = '' } = data;

  const w        = ctx.canvas.width;
  const h        = ctx.canvas.height;
  const pad      = px(28, S);
  const photoH   = Math.round(h * 0.63);
  const pct      = Math.round((confidence || 0) * 100);
  const patUpper = (pattern || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const kl       = lights.find(l => l.role === 'key') || lights[0] || null;
  const mod      = kl?.modifier_label || '';
  const pos      = (kl?.position_label || '').replace(/-/g, ' ').toUpperCase();
  const cc       = confColor(confidence);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, photoH);
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w, photoH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, photoH);
    ctx.restore();
    drawPhotoFade(ctx, photoH, w, px(130, S));
  }

  let y = photoH + px(22, S);

  // Row 1: NGW LIGHT READ · pct
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.36)'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NGW LIGHT READ', pad, y);
  ctx.font = `600 ${f(14, S)} ${FONT}`; ctx.letterSpacing = '0px';
  ctx.fillStyle = cc; ctx.textAlign = 'right';
  ctx.fillText(`${pct}%`, w - pad, y);
  ctx.restore();
  y += px(24, S);

  // Row 2: REMBRANDT (dominant)
  let sz = patUpper.replace(/\s/g, '').length <= 8 ? 48 : patUpper.replace(/\s/g, '').length <= 12 ? 40 : 33;
  ctx.save();
  ctx.font = `700 ${f(sz, S)} ${FONT}`; ctx.letterSpacing = `${px(3, S)}px`;
  ctx.fillStyle = TEXT; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  while (sz > 20 && ctx.measureText(patUpper).width > w - pad * 2) { sz -= 2; ctx.font = `700 ${f(sz, S)} ${FONT}`; }
  ctx.fillText(patUpper, pad, y);
  ctx.restore();
  y += px(sz + 10, S);

  // Evidence line
  if (confEvidence) {
    ctx.save();
    ctx.font = `400 ${f(13, S)} ${FONT}`; ctx.letterSpacing = `${px(0.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.55)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(`Confirmed by ${confEvidence}`, pad, y);
    ctx.restore();
    y += px(22, S);
  }

  y += px(10, S);

  // KEY LIGHT block — left column; NAILED IT — right column
  const colR    = w - pad;
  const colMid  = Math.round(w * 0.58);

  // KEY LIGHT header
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.32)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText('KEY LIGHT', pad, y);
  ctx.restore();

  const setupY = y + px(16, S);

  // Modifier
  if (mod) {
    ctx.save();
    ctx.font = `700 ${f(20, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
    ctx.fillStyle = TEXT; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(mod.toUpperCase(), pad, setupY);
    ctx.restore();
  }

  // Position
  if (pos) {
    ctx.save();
    ctx.font = `500 ${f(12, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.55)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(pos, pad, setupY + px(24, S));
    ctx.restore();
  }

  // Light count
  if (lights.length > 0) {
    ctx.save();
    ctx.font = `500 ${f(11, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.40)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(`${lights.length} ${lights.length === 1 ? 'LIGHT' : 'LIGHTS'}`, pad, setupY + px(44, S));
    ctx.restore();
  }

  // NAILED IT (right of KEY LIGHT block)
  if (judgment === 'nailed' || judgment === 'close') {
    const jLabel = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
    const jColor = judgment === 'nailed' ? 'rgba(72,186,136,0.88)' : 'rgba(132,158,184,0.60)';
    ctx.save();
    ctx.font = `700 ${f(30, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = jColor; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    ctx.fillText(jLabel, colR, y);
    ctx.restore();
    ctx.save();
    ctx.font = `500 ${f(11, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.48)'; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    ctx.fillText('CONFIRMED READ', colR, y + px(38, S));
    ctx.restore();
  }

  y = setupY + px(66, S);

  // Small direction diagram (bottom right corner, 180px wide)
  if (lights.length > 0) {
    const dw = px(180, S), dh = px(140, S);
    const dx = w - pad - dw, dy = h - px(50, S) - dh;
    if (dy > y) drawOverheadDiagram(ctx, dx, dy, dw, dh, lights, S);
  }

  // Footer
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  if (branded) ctx.fillText('LIGHT READ · NGW', w - pad, h - px(22, S));
  ctx.restore();

  drawGrain(ctx, w, h);
}

// Variant C — Text-First Proof Receipt
// Dominant typography, no diagram, cleanest shareable layout.
export function drawSignalCardC(ctx, data, S) {
  const { pattern, confidence = 0, imageEl: photo, branded = true,
          judgment = null, lights = [], confEvidence = '' } = data;

  const w        = ctx.canvas.width;
  const h        = ctx.canvas.height;
  const pad      = px(28, S);
  const photoH   = Math.round(h * 0.60);
  const pct      = Math.round((confidence || 0) * 100);
  const patUpper = (pattern || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const kl       = lights.find(l => l.role === 'key') || lights[0] || null;
  const mod      = kl?.modifier_label || '';
  const pos      = (kl?.position_label || '').replace(/-/g, ' ').toUpperCase();
  const cc       = confColor(confidence);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, photoH);
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w, photoH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, photoH);
    ctx.restore();
    drawPhotoFade(ctx, photoH, w, px(120, S));
  }

  let y = photoH + px(22, S);

  // Header row: NGW LIGHT READ left · pct right
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.36)'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NGW LIGHT READ', pad, y);
  ctx.font = `600 ${f(14, S)} ${FONT}`; ctx.letterSpacing = '0px';
  ctx.fillStyle = cc; ctx.textAlign = 'right';
  ctx.fillText(`${pct}%`, w - pad, y);
  ctx.restore();
  y += px(26, S);

  // REMBRANDT — 52pt dominant hero
  let sz = patUpper.replace(/\s/g, '').length <= 8 ? 52 : patUpper.replace(/\s/g, '').length <= 12 ? 44 : 36;
  ctx.save();
  ctx.font = `700 ${f(sz, S)} ${FONT}`; ctx.letterSpacing = `${px(3, S)}px`;
  ctx.fillStyle = TEXT; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  while (sz > 20 && ctx.measureText(patUpper).width > w - pad * 2) { sz -= 2; ctx.font = `700 ${f(sz, S)} ${FONT}`; }
  ctx.fillText(patUpper, pad, y);
  ctx.restore();
  y += px(sz + 10, S);

  // Evidence
  if (confEvidence) {
    ctx.save();
    ctx.font = `400 ${f(14, S)} ${FONT}`; ctx.letterSpacing = `${px(0.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.55)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(`Confirmed by ${confEvidence}`, pad, y);
    ctx.restore();
    y += px(26, S);
  }

  // Divider
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.14)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  ctx.restore();
  y += px(18, S);

  // KEY LIGHT section
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.32)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText('KEY LIGHT', pad, y);
  ctx.restore();
  y += px(18, S);

  if (mod) {
    ctx.save();
    ctx.font = `700 ${f(18, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
    ctx.fillStyle = TEXT; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(mod.toUpperCase(), pad, y);
    ctx.restore();
    y += px(26, S);
  }

  if (pos) {
    ctx.save();
    ctx.font = `500 ${f(13, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.55)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(pos, pad, y);
    ctx.restore();
    y += px(20, S);
  }

  if (lights.length > 0) {
    ctx.save();
    ctx.font = `500 ${f(11, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.40)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(`${lights.length} ${lights.length === 1 ? 'LIGHT' : 'LIGHTS'}`, pad, y);
    ctx.restore();
    y += px(22, S);
  }

  // Divider before judgment
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.14)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  ctx.restore();
  y += px(18, S);

  // NAILED IT · CONFIRMED READ (horizontal, prominent)
  if (judgment === 'nailed' || judgment === 'close') {
    const jLabel    = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
    const jColor    = judgment === 'nailed' ? 'rgba(72,186,136,0.90)' : 'rgba(132,158,184,0.60)';
    ctx.save();
    ctx.font = `700 ${f(28, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
    ctx.fillStyle = jColor; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(jLabel, pad, y);
    const jw = ctx.measureText(jLabel).width;
    ctx.font = `500 ${f(11, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.45)';
    ctx.fillText(' · CONFIRMED READ', pad + jw + px(4, S), y + px(9, S));
    ctx.restore();
  }

  // Footer
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  if (branded) ctx.fillText('LIGHT READ · NGW', w - pad, h - px(22, S));
  ctx.restore();

  drawGrain(ctx, w, h);
}

// Variant D — No-Diagram Light Card
// Like the current Signal Card but with setup info and promoted NAILED IT.
export function drawSignalCardD(ctx, data, S) {
  const { pattern, confidence = 0, imageEl: photo, branded = true,
          judgment = null, lights = [], confEvidence = '' } = data;

  const w        = ctx.canvas.width;
  const h        = ctx.canvas.height;
  const pad      = px(28, S);
  const photoH   = Math.round(h * 0.55);
  const pct      = Math.round((confidence || 0) * 100);
  const patUpper = (pattern || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const kl       = lights.find(l => l.role === 'key') || lights[0] || null;
  const mod      = kl?.modifier_label || '';
  const pos      = (kl?.position_label || '').replace(/-/g, ' ').toUpperCase();
  const cc       = confColor(confidence);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, photoH);
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w, photoH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, photoH);
    ctx.restore();
    drawPhotoFade(ctx, photoH, w, px(100, S));
  }

  let y = photoH + px(22, S);

  // Header row
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.36)'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('LIGHT READ', pad, y);
  ctx.font = `600 ${f(14, S)} ${FONT}`; ctx.letterSpacing = '0px';
  ctx.fillStyle = cc; ctx.textAlign = 'right';
  ctx.fillText(`${pct}%`, w - pad, y);
  ctx.restore();
  y += px(24, S);

  // Pattern
  let sz = patUpper.replace(/\s/g, '').length <= 8 ? 48 : patUpper.replace(/\s/g, '').length <= 12 ? 40 : 33;
  ctx.save();
  ctx.font = `700 ${f(sz, S)} ${FONT}`; ctx.letterSpacing = `${px(3, S)}px`;
  ctx.fillStyle = TEXT; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  while (sz > 20 && ctx.measureText(patUpper).width > w - pad * 2) { sz -= 2; ctx.font = `700 ${f(sz, S)} ${FONT}`; }
  ctx.fillText(patUpper, pad, y);
  ctx.restore();
  y += px(sz + 8, S);

  // Evidence
  if (confEvidence) {
    ctx.save();
    ctx.font = `400 ${f(13, S)} ${FONT}`; ctx.letterSpacing = `${px(0.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(`Confirmed by ${confEvidence}`, pad, y);
    ctx.restore();
    y += px(22, S);
  }

  y += px(8, S);

  // Setup block: modifier · position · count
  if (mod || pos) {
    const setupParts = [mod ? mod.toUpperCase() : null, pos || null, lights.length > 0 ? `${lights.length} ${lights.length === 1 ? 'LIGHT' : 'LIGHTS'}` : null].filter(Boolean);
    ctx.save();
    ctx.font = `500 ${f(16, S)} ${FONT}`; ctx.letterSpacing = `${px(1, S)}px`;
    ctx.fillStyle = TEXT_MID; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(setupParts.join('  ·  '), pad, y);
    ctx.restore();
    y += px(26, S);
  }

  // Full-width divider
  y += px(12, S);
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.14)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  ctx.restore();
  y += px(18, S);

  // NAILED IT — promoted, left-aligned, 28pt
  if (judgment === 'nailed' || judgment === 'close') {
    const jLabel = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
    const jColor = judgment === 'nailed' ? 'rgba(72,186,136,0.90)' : 'rgba(132,158,184,0.60)';
    ctx.save();
    ctx.font = `700 ${f(28, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
    ctx.fillStyle = jColor; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(jLabel, pad, y);
    ctx.restore();
    y += px(34, S);
    ctx.save();
    ctx.font = `500 ${f(11, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.42)'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText('CONFIRMED READ', pad, y);
    ctx.restore();
  }

  // Footer
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  if (branded) ctx.fillText('LIGHT READ · NGW', w - pad, h - px(22, S));
  ctx.restore();

  drawGrain(ctx, w, h);
}

// Variant E — Blueprint Hybrid
// Smaller photo (40%), full-width overhead diagram, light rows below.
export function drawSignalCardE(ctx, data, S) {
  const { pattern, confidence = 0, imageEl: photo, branded = true,
          judgment = null, lights = [], confEvidence = '' } = data;

  const w        = ctx.canvas.width;
  const h        = ctx.canvas.height;
  const pad      = px(36, S);
  const cw       = w - pad * 2;
  const photoH   = Math.round(h * 0.40);
  const pct      = Math.round((confidence || 0) * 100);
  const patUpper = (pattern || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const cc       = confColor(confidence);

  ctx.fillStyle = BG; ctx.fillRect(0, 0, w, h);

  if (photo && photo.complete && photo.naturalWidth > 0) {
    const crop = smartCrop(photo, null, w, photoH);
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w, photoH); ctx.clip();
    ctx.drawImage(photo, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, photoH);
    ctx.restore();
    drawPhotoFade(ctx, photoH, w, px(80, S));
  }

  let y = photoH + px(20, S);

  // Centered series label
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(2.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.32)'; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NGW LIGHT READ', w / 2, y);
  ctx.restore();
  y += px(22, S);

  // Pattern centered, 44pt
  let sz = patUpper.replace(/\s/g, '').length <= 8 ? 44 : patUpper.replace(/\s/g, '').length <= 12 ? 38 : 30;
  ctx.save();
  ctx.font = `700 ${f(sz, S)} ${FONT}`; ctx.letterSpacing = `${px(4, S)}px`;
  ctx.fillStyle = TEXT; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  while (sz > 18 && ctx.measureText(patUpper).width > cw) { sz -= 2; ctx.font = `700 ${f(sz, S)} ${FONT}`; }
  ctx.fillText(patUpper, w / 2, y);
  ctx.restore();

  // pct right-aligned on same baseline
  ctx.save();
  ctx.font = `600 ${f(14, S)} ${FONT}`; ctx.letterSpacing = '0px';
  ctx.fillStyle = cc; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
  ctx.fillText(`${pct}%`, w - pad, y + px(4, S));
  ctx.restore();

  y += px(sz + 10, S);

  // Evidence (centered, compact)
  if (confEvidence) {
    ctx.save();
    ctx.font = `400 ${f(12, S)} ${FONT}`; ctx.letterSpacing = `${px(0.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(`Confirmed by ${confEvidence}`, w / 2, y);
    ctx.restore();
    y += px(20, S);
  }

  // Divider
  y += px(8, S);
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.14)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  ctx.restore();
  y += px(14, S);

  // Full-width overhead diagram
  const diagH = px(220, S);
  drawOverheadDiagram(ctx, pad, y, cw, diagH, lights, S);
  y += diagH + px(14, S);

  // Divider
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.14)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  ctx.restore();
  y += px(14, S);

  // Light rows (up to 2)
  lights.slice(0, 2).forEach((l) => {
    const rowH = drawLightRow(ctx, pad + px(2, S), y, l, S);
    y += rowH + px(10, S);
  });

  // NAILED IT + CONFIRMED READ footer block
  if (judgment === 'nailed' || judgment === 'close') {
    const jLabel = judgment === 'nailed' ? 'NAILED IT' : 'CLOSE READ';
    const jColor = judgment === 'nailed' ? 'rgba(72,186,136,0.88)' : 'rgba(132,158,184,0.60)';
    ctx.save();
    ctx.font = `700 ${f(20, S)} ${FONT}`; ctx.letterSpacing = `${px(2, S)}px`;
    ctx.fillStyle = jColor; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.fillText(jLabel, pad, h - px(36, S));
    ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
    ctx.fillStyle = 'rgba(132,158,184,0.40)';
    ctx.fillText('CONFIRMED READ', pad, h - px(22, S));
    ctx.restore();
  }

  // Brand footer
  ctx.save();
  ctx.font = `500 ${f(10, S)} ${FONT}`; ctx.letterSpacing = `${px(1.5, S)}px`;
  ctx.fillStyle = 'rgba(132,158,184,0.50)'; ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  if (branded) ctx.fillText('LIGHT READ · NGW', w - pad, h - px(22, S));
  ctx.restore();

  drawGrain(ctx, w, h);
}

// ── Download helpers ────────────────────────────────────────────────────────
export function downloadCanvas(canvas, filename) {
  canvas.toBlob(blob => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 'image/png');
}

/**
 * Animate and record a social card as a WebM video for Reels / TikTok.
 * Uses canvas.captureStream + MediaRecorder. Download triggers automatically when done.
 *
 * @param {string} templateId - 'bts' | 'story' | 'summary' | 'carousel'
 * @param {object} opts - same opts as the render functions, minus progress & format
 * @param {number} durationMs - total animation duration (default 3000ms)
 * @returns {Promise<void>}
 */
export function downloadReel(templateId, opts, durationMs = 3000) {
  const fmtKey = templateId === 'story' ? 'STORY' : templateId === 'carousel' ? 'SQUARE' : 'PORTRAIT';
  const fmt    = FORMATS[fmtKey];
  const canvas = document.createElement('canvas');
  canvas.width = fmt.w; canvas.height = fmt.h;
  const ctx = canvas.getContext('2d');

  const S = fmt.w / 1080;
  const renderFn = {
    bts:      (p) => drawSignalCard(ctx, { ...opts, imageEl: opts.photo, progress: p }, S),
    story:    (p) => renderStoryTemplate(ctx, { ...opts, format: fmt, progress: p }),
    summary:  (p) => drawBlueprintCard(ctx, { ...opts, imageEl: opts.photo, progress: p }, S),
    carousel: (p) => renderCarouselSlide(ctx, { ...opts, format: fmt, progress: p }),
  }[templateId];

  if (!renderFn) return Promise.resolve();

  const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
    ? 'video/webm;codecs=vp9'
    : 'video/webm';

  return new Promise((resolve) => {
    const stream   = canvas.captureStream(30);
    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks   = [];

    recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;
      const patSlug = (opts.pattern || 'lighting').replace(/[^a-z0-9]/gi, '-').replace(/-+/g, '-');
      const Pat = patSlug.charAt(0).toUpperCase() + patSlug.slice(1);
      const TPL = { bts: 'Signal-Card', story: 'Story', summary: 'Blueprint', carousel: 'Carousel' };
      a.download = `NGW_${Pat}_${TPL[templateId] || templateId}_reel.webm`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      resolve();
    };

    recorder.start();
    const start = performance.now();

    const tick = () => {
      const p = Math.min(1, (performance.now() - start) / durationMs);
      renderFn(p);
      if (p < 1) requestAnimationFrame(tick);
      else setTimeout(() => recorder.stop(), 100); // flush last frame
    };
    requestAnimationFrame(tick);
  });
}
