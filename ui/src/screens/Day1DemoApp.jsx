import { useState, useEffect, useRef, useCallback } from 'react';
import HomeScreen from './studio/_core/HomeScreen';
import ProcessingScreen from './studio/_core/ProcessingScreen';
import ResultScreen from './studio/_core/ResultScreen';
import SetupScreen from './studio/_core/SetupScreen';
import Day1ShootScreen from './studio/_adjacent/Day1ShootScreen';
import StudioLoginScreen from './studio/_adjacent/StudioLoginScreen';
import FitToViewport from './studio/_shared/FitToViewport';
import Day1SettingsScreen from './studio/_deferred/Day1SettingsScreen';
import RecipeScreen from './studio/_core/RecipeScreen';
import SavedSetupsScreen from './studio/_core/SavedSetupsScreen';
import SessionLogScreen from './studio/_core/SessionLogScreen';
import VideoFrameCapture from '../components/VideoFrameCapture';
import LookLibraryScreen from './studio/_core/LookLibraryScreen';
import ClientBriefScreen from './studio/_core/ClientBriefScreen';
import BuildWizardScreen from './studio/_core/BuildWizardScreen';
import MyKitScreen from './studio/_core/MyKitScreen';
import StudioLabWrapper from './studio/_core/StudioLabWrapper';
import RoomPlannerWrapper from './studio/_core/RoomPlannerWrapper';
import OnboardingScreen from './studio/_adjacent/OnboardingScreen';
import ShotMatchAdapter from './studio/_adjacent/ShotMatchAdapter';
import { analyzeImage, shootMatch } from '../data/labApi';
import { getUser, clearAuth, loadPreferences } from '../data/authApi';
import usePlan from '../hooks/usePlan';
import { PLAN_LABELS } from '../data/planStore';
import { steel, C, FONT_SMOOTH as FS, VIEWFINDER_INNER_SHADOW, GLASS_REFLECTION, LENS_VIGNETTE, SCREEN_BG } from '../theme/studioMatte';
import { Panel, CtaButton, HomeIndicator } from './studio/_core/components';
import { tapHaptic, warnHaptic } from '../utils/haptics';
import { softClickSound, navSlideSound } from '../utils/sounds';
import { LAYOUT_DESKTOP_MIN, TABLET_MIN_WIDTH, useMinWidth } from '../utils/useIsDesktop';
import { pushScreen, popScreen } from '../utils/screenHistory';
import { applyTheme } from '../data/themeStore';
import MatteBackground from './studio/_shared/MatteBackground';

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MB

/** Downsample an image file via canvas if it exceeds the size limit. */
function downsampleImage(file, maxBytes) {
  return new Promise((resolve) => {
    if (file.size <= maxBytes) return resolve(file);
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      let { width, height } = img;
      // Scale factor to roughly hit target size (JPEG ~8:1 from raw pixels)
      const ratio = Math.sqrt(maxBytes / file.size);
      width = Math.round(width * ratio);
      height = Math.round(height * ratio);
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, width, height);
      canvas.toBlob(
        (blob) => {
          if (!blob) return resolve(file);
          const smaller = new File([blob], file.name, { type: 'image/jpeg' });
          // If still too big, recurse with lower quality
          if (smaller.size > maxBytes) {
            canvas.toBlob(
              (blob2) => resolve(blob2 ? new File([blob2], file.name, { type: 'image/jpeg' }) : smaller),
              'image/jpeg', 0.6
            );
          } else {
            resolve(smaller);
          }
        },
        'image/jpeg', 0.82
      );
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

/**
 * Map a BuildWizard `onComplete` payload → /api/shoot-match request body.
 *
 * Wizard emits internal enum codes (e.g. mood="beauty", environment="studio_medium",
 * gearMode="my_gear"|"best_setup") — the shoot-match route's MOOD_MAP /
 * ENVIRONMENT_MAP already accept these as identity keys.  Two translations
 * are needed:
 *   - gearMode:  my_gear → myGear   |   best_setup → anyGear
 *   - gear:      flatten lights[] + modifiers[] into a single gear list
 *
 * Defensive defaults: mood/environment are required by the server; fall back
 * to sensible values if the wizard ever submits without them.
 */
function wizardPayloadToShootMatch(payload) {
  const gear = [
    ...(Array.isArray(payload.lights) ? payload.lights : []),
    ...(Array.isArray(payload.modifiers) ? payload.modifiers : []),
  ];
  const gearMode = payload.gearMode === 'my_gear' ? 'myGear' : 'anyGear';
  return {
    subject: payload.subject || 'headshot',
    mood: payload.mood || 'natural',
    environment: payload.environment || 'studio_medium',
    ceiling: payload.ceiling || 'normal',
    gearMode,
    gear,
    skinTone: payload.skinTone || null,
  };
}

/**
 * Day 1 Demo App
 * Studio Matte design — matches Figma prototype (file: YQgGd8KZyZoXzZwJV7p4b6, Studio Matte Theme page)
 * Flow: Home → Processing → Result (High/Low confidence) → Save Setup
 *
 * Wired to real analysis engine: POST /api/lab/analyze
 */

/**
 * Display rule for lighting patterns + modifiers: capital first letter on
 * each word, no underscores (Title Case — e.g. "ring_light" → "Ring Light",
 * "beauty_dish" → "Beauty Dish", "softbox_rect" → "Softbox Rect").
 */
function toTitleCase(str) {
  if (!str) return '';
  return String(str)
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, c => c.toUpperCase());
}

// Engine modifier slugs → photographer-friendly display names.
// Used so result UIs never show raw tokens like "softbox_rect" or
// the awkward title-cased "Softbox Rect".
const MODIFIER_DISPLAY = {
  softbox_rect:    'Rectangular Softbox',
  softbox_oct:     'Octa Softbox',
  octabox:         'Octa Softbox',
  beauty_dish:     'Beauty Dish',
  ring_light:      'Ring Light',
  strip_box:       'Strip Box',
  stripbox:        'Strip Box',
  umbrella:        'Umbrella',
  umbrella_shoot:  'Shoot-Through Umbrella',
  umbrella_bounce: 'Bounce Umbrella',
  parabolic:       'Parabolic Reflector',
  hard_source:     'Bare Hard Source',
  bare_bulb:       'Bare Bulb',
  bare_strobe:     'Bare Strobe',
  reflector:       'Reflector',
  scrim:           'Scrim / Diffuser',
  window:          'Window Light',
};

function prettyModifierLabel(raw) {
  if (!raw) return '';
  const key = String(raw).toLowerCase().trim().replace(/\s+/g, '_');
  if (MODIFIER_DISPLAY[key]) return MODIFIER_DISPLAY[key];
  // Fallback: cleanup engine slug heuristically.
  // "softbox rect" / "rect softbox" → "Rectangular Softbox"
  const lc = String(raw).toLowerCase();
  if (lc.includes('softbox') && lc.includes('rect')) return 'Rectangular Softbox';
  if (lc.includes('softbox') && (lc.includes('oct') || lc.includes('octa'))) return 'Octa Softbox';
  if (lc.includes('softbox') && lc.includes('strip')) return 'Strip Box';
  return toTitleCase(raw);
}

function displayPattern(name) {
  if (!name) return 'Unknown';
  return toTitleCase(name);
}

/** Map API response → ResultScreen prop shape */
function mapApiResult(data) {
  const li = data.lighting_inference || {};
  const ci = li.catchlight_intelligence || {};
  const sd = data.signal_diagnostics || {};
  const signals = sd.signals || {};

  // Confidence: API returns 0–1 float → display as 0–100 int
  const confidence = Math.round((data.authoritative_confidence || 0) * 100);
  const pattern = displayPattern(data.authoritative_pattern);
  // Compound pattern: when a tonal overlay (low_key, high_key) overrides
  // a geometric base, show the geometry as a subtitle so photographers
  // see both classification levels (e.g. "Low Key · Rembrandt geometry").
  const geometricBase = data.geometric_base ? displayPattern(data.geometric_base) : null;

  // Meta pills — short descriptors from lighting inference.  Pattern/modifier
  // display rule: Title Case, no underscores.
  const fillPill = (() => {
    const f = li.fill_method_text || '';
    if (!f || f === 'none') return null;
    const label = f === 'bilateral' ? 'Bilateral Fill'
      : f === 'unilateral' ? 'Unilateral Fill'
      : f === 'bounce'     ? 'Bounce Fill'
      : null;
    return label;
  })();
  const meta = [
    li.key_position_text ? toTitleCase(li.key_position_text) : null,
    li.modifier_family   ? prettyModifierLabel(li.modifier_family) : null,
    li.light_count ? `${li.light_count} light${li.light_count !== 1 ? 's' : ''}` : null,
    fillPill,
    // Environment only if non-studio (studio is assumed, not informative as a pill)
    li.detected_environment && li.detected_environment !== 'studio'
      ? toTitleCase(li.detected_environment) : null,
  ].filter(Boolean);

  // Pattern candidates — use real resolver output from engine.
  // API returns data.pattern_candidates with primary_candidate + alternate_candidates,
  // each carrying an actual confidence value from the resolver stack.
  // Fall back to legacy signal_diagnostics proxies only when resolver data is absent.
  const pc = data.pattern_candidates || {};
  const pcAlternates = pc.alternate_candidates || [];
  const candidates = [{ name: pattern, score: confidence }];

  for (const alt of pcAlternates.slice(0, 2)) {
    const altName = displayPattern(alt.pattern);
    if (!altName) continue;
    if (altName.toLowerCase() === candidates[0].name.toLowerCase()) continue;
    const altScore = Math.round((alt.confidence || 0) * 100);
    // Only show alternate if it has a meaningfully different score (avoid near-dupes)
    if (altScore > 0 && altScore < confidence) {
      candidates.push({ name: altName, score: altScore });
    }
  }

  // Legacy fallbacks if resolver gave no alternates.
  // Guard against junk placeholders (empty / "unknown" / "none") — we'd rather
  // show a single real candidate than a fake alternate labelled "Unknown".
  const isJunkPattern = (p) => {
    const s = (p || '').toLowerCase().trim();
    return !s || s === 'unknown' || s === 'none' || s === 'n/a';
  };
  if (candidates.length < 2) {
    const sdFinal = sd.final_pattern || '';
    if (!isJunkPattern(sdFinal) && sdFinal !== data.authoritative_pattern) {
      candidates.push({ name: displayPattern(sdFinal), score: Math.round(confidence * 0.65) });
    }
  }
  if (candidates.length < 2) {
    const shadowPassPattern = signals.shadow_pass_pattern || '';
    const existingNames = candidates.map(c => c.name.toLowerCase());
    if (!isJunkPattern(shadowPassPattern) && !existingNames.includes(displayPattern(shadowPassPattern).toLowerCase())) {
      candidates.push({ name: displayPattern(shadowPassPattern), score: Math.round(confidence * 0.5) });
    }
  }

  // Shadow analysis — build from reference_analysis.lighting_read which carries structured
  // human-readable fields: source_quality, shadow_pattern, fill_presence, rim_presence,
  // key_observations.  This is the authoritative physical read of the light.
  // Fall back to li.notes (engine debug notes) then to raw signal metrics.
  const lightingRead = data.reference_analysis?.lighting_read || {};
  let shadowAnalysis = '';
  // Structured fields extracted from lighting_read so the ResultScreen can
  // render them as graphics (component chips, directional compass, multi-dot
  // catchlight eye) instead of dumping the raw narrative as a wall of text.
  let shadowComponents = null;   // { source, fill, rim, pattern }
  let shadowDirection  = null;   // { shadowQuadrant, keyQuadrant, keyIntensity }
  let catchlightPositions = null; // string[] — clock hours parsed from observations
  let shadowEdgeNote   = null;    // "Soft shadow edges → large/diffused source"

  // Parse a "key_observations" string to pull directional cues + catchlight
  // arrays OUT of the narrative so they can be rendered visually.
  const DIR_QUADRANTS = ['upper_left','upper_right','lower_left','lower_right','left','right','above','below','front','back'];
  const parseDirectionalObs = (obs) => {
    const m = /shadow(?:s)?\s+fall[s]?\s+([a-z_]+)\s*(?:→|->|to)\s*key\s*light\s*at\s+([a-z_]+)(?:\s*\(([-\d.]+)\))?/i.exec(obs);
    if (!m) return null;
    return {
      shadowQuadrant: m[1].replace(/_/g,' '),
      keyQuadrant:    m[2].replace(/_/g,' '),
      keyIntensity:   m[3] ? parseFloat(m[3]) : null,
    };
  };
  const parseCatchlightObs = (obs) => {
    const m = /catchlight\s+positions?\s*:?\s*\[([^\]]+)\]/i.exec(obs);
    if (!m) return null;
    return m[1].split(',').map(s => s.replace(/['"]/g,'').trim()).filter(Boolean);
  };
  const isEdgeObs = (obs) => /shadow\s+edge/i.test(obs);

  if (lightingRead.shadow_pattern || lightingRead.source_quality) {
    // Lead sentence — the physical headline.
    const lead = (() => {
      if (lightingRead.source_quality && lightingRead.shadow_pattern) {
        return `${toTitleCase(lightingRead.source_quality)} source with ${toTitleCase(lightingRead.shadow_pattern)} shadow pattern`;
      }
      if (lightingRead.shadow_pattern) return `${toTitleCase(lightingRead.shadow_pattern)} shadow pattern`;
      if (lightingRead.source_quality) return `${toTitleCase(lightingRead.source_quality)} source`;
      return null;
    })();

    // Structured components — these render as chips so they get pulled OUT of
    // the narrative string below.
    shadowComponents = {
      source:  lightingRead.source_quality ? toTitleCase(lightingRead.source_quality) : null,
      pattern: lightingRead.shadow_pattern ? toTitleCase(lightingRead.shadow_pattern) : null,
      fill:    (lightingRead.fill_presence && !['none','unknown'].includes(lightingRead.fill_presence))
        ? lightingRead.fill_presence : null,
      rim:     (lightingRead.rim_presence && !['none','unknown'].includes(lightingRead.rim_presence))
        ? lightingRead.rim_presence : null,
    };

    // Observations — triage into directional / catchlight / edge / other so
    // each one lands in the right visual home.
    const rawObs = (lightingRead.key_observations || []).filter(o => o && o.length < 200);
    const otherObs = [];
    // The engine emits a vertical prefix on shadow direction by comparing
    // upper-vs-lower face brightness, but that test only fires when the
    // bottom of the face is dramatically brighter (>25 luma diff).  In every
    // other case it defaults to "upper_*" — which is misleading because the
    // shadow physically falls on the LOWER side of the face whenever the
    // key is above the subject (which is the dominant case).  We post-fix
    // the parsed quadrant against the engine's `key_elevation` so the
    // DirectionalCompass shows the physically correct cell.
    // Determine whether the key sits ABOVE or BELOW the subject.  Prefer the
    // engine's explicit key_elevation; when it's absent (common — the engine
    // frequently leaves it blank), assume "above" because ~95% of real-world
    // lighting setups put the key at or above eye level.  The only case this
    // assumption is wrong is intentional uplighting / horror lighting, which
    // the engine normally flags via the shadow_pattern narrative anyway.
    const _keyElevRaw = (li.key_elevation || li.key_height || '').toLowerCase();
    const _keyAbove =
      _keyElevRaw === 'high' || _keyElevRaw === 'medium' || _keyElevRaw === ''
        ? true
        : _keyElevRaw === 'low' ? false : true;
    for (const o of rawObs) {
      const dir = parseDirectionalObs(o);
      if (dir) {
        // Physics rule: the shadow's vertical band is OPPOSITE the key's
        // vertical band — high key → shadow falls low, low key → shadow
        // falls high.  The horizontal axis is unchanged.  The engine often
        // emits "shadow falls upper_* → key light at upper_*" for a
        // loop-standard test image because its vertical inference only
        // flips when the bottom of the face is dramatically brighter
        // (>25 luma diff).  Post-fix here so the DirectionalCompass cell
        // lands in the physically correct quadrant.
        if (_keyAbove) {
          dir.shadowQuadrant = (dir.shadowQuadrant || '').replace(/^upper /, 'lower ');
          dir.keyQuadrant    = (dir.keyQuadrant    || '').replace(/^lower /, 'upper ');
        } else {
          dir.shadowQuadrant = (dir.shadowQuadrant || '').replace(/^lower /, 'upper ');
          dir.keyQuadrant    = (dir.keyQuadrant    || '').replace(/^upper /, 'lower ');
        }
        shadowDirection = dir;
        continue;
      }
      const cl = parseCatchlightObs(o);
      if (cl) { catchlightPositions = cl; continue; }
      if (isEdgeObs(o)) { shadowEdgeNote = o; continue; }
      if (/shadow_pattern_detail|loop|rembrandt|split/i.test(o) && o.length < 40) continue; // noise
      otherObs.push(o);
    }

    // Detail line — only attach shadow_pattern_detail if it adds information
    // beyond the lead pattern name.
    const detailLine = (lightingRead.shadow_pattern_detail && lightingRead.shadow_pattern_detail.toLowerCase() !== (lightingRead.shadow_pattern || '').toLowerCase())
      ? lightingRead.shadow_pattern_detail : null;

    // Ambiguity — surface uncertainty when present, but cap at one.
    const amb = (lightingRead.ambiguity_notes || []).filter(o => o && !o.startsWith('[VLW'));

    const parts = [];
    if (lead) parts.push(lead);
    if (detailLine) parts.push(detailLine);
    parts.push(...otherObs.slice(0, 2));
    if (amb.length > 0 && parts.length < 3) parts.push(amb[0]);

    shadowAnalysis = parts.join('. ').trim();
    if (shadowAnalysis && !shadowAnalysis.endsWith('.')) shadowAnalysis += '.';
  }

  if (!shadowAnalysis && li.notes && li.notes.length > 0) {
    shadowAnalysis = li.notes.join('. ');
  }

  if (!shadowAnalysis) {
    const parts = [];
    if (signals.shadow_pass_pattern) parts.push(`Shadow: ${toTitleCase(signals.shadow_pass_pattern)}`);
    if (signals.nose_shadow_angle_deg != null) parts.push(`nose shadow at ${signals.nose_shadow_angle_deg}°`);
    if (signals.left_right_asymmetry != null) parts.push(`L/R asymmetry ${(signals.left_right_asymmetry * 100).toFixed(0)}%`);
    shadowAnalysis = parts.join('. ') || 'Shadow analysis complete.';
  }

  // Catchlight & modifier — build from catchlight intelligence.  Modifier
  // family/shape names follow the Title Case display rule.
  let catchlightModifier = '';
  if (ci && ci.modifier) {
    const mod = ci.modifier;
    const modName = prettyModifierLabel(mod.type || mod.family || li.modifier_family || mod.label || 'Unknown');
    catchlightModifier = `${modName} ${mod.size_estimate || mod.size_label || ''}`.trim();
    if (ci.primary_key) {
      const pk = ci.primary_key;
      catchlightModifier += `. Key catchlight at ${pk.position || 'unknown'}, ${toTitleCase(pk.shape || '') || 'unknown'} shape`;
    }
  } else if (li.modifier_family) {
    catchlightModifier = prettyModifierLabel(li.modifier_family);
    if (sd.catchlights && sd.catchlights.length > 0) {
      const first = sd.catchlights[0];
      if (first.position) catchlightModifier += ` — catchlight at ${first.position}`;
      if (first.shape) catchlightModifier += `, ${toTitleCase(first.shape)} shape`;
    }
  } else {
    catchlightModifier = 'Modifier analysis complete.';
  }

  // Structured modifier data — size range + distance guidance derived from size class.
  // Columns: oct (octabox), rect (rectangular softbox), strip (strip box), bd (beauty dish).
  // Distances are shared across modifier types at a given size class.
  const SIZE_RANGES = {
    'small':  { oct: '24"–36"',   rect: '12"×16" – 16"×22"', strip: '9"×24" – 12"×36"', bd: '16"–18"',  dist: '3–6 ft',  optimal: '4–5 ft' },
    'medium': { oct: '36"–48"',   rect: '24"×30" – 24"×36"', strip: '12"×48" – 16"×60"', bd: '20"–22"', dist: '4–8 ft',  optimal: '5–7 ft' },
    'large':  { oct: '48"–60"',   rect: '36"×48" – 36"×60"', strip: '20"×60" – 36"×90"', bd: '27"–32"', dist: '5–10 ft', optimal: '6–8 ft' },
    'xl':     { oct: '60"–80"',   rect: '36"×72" – 48"×72"', strip: '36"×90"+',            bd: '32"+',    dist: '6–12 ft', optimal: '8–10 ft' },
    'xxl':    { oct: '60"–80"+',  rect: '48"×80" – 60"×84"', strip: '36"×90"+',            bd: null,      dist: '8–14 ft', optimal: '10–12 ft' },
  };

  // Resolve which SIZE_RANGES column to use based on modifier family slug.
  function modSizeCol(slug) {
    const s = (slug || '').toLowerCase();
    if (s.includes('strip'))           return 'strip';
    if (s.includes('beauty') || s.includes('beauty_dish')) return 'bd';
    if (s.includes('oct'))             return 'oct';
    return 'rect'; // softbox, umbrella, parabolic, unknown → rect as best proxy
  }

  let modifierData = null;
  const ciMod = ci?.modifier || {};
  // API returns: type, label, size_class, size_estimate, distance_est_ft, distance_class
  // Also check legacy field names: family, size_label
  const modFamily = (ciMod.type || ciMod.family || li.modifier_family || '').toLowerCase();
  const modSizeClass = (ciMod.size_class || '').toLowerCase();
  const modSizeRaw = (ciMod.size_label || ciMod.label || '').toLowerCase().replace(/\s+/g, '');
  // Penumbra apparent source size — fallback when no catchlight size info.
  // Maps shadow-edge width to modifier size class (independent of eye visibility).
  const PENUMBRA_SIZE_MAP = { small: 'small', medium: 'medium', large: 'large', very_large: 'xl' };
  const penumbraSize = li.penumbra_source_size ? PENUMBRA_SIZE_MAP[li.penumbra_source_size] || null : null;
  const sizeKey = modSizeClass || ['xxl','xl','large','medium','small'].find(k => modSizeRaw.includes(k)) || penumbraSize || null;
  if (modFamily || sizeKey) {
    const col    = modSizeCol(modFamily);
    const ranges = sizeKey ? SIZE_RANGES[sizeKey] : null;
    // Prefer engine-computed distance over lookup table
    const engineDist = ciMod.distance_est_ft || null;
    // family  = human-readable label ("Small Softbox") — shown as hero text
    // sizeRange = dimensional estimate shown as sub-line; pick type-specific column
    const _slug  = ciMod.type || ciMod.family || li.modifier_family || '';
    const _label = _slug
      ? prettyModifierLabel(_slug)
      : (ciMod.label ? toTitleCase(ciMod.label) : 'Unknown Modifier');
    const _pk = ci?.primary_key || {};
    modifierData = {
      family:     _label,
      sizeLabel:  null,
      sizeRange:  ciMod.size_estimate || (ranges ? (ranges[col] ?? ranges.rect) : null),
      position:   _pk.position || null,
      positionQuad: _pk.quad ? _pk.quad.replace(/_/g, ' ') : null,
      positionIntensity: _pk.intensity != null ? `${Math.round(_pk.intensity * 100)}% intensity` : null,
      shape:      toTitleCase(_pk.shape || ciMod.shape || '') || null,
      catchlightSize: _pk.size_ratio != null ? `${(_pk.size_ratio * 100).toFixed(1)}% iris` : null,
      distRange:  engineDist || ranges?.dist || null,
      optDist:    ranges?.optimal || null,
      distQuality: ciMod.distance_quality || null,
      lightCount: li.light_count || null,
      angularArea: ciMod.total_relative_area != null
        ? `${ciMod.total_relative_area.toFixed(3)} ir²` : null,
      physicalMeaning: ciMod.physical_meaning || null,
    };
  }

  // Modifier fallback — when catchlight intelligence is absent (e.g. closed eyes,
  // obscured face) but lighting inference has useful data, build a partial block
  // so the modifier panel always shows something actionable.
  if (!modifierData) {
    const hasLiData = li.light_count || li.key_position_text || li.modifier_family || li.source_quality;
    if (hasLiData) {
      const fallbackSlug = li.modifier_family || '';
      const fallbackSizeKey = penumbraSize;
      const fallbackRanges = fallbackSizeKey ? SIZE_RANGES[fallbackSizeKey] : null;
      const fallbackCol = modSizeCol(fallbackSlug);
      modifierData = {
        family:          fallbackSlug ? prettyModifierLabel(fallbackSlug) : 'Modifier Unresolved',
        sizeLabel:       null,
        sizeRange:       fallbackRanges ? (fallbackRanges[fallbackCol] ?? fallbackRanges.rect) : null,
        position:        li.key_position_text ? toTitleCase(li.key_position_text) : null,
        shape:           null,
        distRange:       fallbackRanges?.dist || null,
        optDist:         fallbackRanges?.optimal || null,
        distQuality:     null,
        lightCount:      li.light_count || null,
        angularArea:     null,
        physicalMeaning: 'Catchlight obscured — modifier estimated from shadow and source analysis only.',
      };
    }
  }

  // Scene description — from reference_analysis.image_read.
  // Prefer a pre-composed narrative.  If absent, compose from structured fields
  // so the SCENE panel always has something meaningful.
  const imageRead = data.reference_analysis?.image_read || {};
  let sceneDescription = (
    imageRead.narrative ||
    imageRead.scene_description ||
    ''
  ).trim();

  if (!sceneDescription) {
    const parts = [];
    if (imageRead.subject_type) parts.push(toTitleCase(imageRead.subject_type));
    if (imageRead.genre && imageRead.genre !== imageRead.subject_type)
      parts.push(toTitleCase(imageRead.genre));
    if (imageRead.mood) parts.push(`${imageRead.mood} mood`);
    if (imageRead.contrast_shadow_feel) parts.push(imageRead.contrast_shadow_feel);
    if (imageRead.pose_notes) parts.push(imageRead.pose_notes);
    sceneDescription = parts.join(', ').trim();
  }

  // ── Pattern source attribution ──────────────────────────────────────────────
  // Tells the photographer how the authoritative pattern was resolved —
  // i.e. which layer of the engine stack "won".
  const SOURCE_LABELS = {
    reference_read:     'full analysis',
    lighting_inference: 'catchlight analysis',
    definitive_sig:     'definitive signal',
    cue_inference:      'shadow analysis',
    light_structure:    'geometry analysis',
  };
  const patternSource    = SOURCE_LABELS[data.authoritative_pattern_source] || null;
  const confidenceLabel  = data.authoritative_confidence_label || null; // "strong" | "partial" | "weak"

  // ── Edge case warnings ───────────────────────────────────────────────────────
  // Surfaces analysis caveats before the photographer commits to "Set Up This Light".
  const EDGE_FLAGS = {
    blown_highlights:               { label: 'Blown Highlights',    sev: 'warn',
      detail: 'Specular highlights are clipped to pure white. The engine cannot recover catchlight position or modifier shape from those pixels — diagram angles are estimated from shadows alone.' },
    mixed_color_temperature:        { label: 'Mixed CCT',           sev: 'info',
      detail: 'Key and fill (or ambient) light have different color temperatures. Pattern detection is unaffected, but white balance and palette readouts will reflect the dominant source.' },
    outdoor_foliage_shadows:        { label: 'Foliage Shadows',     sev: 'info',
      detail: 'Dappled light from tree cover creates broken shadow edges that are not from the key light. The shadow analyzer compensates, but density readouts may run high.' },
    window_light_gradient:          { label: 'Window Gradient',     sev: 'info',
      detail: 'Light falls off across the subject because the source is large and close. Treat the diagram distance as a guide, not literal — the inverse-square slope is steep here.' },
    extreme_low_key:                { label: 'Extreme Low Key',     sev: 'info',
      detail: 'Most of the frame sits in deep shadow. Pattern confidence is lower because the engine has fewer mid-tone pixels to triangulate the key direction from.' },
    bw_processing:                  { label: 'B&W Detected',        sev: 'info',
      detail: 'Image is monochrome, so the color palette panel is suppressed. Shadow density and direction still read normally.' },
    earring_catchlight_contamination: { label: 'Catchlight Noise',  sev: 'warn',
      detail: 'Reflective jewelry near the eye is producing false catchlights that confuse modifier detection. Trust the shadow-derived light angle over the catchlight-derived one.' },
  };
  const edgeCaseWarnings = [];
  const rawFlags = data.edge_case_flags || {};
  Object.entries(EDGE_FLAGS).forEach(([k, v]) => {
    if (rawFlags[k]) edgeCaseWarnings.push(v);
  });

  // ── Color palette ────────────────────────────────────────────────────────────
  // Dominant colors, harmony, warm/cool CCT split from reference_analysis.
  const cpRaw = data.reference_analysis?.color_palette || null;
  const colorPalette = cpRaw ? {
    colors:       (cpRaw.dominant_colors   || []).slice(0, 5),
    hexes:        (cpRaw.dominant_color_hexes || []).slice(0, 5),
    harmony:      cpRaw.color_harmony     || null,
    warmCool:     !!cpRaw.warm_cool_split,
    cctKey:       cpRaw.color_temperature_key    || null,
    cctShadows:   cpRaw.color_temperature_shadows || null,
    character:    cpRaw.palette_character  || null,
  } : null;

  // ── Signal quality / confidence detail ──────────────────────────────────────
  // signal_coverage lives at data.observability.signal_coverage in the real API.
  // perception_explanation / signal_reliability are legacy top-level keys kept for compat.
  const sc = data.observability?.signal_coverage || data.signal_reliability || {};
  const pe = data.perception_explanation || {};
  const passSummaries = data.solver?.signal_reliability?.pass_summaries || null;
  const signalQuality = (sc.signals_available != null || pe.pattern_reasoning) ? {
    strength:      sc.overall_strength ?? sc.overall_signal_strength ?? null,
    available:     sc.signals_available ?? null,
    total:         sc.signals_total ?? null,
    supporting:    (pe.supporting_signals    || sc.weak_signals || []).slice(0, 4),
    contradicting: (pe.contradicting_signals || []).slice(0, 3),
    reasoning:     pe.pattern_reasoning || null,
    passSummaries: passSummaries || null,
  } : null;

  const lightQuality = (data.classification?.lightQuality || '').toLowerCase() || null;

  const mood = (imageRead.mood || '').trim() || null;

  // ── VLM Narrative — structured VLM description fields ────────────────────────
  // data.vlm is a VLMDescription: lighting_style, overall_mood, pose, expression,
  // framing, likely_photographer, derivation (reasoning dict), etc.
  const vlmRaw = data.vlm || null;
  let vlmNarrative = null;
  if (vlmRaw && vlmRaw.ok !== false) {
    const fields = [];
    if (vlmRaw.lighting_style) fields.push({ label: 'Lighting', value: vlmRaw.lighting_style });
    if (vlmRaw.overall_mood)   fields.push({ label: 'Mood',     value: vlmRaw.overall_mood });
    if (vlmRaw.framing)        fields.push({ label: 'Framing',  value: vlmRaw.framing });
    if (vlmRaw.pose)           fields.push({ label: 'Pose',     value: vlmRaw.pose });
    if (vlmRaw.expression)     fields.push({ label: 'Expression', value: vlmRaw.expression });
    if (vlmRaw.likely_photographer && vlmRaw.likely_photographer !== 'unknown')
      fields.push({ label: 'Style reference', value: vlmRaw.likely_photographer });
    // Derivation — VLM reasoning per conclusion
    const derivEntries = Object.entries(vlmRaw.derivation || {}).filter(([, v]) => v);
    if (fields.length > 0 || derivEntries.length > 0) {
      vlmNarrative = {
        fields,
        derivation: derivEntries.slice(0, 6),
        summary: vlmRaw.lighting_style || vlmRaw.overall_mood || null,
      };
    }
  }

  // ── EXIF camera data — real camera settings from uploaded photo ──────────
  const exifCamera = data.camera_settings || null;

  // ── Setup notes / quick fixes from recreation_setup ────────────────────
  const recreationSetup = data.reference_analysis?.recreation_setup || {};
  const setupNotes = recreationSetup.setup_notes || [];

  return {
    pattern,
    geometricBase,
    confidence,
    meta,
    mood,
    cameraSettings: exifCamera,
    setupNotes,
    sections: {
      patternCandidates: candidates,
      patternSource,
      confidenceLabel,
      edgeCaseWarnings,
      shadowAnalysis,
      shadowComponents,
      shadowDirection,
      shadowEdgeNote,
      catchlightPositions,
      lightQuality,
      catchlightModifier,
      modifier: modifierData,
      sceneDescription,
      colorPalette,
      signalQuality,
      vlmNarrative,
    },
    _raw: data,
  };
}

// Dev hook — lets browser testing call the real mapApiResult after a background fetch
if (typeof window !== 'undefined') window.__ngwMapResult = mapApiResult;

export default function Day1DemoApp() {
  const [screen, _setScreen] = useState('home');
  const prevScreenRef = useRef('home');
  //: Navigation trail. Without it every onBack had to hardcode a destination,
  //: and 8 of 11 chose 'home' — so any second hop lost the user's place.
  const historyRef = useRef([]);
  //: Mirrors `screen` synchronously so setScreen stays a pure updater.
  //: Mutating a ref inside the updater breaks under StrictMode double-invoke.
  const screenRef = useRef('home');

  const setScreen = useCallback((next) => {
    const prev = screenRef.current;
    if (prev !== next) {
      prevScreenRef.current = prev;
      pushScreen(historyRef.current, prev, next);
      screenRef.current = next;
    }
    _setScreen(next);
  }, []);

  /** Pop the trail. `fallback` is used when nothing is recorded. */
  const goBack = useCallback((fallback = 'home') => {
    const prev = screenRef.current;
    const next = popScreen(historyRef.current, prev, fallback);
    prevScreenRef.current = prev;
    screenRef.current = next;
    _setScreen(next);
  }, []);
  //: Reactive layout regimes. These replaced fourteen raw window.innerWidth
  //: reads that were evaluated once per render and never re-run, so a resize
  //: or rotation left the shell in the wrong regime.
  const isDesktopUp = useMinWidth(LAYOUT_DESKTOP_MIN);   // >= 1024
  const isTabletUp  = useMinWidth(TABLET_MIN_WIDTH);     // >= 768

  useEffect(() => { screenRef.current = screen; }, [screen]);

  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [result, setResult] = useState(null);
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisReady, setAnalysisReady] = useState(false);
  const [user, setUser] = useState(() => getUser());
  const [lastAnalysisTime, setLastAnalysisTime] = useState(null);
  const [shootMode, setShootMode] = useState('photographer');
  const { plan: appPlan, isPaid: appIsPaid, isAdmin: appIsAdmin } = usePlan(user?.email);
  const abortRef = useRef(null);
  const wakeLockRef = useRef(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  // Force studio theme so [data-theme="studio"] CSS overrides apply everywhere
  useEffect(() => { applyTheme('studio'); }, []);

  // ── Session join flow — detect ?session=TOKEN on mount ──────────────────
  const [sharedSession, setSharedSession] = useState(null);
  const [joinLoading, setJoinLoading] = useState(() => {
    // Pre-read the param synchronously so we can show loading immediately
    try { return !!new URLSearchParams(window.location.search).get('session'); } catch { return false; }
  });
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('session');
    if (!token) return;
    import('../data/teamStore').then(({ getSession }) => {
      getSession(token)
        .then(session => {
          setSharedSession(session);
          // Hydrate the result from the shared setup data
          if (session.setup_data) {
            const mapped = typeof session.setup_data === 'string'
              ? JSON.parse(session.setup_data)
              : session.setup_data;
            setResult(mapped);
            setScreen('setup');
          }
        })
        .catch(err => {
          console.warn('[TeamSession] Join failed:', err.message);
          if (err.status === 410) {
            setSharedSession({ expired: true, detail: err.detail });
          } else {
            setSharedSession({ error: true, detail: err.detail || 'Session not found' });
          }
        })
        .finally(() => setJoinLoading(false));
    });
    // Clean the URL param so refresh doesn't re-fetch
    const url = new URL(window.location.href);
    url.searchParams.delete('session');
    window.history.replaceState({}, '', url);
  }, []);

  // Check if onboarding is needed (first login, no photographer_profile)
  useEffect(() => {
    if (!user) return;
    try {
      if (localStorage.getItem('ngw_onboarding_skipped') === '1') return;
      if (localStorage.getItem('ngw_onboarding_done') === '1') return;
      if (localStorage.getItem('ngw_photographer_profile')) return;
    } catch { return; }
    // No local record — check server
    loadPreferences().then(prefs => {
      if (prefs?.photographer_profile) {
        // Server has it, cache locally so we don't ask again
        try { localStorage.setItem('ngw_onboarding_done', '1'); } catch {}
      } else {
        setNeedsOnboarding(true);
      }
    }).catch(() => {
      // Server unreachable — don't block the user, skip onboarding
    });
  }, [user]);

  // ── Dev: ?day1_screen=result jumps straight to the result screen with a
  // canned Rembrandt result so layout + typography can be reviewed instantly.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'result') return;
      const cannedResult = {
        pattern: 'Rembrandt', confidence: 91,
        meta: ['Camera-Left High', 'Large Octabox', '1 light'],
        mood: 'Dramatic',
        sections: {
          patternCandidates: [{ name: 'Rembrandt', score: 91 }, { name: 'Loop', score: 64 }],
          patternSource: 'shadow analysis',
          confidenceLabel: 'strong',
          edgeCaseWarnings: [],
          shadowAnalysis: 'Hard-edged shadow. Triangle of light on shadow cheek.',
          shadowComponents: { source: 'Soft', pattern: 'Rembrandt', fill: 'subtle', rim: null },
          shadowDirection: { shadowQuadrant: 'lower right', keyQuadrant: 'upper left', keyIntensity: 0.8 },
          shadowEdgeNote: null,
          catchlightPositions: ['10'],
          lightQuality: 'soft',
          catchlightModifier: 'Large Octabox — catchlight at 10 o\'clock, round shape',
          modifier: {
            family: 'Large Octabox',
            sizeLabel: 'Large',
            sizeRange: '48"–60"',
            distRange: '5–10 ft',
            optDist: '6–8 ft',
            position: 'Upper Left',
            positionQuad: 'Camera-Left',
            positionIntensity: 'High',
            catchlightSize: '85% iris',
          },
          sceneDescription: 'Single key light, studio background.',
          colorPalette: null, signalQuality: null, vlmNarrative: null,
        },
        _raw: {},
      };
      setResult(cannedResult);
      setImagePreview('/loop_standard.jpg');
      setScreen('result');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=processing previews the processing screen.
  //    Auto-completes after 6s so the full flow (processing → result) is visible.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'processing') return;
      setImagePreview('/loop_standard.jpg');
      setScreen('processing');
      // Simulate analysis completion after 6s
      const t = setTimeout(() => {
        setResult({
          pattern: 'Rembrandt', confidence: 91,
          meta: ['Camera-Left High', 'Large Octabox', '1 light'],
          mood: 'Dramatic',
          sections: {
            patternCandidates: [{ name: 'Rembrandt', score: 91 }, { name: 'Loop', score: 64 }],
            patternSource: 'shadow analysis', confidenceLabel: 'strong', edgeCaseWarnings: [],
            shadowAnalysis: 'Hard-edged shadow. Triangle of light on shadow cheek.',
            shadowComponents: { source: 'Soft', pattern: 'Rembrandt', fill: 'subtle', rim: null },
            shadowDirection: { shadowQuadrant: 'lower right', keyQuadrant: 'upper left', keyIntensity: 0.8 },
            catchlightPositions: ['10'], lightQuality: 'soft',
            catchlightModifier: 'Large Octabox — catchlight at 10 o\'clock, round shape',
            modifier: { family: 'Large Octabox', sizeLabel: 'Large', sizeRange: '48"–60"', distRange: '5–10 ft', optDist: '6–8 ft', position: 'Upper Left', positionQuad: 'Camera-Left', positionIntensity: 'High', catchlightSize: '85% iris' },
            sceneDescription: 'Single key light, studio background.',
          },
          _raw: {},
        });
        setAnalysisReady(true);
      }, 6000);
      return () => clearTimeout(t);
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=setup previews the setup/recipe screen directly
  //    with rich canned data so all panels, specs, and drawers render.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'setup') return;
      const cannedResult = {
        pattern: 'Rembrandt', confidence: 91,
        meta: ['Camera-Left High', 'Large Octabox', '1 light'],
        mood: 'Dramatic',
        sections: {
          patternCandidates: [{ name: 'Rembrandt', score: 91 }, { name: 'Loop', score: 64 }],
          patternSource: 'shadow analysis', confidenceLabel: 'strong', edgeCaseWarnings: [],
          shadowAnalysis: 'Hard-edged shadow. Triangle of light on shadow cheek.',
          shadowComponents: { source: 'Soft', pattern: 'Rembrandt', fill: 'subtle', rim: null },
          shadowDirection: { shadowQuadrant: 'lower right', keyQuadrant: 'upper left', keyIntensity: 0.8 },
          catchlightPositions: ['10'], lightQuality: 'soft',
          catchlightModifier: 'Large Octabox — catchlight at 10 o\'clock, round shape',
          modifier: {
            family: 'Large Octabox', sizeLabel: 'Large', sizeRange: '48"–60"',
            distRange: '5–10 ft', optDist: '6–8 ft',
            position: 'Upper Left', positionQuad: 'Camera-Left', positionIntensity: 'High',
            catchlightSize: '85% iris',
          },
          sceneDescription: 'Single key light, studio background.',
        },
        _raw: {
          lighting_inference: {
            key_side: 'upper_left', key_elevation: 'high',
            key_position_text: 'Camera-Left · High',
            off_axis_angle: 45,
          },
          reference_analysis: {
            recreation_setup: {
              key_placement: 'Camera-left, 45° off axis, raised high',
              fill_strategy: 'Negative fill — V-flat camera right',
              background_strategy: 'Medium grey seamless, 6–8 ft behind subject. No background light.',
              focal_length: '85–135mm',
              aperture: 'f/2.8–4',
              camera_subject_guidance: 'Eye-level camera, subject at edge of light fall-off',
              setup_notes: [
                'Position key at roughly 45° camera-left, 6–8 ft from subject',
                'Feather modifier slightly past subject for softer wrap',
                'Use V-flat on shadow side to deepen Rembrandt triangle',
                'Watch for catchlight at 10 o\'clock position to confirm placement',
              ],
            },
          },
          reconstruction: {
            key_light_angle_deg: 45,
            key_light_height: 'high',
            modifier_distance_ft: 7,
            light_roles: {
              key: {
                present: true, confidence: 0.91, role: 'key', modifier: 'Large Octabox', distance: '5–10 ft',
                position: 'Camera-Left · High', evidence: ['Strong shadow edge', 'Round catchlight at 10 o\'clock'],
              },
            },
          },
        },
      };
      setResult(cannedResult);
      setImagePreview('/loop_standard.jpg');
      setScreen('setup');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=recipes previews the recipe browser directly.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'recipes') return;
      setScreen('recipes');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=saved previews the saved setups library.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'saved') return;
      setScreen('saved');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=build previews the build wizard.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('day1_screen') !== 'build') return;
      setScreen('build');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_screen=shoot jumps straight into the cockpit.
  //    Two variants for cross-device review without driving the full flow:
  //      ?day1_screen=shoot          — analyze/teach-sample path (canned Rembrandt)
  //      ?day1_screen=shoot_wizard   — wizard-path result shape (mood='beauty')
  //    The shoot mode is 'photographer' by default; override with &mode=learning
  //    or &mode=assistant.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    try {
      const params = new URLSearchParams(window.location.search);
      const s = params.get('day1_screen');
      if (s !== 'shoot' && s !== 'shoot_wizard') return;
      const requestedMode = params.get('mode');
      const validModes = ['photographer', 'assistant', 'learning'];
      setShootMode(validModes.includes(requestedMode) ? requestedMode : 'photographer');

      if (s === 'shoot_wizard') {
        // Wizard-source result shape — mirrors handleBuildComplete output
        // BEFORE the shoot-match cards arrive.  This is what the cockpit
        // actually sees when a user walks the Build From Scratch flow.
        setResult({
          pattern: toTitleCase('beauty'),
          confidence: 100,
          meta: ['Headshot', 'Studio Medium', 'Best Setup'],
          mood: 'Beauty',
          _wizardSource: true,
          sections: {
            patternCandidates: [],
            patternSource: 'wizard', confidenceLabel: 'custom build',
            edgeCaseWarnings: [], shadowAnalysis: null, shadowComponents: null,
            shadowDirection: null, catchlightPositions: [], lightQuality: null,
            catchlightModifier: null, modifier: null,
            sceneDescription: 'Beauty Headshot — Studio Medium',
            colorPalette: null, signalQuality: null, vlmNarrative: null,
          },
          _raw: { wizard: { mood: 'beauty', subject: 'headshot', environment: 'studio_medium', gearMode: 'best_setup' } },
        });
        setImagePreview(null);
      } else {
        // Analyze/teach-sample path — reuses the setup shortcut's canned Rembrandt
        setResult({
          pattern: 'Rembrandt', confidence: 91,
          meta: ['Camera-Left High', 'Large Octabox', '1 light'],
          mood: 'Dramatic',
          sections: {
            patternCandidates: [{ name: 'Rembrandt', score: 91 }, { name: 'Loop', score: 64 }],
            patternSource: 'shadow analysis', confidenceLabel: 'strong', edgeCaseWarnings: [],
            shadowAnalysis: 'Hard-edged shadow. Triangle of light on shadow cheek.',
            shadowComponents: { source: 'Soft', pattern: 'Rembrandt', fill: 'subtle', rim: null },
            shadowDirection: { shadowQuadrant: 'lower right', keyQuadrant: 'upper left', keyIntensity: 0.8 },
            catchlightPositions: ['10'], lightQuality: 'soft',
            catchlightModifier: 'Large Octabox — catchlight at 10 o\'clock, round shape',
            modifier: {
              family: 'Large Octabox', sizeLabel: 'Large', sizeRange: '48"–60"',
              distRange: '5–10 ft', optDist: '6–8 ft',
              position: 'Upper Left', positionQuad: 'Camera-Left', positionIntensity: 'High',
              catchlightSize: '85% iris',
            },
            sceneDescription: 'Single key light, studio background.',
          },
          _raw: {
            authoritative_pattern: 'rembrandt',
            lighting_inference: {
              key_side: 'upper_left', key_elevation: 'high',
              key_position_text: 'Camera-Left · High', off_axis_angle: 45,
              detected_cct_kelvin: 5500,
            },
            reconstruction: {
              key_light_angle_deg: 45, key_light_height: 'high', modifier_distance_ft: 7,
            },
            signal_diagnostics: {
              signals: { left_right_asymmetry: 0.72, nose_shadow_angle_deg: 38 },
            },
          },
        });
        setImagePreview('/loop_standard.jpg');
      }
      setScreen('shoot');
    } catch { /* ignore */ }
  }, []);

  // ── Dev: ?day1_error=<key> jumps straight to the error screen with a
  // canned message so each scenario can be reviewed without going through
  // the full analyze flow.  Harmless in prod (no-op without the param).
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const key = params.get('day1_error');
      if (!key) return;
      const canned = {
        noface:  'No face detected in the image',
        quota:   'API quota exceeded (429)',
        timeout: 'Request timeout — server took too long',
        offline: 'Failed to fetch — network unreachable',
        server:  'Server returned 503',
        upload:  'Upload failed — file rejected',
        unknown: 'Unexpected internal error',
      };
      setAnalysisError(canned[key] || canned.unknown);
      setScreen('error');
    } catch { /* ignore */ }
  }, []);

  // Keep screen awake while app is active
  useEffect(() => {
    async function requestWakeLock() {
      try {
        if ('wakeLock' in navigator) {
          wakeLockRef.current = await navigator.wakeLock.request('screen');
        }
      } catch { /* user denied or not supported */ }
    }
    requestWakeLock();
    // Re-acquire on visibility change (browser releases on tab switch)
    const reacquire = () => { if (document.visibilityState === 'visible') requestWakeLock(); };
    document.addEventListener('visibilitychange', reacquire);
    return () => {
      document.removeEventListener('visibilitychange', reacquire);
      if (wakeLockRef.current) wakeLockRef.current.release().catch(() => {});
    };
  }, []);

  const [exifData, setExifData] = useState(null);

  const handleAnalyze = (file, preview, exif) => {
    setImageFile(file);
    setImagePreview(preview);
    setExifData(exif || null);
    setResult(null);
    setAnalysisError(null);
    setAnalysisReady(false);
    setScreen('processing');

    const controller = new AbortController();
    abortRef.current = controller;

    // Downsample if over 10 MB, then analyze
    downsampleImage(file, MAX_UPLOAD_BYTES)
      .then(readyFile => analyzeImage(readyFile, { signal: controller.signal }))
      .then(data => {
        setResult(mapApiResult(data));
        setAnalysisReady(true);
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          console.error('[Day1] Analysis failed:', err);
          setAnalysisError(err.message);
          setAnalysisReady(true);
        }
      });
  };

  // Dev hook: window.__ngwLoadImage('/test-benchmark.jpg') drives the full analyze flow
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.__ngwLoadImage = async (url) => {
      const resp = await fetch(url);
      const blob = await resp.blob();
      const file = new File([blob], url.split('/').pop(), { type: blob.type || 'image/jpeg' });
      const preview = URL.createObjectURL(blob);
      handleAnalyze(file, preview);
    };
    return () => { delete window.__ngwLoadImage; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist last result for quick recall from home screen
  const [lastResult, setLastResult] = useState(() => {
    try { const r = sessionStorage.getItem('ngw_last_result'); return r ? JSON.parse(r) : null; } catch { return null; }
  });
  const [lastPreview, setLastPreview] = useState(() => sessionStorage.getItem('ngw_last_preview') || null);

  // Transition to result when analysis finishes.  A brief 1.2s dwell lets
  // the pattern tease flash on the ProcessingScreen photo before we switch —
  // the "reveal moment" that makes the user feel the analysis landed.
  useEffect(() => {
    if (screen === 'processing' && analysisReady) {
      if (result) {
        // Cache immediately (don't wait for the dwell timer)
        setLastResult(result);
        setLastPreview(imagePreview);
        setLastAnalysisTime(Date.now());
        try {
          sessionStorage.setItem('ngw_last_result', JSON.stringify(result));
          if (imagePreview && imagePreview.startsWith('blob:')) {
            fetch(imagePreview).then(r => r.blob()).then(blob => {
              const reader = new FileReader();
              reader.onloadend = () => {
                const dataUrl = reader.result;
                sessionStorage.setItem('ngw_last_preview', dataUrl);
                setLastPreview(dataUrl);
              };
              reader.readAsDataURL(blob);
            }).catch(() => {});
          } else if (imagePreview) {
            sessionStorage.setItem('ngw_last_preview', imagePreview);
          }
        } catch { /* quota */ }
        // 1.2s dwell — pattern tease shows on the processing photo
        const timer = setTimeout(() => setScreen('result'), 1200);
        return () => clearTimeout(timer);
      } else if (analysisError) {
        setScreen('error');
      }
    }
  }, [screen, analysisReady, result, analysisError, imagePreview]);

  const handleViewLastResult = () => {
    if (lastResult) {
      setResult(lastResult);
      setImagePreview(lastPreview);
      setScreen('result');
    }
  };

  const handleSetup = (altPattern) => {
    if (altPattern && typeof altPattern === 'string') {
      // Runner-up candidate selected — update result with the alternative pattern
      setResult(prev => ({
        ...prev,
        pattern: toTitleCase(altPattern),
        _altPatternOverride: altPattern,
      }));
    }
    setScreen('setup');
  };
  const handleSettings = () => setScreen('settings');

  const handleSetupSave = () => {
    // Persistence happens inside SetupScreen; stay on setup so the user can
    // see the "Saved" confirmation before deciding to Start Cockpit.
  };

  // Bucket B cockpit gate — REMOVED.
  // Originally gated all paths into Day1ShootScreen behind
  // ?studio=1&cockpit=1 session flag while the cockpit stabilised.
  // The cockpit is now functional for analyze, wizard, and recipe paths,
  // so the gate is no longer needed.  The separate login gate below
  // still blocks unauthenticated users from loading Studio Matte.
  const handleStartCockpit = (mode) => {
    setShootMode(mode || 'photographer');
    setScreen('shoot');
  };

  const handleExitShoot = () => {
    setScreen('home');
    setImageFile(null);
    setImagePreview(null);
    setResult(null);
  };

  const handleSetupCancel = () => {
    // If result came from recipe or wizard (no real analysis), go home instead of result screen
    if (result?._recipeSource || result?._wizardSource) {
      setScreen('home');
      setResult(null);
    } else {
      setScreen('result');
    }
  };
  const handleRecipes = () => setScreen('recipes');
  const handleRecipeSelect = (recipe) => {
    // Build a result object from recipe data so SetupScreen can render it
    const lightCount = recipe.setupTime?.match(/(\d+)\s*light/)?.[1] || '1';
    const recipeResult = {
      pattern: toTitleCase(recipe.pattern),
      confidence: 100,
      meta: [
        recipe.modifierFamily ? prettyModifierLabel(recipe.modifierFamily) : null,
        `${lightCount} light${lightCount !== '1' ? 's' : ''}`,
        recipe.environment ? toTitleCase(recipe.environment) : null,
      ].filter(Boolean),
      mood: toTitleCase(recipe.mood),
      _recipeSource: recipe.id,
      sections: {
        patternCandidates: [{ name: toTitleCase(recipe.pattern), score: 100 }],
        patternSource: 'recipe',
        confidenceLabel: 'recipe',
        edgeCaseWarnings: [],
        shadowAnalysis: null,
        shadowComponents: null,
        shadowDirection: null,
        catchlightPositions: [],
        lightQuality: recipe.difficulty <= 1 ? 'soft' : 'mixed',
        catchlightModifier: recipe.modifierFamily
          ? prettyModifierLabel(recipe.modifierFamily)
          : null,
        modifier: recipe.modifierFamily ? {
          family: prettyModifierLabel(recipe.modifierFamily),
          sizeLabel: null,
          sizeRange: null,
          distRange: null,
          optDist: null,
          position: null,
          positionQuad: null,
          positionIntensity: null,
          catchlightSize: null,
        } : null,
        sceneDescription: recipe.description,
        colorPalette: null, signalQuality: null, vlmNarrative: null,
      },
      _raw: {
        shoot_checklist: recipe.warning ? [recipe.warning] : [],
        recipe: {
          id: recipe.id,
          name: recipe.name,
          whyItWorks: recipe.whyItWorks,
          gearFlexibility: recipe.gearFlexibility,
          useCase: recipe.useCase,
          variations: recipe.variations,
        },
      },
    };
    setResult(recipeResult);
    setImagePreview(null);
    setScreen('setup');
  };
  const handleSavedSetups = () => setScreen('saved');
  const handleBuildWizard = () => setScreen('build');
  const handleMyKit = () => setScreen('mykit');
  const handleRoomPlanner = () => setScreen('roomplanner');
  const handleShotMatch = () => setScreen('shotmatch');
  const handleSessionLog = () => setScreen('journal');
  const [showVideoCapture, setShowVideoCapture] = useState(false);
  const handleVideoCapture = () => setShowVideoCapture(true);

  // Team session — backend-backed shoot session sharing
  const [activeSessionToken, setActiveSessionToken] = useState(null);
  const [shareLoading, setShareLoading] = useState(false);
  const handleShareSession = useCallback(async () => {
    if (shareLoading) return null;
    setShareLoading(true);
    try {
      // Re-share existing session if one was created this cockpit visit
      if (activeSessionToken) {
        const { getShareUrl } = await import('../data/teamStore');
        const url = getShareUrl(activeSessionToken);
        let clipboardFailed = false;
        try { await navigator.clipboard.writeText(url); } catch { clipboardFailed = true; }
        setShareLoading(false);
        return { url, clipboardFailed };
      }
      // Create new backend session
      const { createSession } = await import('../data/teamStore');
      const session = await createSession(
        result?.pattern || 'Shoot Session',
        result || {},
      );
      setActiveSessionToken(session.share_token);
      const url = session.share_url;
      let clipboardFailed = false;
      try { await navigator.clipboard.writeText(url); } catch { clipboardFailed = true; }
      setShareLoading(false);
      return { url, clipboardFailed };
    } catch (err) {
      setShareLoading(false);
      console.error('[TeamSession] Create failed:', err.message);
      return null;
    }
  }, [result, activeSessionToken, shareLoading]);
  const handleLookLibrary = () => setScreen('looklibrary');
  const handleClientBrief = () => setScreen('clientbrief');
  const handleBuildComplete = (payload) => {
    // Build a result object from wizard payload so SetupScreen can render it
    const wizardResult = {
      pattern: toTitleCase(payload.mood || 'custom'),
      confidence: 100,
      meta: [
        payload.subject ? toTitleCase(payload.subject) : null,
        payload.environment ? toTitleCase(payload.environment) : null,
        payload.gearMode === 'best_setup' ? 'Best Setup' : 'My Gear',
      ].filter(Boolean),
      mood: toTitleCase(payload.mood),
      _wizardSource: true,
      sections: {
        patternCandidates: [],
        patternSource: 'wizard',
        confidenceLabel: 'custom build',
        edgeCaseWarnings: [],
        shadowAnalysis: null,
        shadowComponents: null,
        shadowDirection: null,
        catchlightPositions: [],
        lightQuality: null,
        catchlightModifier: null,
        modifier: null,
        sceneDescription: `${toTitleCase(payload.mood)} ${toTitleCase(payload.subject)} — ${toTitleCase(payload.environment)}`,
        colorPalette: null, signalQuality: null, vlmNarrative: null,
      },
      _raw: {
        wizard: payload,
      },
    };
    setResult(wizardResult);
    setImagePreview(null);
    setScreen('setup');

    // Fetch engine-built result cards in the background and merge them into
    // the result when they arrive.  Navigation is not blocked on this — the
    // wizard→setup transition stays instant.  If the call fails we keep the
    // fallback wizardResult in place; new card renderers must tolerate a
    // missing `cards` field.
    shootMatch(wizardPayloadToShootMatch(payload))
      .then(resp => {
        if (!resp) return;
        const cards = resp.cards || {};
        const diag = cards.diagram || {};
        const keyLight = cards.shootThisSetup?.lights?.[0];
        const cam = cards.cameraSettings || {};

        // Canonical pattern from the engine's diagram (e.g. "loop",
        // "rembrandt") — NOT the mood label the wizard used as a
        // placeholder.  This is what the cockpit keys coaching on.
        const enginePattern = diag.pattern
          || resp.authoritative_pattern
          || null;
        const patternDisplay = enginePattern
          ? toTitleCase(enginePattern)
          : toTitleCase(payload.mood || 'custom');

        // Flatten key-light data into the shapes Day1ShootScreen reads:
        //   result.sections.modifier.*   (catchlight / modifier panel)
        //   result._raw.reconstruction.* (angle, height, distance)
        //   result._raw.lighting_inference.* (position text, CCT)
        const modifier = keyLight ? {
          family: keyLight.modifier || null,
          sizeLabel: null,
          sizeRange: null,
          distRange: keyLight.distance || null,
          optDist: keyLight.distance || null,
          position: keyLight.position || null,
          positionQuad: keyLight.angle || null,
          positionIntensity: null,
          catchlightSize: null,
        } : null;

        // Convention conversion: shoot-match diagram_spec uses
        // 0°=camera-facing, 90°=side, 180°=behind. The engine/cockpit
        // convention is inverted: 0°=behind, 90°=side, 180°=camera-facing.
        const _smAngle = keyLight?.angle_deg;
        const reconstruction = keyLight ? {
          key_light_angle_deg: typeof _smAngle === 'number' ? 180 - _smAngle : null,
          key_light_height: keyLight.height_m != null
            ? (keyLight.height_m >= 2.0 ? 'high'
              : keyLight.height_m >= 1.5 ? 'medium' : 'low')
            : null,
          modifier_distance_ft: keyLight.distance_m != null
            ? Math.round(keyLight.distance_m * 3.281)
            : null,
        } : {};

        const cctRaw = cam.wb;
        const cctKelvin = typeof cctRaw === 'string'
          ? parseInt(cctRaw.replace(/[^\d]/g, ''), 10) || null
          : null;

        setResult(prev => ({
          ...prev,
          pattern: patternDisplay,
          confidence: cards.bestMatch?.reliability ?? prev.confidence,
          cards,
          shootLoop: resp.shootLoop || null,
          authoritative_pattern: resp.authoritative_pattern || null,
          _shootMatchRaw: resp,
          sections: {
            ...prev.sections,
            modifier,
            patternSource: 'shoot-match',
            confidenceLabel: cards.bestMatch?.reliabilityLabel || prev.sections?.confidenceLabel,
          },
          _raw: {
            ...prev._raw,
            authoritative_pattern: enginePattern,
            reconstruction,
            lighting_inference: {
              key_position_text: keyLight?.position || null,
              key_side: keyLight?.angle_deg != null
                ? (keyLight.angle_deg > 5 ? 'upper_right'
                  : keyLight.angle_deg < -5 ? 'upper_left' : 'center')
                : null,
              key_elevation: reconstruction.key_light_height || null,
              detected_cct_kelvin: cctKelvin,
            },
          },
        }));
      })
      .catch(err => {
        console.warn('[Studio] shoot-match failed for wizard payload:', err?.message || err);
      });
  };
  const handleSavedSetupSelect = (setup) => {
    // Load the saved setup's result and show the setup sheet
    if (setup.result) {
      setResult(setup.result);
      setImagePreview(setup.imagePreview || null);
      setScreen('setup');
    }
  };

  const handleRetry = () => {
    // Abort any in-flight analysis
    if (abortRef.current) abortRef.current.abort();
    setScreen('home');
    setImageFile(null);
    setImagePreview(null);
    setResult(null);
    setAnalysisError(null);
    setAnalysisReady(false);
  };

  // Login gate — unauthenticated users see the Studio login screen.
  // (The old Bucket B cockpit-unlock branch that redirected to prod auth
  // was removed along with the cockpit gate — all studio paths now show
  // the in-studio login screen.)
  if (!user) {
    return <StudioLoginScreen onLogin={(u) => setUser(u)} />;
  }

  // Onboarding gate — first-run profiling wizard
  if (needsOnboarding) {
    return <OnboardingScreen onComplete={() => {
      setNeedsOnboarding(false);
      try { localStorage.setItem('ngw_onboarding_done', '1'); } catch {}
    }} />;
  }

  // ── Session join: loading + error gates ─────────────────────────────────
  if (joinLoading) {
    return (
      <div style={{
        minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--color-bg, #0a0a0c)',
      }}>
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            border: '2px solid rgba(90,120,160,0.18)',
            borderTopColor: 'rgba(90,120,160,0.65)',
            animation: 'sessionSpinner 0.8s linear infinite',
          }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'rgba(160,180,210,0.55)', letterSpacing: '0.6px', WebkitFontSmoothing: 'antialiased' }}>
            Loading shared session…
          </span>
        </div>
        <style>{`@keyframes sessionSpinner { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (sharedSession?.expired || sharedSession?.error) {
    const isExpired = !!sharedSession.expired;
    return (
      <div style={{
        minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--color-bg, #0a0a0c)',
        padding: '0 24px',
      }}>
        <div style={{
          maxWidth: 340, width: '100%', textAlign: 'center',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20,
        }}>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            background: isExpired ? 'rgba(200,155,60,0.10)' : 'rgba(200,70,70,0.10)',
            border: `1.5px solid ${isExpired ? 'rgba(200,155,60,0.25)' : 'rgba(200,70,70,0.22)'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {isExpired ? (
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="rgba(200,155,60,0.70)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
              </svg>
            ) : (
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="rgba(200,70,70,0.70)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <p style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'rgba(200,215,235,0.85)', letterSpacing: '0.3px', WebkitFontSmoothing: 'antialiased' }}>
              {isExpired ? 'Session Expired' : 'Session Not Found'}
            </p>
            <p style={{ margin: 0, fontSize: 13, color: 'rgba(140,165,195,0.55)', lineHeight: 1.5, fontWeight: 400 }}>
              {isExpired
                ? 'This shared session has expired. Sessions are valid for 24 hours. Ask the photographer to share a new link.'
                : 'This session link is invalid or has been removed. Ask the photographer to share a new link.'}
            </p>
          </div>
          <button
            onClick={() => { setSharedSession(null); setScreen('home'); }}
            style={{
              background: 'rgba(90,120,160,0.10)', border: '1px solid rgba(90,120,160,0.22)',
              borderRadius: 8, padding: '9px 22px', cursor: 'pointer',
              fontSize: 13, fontWeight: 600, color: 'rgba(160,185,215,0.75)',
              letterSpacing: '0.5px', WebkitFontSmoothing: 'antialiased',
              transition: 'background 0.15s ease',
            }}
          >
            Go Home
          </button>
        </div>
      </div>
    );
  }

  // ── Screen crossfade — each screen fades in on mount (200ms) ──
  const screenContent = (() => {
    switch (screen) {
    case 'home': {
      // Desktop: HomeScreen manages its own two-column grid layout at native
      // viewport width — no FitToViewport scaling needed.
      // Mobile: 430×932 aspect-preserving contain via FitToViewport.
      const homeMobile = !isDesktopUp;
      const homeEl = (
        <HomeScreen
          onAnalyze={handleAnalyze}
          hasLastResult={!!lastResult}
          onViewLastResult={handleViewLastResult}
          user={user}
          onLogout={() => { clearAuth(); setUser(null); }}
          onSettings={handleSettings}
          onRecipes={handleRecipes}
          onSavedSetups={handleSavedSetups}
          onBuildWizard={handleBuildWizard}
          onMyKit={handleMyKit}
          onSessionLog={handleSessionLog}
          onLookLibrary={handleLookLibrary}
          onClientBrief={handleClientBrief}
          onVideoCapture={handleVideoCapture}
          lastAnalysisTime={lastAnalysisTime}
        />
      );
      if (!homeMobile) return homeEl;
      return (
        <FitToViewport
          designWidth={430}
          designHeight={932}
          maxScale={1.9}
          tightness={0.92}
        >
          {homeEl}
        </FitToViewport>
      );
    }
    case 'processing': {
      const procMobile = !isDesktopUp;
      const procEl = <ProcessingScreen imagePreview={imagePreview} imageFile={imageFile} analysisComplete={analysisReady} exifData={exifData} result={result} onCancel={handleRetry} />;
      if (!procMobile) return procEl;
      return (
        <FitToViewport designWidth={430} designHeight={932} maxScale={1.9} tightness={0.96}>
          {procEl}
        </FitToViewport>
      );
    }
    case 'result': {
      // Desktop/tablet: bypass FitToViewport — ResultScreen manages its own layout.
      // Tablet portrait (768–1023px) also bypasses scaling; ResultScreen activates
      // its two-column grid internally via the TABLET_MIN_WIDTH check.
      // Mobile: 430-wide with width-only scaling.
      const resultMobile = !isTabletUp;
      const resultEl = (
        <ResultScreen
          result={result}
          imagePreview={imagePreview}
          onSetup={handleSetup}
          onRetry={handleRetry}
          onShotMatch={handleShotMatch}
          isPaid={appIsPaid}
          plan={appPlan}
          isAdmin={appIsAdmin}
        />
      );
      if (!resultMobile) return resultEl;
      return (
        <FitToViewport designWidth={430} fitMode="width" minScale={1} maxScale={1.3} tightness={0.96}>
          {resultEl}
        </FitToViewport>
      );
    }
    case 'setup': {
      // Desktop/tablet: bypass FitToViewport — SetupScreen manages its own layout.
      // Mobile: 430×932 with standard scaling.
      const setupMobile = !isTabletUp;
      const setupEl = (
        <SetupScreen
          result={result}
          imagePreview={imagePreview}
          onSave={handleSetupSave}
          onCancel={handleSetupCancel}
          onStartCockpit={handleStartCockpit}
          onRoomPlanner={handleRoomPlanner}
          isPaid={appIsPaid}
          plan={appPlan}
        />
      );
      if (!setupMobile) return setupEl;
      return (
        <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>
          {setupEl}
        </FitToViewport>
      );
    }
    case 'shoot': {
      // Cockpit uses a LOCAL 768px threshold (not the global 1024)
      // so tablet portrait gets the two-column photo+chrome layout
      // in both FitToViewport AND the internal isDesktop branching.
      const shootMobile = !isTabletUp;
      const shootDesktopVH = typeof window !== 'undefined' ? window.innerHeight : 800;
      return (
        <FitToViewport
          designWidth={shootMobile ? 430 : 1180}
          designHeight={shootMobile ? 932 : shootDesktopVH}
          minScale={shootMobile ? 0.8 : 0.5}
          maxScale={shootMobile ? 1.9 : 2.0}
          tightness={shootMobile ? 0.96 : 1}
        >
          <Day1ShootScreen
            result={result}
            imagePreview={imagePreview}
            mode={shootMode}
            onExit={handleExitShoot}
            onLiveView={handleVideoCapture}
            onShare={handleShareSession}
          />
        </FitToViewport>
      );
    }
    case 'build': {
      const buildMobile = !isDesktopUp;
      const buildEl = <BuildWizardScreen onComplete={handleBuildComplete} onBack={() => goBack()} />;
      if (!buildMobile) return buildEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{buildEl}</FitToViewport>;
    }
    case 'saved': {
      const savedMobile = !isDesktopUp;
      const savedEl = (
        <SavedSetupsScreen
          onSelect={handleSavedSetupSelect}
          onBack={() => goBack()}
          onBuild={() => setScreen('recipes')}
          onShoot={(setup) => { if (setup.result) { setResult(setup.result); handleStartCockpit('photographer'); } }}
        />
      );
      if (!savedMobile) return savedEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{savedEl}</FitToViewport>;
    }
    case 'recipes': {
      const recipesMobile = !isDesktopUp;
      const recipesEl = <RecipeScreen onSelect={handleRecipeSelect} onBack={() => goBack()} onBuild={handleBuildWizard} />;
      if (!recipesMobile) return recipesEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{recipesEl}</FitToViewport>;
    }
    case 'journal': {
      const journalMobile = !isDesktopUp;
      const journalEl = (
        <SessionLogScreen
          onBack={() => goBack()}
          onSelectAnalysis={async (id) => {
            try {
              const { fetchAnalysisDetail } = await import('../data/sessionLogApi');
              const data = await fetchAnalysisDetail(id);
              if (data?.result) {
                setResult(data.result);
                setImagePreview(null);
                setScreen('result');
              }
            } catch (err) {
              console.error('Failed to load analysis:', err);
            }
          }}
        />
      );
      if (!journalMobile) return journalEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{journalEl}</FitToViewport>;
    }
    case 'clientbrief': {
      const cbMobile = !isDesktopUp;
      const cbEl = <ClientBriefScreen onBack={() => goBack()} />;
      if (!cbMobile) return cbEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{cbEl}</FitToViewport>;
    }
    case 'looklibrary': {
      const llMobile = !isDesktopUp;
      const llEl = <LookLibraryScreen onBack={() => goBack()} />;
      if (!llMobile) return llEl;
      return <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>{llEl}</FitToViewport>;
    }
    case 'roomplanner':
      return <RoomPlannerWrapper result={result} onBack={() => goBack(result ? 'setup' : 'home')} />;
    case 'shotmatch':
      return (
        <ShotMatchAdapter
          result={result}
          imagePreview={imagePreview}
          user={user}
          isPaid={appIsPaid}
          isAdmin={appIsAdmin}
          onBack={() => goBack(result ? 'result' : 'home')}
        />
      );
    case 'mykit': {
      const mkMobile = !isDesktopUp;
      const mkEl = <MyKitScreen onBack={() => goBack()} onRecipes={handleRecipes} />;
      if (!mkMobile) return mkEl;
      return (
        <FitToViewport designWidth={430} designHeight={932} minScale={1} maxScale={1.9} tightness={0.96}>
          {mkEl}
        </FitToViewport>
      );
    }
    case 'settings': {
      const settingsMobile = !isDesktopUp;
      const settingsEl = (
        <Day1SettingsScreen
          user={user}
          onBack={() => goBack()}
          onLogout={() => { clearAuth(); setUser(null); setScreen('home'); }}
          onLab={() => setScreen('lab')}
        />
      );
      if (!settingsMobile) return settingsEl;
      return (
        <FitToViewport designWidth={430} designHeight={932} maxScale={1.9} tightness={0.96}>
          {settingsEl}
        </FitToViewport>
      );
    }
    case 'lab':
      return <StudioLabWrapper onBack={() => goBack('settings')} onSessionLog={() => setScreen('sessionLog')} onLookLibrary={() => setScreen('lookLibrary')} />;
    case 'error':
      return (
        <FallbackReveal
          message={analysisError}
          onRetry={handleRetry}
          onHome={handleRetry}
        />
      );
    default: {
      // Fallback to home — same bypass pattern
      const defMobile = !isDesktopUp;
      const defEl = (
        <HomeScreen onAnalyze={handleAnalyze} hasLastResult={!!lastResult} onViewLastResult={handleViewLastResult}
          user={user} onLogout={() => { clearAuth(); setUser(null); }} onSettings={handleSettings}
          onRecipes={handleRecipes} onSavedSetups={handleSavedSetups} onBuildWizard={handleBuildWizard}
          onMyKit={handleMyKit} onSessionLog={handleSessionLog} onLookLibrary={handleLookLibrary} onClientBrief={handleClientBrief} onVideoCapture={handleVideoCapture} lastAnalysisTime={lastAnalysisTime} />
      );
      if (!defMobile) return defEl;
      return <FitToViewport designWidth={430} designHeight={932} maxScale={1.9} tightness={0.96}>{defEl}</FitToViewport>;
    }
    }
  })();

  // Admin testing indicator — shows when plan is overridden from default
  const showTestingBadge = appIsAdmin && appPlan !== 'enterprise';

  return (
    <div key={screen} style={{
      animation: `${prevScreenRef.current === 'processing' && screen === 'result' ? 'screenRevealIn' : 'screenFadeIn'} ${prevScreenRef.current === 'processing' && screen === 'result' ? '0.45s' : '0.2s'} ease both`,
      position: 'relative',
    }}>
      {screenContent}
      {/* Admin tier testing indicator — fixed bottom-right corner */}
      {showTestingBadge && (
        <div style={{
          position: 'fixed', bottom: 12, right: 12, zIndex: 9999,
          padding: '4px 10px', borderRadius: 6,
          background: appPlan === 'free'
            ? 'linear-gradient(141.71deg, rgba(40,32,18,0.90) 0%, rgba(28,22,12,0.90) 100%)'
            : 'linear-gradient(141.71deg, rgba(20,34,28,0.90) 0%, rgba(14,26,20,0.90) 100%)',
          boxShadow: '0 2px 8px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          display: 'flex', alignItems: 'center', gap: 5,
          pointerEvents: 'none',
        }}>
          <div style={{
            width: 5, height: 5, borderRadius: '50%',
            background: appPlan === 'free'
              ? 'radial-gradient(circle, rgba(255,200,100,0.95) 0%, rgba(200,155,60,0.80) 100%)'
              : 'radial-gradient(circle, rgba(180,255,220,0.95) 0%, rgba(72,186,136,0.80) 100%)',
            boxShadow: appPlan === 'free' ? '0 0 4px rgba(200,155,60,0.50)' : '0 0 4px rgba(72,186,136,0.50)',
          }} />
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase',
            color: appPlan === 'free' ? 'rgba(200,155,60,0.75)' : 'rgba(140,225,180,0.70)',
            WebkitFontSmoothing: 'antialiased',
          }}>Testing as {PLAN_LABELS[appPlan]}</span>
        </div>
      )}
      {/* Shared session banner — shown when viewing a session joined via URL */}
      {sharedSession && !sharedSession.expired && !sharedSession.error && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9000,
          padding: '6px 16px',
          background: 'rgba(14,20,30,0.92)',
          borderBottom: '1px solid rgba(90,120,160,0.18)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          pointerEvents: 'auto',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(90,140,200,0.65)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>
              <path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>
            </svg>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(140,170,210,0.60)', letterSpacing: '0.4px', WebkitFontSmoothing: 'antialiased' }}>
              Shared session
              {sharedSession.creator_email ? ` · ${sharedSession.creator_email}` : ''}
              {sharedSession.setup_name ? ` — ${sharedSession.setup_name}` : ''}
            </span>
          </div>
          <button
            onClick={() => setSharedSession(null)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px',
              color: 'rgba(140,165,195,0.40)', fontSize: 14, lineHeight: 1,
              WebkitTapHighlightColor: 'transparent',
            }}
            title="Dismiss"
          >×</button>
        </div>
      )}
      <style>{`
        @keyframes screenFadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes screenRevealIn { from { opacity: 0; } 40% { opacity: 0.6; } to { opacity: 1; } }
      `}</style>
      {showVideoCapture && (
        <VideoFrameCapture
          onCapture={(frameFile) => {
            setShowVideoCapture(false);
            // Feed captured frame into normal analysis flow
            if (frameFile) {
              const preview = URL.createObjectURL(frameFile);
              setImageFile(frameFile);
              setImagePreview(preview);
              setScreen('home');
            }
          }}
          onClose={() => setShowVideoCapture(false)}
        />
      )}
    </div>
  );
}

// ─── Fallback Reveal ─────────────────────────────────────────────────────────
/**
 * Shown when analysis errors out.
 * Pixel-matched to Figma node 1317:2 (Studio Matte → Analysis Failed).
 *
 * Layout mirrors HomeScreen so the user stays in the same shell:
 *   • Wordmark top-left + sensor well top-right
 *   • Glass viewfinder showing the failure label / headline / subtext
 *   • Recessed indicator well + "TRY AGAIN" label as the retry affordance
 */
function FallbackReveal({ message, onRetry }) {
  // Run mount sound + warn haptic so the user feels something landed
  useEffect(() => { warnHaptic(); }, []);

  // Parse the error and pick the right framing for each scenario.
  // Each error type has its own small-caps label, headline, and detail copy
  // — the layout stays the same but the content adapts to the failure mode.
  const lc = (message || '').toLowerCase();
  const isNoFace  = lc.includes('face') || lc.includes('no_face') || lc.includes('not detect');
  const isQuota   = lc.includes('quota') || lc.includes('429') || lc.includes('rate');
  const isTimeout = lc.includes('timeout') || lc.includes('econnreset') || lc.includes('aborted');
  // "Failed to fetch" = network layer error but NOT necessarily offline.
  // Check navigator.onLine: if the device is online, it's a CORS/access/blocked-URL issue, not offline.
  const isFetchFailed = lc.includes('failed to fetch') || lc.includes('networkerror') || lc.includes('network request failed');
  const isActuallyOffline = isFetchFailed && (typeof navigator !== 'undefined' ? !navigator.onLine : false);
  const isAccessBlocked   = isFetchFailed && !isActuallyOffline;
  const isNetwork = isActuallyOffline || lc.includes('offline');
  const isAccess  = isAccessBlocked || lc.includes('cors') || lc.includes('couldn\'t fetch') || lc.includes('could not fetch');
  const isServer  = lc.includes('500') || lc.includes('502') || lc.includes('503') || lc.includes('server');
  const isUpload  = lc.includes('upload') || lc.includes('file') || lc.includes('image');

  // ── Studio Matte signal palette — three "tones" the design system uses
  // for status colors.  Each scenario picks one based on the failure mode
  // so the kicker, sensor LED, retry indicator, and glow all sing the same
  // color story without breaking the language. ────────────────────────
  const TONE = {
    danger: {
      // Engine/analysis problems — coral/red.  Matches confLow on results.
      kicker:    'rgba(225,95,95,0.92)',
      kickerGlow:'rgba(225,95,95,0.20)',
      ledHi:     'rgba(235,100,100,0.98)',
      ledMid:    'rgba(170,55,55,0.85)',
      ledLo:     'rgba(85,22,22,0.6)',
      ledHalo1:  'rgba(225,90,90,0.50)',
      ledHalo2:  'rgba(225,90,90,0.18)',
      sensorBg:  'rgba(225,90,90,0.85)',
      sensorMid: 'rgba(140,40,40,0.65)',
      sensorLo:  'rgba(70,18,18,0.5)',
      sensorHalo:'rgba(180,60,60,0.30)',
    },
    caution: {
      // Quota / timeout / upload — amber.  Matches confLow on results.
      kicker:    'rgba(245,190,72,0.92)',
      kickerGlow:'rgba(245,190,72,0.22)',
      ledHi:     'rgba(255,215,120,0.98)',
      ledMid:    'rgba(200,150,55,0.85)',
      ledLo:     'rgba(115,80,28,0.6)',
      ledHalo1:  'rgba(245,190,72,0.50)',
      ledHalo2:  'rgba(245,190,72,0.18)',
      sensorBg:  'rgba(245,190,72,0.80)',
      sensorMid: 'rgba(160,115,40,0.65)',
      sensorLo:  'rgba(80,55,18,0.5)',
      sensorHalo:'rgba(200,150,55,0.30)',
    },
    info: {
      // Network / server — steel-blue.  Reads as "infrastructure", not user.
      kicker:    'rgba(150,180,210,0.92)',
      kickerGlow:`${steel(0.22)}`,
      ledHi:     'rgba(180,210,235,0.98)',
      ledMid:    'rgba(132, 158, 184,0.85)',
      ledLo:     'rgba(40,60,80,0.6)',
      ledHalo1:  `${steel(0.45)}`,
      ledHalo2:  `${steel(0.16)}`,
      sensorBg:  'rgba(150,180,210,0.80)',
      sensorMid: `${steel(0.55)}`,
      sensorLo:  'rgba(40,60,80,0.5)',
      sensorHalo:`${steel(0.30)}`,
    },
  };

  // Each scenario gets: kicker text, headline, detail, retry label, and a tone.
  // The tone drives every color signal in the layout — kicker, sensor LED,
  // retry indicator dot, glows.  Layout stays consistent; signaling adapts.
  const scenario =
    isNoFace  ? { kicker: 'Analysis Failed', headline: 'No face detected',       detail: "Make sure the subject's face is visible.",                                       retry: 'Try Again', tone: TONE.danger }
  : isQuota   ? { kicker: 'Limit Reached',   headline: 'Daily quota exceeded',   detail: 'Usage limit reached. Try again in a moment.',                                    retry: 'Retry',     tone: TONE.caution }
  : isTimeout ? { kicker: 'Timed Out',       headline: 'Server is slow',         detail: 'The analysis took too long. Check your connection and try again.',               retry: 'Retry',     tone: TONE.caution }
  : isNetwork ? { kicker: 'No Connection',   headline: 'Offline',                detail: "Can't reach the server. Check your connection.",                                  retry: 'Retry',     tone: TONE.danger }
  : isAccess  ? { kicker: 'Connection Refused', headline: "Request blocked",       detail: "The connection was blocked. If you loaded from a cloud link, save to your device first.", retry: 'New Photo', tone: TONE.caution }
  : isServer  ? { kicker: 'Server Error',    headline: 'Engine unavailable',     detail: 'The analysis engine is temporarily down. Please try again.',                     retry: 'Retry',     tone: TONE.danger }
  : isUpload  ? { kicker: 'Upload Failed',   headline: 'Image not accepted',     detail: 'The photo could not be processed. Try a different shot.',                        retry: 'New Photo', tone: TONE.caution }
  :             { kicker: 'Analysis Failed', headline: 'Something went wrong',   detail: message || 'An unexpected error occurred.',                                       retry: 'Try Again', tone: TONE.danger };

  const { kicker, headline, detail, retry: retryLabel, tone } = scenario;

  const handleRetryClick = () => {
    softClickSound();
    tapHaptic();
    onRetry?.();
  };

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, overflow: 'hidden' }}>
      <div style={{
        position: 'relative',
        width: '100%', maxWidth: 430, height: '100%', minHeight: 600,
        margin: '0 auto', backgroundColor: C.bg,
        boxShadow: '2px 4px 40px rgba(0,0,0,0.6), -1px -1px 1px rgba(255,255,255,0.02)',
        overflow: 'hidden',
        fontFamily: 'Inter, system-ui, sans-serif',
      }}>
        <MatteBackground variant="carbon" />

        {/* ── Wordmark (top-left) — static, not interactive on this screen ── */}
        <div style={{ position: 'absolute', top: 24, left: 22, padding: 6, zIndex: 15, userSelect: 'none' }}>
          <p style={{
            margin: 0, fontWeight: 800, fontSize: 18, lineHeight: '22px',
            color: C.textPrimary, letterSpacing: '-0.3px',
            textShadow: '0 0 1px rgba(245,247,250,0.12)',
            ...FS,
          }}>No Guesswork</p>
          <p style={{
            margin: '2px 0 0 1px', fontWeight: 800, fontSize: 9.5, lineHeight: '12px',
            color: 'rgba(145,168,190,0.95)', letterSpacing: '3.2px',
            textShadow: `0 0 3px ${steel(0.15)}`,
            ...FS,
          }}>LIGHTING</p>
        </div>

        {/* ── Sensor well (top-right) — quiet, dim red dot ── */}
        <div style={{
          position: 'absolute', top: 30, right: 24, width: 40, height: 40,
          borderRadius: 20, backgroundColor: C.slotBg,
          boxShadow: [
            'inset 2px 3px 6px 0px rgba(0,0,0,0.85)',
            'inset 1px 2px 3px 0px rgba(0,0,0,0.65)',
            'inset -0.5px -0.5px 1px 0px rgba(255,255,255,0.04)',
            `inset 0px 0px 8px 0px ${steel(0.05)}`,
          ].join(', '),
        }}>
          <div style={{
            position: 'absolute', top: 17, left: 17, width: 6, height: 6, borderRadius: '50%',
            background: `radial-gradient(circle at 50% 55%, ${tone.sensorBg} 0%, ${tone.sensorMid} 65%, ${tone.sensorLo} 100%)`,
            boxShadow: [
              'inset 0 1px 1.5px rgba(0,0,0,0.9)',
              'inset 1px 0 1px rgba(0,0,0,0.55)',
              'inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10)',
              `0 0 1.5px ${tone.sensorHalo}`,
            ].join(', '),
          }} />
        </div>

        {/* ── Glass viewfinder — error message lives inside ── */}
        <div style={{
          position: 'absolute', top: 140, left: 24, right: 24, height: 360,
          borderRadius: 8, overflow: 'hidden',
          backgroundColor: C.slotBg,
          border: '0.5px solid rgba(0,0,0,0.45)',
          boxShadow: '0 -1px 0 rgba(0,0,0,0.5), -1px 0 0 rgba(0,0,0,0.4), 1px 1px 0 rgba(255,255,255,0.05)',
        }}>
          {/* Centered error copy */}
          <div style={{
            position: 'absolute', inset: 0, zIndex: 7,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            padding: '0 32px', textAlign: 'center',
          }}>
            <p style={{
              margin: '0 0 14px',
              fontSize: 11, fontWeight: 700,
              color: tone.kicker, letterSpacing: '2.2px',
              textTransform: 'uppercase',
              textShadow: `0 0 8px ${tone.kickerGlow}`,
              ...FS,
            }}>
              {kicker}
            </p>
            <p style={{
              margin: '0 0 10px',
              fontSize: 22, fontWeight: 700,
              color: C.textPrimary, letterSpacing: '-0.4px',
              lineHeight: 1.2,
              ...FS,
            }}>
              {headline}
            </p>
            <p style={{
              margin: 0,
              fontSize: 14, fontWeight: 400,
              color: steel(0.6), lineHeight: 1.5,
              ...FS,
            }}>
              {detail}
            </p>
          </div>

          {/* Glass overlay: lens vignette + upper-left key reflection */}
          <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 9 }}>
            <div style={{ position: 'absolute', inset: 0, background: LENS_VIGNETTE }} />
            <div style={{ position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0, background: GLASS_REFLECTION, borderRadius: 8, opacity: 0.48 }} />
          </div>

          {/* Inner shadow — matches HomeScreen viewfinder bevel */}
          <div style={{
            position: 'absolute', inset: 0, borderRadius: 8,
            pointerEvents: 'none', boxShadow: VIEWFINDER_INNER_SHADOW, zIndex: 10,
          }} />
        </div>

        {/* ── Retry indicator — recessed well with red dot ── */}
        <div
          role="button"
          aria-label="Try again"
          onClick={handleRetryClick}
          style={{
            position: 'absolute',
            left: '50%', top: 580,
            transform: 'translateX(-50%)',
            width: 100, height: 100, borderRadius: 50,
            backgroundColor: C.slotBg,
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
            boxShadow: [
              'inset 4px 5px 14px 0px rgba(0,0,0,0.88)',
              'inset 2px 3px 7px 0px rgba(0,0,0,0.68)',
              'inset 1px 1px 3px 0px rgba(0,0,0,0.55)',
              'inset -1px -1px 1.5px 0px rgba(255,255,255,0.05)',
              `inset -2px -2px 6px 0px ${steel(0.07)}`,
              `inset 0px 0px 22px 0px ${steel(0.05)}`,
            ].join(', '),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {/* Center indicator dot — recessed-LED treatment, tone-adaptive */}
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: `radial-gradient(circle at 50% 55%, ${tone.ledHi} 0%, ${tone.ledMid} 60%, ${tone.ledLo} 100%)`,
            boxShadow: [
              'inset 0 1.2px 2.2px rgba(0,0,0,0.95)',
              'inset 1px 0 1.4px rgba(0,0,0,0.7)',
              'inset -0.6px -0.6px 1px rgba(255,255,255,0.14)',
              `0 0 2.2px ${tone.ledHalo1}`,
              `0 0 6px ${tone.ledHalo2}`,
            ].join(', '),
          }} />
        </div>

        {/* ── TRY AGAIN label ── */}
        <button
          type="button"
          onClick={handleRetryClick}
          style={{
            position: 'absolute',
            left: '50%', top: 700,
            transform: 'translateX(-50%)',
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '6px 14px',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <span style={{
            fontSize: 11, fontWeight: 700,
            color: steel(0.75), letterSpacing: '3.2px',
            textShadow: `0 0 6px ${steel(0.18)}`,
            ...FS,
          }}>
            {retryLabel.toUpperCase()}
          </span>
        </button>

        {/* ── Home indicator ── */}
        <div style={{
          position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
          width: 134, height: 5, borderRadius: 3,
          backgroundColor: 'rgba(89,94,107,0.55)',
          boxShadow: 'inset 0px 1px 1px 0px rgba(255,255,255,0.12), inset 0px -0.5px 0.5px 0px rgba(0,0,0,0.2)',
          zIndex: 50, pointerEvents: 'none',
        }} />
      </div>
    </div>
  );
}
