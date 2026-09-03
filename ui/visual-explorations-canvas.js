/* visual-explorations-canvas.js — injected into headless page, no modules */
/* Plain ES5-safe JS: no template literals, no import/export               */

var SM = {
  bg:         '#09090b',
  surface:    '#111218',
  text:       'rgba(248,249,252,0.96)',
  textMid:    'rgba(248,249,252,0.60)',
  steel:      'rgba(132,158,184,0.65)',
  steelMid:   'rgba(132,158,184,0.42)',
  steelDim:   'rgba(132,158,184,0.28)',
  steelFaint: 'rgba(132,158,184,0.10)',
  green:      '#48ba88',
  amber:      '#d4a054',
};

var FONT = '"Geist","Inter",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif';

function px(n, S) { return Math.round(n * (S || 1)); }
function f(n, S)  { return px(n, S) + 'px'; }
function fw(w, sz, S) { return w + ' ' + f(sz, S) + ' ' + FONT; }

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y);
  ctx.arcTo(x+w, y, x+w, y+r, r); ctx.lineTo(x+w, y+h-r);
  ctx.arcTo(x+w, y+h, x+w-r, y+h, r); ctx.lineTo(x+r, y+h);
  ctx.arcTo(x, y+h, x, y+h-r, r); ctx.lineTo(x, y+r);
  ctx.arcTo(x, y, x+r, y, r); ctx.closePath();
}

function divider(ctx, y, x1, x2, a) {
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,' + (a || 0.10) + ')';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
  ctx.restore();
}

function photoCover(ctx, img, x, y, w, h, anchorY) {
  if (!img || !img.complete || !img.naturalWidth) return;
  var ay = anchorY == null ? 0.22 : anchorY;
  var iw = img.naturalWidth, ih = img.naturalHeight;
  var ar = w / h, iar = iw / ih;
  var sw, sh, sx, sy;
  if (iar > ar) {
    sh = ih; sw = ih * ar;
    sx = (iw - sw) / 2; sy = 0;
  } else {
    sw = iw; sh = iw / ar;
    sx = 0; sy = Math.max(0, Math.min(ih - sh, (ih - sh) * ay));
  }
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.drawImage(img, sx, sy, sw, sh, x, y, w, h);
  ctx.restore();
}

function photoFade(ctx, bottomY, w, fadeH) {
  var fh = fadeH || 120;
  var g = ctx.createLinearGradient(0, bottomY - fh, 0, bottomY);
  g.addColorStop(0, 'rgba(9,9,11,0)');
  g.addColorStop(1, 'rgba(9,9,11,1)');
  ctx.fillStyle = g;
  ctx.fillRect(0, bottomY - fh, w, fh);
}

function confBar(ctx, x, y, w, pct, S) {
  var h = px(3, S);
  ctx.fillStyle = 'rgba(132,158,184,0.10)';
  roundRect(ctx, x, y, w, h, h/2); ctx.fill();
  ctx.fillStyle = SM.green;
  var fw2 = Math.round(w * Math.min(1, pct / 100));
  if (fw2 > 0) { roundRect(ctx, x, y, fw2, h, h/2); ctx.fill(); }
}

function micro(ctx, x, y, text, S, opts) {
  var o = opts || {};
  var color   = o.color   || SM.steelDim;
  var size    = o.size    || 10;
  var align   = o.align   || 'left';
  var track   = o.track   || 2.5;
  var weight  = o.weight  || '600';
  ctx.save();
  ctx.font = fw(weight, size, S);
  ctx.letterSpacing = px(track, S) + 'px';
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text.toUpperCase(), x, y);
  ctx.restore();
}

function lightRow(ctx, x, y, light, S) {
  var roles = { key: SM.amber, fill: '#7da3c8', rim: SM.green };
  var rc = roles[(light.role || '').toLowerCase()] || SM.steelMid;
  var r = px(5, S);
  ctx.beginPath();
  ctx.arc(x + r, y - r, r, 0, Math.PI * 2);
  ctx.fillStyle = rc; ctx.fill();
  ctx.save();
  ctx.textBaseline = 'alphabetic';
  ctx.font = fw('700', 11, S);
  ctx.letterSpacing = px(1.5, S) + 'px';
  ctx.fillStyle = rc; ctx.textAlign = 'left';
  ctx.fillText((light.role || 'KEY').toUpperCase(), x + px(15, S), y);
  ctx.font = fw('600', 18, S);
  ctx.letterSpacing = '0px';
  ctx.fillStyle = SM.text;
  ctx.fillText(light.modifier || '', x + px(15, S), y + px(22, S));
  ctx.font = fw('400', 13, S);
  ctx.fillStyle = SM.steel;
  ctx.fillText(light.position || '', x + px(15, S), y + px(40, S));
  ctx.restore();
  return px(58, S);
}

function diagram(ctx, x, y, w, h, S) {
  ctx.save();
  ctx.fillStyle = 'rgba(15,17,26,0.85)';
  roundRect(ctx, x, y, w, h, px(8, S)); ctx.fill();
  ctx.strokeStyle = 'rgba(132,158,184,0.12)';
  ctx.lineWidth = 1; ctx.stroke();

  var cx = x + w / 2, cy = y + h * 0.54;

  /* subject */
  ctx.beginPath(); ctx.arc(cx, cy, px(10, S), 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(132,158,184,0.48)'; ctx.lineWidth = px(1.5, S); ctx.stroke();
  ctx.fillStyle = 'rgba(132,158,184,0.14)'; ctx.fill();

  /* camera — bottom center */
  var camX = cx, camY = y + h * 0.84;
  ctx.beginPath(); ctx.arc(camX, camY, px(7, S), 0, Math.PI * 2);
  ctx.strokeStyle = SM.steelDim; ctx.lineWidth = px(1.5, S); ctx.stroke();

  /* camera → subject (dashed) */
  ctx.save();
  ctx.setLineDash([px(3, S), px(5, S)]);
  ctx.strokeStyle = 'rgba(132,158,184,0.16)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(camX, camY - px(8, S)); ctx.lineTo(cx, cy + px(10, S)); ctx.stroke();
  ctx.restore();

  /* key light — upper left */
  var klX = x + w * 0.17, klY = y + h * 0.20;
  ctx.save();
  ctx.shadowColor = SM.amber; ctx.shadowBlur = px(12, S);
  ctx.beginPath(); ctx.arc(klX, klY, px(9, S), 0, Math.PI * 2);
  ctx.fillStyle = SM.amber; ctx.fill();
  ctx.restore();

  /* key → subject (dashed amber) */
  ctx.save();
  ctx.setLineDash([px(4, S), px(5, S)]);
  ctx.strokeStyle = 'rgba(212,160,84,0.32)'; ctx.lineWidth = px(1.5, S);
  ctx.beginPath(); ctx.moveTo(klX + px(9, S), klY + px(5, S)); ctx.lineTo(cx - px(8, S), cy - px(8, S)); ctx.stroke();
  ctx.restore();

  micro(ctx, x + px(8, S), y + h - px(9, S), 'key', S, { color: 'rgba(212,160,84,0.50)', size: 9, track: 1.5 });
  micro(ctx, cx + px(14, S), cy - px(5, S), 'subject', S, { color: SM.steelDim, size: 9, track: 1.5 });
  ctx.restore();
}

function brandMark(ctx, x, y, S, opts) {
  var o = opts || {};
  micro(ctx, x, y, 'No Guesswork Lighting', S,
    { color: o.color || SM.steelDim, size: 8, align: o.align || 'right', track: 0.8, weight: '500' });
}

function brackets(ctx, x, y, w, h, size, S) {
  var s = px(size, S);
  ctx.save();
  ctx.strokeStyle = 'rgba(132,158,184,0.22)'; ctx.lineWidth = px(1, S);
  ctx.beginPath(); ctx.moveTo(x, y+s); ctx.lineTo(x, y); ctx.lineTo(x+s, y); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x+w-s, y); ctx.lineTo(x+w, y); ctx.lineTo(x+w, y+s); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x, y+h-s); ctx.lineTo(x, y+h); ctx.lineTo(x+s, y+h); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x+w-s, y+h); ctx.lineTo(x+w, y+h); ctx.lineTo(x+w, y+h-s); ctx.stroke();
  ctx.restore();
}

/* ── EA-1 · Editorial Proof — Hard Edge + Corner Brackets ────────────────── */
window.renderEA1 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.60);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);
  photoFade(ctx, photoH, W, px(130, S));
  brackets(ctx, px(16, S), px(16, S), W - px(32, S), photoH - px(16, S), 20, S);

  var sY = photoH + px(26, S);
  micro(ctx, pad, sY, 'NGW LIGHT READ', S, { size: 9, track: 3 });
  micro(ctx, W - pad, sY, '· 01', S, { align: 'right', size: 9, track: 2 });

  var patY = sY + px(40, S);
  ctx.save();
  ctx.font = fw('800', 56, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, patY);
  ctx.restore();

  ctx.save();
  ctx.font = fw('700', 15, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W - pad, patY);
  ctx.restore();

  var evidY = patY + px(20, S);
  ctx.save();
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, evidY);
  ctx.restore();

  divider(ctx, evidY + px(18, S), pad, W - pad);

  var sy = evidY + px(34, S);
  micro(ctx, pad, sy, 'KEY LIGHT', S, { color: 'rgba(212,160,84,0.55)', size: 9, track: 2.5 });
  sy += px(18, S);
  ctx.save();
  ctx.font = fw('700', 20, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Strip Box', pad, sy);
  ctx.restore();
  sy += px(18, S);
  ctx.save();
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  ctx.fillText('Camera-left \xb7 high source \xb7 1 light', pad, sy);
  ctx.restore();

  divider(ctx, sy + px(18, S), pad, W - pad);

  var jy = sy + px(36, S);
  ctx.save();
  ctx.font = fw('800', 30, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(16, S);
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', W - pad, jy);
  ctx.restore();
  ctx.save();
  ctx.font = fw('500', 11, S); ctx.fillStyle = SM.steelMid;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('CONFIRMED READ', W - pad, jy + px(18, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── EA-2 · Editorial Proof — Gradient Bridge + Two-Column ───────────────── */
window.renderEA2 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.65);
  photoCover(ctx, img, 0, 0, W, photoH, 0.18);
  photoFade(ctx, photoH, W, px(140, S));

  /* Over-photo header */
  ctx.save();
  ctx.font = fw('600', 10, S); ctx.letterSpacing = px(3, S) + 'px';
  ctx.fillStyle = 'rgba(132,158,184,0.36)';
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NGW LIGHT READ', pad, px(36, S));
  ctx.fillStyle = SM.green; ctx.textAlign = 'right';
  ctx.fillText('95%', W - pad, px(36, S));
  ctx.restore();

  var patY = photoH + px(22, S);
  ctx.save();
  ctx.font = fw('800', 54, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, patY);
  var patTextW = ctx.measureText('Rembrandt').width;
  ctx.restore();

  /* Green accent rule */
  ctx.fillStyle = SM.green;
  ctx.fillRect(pad, patY + px(5, S), Math.min(patTextW, px(320, S)), px(2.5, S));

  var evidY = patY + px(24, S);
  ctx.save();
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, evidY);
  ctx.restore();

  divider(ctx, evidY + px(18, S), pad, W - pad);

  /* Two-column */
  var colY = evidY + px(34, S);
  micro(ctx, pad, colY, 'KEY LIGHT', S, { color: 'rgba(212,160,84,0.55)', size: 9, track: 2 });
  ctx.save();
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  ctx.font = fw('700', 19, S); ctx.fillStyle = SM.text;
  ctx.fillText('Strip Box', pad, colY + px(20, S));
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
  ctx.fillText('Camera-left \xb7 high source', pad, colY + px(38, S));
  ctx.fillText('1 light', pad, colY + px(54, S));
  ctx.restore();

  ctx.save();
  ctx.font = fw('800', 32, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(20, S);
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', W - pad, colY + px(22, S));
  ctx.restore();
  ctx.save();
  ctx.font = fw('500', 11, S); ctx.fillStyle = SM.steelMid;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('CONFIRMED READ', W - pad, colY + px(40, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── EA-3 · Editorial Proof — Role Dot + Ghost Watermark ─────────────────── */
window.renderEA3 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.58);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);

  /* Ghost watermark under photo */
  ctx.save();
  ctx.globalAlpha = 0.04;
  ctx.font = fw('900', 160, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('REMBRANDT', W / 2, photoH * 0.52);
  ctx.restore();

  photoFade(ctx, photoH, W, px(120, S));

  var sY = photoH + px(22, S);
  micro(ctx, pad, sY, 'NGW LIGHT READ', S, { size: 9, track: 3 });

  var patY = sY + px(36, S);
  ctx.save();
  ctx.font = fw('800', 52, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, patY);
  ctx.restore();
  ctx.save();
  ctx.font = fw('700', 14, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W - pad, patY);
  ctx.restore();

  ctx.save();
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, patY + px(20, S));
  ctx.restore();

  divider(ctx, patY + px(38, S), pad, W - pad);

  var ry = patY + px(52, S);
  micro(ctx, pad, ry, 'LIGHTS \xb7 1', S, { size: 9, track: 3 });
  ry += px(8, S);

  lightRow(ctx, pad, ry + px(14, S),
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);
  ry += px(62, S);

  ctx.save();
  ctx.font = fw('400', 11, S); ctx.fillStyle = 'rgba(132,158,184,0.30)';
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('catchlight: strip box', pad + px(22, S), ry);
  ctx.restore();

  divider(ctx, ry + px(16, S), pad, W - pad);

  var jy = ry + px(32, S);
  ctx.save();
  ctx.font = fw('800', 26, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(14, S);
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', pad, jy);
  var niW = ctx.measureText('NAILED IT').width;
  ctx.restore();
  ctx.save();
  ctx.font = fw('500', 11, S); ctx.fillStyle = SM.steelMid;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText(' \xb7 CONFIRMED READ', pad + niW + px(2, S), jy);
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── TP-1 · Technical Plate — Centered + Diagram + Row ───────────────────── */
window.renderTP1 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.46);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);
  photoFade(ctx, photoH, W, px(110, S));

  var sY = photoH + px(20, S);
  micro(ctx, W / 2, sY, 'NGW LIGHT READ', S, { size: 9, track: 3.5, align: 'center' });

  var patY = sY + px(36, S);
  ctx.save();
  ctx.font = fw('800', 46, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', W / 2, patY);
  ctx.restore();

  var confY = patY + px(22, S);
  ctx.save();
  ctx.font = fw('800', 22, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W / 2 - px(30, S), confY);
  ctx.font = fw('400', 14, S); ctx.fillStyle = SM.steel;
  ctx.textAlign = 'left';
  ctx.fillText('Confidence', W / 2 - px(10, S), confY);
  ctx.restore();

  confBar(ctx, pad * 2, confY + px(8, S), W - pad * 4, 95, S);

  ctx.save();
  ctx.font = 'italic ' + fw('400', 12, S); ctx.fillStyle = 'rgba(132,158,184,0.52)';
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', W / 2, confY + px(24, S));
  ctx.restore();

  divider(ctx, confY + px(40, S), pad, W - pad);

  var diagY = confY + px(52, S);
  var diagH = px(200, S);
  diagram(ctx, pad, diagY, W - pad * 2, diagH, S);

  divider(ctx, diagY + diagH + px(16, S), pad, W - pad);

  var lrY = diagY + diagH + px(30, S);
  lightRow(ctx, pad, lrY,
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);

  ctx.save();
  ctx.font = fw('400', 11, S); ctx.fillStyle = 'rgba(132,158,184,0.30)';
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('catchlight: strip box', pad + px(22, S), lrY + px(58, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── TP-2 · Technical Plate — Diagram Dominant ───────────────────────────── */
window.renderTP2 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.40);
  photoCover(ctx, img, 0, 0, W, photoH, 0.18);
  photoFade(ctx, photoH, W, px(88, S));

  /* Left accent bar */
  ctx.fillStyle = SM.green;
  ctx.fillRect(0, 0, px(3, S), photoH);

  var sY = photoH + px(20, S);
  micro(ctx, pad, sY, 'NGW LIGHT READ', S, { size: 9, track: 3 });

  var patY = sY + px(30, S);
  ctx.save();
  ctx.font = fw('800', 42, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, patY);
  ctx.restore();
  ctx.save();
  ctx.font = fw('800', 28, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W - pad, patY);
  ctx.restore();
  ctx.save();
  ctx.font = fw('400', 10, S); ctx.fillStyle = SM.steelDim;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('CONFIDENCE', W - pad, patY + px(16, S));
  ctx.restore();

  confBar(ctx, pad, patY + px(22, S), W - pad * 2, 95, S);

  ctx.save();
  ctx.font = 'italic ' + fw('400', 12, S); ctx.fillStyle = SM.steelMid;
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, patY + px(40, S));
  ctx.restore();

  divider(ctx, patY + px(56, S), pad, W - pad);

  var diagY = patY + px(68, S);
  var diagH = px(240, S);
  diagram(ctx, pad, diagY, W - pad * 2, diagH, S);

  var lrY = diagY + diagH + px(22, S);
  lightRow(ctx, pad, lrY,
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);
  micro(ctx, W - pad, lrY, '1 LIGHT', S, { align: 'right', size: 9, track: 2 });

  ctx.save();
  ctx.font = fw('700', 16, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', pad, H - px(24, S));
  ctx.restore();
  brandMark(ctx, W - pad, H - px(24, S), S);
};

/* ── TP-3 · Technical Plate — Evidence Hierarchy ─────────────────────────── */
window.renderTP3 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.50);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);
  photoFade(ctx, photoH, W, px(120, S));

  /* Confidence badge over photo */
  ctx.save();
  ctx.fillStyle = 'rgba(9,9,11,0.70)';
  roundRect(ctx, W - pad - px(58, S), px(18, S), px(58, S), px(32, S), px(6, S)); ctx.fill();
  ctx.font = fw('800', 17, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('95%', W - pad - px(29, S), px(34, S));
  ctx.restore();

  var sY = photoH + px(20, S);
  micro(ctx, pad, sY, 'NGW LIGHT READ', S, { size: 9, track: 3 });

  var patY = sY + px(32, S);
  ctx.save();
  ctx.font = fw('800', 50, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, patY);
  ctx.restore();

  divider(ctx, patY + px(14, S), pad, W - pad);

  var ey = patY + px(30, S);
  var evids = [
    'Catchlights confirm key direction',
    'Shadow geometry confirms pattern',
  ];
  for (var i = 0; i < evids.length; i++) {
    ctx.beginPath();
    ctx.arc(pad + px(4, S), ey - px(4, S), px(3, S), 0, Math.PI * 2);
    ctx.fillStyle = SM.green; ctx.fill();
    ctx.save();
    ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steel;
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.fillText(evids[i], pad + px(14, S), ey);
    ctx.restore();
    ey += px(22, S);
  }

  divider(ctx, ey + px(8, S), pad, W - pad);
  ey += px(22, S);

  lightRow(ctx, pad, ey,
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);
  ey += px(62, S);

  divider(ctx, ey, pad, W - pad);
  ey += px(20, S);

  ctx.save();
  ctx.font = fw('800', 22, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(12, S);
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', pad, ey + px(20, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── MS-1 · Minimal Social — Photo Hero ──────────────────────────────────── */
window.renderMS1 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.73);
  photoCover(ctx, img, 0, 0, W, photoH, 0.18);
  photoFade(ctx, photoH, W, px(100, S));

  var baseY = photoH + px(18, S);
  ctx.save();
  ctx.font = fw('800', 42, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', pad, baseY);
  ctx.restore();
  ctx.save();
  ctx.font = fw('800', 16, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W - pad, baseY);
  ctx.restore();

  ctx.save();
  ctx.font = fw('400', 12, S); ctx.fillStyle = SM.steelMid;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, baseY + px(18, S));
  ctx.restore();

  divider(ctx, baseY + px(36, S), pad, W - pad, 0.08);

  ctx.save();
  ctx.font = fw('700', 13, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Nailed It', pad, baseY + px(54, S));
  ctx.restore();

  brandMark(ctx, W - pad, baseY + px(54, S), S);
};

/* ── MS-2 · Minimal Social — Centered Proof ──────────────────────────────── */
window.renderMS2 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(52, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.66);
  photoCover(ctx, img, 0, 0, W, photoH, 0.18);
  photoFade(ctx, photoH, W, px(150, S));

  micro(ctx, W / 2, px(32, S), 'NGW LIGHT READ', S,
    { color: 'rgba(132,158,184,0.26)', size: 9, track: 3.5, align: 'center' });

  var ay = photoH + px(18, S);
  ctx.save();
  ctx.font = fw('800', 50, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', W / 2, ay);
  ctx.restore();

  ay += px(18, S);
  ctx.save();
  ctx.font = fw('700', 16, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95% Confidence', W / 2, ay);
  ctx.restore();
  ay += px(12, S);
  confBar(ctx, pad, ay, W - pad * 2, 95, S);
  ay += px(18, S);

  divider(ctx, ay, pad, W - pad, 0.08);
  ay += px(18, S);

  ctx.save();
  ctx.font = fw('800', 22, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(14, S);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', W / 2, ay + px(14, S));
  ctx.restore();

  brandMark(ctx, W / 2, H - px(18, S), S, { align: 'center' });
};

/* ── BH-1 · Blueprint Hybrid — Diagram + Rows ────────────────────────────── */
window.renderBH1 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.37);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);
  photoFade(ctx, photoH, W, px(80, S));

  var sY = photoH + px(20, S);
  micro(ctx, W / 2, sY, 'LIGHT READ', S, { align: 'center', size: 9, track: 3 });

  var patY = sY + px(28, S);
  ctx.save();
  ctx.font = fw('800', 44, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', W / 2, patY);
  ctx.restore();

  ctx.save();
  ctx.font = fw('700', 18, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', pad, patY + px(22, S));
  ctx.font = fw('400', 12, S); ctx.fillStyle = SM.steelDim;
  ctx.fillText('  confidence', pad + px(40, S), patY + px(22, S));
  ctx.restore();
  confBar(ctx, pad, patY + px(30, S), W - pad * 2, 95, S);

  divider(ctx, patY + px(44, S), pad, W - pad);

  var diagY = patY + px(58, S);
  var diagH = px(240, S);
  diagram(ctx, pad, diagY, W - pad * 2, diagH, S);

  divider(ctx, diagY + diagH + px(16, S), pad, W - pad);

  var lrY = diagY + diagH + px(30, S);
  lightRow(ctx, pad, lrY,
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);

  ctx.save();
  ctx.font = fw('400', 11, S); ctx.fillStyle = 'rgba(132,158,184,0.30)';
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  ctx.fillText('catchlight: strip box', pad + px(22, S), lrY + px(58, S));
  ctx.restore();

  var jy = lrY + px(78, S);
  ctx.save();
  ctx.font = fw('700', 16, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', pad, jy);
  ctx.restore();
  ctx.save();
  ctx.font = fw('400', 11, S); ctx.fillStyle = SM.steelMid;
  ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
  ctx.fillText('CONFIRMED READ', pad, jy + px(16, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── BH-2 · Blueprint Hybrid — Diagram Hero ──────────────────────────────── */
window.renderBH2 = function(ctx, img, W, H) {
  var S = W / 1080, pad = px(44, S);
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);

  var photoH = Math.round(H * 0.41);
  photoCover(ctx, img, 0, 0, W, photoH, 0.20);
  photoFade(ctx, photoH, W, px(90, S));

  /* Slightly blued surface for technical feel */
  ctx.fillStyle = 'rgba(13,15,22,0.75)';
  ctx.fillRect(0, photoH, W, H - photoH);

  var hY = photoH + px(18, S);
  micro(ctx, pad, hY, 'NGW LIGHT READ', S, { size: 9, track: 3 });
  micro(ctx, W - pad, hY, 'BLUEPRINT', S, { align: 'right', size: 9, track: 2 });

  var patY = hY + px(26, S);
  ctx.save();
  ctx.textBaseline = 'alphabetic';
  ctx.font = fw('800', 40, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'left'; ctx.fillText('Rembrandt', pad, patY);
  ctx.font = fw('800', 20, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'right'; ctx.fillText('95%', W - pad, patY);
  ctx.restore();
  confBar(ctx, pad, patY + px(8, S), W - pad * 2, 95, S);

  divider(ctx, patY + px(22, S), pad, W - pad);

  var diagY = patY + px(34, S);
  var diagH = px(260, S);
  diagram(ctx, pad, diagY, W - pad * 2, diagH, S);

  divider(ctx, diagY + diagH + px(14, S), pad, W - pad);

  var lrY = diagY + diagH + px(26, S);
  lightRow(ctx, pad, lrY,
    { role: 'key', modifier: 'Strip Box', position: 'Camera-left \xb7 high source' }, S);

  ctx.save();
  ctx.font = fw('400', 11, S); ctx.fillStyle = SM.steelDim;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights + shadow geometry', pad, lrY + px(62, S));
  ctx.restore();

  brandMark(ctx, W - pad, H - px(20, S), S);
};

/* ── SR-1 · Story/Reel — Cinematic Reveal ────────────────────────────────── */
window.renderSR1 = function(ctx, img, W, H) {
  var S = W / 1080;
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);
  photoCover(ctx, img, 0, 0, W, H, 0.16);

  var ov = ctx.createLinearGradient(0, 0, 0, H);
  ov.addColorStop(0,    'rgba(9,9,11,0.30)');
  ov.addColorStop(0.20, 'rgba(9,9,11,0.04)');
  ov.addColorStop(0.40, 'rgba(9,9,11,0.14)');
  ov.addColorStop(0.52, 'rgba(9,9,11,0.66)');
  ov.addColorStop(0.62, 'rgba(9,9,11,0.83)');
  ov.addColorStop(0.76, 'rgba(9,9,11,0.92)');
  ov.addColorStop(1,    'rgba(9,9,11,0.97)');
  ctx.fillStyle = ov; ctx.fillRect(0, 0, W, H);

  micro(ctx, W / 2, px(82, S), 'Lighting Breakdown', S,
    { color: 'rgba(132,158,184,0.38)', size: 13, align: 'center', track: 3 });

  var heroY = Math.round(H * 0.52);
  ctx.save();
  ctx.font = fw('800', 80, S);
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(28, S);
  ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Rembrandt', W / 2, heroY);
  ctx.restore();

  var ruleY = heroY + px(14, S);
  var rg = ctx.createLinearGradient(W/2 - px(60,S), 0, W/2 + px(60,S), 0);
  rg.addColorStop(0, 'rgba(132,158,184,0)');
  rg.addColorStop(0.5, 'rgba(132,158,184,0.40)');
  rg.addColorStop(1, 'rgba(132,158,184,0)');
  ctx.fillStyle = rg;
  ctx.fillRect(W/2 - px(60,S), ruleY, px(120,S), px(2,S));

  var confY = ruleY + px(42, S);
  ctx.save();
  ctx.font = fw('800', 52, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(14, S);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W / 2, confY);
  ctx.restore();

  micro(ctx, W / 2, confY + px(14, S), 'Confidence', S,
    { color: SM.steelMid, size: 13, align: 'center', track: 2.5 });
  confBar(ctx, W/2 - px(160,S), confY + px(28,S), px(320,S), 95, S);

  var setupY = confY + px(74, S);
  micro(ctx, W / 2, setupY, 'KEY LIGHT', S,
    { color: 'rgba(212,160,84,0.75)', size: 10, align: 'center', track: 2.5 });
  ctx.save();
  ctx.font = fw('600', 20, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Strip Box \xb7 Camera-left \xb7 high source', W / 2, setupY + px(20, S));
  ctx.restore();
  ctx.save();
  ctx.font = fw('400', 13, S); ctx.fillStyle = SM.steelDim;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('1 light', W / 2, setupY + px(38, S));
  ctx.restore();

  var jy = Math.round(H * 0.87);
  ctx.save();
  ctx.font = fw('800', 24, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(16, S);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT \xb7 CONFIRMED READ', W / 2, jy);
  ctx.restore();

  micro(ctx, W / 2, H - px(48, S), 'NGW LIGHT READ', S,
    { color: 'rgba(132,158,184,0.20)', size: 10, align: 'center', track: 2.5 });
};

/* ── SR-2 · Story/Reel — Proof Stamp Top ─────────────────────────────────── */
window.renderSR2 = function(ctx, img, W, H) {
  var S = W / 1080;
  ctx.fillStyle = SM.bg; ctx.fillRect(0, 0, W, H);
  photoCover(ctx, img, 0, 0, W, H, 0.14);

  var ov2 = ctx.createLinearGradient(0, 0, 0, H);
  ov2.addColorStop(0,    'rgba(9,9,11,0.72)');
  ov2.addColorStop(0.12, 'rgba(9,9,11,0.18)');
  ov2.addColorStop(0.30, 'rgba(9,9,11,0.04)');
  ov2.addColorStop(0.54, 'rgba(9,9,11,0.40)');
  ov2.addColorStop(0.70, 'rgba(9,9,11,0.76)');
  ov2.addColorStop(1,    'rgba(9,9,11,0.96)');
  ctx.fillStyle = ov2; ctx.fillRect(0, 0, W, H);

  var stampY = px(72, S);
  ctx.save();
  ctx.font = fw('800', 28, S); ctx.fillStyle = SM.green;
  ctx.shadowColor = SM.green; ctx.shadowBlur = px(20, S);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('NAILED IT', W / 2, stampY);
  ctx.restore();
  micro(ctx, W / 2, stampY + px(16, S), 'Confirmed Read', S,
    { color: SM.steelMid, size: 11, align: 'center', track: 1.5, weight: '500' });

  var heroY = Math.round(H * 0.62);
  ctx.save();
  ctx.font = fw('800', 72, S); ctx.fillStyle = SM.text;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('REMBRANDT', W / 2, heroY);
  ctx.restore();

  ctx.save();
  ctx.font = fw('400', 16, S); ctx.fillStyle = SM.steelMid;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Confirmed by catchlights', W / 2, heroY + px(26, S));
  ctx.restore();
  ctx.save();
  ctx.font = fw('700', 18, S); ctx.fillStyle = SM.green;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('95%', W / 2, heroY + px(52, S));
  ctx.restore();

  ctx.save();
  ctx.font = fw('400', 14, S); ctx.fillStyle = SM.steelDim;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillText('Key Light \xb7 Strip Box \xb7 Camera-left \xb7 1 light', W / 2, heroY + px(82, S));
  ctx.restore();

  micro(ctx, W / 2, H - px(52, S), 'No Guesswork Lighting', S,
    { color: 'rgba(132,158,184,0.18)', size: 10, align: 'center', track: 1.5, weight: '500' });
};
