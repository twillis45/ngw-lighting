/**
 * Day1ShootScreen — cockpit for Studio Matte Day 1 demo flow.
 *
 * Entered from SetupScreen's mode picker after the photographer chooses a
 * role (photographer / assistant / learning). Each role renders a distinctly
 * different cockpit philosophy:
 *
 *   Photographer — data-dense, terse leads, full numeric specs visible
 *   Assistant    — oversized single-command type, no prose, no reference
 *                  photo; readable across a studio for hands-free ops
 *   Learning     — narrative leads + "WHY" callout with lighting theory
 *                  pulled from signal diagnostics; reference photo is large
 *
 * Capture semantics: Capture is a gesture meaning "I fired a frame on my
 * camera". It increments a session-scoped frame counter. After the first
 * frame, a DONE action appears that exits back to home.
 *
 * Props:
 *   result        — mapped result from Day1DemoApp (pattern, confidence, sections, _raw)
 *   imagePreview  — analyzed photo data URL (for reference)
 *   mode          — 'photographer' | 'assistant' | 'learning'
 *   onExit        — exit cockpit and return to home
 */
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { navHaptic, tapHaptic, successHaptic, grainHaptic, longPressHaptic } from '../../../utils/haptics';
import { softClickSound, navSlideSound } from '../../../utils/sounds';
import { steel, C, FONT_SMOOTH, PANEL_SHADOW, PANEL_BEVEL,
         CTA_BG, CTA_SHADOW, CTA_BEVEL, KEY_ACCENT, SCREEN_BG } from '../../../theme/studioMatte';
import { trackEvent, getSessionId } from '../../../data/analytics';
import { loadSettings } from '../../../data/settingsStore';
import { postSignal } from '../../../data/signalsApi';
import useStableViewport from '../../../utils/useStableViewport';
import { getUser } from '../../../data/authApi';
import ZoomableHeroOverlay from './components/ZoomableHeroOverlay';
import NailedItOverlay from './components/NailedItOverlay';
import LightingDiagram from '../_core/components/LightingDiagram';
import useWakeLock from '../../../hooks/useWakeLock';
import { createPortal } from 'react-dom';
import MatteBackground from '../_shared/MatteBackground';
import { useMinWidth, TABLET_MIN_WIDTH } from '../../../utils/useIsDesktop';

const MODE_LABELS = {
  photographer: { label: 'Photographer', tag: 'FULL DETAILS' },
  assistant:    { label: 'Assistant',    tag: 'COMMANDS ONLY' },
  learning:     { label: 'Learning',     tag: 'EXPLAINS WHY' },
};

// Traditional off-axis angle ranges for classical portrait lighting patterns.
// These are the *target* ranges — the angle the key light should sit at
// relative to the camera-subject axis to produce the named pattern.
const PATTERN_TARGET_ANGLES = {
  BUTTERFLY: [0, 15],    // Paramount / glamour — on-axis, high above
  LOOP:      [30, 45],   // Classic portrait — loop/triangle under nose
  REMBRANDT: [45, 60],   // Shadow triangle on cheek bounded by nose + eye
  SPLIT:     [85, 95],   // Half-lit, half-shadow — key at 3 or 9 o'clock
  BROAD:     [30, 60],   // Broad side of face lit
  SHORT:     [30, 60],   // Short (shadow) side of face toward camera
  CLAMSHELL: [0, 15],    // Butterfly above + fill below — beauty standard
  RING_LIGHT:[0, 5],     // On-axis; donut catchlights
};
function targetRangeFor(pattern) {
  if (!pattern) return null;
  const range = PATTERN_TARGET_ANGLES[pattern.toUpperCase()];
  return range ? `${range[0]}–${range[1]}°` : null;
}

// Per-step coaching: what visual cues confirm the pattern is landing,
// and what to adjust when it isn't. Keyed by pattern then step.
const PATTERN_COACHING = {
  LOOP: {
    position: {
      lookFor: [
        'Small loop/triangle shadow under the nose, on the shadow side',
        'Catchlight sits around 1 o\'clock (or 11) in the iris',
        'Shadow does NOT touch the cheek shadow',
      ],
      fixes: [
        ['Shadow touches cheek', 'Move key closer to camera axis (lower angle)'],
        ['No loop visible', 'Move key further off-axis'],
        ['Catchlight off-center', 'Rotate subject\'s head toward the light'],
      ],
    },
    distance: {
      lookFor: [
        'Smooth wrap from forehead into shadow — no hard edge',
        'Skin highlights soft but not blown',
        'Catchlight is a readable shape, not a pinpoint',
      ],
      fixes: [
        ['Shadow edge too hard', 'Pull light closer (larger apparent size)'],
        ['Light too flat / no falloff', 'Back the light off'],
        ['Catchlight tiny/dim', 'Move closer for more eye presence'],
      ],
    },
    height: {
      lookFor: [
        'Catchlight lands in the UPPER half of the iris (~10–11 o\'clock)',
        'Nose shadow ~½ length of the nose',
        'Small shadow triangle visible under the shadow-side eye',
      ],
      fixes: [
        ['No catchlights in eyes', 'Drop the light — too high'],
        ['Pattern flattens to butterfly', 'Raise the light'],
        ['Nose shadow reaches lip', 'Lower the light slightly'],
      ],
    },
    capture: {
      lookFor: [
        'Loop/triangle shape matches the reference',
        'Both catchlights similar in size & clock position',
        'Shadow-side cheek has definition, not mud',
      ],
      fixes: [
        ['Asymmetric catchlights', 'Fix head angle before touching the light'],
        ['Pattern drifted since setup', 'Re-check angle FIRST, then height'],
        ['Flat/low contrast', 'Verify fill ratio and ambient spill'],
      ],
    },
  },

  BUTTERFLY: {
    position: {
      lookFor: [
        'Symmetric shadow directly under the nose (butterfly wings)',
        'Catchlight dead-center at 12 o\'clock in both irises',
        'Equal fall-off on both cheeks — no lateral bias',
      ],
      fixes: [
        ['Nose shadow pulls to one side', 'Re-center the key on the lens axis'],
        ['Catchlight off to 10 or 2', 'Light is drifting off-axis — pull back to 0°'],
        ['One cheek brighter than the other', 'Subject is off-axis, not the light — square them up'],
      ],
    },
    distance: {
      lookFor: [
        'Soft, readable wings shadow — no hard edge',
        'Cheekbones carved but not crunchy',
        'Clean specular across the forehead, no hot spot',
      ],
      fixes: [
        ['Wings shadow razor-sharp', 'Pull the light closer — apparent size too small'],
        ['Face looks flat, no modeling', 'Back the light off slightly'],
        ['Forehead blowing out', 'Ease distance or feather the modifier upward'],
      ],
    },
    height: {
      lookFor: [
        'Nose shadow stops SHORT of the upper lip',
        'Catchlight in the UPPER third of the iris',
        'Clear triangle of light on the chin',
      ],
      fixes: [
        ['Shadow runs into the lip', 'Drop the light a hair — you\'re too high'],
        ['No shadow under nose at all', 'Raise the light — it\'s too low, becoming flat'],
        ['Eye sockets going dark', 'Lower the light or add chin fill'],
      ],
    },
    capture: {
      lookFor: [
        'Perfectly symmetric butterfly wings under the nose',
        'Glamour-style sculpt on cheekbones',
        'Even catchlights, dead center, matching size',
      ],
      fixes: [
        ['Asymmetry creeping in', 'Check subject head tilt FIRST'],
        ['Under-eye circles reading dark', 'Add a reflector/clamshell below'],
        ['Looks like a loop instead', 'Key drifted off-axis — pull back to 0°'],
      ],
    },
  },

  REMBRANDT: {
    position: {
      lookFor: [
        'Defined triangle of light on the shadow-side cheek',
        'Triangle bounded by nose shadow and cheek shadow',
        'Catchlight at ~1 or 11 o\'clock, key-side eye only',
      ],
      fixes: [
        ['Triangle closed (shadows meet)', 'Raise the light OR pull angle inward'],
        ['Triangle runs off the face', 'Lower the light OR reduce off-axis angle'],
        ['No triangle forming at all', 'Push key further off-axis — you\'re stuck in loop'],
      ],
    },
    distance: {
      lookFor: [
        'Painterly falloff — chiaroscuro, not harsh',
        'Triangle has soft edges, readable at a glance',
        'Shadow side retains texture, not crushed black',
      ],
      fixes: [
        ['Shadow side crushed to black', 'Pull closer or add negative-less fill'],
        ['Triangle edge jagged/digital', 'Pull light in — need larger apparent size'],
        ['Whole face too evenly lit', 'Back light off — you\'re killing the drama'],
      ],
    },
    height: {
      lookFor: [
        'Triangle sits on the cheek, NOT on the jawline',
        'Nose shadow angled down toward the corner of the mouth',
        'Key-side eye has a clear catchlight; shadow-side dim',
      ],
      fixes: [
        ['Triangle slid down to jaw', 'Raise the light'],
        ['Triangle collapsed onto nose', 'Lower the light'],
        ['Both eyes bright equally', 'Key is too frontal — push off-axis further'],
      ],
    },
    capture: {
      lookFor: [
        'Classical triangle anchored on the cheek',
        'Dramatic shadow-to-light ratio, cinematic mood',
        'Nose shadow flows smoothly into cheek shadow',
      ],
      fixes: [
        ['Triangle breaking apart', 'Usually height — raise or lower 2 inches'],
        ['Shadow looks muddy', 'Tighten modifier or flag spill off shadow side'],
        ['Lost the mood', 'Kill ambient fill — Rembrandt lives on contrast'],
      ],
    },
  },

  SPLIT: {
    position: {
      lookFor: [
        'Light exactly bisects the face — one side lit, one dark',
        'Key light 90° off-axis, parallel to the subject\'s face plane',
        'Catchlight only in the key-side eye',
      ],
      fixes: [
        ['Light bleeds across the nose bridge', 'Push the key further back — past 90°'],
        ['Both eyes have catchlights', 'Key still too frontal — rotate further off-axis'],
        ['Shadow side totally invisible', 'Bring negative fill or let ambient breathe a hair'],
      ],
    },
    distance: {
      lookFor: [
        'Clean vertical shadow line down the center of the face',
        'Lit side has skin texture, not blown',
        'Shadow side has a faint rim of ambient definition',
      ],
      fixes: [
        ['Lit side blowing out', 'Back the light off'],
        ['Shadow line ragged/soft', 'Tighten the modifier or pull closer'],
        ['Shadow side pure black', 'Acceptable for split, but add rim if you need separation'],
      ],
    },
    height: {
      lookFor: [
        'Shadow line falls vertically, straight down the nose',
        'Catchlight at 3 or 9 o\'clock position',
        'No light spill onto the shadow-side cheek',
      ],
      fixes: [
        ['Shadow line tilted', 'Level the light to subject\'s eyeline'],
        ['Light spills onto shadow cheek', 'Subject head is rotated — square them to the light'],
        ['Eye socket key-side is dark', 'Raise the light slightly, add minor tilt down'],
      ],
    },
    capture: {
      lookFor: [
        'Dead-perfect vertical split down the face',
        'One catchlight only, key-side',
        'High-contrast mood, gender-neutral drama',
      ],
      fixes: [
        ['Split drifting to a rembrandt', 'Key has crept forward — reset to 90°'],
        ['Too harsh for the look', 'Feather modifier or add subtle fill on shadow side'],
        ['Lost the knife edge', 'Flag any ambient bounce hitting shadow side'],
      ],
    },
  },

  BROAD: {
    position: {
      lookFor: [
        'Subject face turned AWAY from camera slightly',
        'Key lighting the side of the face TOWARD camera (the broad side)',
        'Loop or triangle pattern visible on the broad cheek',
      ],
      fixes: [
        ['Face looks wide/heavy', 'Correct — broad lighting widens; if unwanted, switch to short'],
        ['Pattern on wrong side of face', 'Subject turned wrong way — flip head direction'],
        ['Pattern gone flat', 'Push key further off-axis on the broad side'],
      ],
    },
    distance: {
      lookFor: [
        'Smooth wrap across the broad cheek',
        'Far (narrow) side reads as shadow without falling to black',
        'Highlights on broad side open and luminous',
      ],
      fixes: [
        ['Broad side blown', 'Back light off'],
        ['Face looks 2D/poster-like', 'Pull in for more wrap'],
        ['Narrow side pure black', 'Add fill — broad lighting benefits from some shadow detail'],
      ],
    },
    height: {
      lookFor: [
        'Catchlight in upper half of broad-side eye',
        'Nose shadow falls onto the broad cheek',
        'No deep under-eye shadow',
      ],
      fixes: [
        ['Heavy under-eye shadow', 'Lower the light'],
        ['Pattern lost to flat light', 'Raise the light'],
        ['Nose shadow crossing onto narrow side', 'Angle is wrong — pull key back toward broad side'],
      ],
    },
    capture: {
      lookFor: [
        'Broad cheek lit, narrow cheek in shadow',
        'Face appears fuller, open, approachable',
        'Good for thin or angular faces',
      ],
      fixes: [
        ['Subject looks heavier than desired', 'Switch to short lighting instead'],
        ['Pattern drifting to loop', 'That\'s fine — broad loop is the common case'],
        ['Flat/dimensionless', 'Verify subject actually turned AWAY from camera'],
      ],
    },
  },

  SHORT: {
    position: {
      lookFor: [
        'Subject face turned TOWARD camera slightly',
        'Key lighting the side of the face AWAY from camera (the short side)',
        'Near (camera-side) cheek is the shadow side',
      ],
      fixes: [
        ['Pattern on wrong cheek', 'Subject turned wrong way — flip head direction'],
        ['Face looks wide', 'Not short — key is on broad side, swap sides'],
        ['Pattern gone flat', 'Push key further off-axis on the far side'],
      ],
    },
    distance: {
      lookFor: [
        'Short (far) side lit, near side falling to shadow',
        'Smooth falloff across the bridge of the nose',
        'Cheekbone on camera-side carved and dimensional',
      ],
      fixes: [
        ['Short-side highlight too small', 'Pull light closer or reposition subject head'],
        ['Near side crushed black', 'Lift ambient or add low fill'],
        ['Loss of modeling', 'Pull closer for more wrap'],
      ],
    },
    height: {
      lookFor: [
        'Catchlight in far (short-side) eye primary',
        'Near eye may have small/dim catchlight',
        'Nose shadow angles across the bridge toward the near cheek',
      ],
      fixes: [
        ['Nose shadow too long', 'Lower the light'],
        ['Pattern flattening toward butterfly', 'Raise the light slightly or increase off-axis'],
        ['Near side eye totally dark', 'Raise light or add fill — avoid dead socket'],
      ],
    },
    capture: {
      lookFor: [
        'Short side lit, near side in shadow — slimming effect',
        'Face reads narrower, sculpted',
        'Best for round or wide faces',
      ],
      fixes: [
        ['Lost the slimming effect', 'Verify near side is actually shadowed'],
        ['Too severe/unflattering', 'Add fill on the camera side to open shadows'],
        ['Drifted to split', 'Reduce off-axis angle back toward 30–60°'],
      ],
    },
  },

  CLAMSHELL: {
    position: {
      lookFor: [
        'Butterfly pattern above — symmetric nose shadow',
        'Fill source (reflector/second light) directly below chin',
        'Two catchlights per eye: one at 12, one at 6',
      ],
      fixes: [
        ['Only one catchlight (top)', 'Add fill below — that\'s the second jaw of the clam'],
        ['Nose shadow offset', 'Top light has drifted off-axis — recenter to 0°'],
        ['Fill overpowering top', 'Pull the bottom fill down or reduce output'],
      ],
    },
    distance: {
      lookFor: [
        'Glossy, even skin — signature beauty look',
        'No harsh shadows anywhere on the face',
        'Cheekbones still have subtle shape, not totally flat',
      ],
      fixes: [
        ['Skin looks pasty/flat', 'Back off the fill OR increase top-to-fill ratio'],
        ['Too much contrast left', 'Bring fill closer — clamshell is a wrap'],
        ['Hot spot on forehead', 'Top light too close — pull back or feather'],
      ],
    },
    height: {
      lookFor: [
        'Top light ~45° above subject, aimed down at the face',
        'Bottom fill level with or just below the chin, tilted up',
        'Catchlights at 12 and 6 in each iris',
      ],
      fixes: [
        ['Bottom catchlight missing', 'Raise the fill into eyeline'],
        ['Ghoulish under-lighting', 'Fill is too strong — it should SUPPORT, not compete'],
        ['Shadows under the jaw', 'Bring fill up closer to the chin line'],
      ],
    },
    capture: {
      lookFor: [
        'Glamour/beauty look — open, luminous, forgiving',
        'Dual catchlights, top AND bottom',
        'No shadow under jaw, no raccoon eyes',
      ],
      fixes: [
        ['Pattern reading as butterfly', 'Fill is missing or too weak — lift it'],
        ['Eyes looking dead', 'Raise fill or tilt reflector up into the eyes'],
        ['Looks over-retouched', 'Reduce fill ratio — you\'ve killed all modeling'],
      ],
    },
  },

  RIM: {
    position: {
      lookFor: [
        'Key light placed BEHIND the subject, off-axis from camera',
        'Clean bright edge along hair, shoulder, and silhouette',
        'Face reads mostly dark with a luminous outline',
      ],
      fixes: [
        ['Light spilling onto the face front', 'Key is too far forward — move it behind the shoulder line'],
        ['No rim visible', 'Key is directly behind subject — angle it off-axis 30–45°'],
        ['Double rim on both sides', 'One of your sources is fronting — isolate the back key'],
      ],
    },
    distance: {
      lookFor: [
        'Rim is a clean edge, not a halo blur',
        'Separation between subject and background',
        'Highlight holds detail, not blown',
      ],
      fixes: [
        ['Rim is blown out and flaring', 'Back the light off or flag lens from direct hit'],
        ['Rim fading into background', 'Pull closer or darken the background'],
        ['Lens flare washing image', 'Add a flag between light and camera'],
      ],
    },
    height: {
      lookFor: [
        'Rim traces hair, temple, cheekbone, jaw — top-down path',
        'No rim line breaking mid-face',
        'Shoulder gets rim without flood onto chest',
      ],
      fixes: [
        ['Only hair is rim-lit', 'Lower the light to catch more of the face edge'],
        ['Rim hits the eye socket directly', 'Raise and tilt away from the eye plane'],
        ['Pants/shoulder flooded', 'Flag lower spill or tilt light up'],
      ],
    },
    capture: {
      lookFor: [
        'Strong separation rim on dark background',
        'Mood is dramatic, cinematic, high-contrast',
        'Face detail is minimal — outline does the work',
      ],
      fixes: [
        ['Too dark to read the subject', 'Add minimal front fill — whisper, not key'],
        ['Drifted to silhouette', 'Boost any available front ambient'],
        ['Background drowning rim', 'Darker background or brighter rim — need 2+ stops'],
      ],
    },
  },

  RING_LIGHT: {
    position: {
      lookFor: [
        'Light encircles the lens — camera peers through the ring',
        'Donut or circular catchlight in both irises',
        'Shadow is an even halo around the subject, NOT directional',
      ],
      fixes: [
        ['Directional shadow on wall', 'Ring is off-axis — center it on the lens'],
        ['Donut catchlight broken', 'Subject is off-center or looking away from the ring'],
        ['Only one eye has the donut', 'Square the subject to the camera/ring axis'],
      ],
    },
    distance: {
      lookFor: [
        'Even, shadowless wrap across the entire face',
        'Signature flat-but-luminous beauty look',
        'Skin reads smooth, porcelain',
      ],
      fixes: [
        ['Face looks harsh/digital', 'Pull closer — ring wants intimate distance'],
        ['Halo shadow creeping onto background', 'Pull subject away from the wall'],
        ['Hot spot on forehead', 'Back ring off or dial power down'],
      ],
    },
    height: {
      lookFor: [
        'Ring centered on the eye line, lens through middle',
        'Donut catchlights sit dead-center at 12 clock position',
        'No bias top or bottom — symmetric wrap',
      ],
      fixes: [
        ['Donut offset low', 'Raise ring to eye level'],
        ['Shadow under chin', 'Ring is above eyeline — drop it'],
        ['Looking up at ring', 'Match subject eyeline exactly'],
      ],
    },
    capture: {
      lookFor: [
        'Perfect circular catchlights — the ring signature',
        'Beauty/editorial look with no cast shadow',
        'Background free of directional shadow',
      ],
      fixes: [
        ['No donut visible', 'Subject is not looking through the ring — recenter'],
        ['Too flat for taste', 'Add a hair light or kicker for separation'],
        ['Skin looks waxy', 'Slight ambient fill will soften the clinical look'],
      ],
    },
  },

  HIGH_KEY: {
    position: {
      lookFor: [
        'Multiple sources lifting shadows everywhere',
        'Background at or near full white',
        'Key light soft and broad — no harsh geometry',
      ],
      fixes: [
        ['Hard shadow visible anywhere', 'Soften or add fill — high-key tolerates no harsh shape'],
        ['Background reading gray', 'Add background lights or raise their output'],
        ['One side dark', 'High-key is ratio 1:1 or 1:1.5 — lift the weak side'],
      ],
    },
    distance: {
      lookFor: [
        'Expansive wrap from large modifiers, close-in',
        'Skin glowing, not blown, with subtle highlights',
        'Negative space in frame is bright white, not textured',
      ],
      fixes: [
        ['Skin losing texture', 'Back the key off slightly — you\'re clipping highlights'],
        ['Background not white enough', 'Move subject further from background OR raise bg lights'],
        ['Ratio feels heavy', 'Bring fill closer OR add another fill source'],
      ],
    },
    height: {
      lookFor: [
        'Soft, even top-down illumination',
        'Minimal under-eye shadow',
        'Chin and jaw both readable without darkness',
      ],
      fixes: [
        ['Under-eye shadow visible', 'Add clamshell fill or lower the key'],
        ['Top of head dark', 'Key is too low — raise it'],
        ['Nose shadow too defined', 'Soften or raise the key'],
      ],
    },
    capture: {
      lookFor: [
        'Bright, airy, optimistic mood',
        'Near-white background without being blown out of the frame',
        'Skin luminous, shadow-free, but with detail',
      ],
      fixes: [
        ['Feels blown out, not high-key', 'Ease key output OR meter to hold highlights'],
        ['Mood reading cold/clinical', 'Warm the key color temp slightly'],
        ['Looks flat/lifeless', 'Add minimal kicker or rim for subtle separation'],
      ],
    },
  },

  LOW_KEY: {
    position: {
      lookFor: [
        'Single directional key, everything else dark',
        'Pools of deep shadow dominate the frame',
        'Background falls to black or near-black',
      ],
      fixes: [
        ['Shadows muddy, not black', 'Flag all ambient spill — low-key demands control'],
        ['Too much fill', 'Cut fill entirely or use negative fill'],
        ['Background reading as gray', 'Add more distance from subject to background'],
      ],
    },
    distance: {
      lookFor: [
        'Controlled, sculpting key — often tighter modifier',
        'Deep falloff from lit side to shadow',
        'Highlights intact, shadows crushed',
      ],
      fixes: [
        ['Highlights clipping', 'Ease the key — drama lives in shadow, not blown white'],
        ['Falloff too gradual', 'Pull key further away OR grid/tighten the modifier'],
        ['Wrap too generous', 'Use a smaller or tighter source'],
      ],
    },
    height: {
      lookFor: [
        'Strong directional shape — Rembrandt or split geometry typical',
        'Clean shadow edges where the light lands',
        'Eyes catch the light, rest of face in mood shadow',
      ],
      fixes: [
        ['Eyes disappearing into shadow', 'Raise or lower key slightly to catch the socket'],
        ['Pattern reading sloppy', 'Commit to a pattern — split or Rembrandt — and shape it'],
        ['Face feels random', 'Pick a geometry and stick with it'],
      ],
    },
    capture: {
      lookFor: [
        'Dark, dramatic, cinematic mood',
        'Deep blacks and controlled highlights',
        'Clear chiaroscuro storytelling',
      ],
      fixes: [
        ['Not dark enough', 'Kill ambient — turn off room lights if needed'],
        ['Feels flat and moody', 'Commit harder to contrast — cut fill entirely'],
        ['Lost detail in shadow', 'Slightly raise fill just for subject, keep bg dark'],
      ],
    },
  },

  FLAT: {
    position: {
      lookFor: [
        'No directional shadow on the face',
        'Even illumination from multiple angles or a huge wrap source',
        'Subject has minimal modeling — fashion/catalog look',
      ],
      fixes: [
        ['Directional shadow visible', 'Add fill opposite the key to eliminate it'],
        ['Catchlights unbalanced', 'Balance both sources — flat wants symmetry'],
        ['Nose shadow present', 'Raise fill or widen wrap'],
      ],
    },
    distance: {
      lookFor: [
        'Close, large sources wrapping the subject',
        'Skin evenly lit, minimal falloff across the face',
        'Clean, editorial, retouch-friendly tonality',
      ],
      fixes: [
        ['Falloff from center to edge of face', 'Pull sources closer OR use larger modifiers'],
        ['Skin hot on one side', 'Balance sources to match output'],
        ['Background darker than subject', 'Light background separately'],
      ],
    },
    height: {
      lookFor: [
        'Sources at or near eye level, symmetric',
        'No top-light shadow under the chin',
        'No cross-shadow on the nose',
      ],
      fixes: [
        ['Shadow under chin', 'Lower the sources toward eye level'],
        ['Eye socket dark', 'Raise slightly OR add small clamshell fill'],
        ['Over-lit forehead', 'Sources too high — drop to eye level'],
      ],
    },
    capture: {
      lookFor: [
        'Clean, even, shadowless portrait',
        'Catalog/fashion/editorial clarity',
        'Skin tone reads accurately with minimal color shift',
      ],
      fixes: [
        ['Feels boring/lifeless', 'Flat is a choice — add a kicker or accent for interest'],
        ['Not flat enough', 'Add more sources or move them closer'],
        ['Reading washed out', 'Pull back overall exposure — flat is not blown'],
      ],
    },
  },
};

function coachingFor(pattern, stepKey) {
  const p = (pattern || '').toUpperCase();
  return PATTERN_COACHING[p]?.[stepKey] || null;
}

// ─── Derive per-step content from engine data ───────────────────────────────
function buildSteps({ pattern, confidence, modName, position, distance,
  heightDisplay, angleDeg, asymmetry, noseShadowAngle, cct, angularArea }) {

  const targetRange = targetRangeFor(pattern);
  const coach = stepKey => coachingFor(pattern, stepKey);

  // PHOTOGRAPHER — terse numeric leads, angle is primary photographer speak
  const photographer = [
    {
      key: 'setup',
      title: 'YOUR SETUP',
      lead: modName,
      subLead: `${pattern} · ${confidence}%`,
      coach: null,
    },
    {
      key: 'position',
      title: 'KEY ANGLE',
      lead: angleDeg != null ? `${angleDeg}°` : position,
      subLead: targetRange
        ? `${pattern.toLowerCase()} target ${targetRange} · ${position}`
        : (angleDeg != null ? `${position} · ${modName}` : modName),
      coach: coach('position'),
    },
    {
      key: 'distance',
      title: 'DISTANCE',
      lead: distance,
      subLead: angularArea ? `${angularArea} wrap` : 'to subject',
      coach: coach('distance'),
    },
    {
      key: 'height',
      title: 'HEIGHT',
      lead: heightDisplay,
      subLead: 'tilt onto eyes',
      coach: coach('height'),
    },
    {
      key: 'capture',
      title: 'READY',
      lead: pattern,
      subLead: `${confidence}% confidence`,
      coach: coach('capture'),
    },
  ];

  // ASSISTANT — single HUGE command, imperative verbs, angle leads, clock as sub
  const assistant = [
    {
      key: 'setup',
      verb: 'SETUP',
      command: modName.toUpperCase(),
      subCommand: `${pattern} · ${confidence}%`,
      coach: null,
    },
    {
      key: 'position',
      verb: 'PLACE KEY',
      command: angleDeg != null ? `${angleDeg}°` : (position || '').toUpperCase(),
      subCommand: (() => {
        const parts = [];
        if (position) parts.push(position.toUpperCase());
        if (targetRange) parts.push(`${pattern} ${targetRange}`);
        if (modName) parts.push(modName.toUpperCase());
        return parts.length ? parts.join(' · ') : null;
      })(),
      coach: coach('position'),
    },
    {
      key: 'distance',
      verb: 'DISTANCE',
      command: (distance || '').toUpperCase(),
      subCommand: modName ? modName.toUpperCase() : null,
      coach: coach('distance'),
    },
    {
      key: 'height',
      verb: 'HEIGHT',
      command: (heightDisplay || '').toUpperCase(),
      subCommand: modName ? modName.toUpperCase() : null,
      coach: coach('height'),
    },
    {
      key: 'capture',
      verb: 'FIRE FRAME',
      command: pattern,
      coach: coach('capture'),
    },
  ];

  // LEARNING — pattern-specific copy. Each lighting pattern has a distinct
  // personality, shadow signature, and teaching angle. A grandmother should
  // be able to follow every sentence.
  const _hLow = heightDisplay === 'Low' || heightDisplay === 'low';
  const _hHigh = heightDisplay === 'High' || heightDisplay === 'high';
  const _p = (pattern || '').toLowerCase();
  const _pos = (position || '').toLowerCase() || 'the side';

  // Pattern-specific personality
  const _patternVibe = {
    rembrandt: { mood: 'dramatic and sculptural', shadow: 'a small triangle of light on the shadow cheek, just below the eye', signature: 'Rembrandt triangle', origin: 'Named after the painter who used this shadow shape in nearly every portrait.' },
    loop:      { mood: 'natural and flattering', shadow: 'a small loop-shaped shadow from the nose that doesn\'t quite touch the cheek', signature: 'loop shadow', origin: 'The most common portrait pattern because it flatters almost every face shape.' },
    butterfly: { mood: 'glamorous and symmetrical', shadow: 'a butterfly-shaped shadow directly under the nose', signature: 'butterfly shadow', origin: 'Used in classic Hollywood glamour photography — the light sits directly in front, high above.' },
    clamshell: { mood: 'clean and beauty-focused', shadow: 'almost no shadows at all — the face is evenly lit with soft, glowing skin', signature: 'shadowless beauty look', origin: 'The go-to for beauty and skincare photography. Two lights (above + below) wrap the face completely.' },
    split:     { mood: 'bold and dramatic', shadow: 'exactly half the face lit, half in deep shadow — a hard vertical line down the center', signature: 'half-and-half split', origin: 'The most dramatic portrait pattern. One side of the face tells the story, the other hides in mystery.' },
    short:     { mood: 'slimming and dimensional', shadow: 'the narrow (short) side of the face is lit while the wider side falls into shadow', signature: 'short-side lighting', origin: 'Photographers use this to slim the face and add depth. The light hits the side of the face that\'s turned away from camera.' },
    broad:     { mood: 'open and wide', shadow: 'the broad (camera-facing) side of the face is lit, with shadow falling away from camera', signature: 'broad-side lighting', origin: 'Makes the face appear wider and more open. Often used for thin faces that need more visual weight.' },
  };
  const _v = _patternVibe[_p] || { mood: 'distinctive', shadow: 'a characteristic shadow pattern on the face', signature: 'shadow pattern', origin: 'Each lighting pattern creates a unique shadow shape that defines the mood of the portrait.' };

  const learning = [
    {
      key: 'setup',
      title: 'WHAT YOU\'RE BUILDING',
      lead: `This is ${pattern} lighting — it creates a ${_v.mood} look. You'll use a ${modName} as your main light.`,
      why: `${_v.origin} The defining feature: ${_v.shadow}. Your ${modName} will create this shape — we just need to put it in the right spot.`,
      coach: null,
    },
    {
      key: 'position',
      title: 'WHERE TO PUT THE LIGHT',
      lead: _p === 'butterfly' || _p === 'clamshell'
        ? `Place your ${modName} directly in front of your subject, centered with the camera. The light should come from straight ahead.`
        : _p === 'split'
          ? `Move your ${modName} to the ${_pos} — all the way to 90°, perpendicular to the face. You want it lighting exactly one half.`
          : _p === 'rembrandt'
            ? `Swing your ${modName} to the ${_pos} — about 45° from the camera. You're looking for that sweet spot where the nose shadow just reaches the far cheek.`
            : `Move your ${modName} to the ${_pos}. The angle creates the ${_v.signature} — further to the side means more dramatic shadows, closer to center means flatter light.`,
      why: _p === 'butterfly' || _p === 'clamshell'
        ? `Centered light eliminates side shadows completely. That's why it's so flattering for beauty work — no unflattering shadows under cheekbones or along the jawline. The only shadow you'll see is a small ${_v.signature} directly under the nose.`
        : _p === 'split'
          ? `At 90°, the nose acts like a wall — light can't wrap around to the other side. That's what creates the clean vertical division. Even a few degrees off will start to let light leak onto the shadow side.`
          : _p === 'rembrandt'
            ? `The magic angle for Rembrandt is where the nose shadow extends just far enough to connect with the cheek shadow — creating a small triangle of light on the shadow-side cheek. If you can't see the triangle, move the light further to the side. If the shadow side goes completely dark, you've gone too far.`
            : `The position of your light relative to the face is what creates the specific shadow shape. Think of it like sunlight through a window — where the window is determines where the shadows fall.`,
      coach: coach('position'),
    },
    {
      key: 'distance',
      title: 'HOW FAR AWAY',
      lead: `Place the light about ${distance} from your subject.`,
      why: _p === 'clamshell' || _p === 'butterfly'
        ? `For ${pattern.toLowerCase()}, distance matters a lot. Too close and the light wraps too much — you lose the clean ${_v.signature}. Too far and the light gets harsh. At ${distance}, your ${modName} is close enough to keep skin smooth but controlled enough to hold the pattern.`
        : _p === 'split'
          ? `With split lighting, moving closer makes the lit side softer and the transition at the center more gradual. Moving farther makes the edge sharper and more dramatic. At ${distance}, you get a defined split that still has some skin texture visible.`
          : _p === 'rembrandt'
            ? `At ${distance}, your ${modName} creates shadows that have a soft edge — firm enough to see the Rembrandt triangle clearly, but gentle enough that the skin still looks natural. Closer would make it too soft to see the triangle; farther would make the shadows too harsh.`
            : `The simple rule: closer = softer shadows (like an overcast day). Farther = harder shadows (like direct sun). At ${distance}, you get the right balance for ${pattern.toLowerCase()} — defined shadows without being harsh.`,
      coach: coach('distance'),
    },
    {
      key: 'height',
      title: 'HOW HIGH',
      lead: _p === 'butterfly' || _p === 'clamshell'
        ? `Raise the light directly above the camera — high enough to create the ${_v.signature}, aimed down at the face.`
        : _p === 'split'
          ? _hHigh
            ? `Raise the light above head height. For split lighting, height adds drama — a higher light makes the lit side more sculpted.`
            : `Keep the light at about face level. This keeps the split clean and even from forehead to chin.`
          : _hHigh
            ? `Raise the light well above your subject's head — aim it down toward the eyes, like afternoon sun.`
            : _hLow
              ? `Keep the light near eye level — you want it looking straight at the face.`
              : `Set the light just above eye level — tilted slightly down toward the face.`,
      why: _p === 'butterfly'
        ? `Height is everything for butterfly lighting. The higher the light, the longer the shadow under the nose. You want a short, symmetrical butterfly shape — not a long shadow that reaches the lip. Watch for the bright spark (catchlight) in the eyes at the 12 o'clock position. If you can't see it, the light is too high.`
        : _p === 'clamshell'
          ? `The top light creates the main shape. Your fill light (or reflector) below opens up the shadows under the chin and eyes. Together they "clam shell" the face in soft, even light. Check for two catchlights — one from above, one from below.`
          : _p === 'rembrandt'
            ? `Height controls the Rembrandt triangle. Too high: the triangle disappears and the eye sockets go dark (raccoon eyes). Too low: the triangle opens up into a loop pattern instead. The sweet spot: you can see the triangle AND a bright spark of light in both eyes.`
            : `Height controls the length of the nose shadow. Higher = longer shadow = more dramatic. Lower = shorter shadow = softer feel. The key check: can you see a bright spark of light reflected in both eyes? If not, the light is too high — lower it until you see that spark.`,
      coach: coach('height'),
    },
    {
      key: 'capture',
      title: 'TAKE THE SHOT',
      lead: (() => {
        try {
          const _cp = (loadSettings().comparisonPrompts || 'auto');
          if (_cp === 'off') return `You're set for ${pattern.toLowerCase()}. Take the shot.`;
          if (_cp === 'low_conf_only' && confidence >= 70) return `You're set for ${pattern.toLowerCase()}. Take the shot.`;
        } catch {}
        return `You're set for ${pattern.toLowerCase()}. Take a photo and compare it to the reference.`;
      })(),
      why: _p === 'rembrandt'
        ? `Check for three things: (1) Can you see the small triangle of light on the shadow cheek? That's the Rembrandt signature. (2) Is there a bright spark in both eyes? (3) Does the shadow side still show some detail — it shouldn't be pure black. If the triangle is missing, adjust position. If eyes are dark, lower the light.`
        : _p === 'butterfly'
          ? `Check for: (1) A symmetrical butterfly shadow under the nose — it should be centered, not leaning to one side. (2) Catchlights at the top of both eyes (12 o'clock). (3) Clean jawline without heavy shadows. If the shadow leans, your light isn't centered.`
          : _p === 'split'
            ? `Check for: (1) A clean, straight line dividing the lit and shadow sides of the face. (2) The line should run through the center of the nose. (3) The shadow side can be very dark — that's intentional. If light is leaking onto the shadow side, push the light further to the side.`
            : `Check your photo against the reference: (1) Does the shadow shape on the face match? (2) Can you see a bright spark of light in both eyes? (3) Is there detail in the shadow side — not pure black? If something's off, adjust one thing at a time. Start with position, then distance, then height.`,
      coach: coach('capture'),
    },
  ];

  return { photographer, assistant, learning };
}

export default function Day1ShootScreen({ result, imagePreview, mode = 'photographer', onExit, onLiveView, onShare }) {
  const [capturePressed, setCapturePressed] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [framesCaptured, setFramesCaptured] = useState(0);
  const [justCaptured, setJustCaptured] = useState(false);
  const [heroZoomed, setHeroZoomed] = useState(false);
  const [heroFitMode, setHeroFitMode] = useState('contain'); // 'contain' | 'cover'
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const outcomeSentRef = useRef(false);
  const [shareStatus, setShareStatus] = useState(null);
  const [shareUrl, setShareUrl] = useState(null);
  const [modalCopied, setModalCopied] = useState(false);

  // ── Cockpit teach overlay (first-time user onboarding) ────────────────────
  const [cockpitTeachStep, setCockpitTeachStep] = useState(0);
  const [cockpitTeachVisible, setCockpitTeachVisible] = useState(() => {
    try { return localStorage.getItem('ngw_cockpit_teach_seen') !== '1'; } catch { return false; }
  });
  const advanceCockpitTeach = useCallback(() => {
    setCockpitTeachStep(prev => {
      if (prev >= 3) {
        setCockpitTeachVisible(false);
        try { localStorage.setItem('ngw_cockpit_teach_seen', '1'); } catch { /* ignore */ }
        return prev;
      }
      return prev + 1;
    });
  }, []);
  const skipCockpitTeach = useCallback(() => {
    setCockpitTeachVisible(false);
    try { localStorage.setItem('ngw_cockpit_teach_seen', '1'); } catch { /* ignore */ }
  }, []);

  // C-5: Horizontal swipe navigation between steps
  const swipeRef = useRef({ startX: 0, startY: 0, swiping: false });
  const stepsCountRef = useRef(5); // updated after steps is computed
  const handleSwipeStart = useCallback((e) => {
    const t = e.touches[0];
    swipeRef.current = { startX: t.clientX, startY: t.clientY, swiping: true };
  }, []);
  const handleSwipeEnd = useCallback((e) => {
    if (!swipeRef.current.swiping) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - swipeRef.current.startX;
    const dy = t.clientY - swipeRef.current.startY;
    swipeRef.current.swiping = false;
    // Only count horizontal swipes where |dx| > 50px and |dx| > |dy| * 1.5
    if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    const maxIdx = stepsCountRef.current - 1;
    if (dx < 0) {
      // Swipe left → next step
      setStepIndex((i) => { const next = Math.min(maxIdx, i + 1); if (next !== i) { tapHaptic(); softClickSound(); } return next; });
    } else {
      // Swipe right → prev step
      setStepIndex((i) => { const prev = Math.max(0, i - 1); if (prev !== i) { navHaptic(); softClickSound(); } return prev; });
    }
  }, []);

  // Long-press detection for hero zoom — same trigger feel as ResultScreen.
  const heroLongPressTimer = useRef(null);
  const heroLongPressFired = useRef(false);
  const startHeroLongPress = useCallback(() => {
    heroLongPressFired.current = false;
    if (heroLongPressTimer.current) clearTimeout(heroLongPressTimer.current);
    heroLongPressTimer.current = setTimeout(() => {
      heroLongPressTimer.current = null;
      heroLongPressFired.current = true;
      longPressHaptic();
      setHeroZoomed(true);
    }, 500);
  }, []);
  const endHeroLongPress = useCallback(() => {
    if (heroLongPressTimer.current) {
      clearTimeout(heroLongPressTimer.current);
      heroLongPressTimer.current = null;
    }
  }, []);
  const heroPressHandlers = {
    onPointerDown: startHeroLongPress,
    onPointerUp: endHeroLongPress,
    onPointerLeave: endHeroLongPress,
    onPointerCancel: endHeroLongPress,
    onDoubleClick: () => { longPressHaptic(); setHeroZoomed(true); },
  };

  useWakeLock(true);

  // ── VF geometry — match Home / Results viewfinder height ───────────────────
  // L-1 / user request: "same vf size for cockpit as other windows".
  // Replicates the HomeScreen fluid VF calc so the reference photo is identical.
  const { stableVH, safeBottom, isDesktop: _isDesktopGlobal } = useStableViewport();
  // Cockpit uses a LOCAL wide-screen check at 768px so tablet portrait
  // (iPad mini) gets the two-column photo+chrome layout.  Other screens
  // keep the global LAYOUT_DESKTOP_MIN = 1024 threshold to avoid the
  // FitToViewport conflict zone.
  const _isTabletUp = useMinWidth(TABLET_MIN_WIDTH);
  const isDesktop = _isDesktopGlobal || _isTabletUp;
  // Scale layout for short phones (same strategy as HomeScreen)
  const VF_TOP = isDesktop ? 100
    : stableVH <= 600 ? 56
    : stableVH <= 700 ? 68
    : 88;
  const VF_BTN_D = 136;
  const VF_WELL_D = 146;
  const VF_BTN_OFFSET = isDesktop ? 48
    : stableVH <= 600 ? 24
    : stableVH <= 700 ? 32
    : stableVH <= 780 ? 40
    : 48;
  const rawVfBtnCY = stableVH - safeBottom - VF_BTN_OFFSET - Math.round(VF_BTN_D / 2);
  const maxVfBtnCY = stableVH - safeBottom - VF_BTN_D / 2 - 8;
  const VF_BTN_CY = Math.min(rawVfBtnCY, maxVfBtnCY);
  const VF_WELL_TOP = VF_BTN_CY - VF_WELL_D / 2;
  const VF_GAP = stableVH <= 700 ? 10 : 16;
  const VF_HEIGHT = Math.max(200, VF_WELL_TOP - VF_GAP - VF_TOP);

  const modeInfo = MODE_LABELS[mode] || MODE_LABELS.photographer;
  const isAssistant = mode === 'assistant';
  const isLearning = mode === 'learning';

  // ── Derived engine data ────────────────────────────────────────────────────
  const pattern = result?.pattern || 'SETUP';
  const confidence = result?.confidence ?? 0;
  const modName = result?.sections?.modifier?.family || 'Modifier';
  const position = result?.sections?.modifier?.position
    || result?._raw?.lighting_inference?.key_position_text
    || '—';
  const distance = result?.sections?.modifier?.distRange || '—';
  const angularArea = result?.sections?.modifier?.angularArea || null;
  const heightRaw = result?._raw?.reconstruction?.key_light_height
    || result?._raw?.lighting_inference?.key_elevation;
  const heightDisplay = (() => {
    if (!heightRaw) return '—';
    if (typeof heightRaw === 'string') return heightRaw.charAt(0).toUpperCase() + heightRaw.slice(1);
    if (typeof heightRaw === 'number') {
      if (heightRaw >= 0.66) return 'High';
      if (heightRaw >= 0.33) return 'Medium';
      return 'Low';
    }
    return '—';
  })();
  const angleDeg = result?._raw?.reconstruction?.key_light_angle_deg;
  const signals = result?._raw?.signal_diagnostics?.signals || {};
  const asymmetry = signals.left_right_asymmetry;
  const noseShadowAngle = signals.nose_shadow_angle_deg;
  const cct = result?._raw?.lighting_inference?.detected_cct_kelvin
    || result?._raw?.reconstruction?.dominant_cct_kelvin;

  const stepsAll = useMemo(() => buildSteps({
    pattern, confidence, modName, position, distance, heightDisplay,
    angleDeg: (typeof angleDeg === 'number') ? Math.round(angleDeg) : null,
    asymmetry, noseShadowAngle, cct, angularArea,
  }), [pattern, confidence, modName, position, distance, heightDisplay,
       angleDeg, asymmetry, noseShadowAngle, cct, angularArea]);

  const steps = stepsAll[mode] || stepsAll.photographer;
  stepsCountRef.current = steps.length; // C-5: keep swipe handler in sync
  const step = steps[stepIndex];
  const isLast = stepIndex === steps.length - 1;
  const isFirst = stepIndex === 0;

  useEffect(() => {
    trackEvent('SHOOT_MODE_ENTERED', { pattern, confidence, mode });
  }, [pattern, confidence, mode]);

  useEffect(() => {
    trackEvent('SHOOT_MODE_STEP_VIEW', { mode, stepKey: step.key, stepIndex });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex]);

  // Build the signal payload from the Day1 result schema and fire it.
  // Every cockpit session must produce a signal — pass null for "skipped".
  const fireOutcomeSignal = useCallback((outcomeValue) => {
    if (outcomeSentRef.current) return;
    outcomeSentRef.current = true;
    const _user = (() => { try { return getUser(); } catch { return null; } })();
    const _patternId = result?._raw?.authoritative_pattern || (result?.pattern || '').toLowerCase();
    if (!_patternId) return; // nothing to attribute
    postSignal({
      pattern_id:        _patternId,
      confidence_score:  typeof result?.confidence === 'number' ? result.confidence / 100 : null,
      outcome:           outcomeValue, // null → 'unknown'
      session_id:        (() => { try { return getSessionId(); } catch { return null; } })(),
      user_id:           _user?.id || null,
      input_method:      'reference_photo',
      subject_type:      result?._raw?.subject_type || null,
      environment:       result?._raw?.lighting_inference?.detected_environment || null,
      mood:              null,
      shoot_mode_entered: true,
      steps_completed:    Math.min(stepIndex + 1, steps.length),
      steps_total:        steps.length,
      deviation_count:    0,
      saved_setup:        false,
      upgraded:           false,
      revenue_value:      0,
    });
    trackEvent('OUTCOME_CAPTURED', { mode, outcome: outcomeValue || 'skipped', framesCaptured });
  }, [result, mode, stepIndex, steps, framesCaptured]);

  const handleExit = () => {
    navHaptic(); navSlideSound();
    // If they shot at least one frame, capture an outcome before leaving
    if (framesCaptured > 0 && !outcomeSentRef.current) {
      trackEvent('SHOOT_MODE_EXIT', { mode, framesCaptured });
      setOutcomeOpen(true);
      return;
    }
    onExit?.();
  };
  const handlePrev = () => {
    if (isFirst) return;
    navHaptic(); softClickSound();
    setStepIndex((i) => Math.max(0, i - 1));
  };
  const handleNext = () => {
    if (isLast) return;
    tapHaptic(); softClickSound();
    setStepIndex((i) => Math.min(steps.length - 1, i + 1));
  };
  const handleCapture = () => {
    if (!isLast) { handleNext(); return; }
    successHaptic(); softClickSound();
    const n = framesCaptured + 1;
    setFramesCaptured(n);
    setJustCaptured(true);
    trackEvent('SHOOT_MODE_FRAME_CAPTURED', { mode, frameCount: n });
    setTimeout(() => setJustCaptured(false), 1600);
    // Assistant auto-returns to first action step for next take after brief ack
    // (step 0 is the setup overview — skip it on subsequent takes)
    if (isAssistant) {
      setTimeout(() => setStepIndex(1), 1800);
    }
  };
  const handleDone = () => {
    successHaptic(); navSlideSound();
    trackEvent('SHOOT_MODE_DONE', { mode, framesCaptured });
    if (!outcomeSentRef.current) {
      setOutcomeOpen(true);
      return;
    }
    onExit?.();
  };

  const handleOutcomePick = useCallback((outcome) => {
    fireOutcomeSignal(outcome);
    // Brief delay so the user sees the confirmation copy before we exit
    setTimeout(() => {
      setOutcomeOpen(false);
      onExit?.();
    }, 1100);
  }, [fireOutcomeSignal, onExit]);

  const handleOutcomeDismiss = useCallback(() => {
    // Per signal hygiene rule: every session must produce a signal
    fireOutcomeSignal(null);
    setOutcomeOpen(false);
    onExit?.();
  }, [fireOutcomeSignal, onExit]);

  // ── Role-specific body ────────────────────────────────────────────────────
  const body = isAssistant
    ? <AssistantBody step={step} />
    : isLearning
      ? <LearningBody step={step} imagePreview={imagePreview}
          result={result} stepKey={step.key} position={position}
          angleDeg={angleDeg} distance={distance} pattern={pattern} mode={mode}
          heightDisplay={heightDisplay} modName={modName}
          heroFitMode={heroFitMode} onToggleFit={() => setHeroFitMode(f => f === "contain" ? "cover" : "contain")}
          heroPressHandlers={heroPressHandlers} vfHeight={VF_HEIGHT} hidePhoto={isDesktop} />
      : <PhotographerBody step={step} imagePreview={imagePreview}
          modName={modName} position={position} distance={distance}
          heightDisplay={heightDisplay} angleDeg={angleDeg}
          pattern={pattern} confidence={confidence} cct={cct}
          result={result} stepKey={step.key} mode={mode}
          heroFitMode={heroFitMode} onToggleFit={() => setHeroFitMode(f => f === "contain" ? "cover" : "contain")}
          heroPressHandlers={heroPressHandlers} vfHeight={VF_HEIGHT} hidePhoto={isDesktop} />;

  const primaryLabel = justCaptured
    ? (isAssistant ? 'FRAME GOT' : 'FRAME CAPTURED')
    : isLast
      ? (framesCaptured > 0 ? `CAPTURE · ${framesCaptured + 1}` : 'CAPTURE')
      : (isAssistant ? 'READY' : 'NEXT STEP');

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: SCREEN_BG, overflow: 'hidden' }}>
      <div
        onTouchStart={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
        onTouchMove={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
        style={{
        width: '100%', maxWidth: isDesktop ? 1440 : undefined, height: '100%', margin: '0 auto',
        backgroundColor: C.bg,
        display: 'flex', flexDirection: 'column',
        position: 'relative', fontFamily: 'Inter, system-ui, sans-serif',
      }}>

        <MatteBackground variant="carbon" />

        {/* ── Desktop: two-column (photo left, controls right) ──
             Mobile: single-column stack (header → body → dots → controls) ── */}
        {isDesktop && !isAssistant ? (
          <div style={{ display: 'flex', flex: 1, minHeight: 0, position: 'relative', zIndex: 1 }}>
            {/* Left column — reference photo with overlays */}
            {imagePreview && (
              <div
                {...(heroPressHandlers || {})}
                style={{
                  flex: '0 0 55%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: 16, cursor: 'zoom-in', WebkitTapHighlightColor: 'transparent',
                  overflow: 'hidden',
                }}
              >
                <ReferenceWithOverlay
                  imagePreview={imagePreview}
                  result={result}
                  stepKey={step.key}
                  position={position}
                  angleDeg={angleDeg}
                  distance={distance}
                  pattern={pattern}
                  maxHeight={stableVH - 80}
                  mode={mode}
                  fullWidth
                  heightDisplay={heightDisplay}
                  modName={modName}
                heroFitMode={heroFitMode}
                onToggleFit={() => setHeroFitMode(f => f === "contain" ? "cover" : "contain")}
                />
              </div>
            )}

            {/* Right column — header, body content, dots, controls */}
            <div style={{
              flex: imagePreview ? '0 0 45%' : '1 1 100%',
              display: 'flex', flexDirection: 'column',
              minHeight: 0, position: 'relative',
            }}>
              {/* Header */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '20px 28px 12px', flexShrink: 0,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button onClick={handleExit} style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: steel(0.65), fontSize: 15, padding: '4px 0',
                    WebkitTapHighlightColor: 'transparent', ...FONT_SMOOTH,
                  }}>‹ Exit</button>
                  {onLiveView && (
                    <button onClick={() => { tapHaptic(); softClickSound(); onLiveView(); }} style={{
                      background: 'none', border: `1px solid ${steel(0.15)}`, borderRadius: 6,
                      padding: '3px 8px', cursor: 'pointer',
                      WebkitTapHighlightColor: 'transparent',
                    }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: steel(0.45), letterSpacing: '0.5px', ...FONT_SMOOTH }}>LIVE</span>
                    </button>
                  )}
                  {onShare && (
                    <button onClick={async () => {
                      tapHaptic(); softClickSound();
                      setShareStatus('sharing');
                      const result = await onShare();
                      if (result && result.url) {
                        setShareUrl(result.url);
                        setShareStatus('clipboard_fail'); // always show modal with URL
                      } else {
                        setShareStatus('error');
                        setTimeout(() => setShareStatus(null), 3000);
                      }
                    }} disabled={shareStatus === 'sharing'} data-testid="cockpit-share" style={{
                      background: shareStatus === 'shared' ? 'rgba(72,186,136,0.12)' : shareStatus === 'error' ? 'rgba(200,70,70,0.12)' : 'none',
                      border: `1px solid ${shareStatus === 'shared' ? 'rgba(72,186,136,0.30)' : shareStatus === 'error' ? 'rgba(200,70,70,0.25)' : steel(0.15)}`,
                      borderRadius: 6, padding: '3px 8px', cursor: shareStatus === 'sharing' ? 'wait' : 'pointer',
                      WebkitTapHighlightColor: 'transparent', transition: 'all 0.2s ease',
                    }}>
                      {shareStatus === 'sharing' ? <span style={{ fontSize: 11, color: steel(0.45), ...FONT_SMOOTH }}>...</span>
                       : shareStatus === 'shared' ? <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(72,186,136,0.85)', ...FONT_SMOOTH }}>SHARED</span>
                       : shareStatus === 'error' ? <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(200,70,70,0.75)', ...FONT_SMOOTH }}>FAILED</span>
                       : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={steel(0.45)} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                           <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8" /><polyline points="16 6 12 2 8 6" /><line x1="12" y1="2" x2="12" y2="15" />
                         </svg>}
                    </button>
                  )}
                </div>
                <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.75),
                  letterSpacing: '1.4px', ...FONT_SMOOTH }}>
                  {pattern.toUpperCase().replace(/_/g, ' ')} <span style={{ color: steel(0.45), fontWeight: 600, letterSpacing: '0.8px' }}>
                    {stepIndex + 1}/{steps.length}
                  </span>
                </p>
                {framesCaptured > 0 ? (
                  <button onClick={handleDone} style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: C.confHigh, fontSize: 14, fontWeight: 700,
                    letterSpacing: '0.6px', padding: '4px 0',
                    WebkitTapHighlightColor: 'transparent', ...FONT_SMOOTH,
                  }}>DONE · {framesCaptured}</button>
                ) : (
                  <div style={{ width: 40 }} />
                )}
              </div>

              {/* Scrollable body */}
              <div
                onTouchStart={handleSwipeStart}
                onTouchEnd={handleSwipeEnd}
                style={{
                  flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden',
                  WebkitOverflowScrolling: 'touch',
                }}>
                {body}
              </div>

              {/* Step dots */}
              <div style={{
                display: 'flex', justifyContent: 'center', gap: 6,
                padding: '10px 20px 0', flexShrink: 0,
              }}>
                {steps.map((_, i) => (
                  <div key={i}
                    onClick={() => { if (i !== stepIndex) { tapHaptic(); softClickSound(); setStepIndex(i); } }}
                    style={{
                      width: i === stepIndex ? 18 : 6, height: 6, borderRadius: 3,
                      backgroundColor: i === stepIndex ? steel(0.75) : steel(0.18),
                      transition: 'width 0.2s ease, background-color 0.2s ease',
                      cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
                      padding: '8px 4px', margin: '-8px -4px',
                      backgroundClip: 'content-box',
                    }} />
                ))}
              </div>

              {/* Action row */}
              <div style={{
                padding: '14px 28px 20px', display: 'flex', alignItems: 'center', gap: 14, flexShrink: 0,
              }}>
                <button onClick={handlePrev} disabled={isFirst} style={{
                  flex: '0 0 auto', width: 44, height: 44, borderRadius: 22,
                  backgroundColor: C.pillBg,
                  boxShadow: 'inset 0px 2px 4px rgba(0,0,0,0.55), inset 0px 1px 2px rgba(0,0,0,0.35)',
                  border: 'none', cursor: isFirst ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: isFirst ? steel(0.25) : steel(0.7), fontSize: 18,
                  WebkitTapHighlightColor: 'transparent', transition: 'color 0.15s ease', ...FONT_SMOOTH,
                }}>‹</button>
                <button
                  onClick={handleCapture}
                  onPointerDown={() => { setCapturePressed(true); tapHaptic(); }}
                  onPointerUp={() => setCapturePressed(false)}
                  onPointerLeave={() => setCapturePressed(false)}
                  style={{
                    flex: 1, height: 44, borderRadius: 22,
                    background: justCaptured
                      ? 'linear-gradient(141.71deg, rgba(72,186,136,0.55) 0%, rgba(72,186,136,0.3) 100%)'
                      : CTA_BG,
                    boxShadow: capturePressed ? 'inset 0px 2px 4px rgba(0,0,0,0.5)' : `${CTA_SHADOW}, ${CTA_BEVEL}`,
                    border: 'none', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                    WebkitTapHighlightColor: 'transparent',
                    transform: capturePressed ? 'scale(0.98)' : 'scale(1)',
                    transition: 'transform 0.1s ease, box-shadow 0.1s ease, background 0.25s ease',
                  }}
                >
                  {justCaptured && (
                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
                      stroke="rgba(245,247,250,0.95)" strokeWidth="3"
                      strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  )}
                  <span style={{
                    fontSize: 14, fontWeight: 600, color: 'rgba(245,247,250,0.95)',
                    letterSpacing: '0.8px', ...FONT_SMOOTH,
                  }}>{primaryLabel}</span>
                </button>
                <button onClick={handleNext} disabled={isLast} style={{
                  flex: '0 0 auto', width: 44, height: 44, borderRadius: 22,
                  backgroundColor: C.pillBg,
                  boxShadow: 'inset 0px 2px 4px rgba(0,0,0,0.55), inset 0px 1px 2px rgba(0,0,0,0.35)',
                  border: 'none', cursor: isLast ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: isLast ? steel(0.25) : steel(0.7), fontSize: 18,
                  WebkitTapHighlightColor: 'transparent', transition: 'color 0.15s ease', ...FONT_SMOOTH,
                }}>›</button>
              </div>
            </div>
          </div>
        ) : (
          /* ── Mobile / Assistant: original single-column layout ── */
          <>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 20px 6px', position: 'relative', zIndex: 1,
              flexShrink: 0,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button
                  onClick={handleExit}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: steel(0.65), fontSize: 14, padding: '4px 0',
                    WebkitTapHighlightColor: 'transparent', ...FONT_SMOOTH,
                  }}
                >
                  ‹ Exit
                </button>
                {onLiveView && (
                  <button onClick={() => { tapHaptic(); softClickSound(); onLiveView(); }} style={{
                    background: 'none', border: `1px solid ${steel(0.15)}`, borderRadius: 6,
                    padding: '3px 8px', cursor: 'pointer',
                    WebkitTapHighlightColor: 'transparent',
                  }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: steel(0.45), letterSpacing: '0.5px', ...FONT_SMOOTH }}>LIVE</span>
                  </button>
                )}
                {onShare && (
                  <button onClick={async () => {
                    tapHaptic(); softClickSound();
                    setShareStatus('sharing');
                    const result = await onShare();
                    if (result && result.clipboardFailed) {
                      setShareUrl(result.url);
                      setShareStatus('clipboard_fail');
                      setTimeout(() => { setShareStatus(null); setShareUrl(null); }, 12000);
                    } else if (result) {
                      setShareStatus('shared');
                      setTimeout(() => setShareStatus(null), 3000);
                    } else {
                      setShareStatus('error');
                      setTimeout(() => setShareStatus(null), 3000);
                    }
                  }} disabled={shareStatus === 'sharing'} data-testid="cockpit-share" style={{
                    background: shareStatus === 'shared' ? 'rgba(72,186,136,0.12)' : shareStatus === 'error' ? 'rgba(200,70,70,0.12)' : 'none',
                    border: `1px solid ${shareStatus === 'shared' ? 'rgba(72,186,136,0.30)' : shareStatus === 'error' ? 'rgba(200,70,70,0.25)' : steel(0.15)}`,
                    borderRadius: 6, padding: '3px 8px', cursor: shareStatus === 'sharing' ? 'wait' : 'pointer',
                    WebkitTapHighlightColor: 'transparent', transition: 'all 0.2s ease',
                  }}>
                    {shareStatus === 'sharing' ? <span style={{ fontSize: 11, color: steel(0.45), ...FONT_SMOOTH }}>...</span>
                     : shareStatus === 'shared' ? <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(72,186,136,0.85)', ...FONT_SMOOTH }}>SHARED</span>
                     : shareStatus === 'error' ? <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(200,70,70,0.75)', ...FONT_SMOOTH }}>FAILED</span>
                     : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={steel(0.45)} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                         <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8" /><polyline points="16 6 12 2 8 6" /><line x1="12" y1="2" x2="12" y2="15" />
                       </svg>}
                  </button>
                )}
              </div>
              <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: steel(0.75),
                letterSpacing: '1.2px', ...FONT_SMOOTH }}>
                {pattern.toUpperCase().replace(/_/g, ' ')} <span style={{ color: steel(0.45), fontWeight: 600, letterSpacing: '0.8px' }}>
                  {stepIndex + 1}/{steps.length}
                </span>
              </p>
              {framesCaptured > 0 ? (
                <button
                  onClick={handleDone}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: C.confHigh, fontSize: 14, fontWeight: 700,
                    letterSpacing: '0.6px', padding: '4px 0',
                    WebkitTapHighlightColor: 'transparent', ...FONT_SMOOTH,
                  }}
                >
                  DONE · {framesCaptured}
                </button>
              ) : (
                <div style={{ width: 40 }} />
              )}
            </div>

            {/* Scrollable body region */}
            <div
              onTouchStart={handleSwipeStart}
              onTouchEnd={handleSwipeEnd}
              style={{
                flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden',
                WebkitOverflowScrolling: 'touch',
                position: 'relative', zIndex: 1,
              }}>
              {body}
            </div>

            {/* Step dots (hidden in assistant) */}
            {!isAssistant && (
              <div style={{
                display: 'flex', justifyContent: 'center', gap: 6,
                padding: '10px 20px 0', position: 'relative', zIndex: 1,
                flexShrink: 0,
              }}>
                {steps.map((_, i) => (
                  <div key={i}
                    onClick={() => { if (i !== stepIndex) { tapHaptic(); softClickSound(); setStepIndex(i); } }}
                    style={{
                      width: i === stepIndex ? 18 : 6, height: 6, borderRadius: 3,
                      backgroundColor: i === stepIndex ? steel(0.75) : steel(0.18),
                      transition: 'width 0.2s ease, background-color 0.2s ease',
                      cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
                      padding: '8px 4px', margin: '-8px -4px',
                      backgroundClip: 'content-box',
                    }} />
                ))}
              </div>
            )}

            {/* Cockpit action row */}
            <div style={{
              padding: '10px 20px 12px', position: 'relative', zIndex: 1,
              display: 'flex', alignItems: 'center', gap: 12,
              flexShrink: 0,
            }}>
              <button
                onClick={handlePrev}
                disabled={isFirst}
                style={{
                  flex: '0 0 auto',
                  width: isAssistant ? 64 : 44, height: isAssistant ? 64 : 44,
                  borderRadius: isAssistant ? 32 : 22,
                  backgroundColor: C.pillBg,
                  boxShadow: 'inset 0px 2px 4px rgba(0,0,0,0.55), inset 0px 1px 2px rgba(0,0,0,0.35)',
                  border: 'none', cursor: isFirst ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: isFirst ? steel(0.25) : steel(0.7),
                  fontSize: isAssistant ? 26 : 18,
                  WebkitTapHighlightColor: 'transparent',
                  transition: 'color 0.15s ease',
                  ...FONT_SMOOTH,
                }}
              >‹</button>

              <button
                onClick={handleCapture}
                onPointerDown={() => { setCapturePressed(true); tapHaptic(); }}
                onPointerUp={() => setCapturePressed(false)}
                onPointerLeave={() => setCapturePressed(false)}
                style={{
                  flex: 1, height: isAssistant ? 64 : 44,
                  borderRadius: isAssistant ? 32 : 22,
                  background: justCaptured
                    ? 'linear-gradient(141.71deg, rgba(72,186,136,0.55) 0%, rgba(72,186,136,0.3) 100%)'
                    : CTA_BG,
                  boxShadow: capturePressed
                    ? 'inset 0px 2px 4px rgba(0,0,0,0.5)'
                    : `${CTA_SHADOW}, ${CTA_BEVEL}`,
                  border: 'none', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  WebkitTapHighlightColor: 'transparent',
                  transform: capturePressed ? 'scale(0.98)' : 'scale(1)',
                  transition: 'transform 0.1s ease, box-shadow 0.1s ease, background 0.25s ease',
                }}
              >
                {justCaptured && (
                  <svg width={isAssistant ? 18 : 14} height={isAssistant ? 18 : 14} viewBox="0 0 24 24" fill="none"
                    stroke="rgba(245,247,250,0.95)" strokeWidth="3"
                    strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                )}
                <span style={{
                  fontSize: isAssistant ? 16 : 13,
                  fontWeight: isAssistant ? 800 : 600,
                  color: 'rgba(245,247,250,0.95)',
                  letterSpacing: isAssistant ? '1.4px' : '0.8px',
                  ...FONT_SMOOTH,
                }}>
                  {primaryLabel}
                </span>
              </button>

              <button
                onClick={handleNext}
                disabled={isLast}
                style={{
                  flex: '0 0 auto',
                  width: isAssistant ? 64 : 44, height: isAssistant ? 64 : 44,
                  borderRadius: isAssistant ? 32 : 22,
                  backgroundColor: C.pillBg,
                  boxShadow: 'inset 0px 2px 4px rgba(0,0,0,0.55), inset 0px 1px 2px rgba(0,0,0,0.35)',
                  border: 'none', cursor: isLast ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: isLast ? steel(0.25) : steel(0.7),
                  fontSize: isAssistant ? 26 : 18,
                  WebkitTapHighlightColor: 'transparent',
                  transition: 'color 0.15s ease',
                  ...FONT_SMOOTH,
                }}
              >›</button>
            </div>

            {/* iOS home indicator */}
            <div style={{ height: 34, display: 'flex', alignItems: 'center',
              justifyContent: 'center', position: 'relative', zIndex: 1 }}>
              <div style={{ width: 134, height: 5, borderRadius: 3,
                backgroundColor: 'rgba(245,247,250,0.06)' }} />
            </div>
          </>
        )}

        {/* ── Cockpit teach overlay — first-time user walkthrough (mobile only) ── */}
        {cockpitTeachVisible && !isDesktop && (() => {
          // Responsive column width — matches Home teach
          const COL_W = Math.min(430, window.innerWidth);
          const COL_CX = Math.round(COL_W / 2);
          // Cockpit layout geometry — adaptive to viewport height.
          // Instead of hardcoded pixel offsets, derive from stableVH
          // so spotlights land correctly on iPhone SE through Pro Max.
          const _vh = stableVH;
          const _sb = safeBottom;
          // Header: ~44px (12px pad top + 20px content + 12px pad bottom)
          const _headerH = 44;
          // Body starts after header — the scrollable content region
          const _bodyTop = _headerH;
          // Photo/hero zone — occupies roughly 30% of viewport below header
          const _photoTop = _bodyTop + 8;
          const _photoH = Math.round(Math.min(_vh * 0.32, 280));
          // Bottom action row: home indicator (34) + action row (~56) + step dots (~36)
          const _actionRowH = 34 + 56 + 36;
          const _dotsTop = _vh - _sb - _actionRowH + 4;
          const _ctaTop = _vh - _sb - 34 - 56;
          // Card height estimate for clamp
          const _CARD_H = 170;
          const _maxTipY = _vh - _sb - _CARD_H - 8;
          const _minTipY = _sb + 8;
          const _vhMid = Math.round(_vh * 0.38); // push cards toward VF center
          const clampTip = (y) => Math.max(_minTipY, Math.min(_maxTipY, y));

          const _spots = [
            { // Step 0: Reference photo — the target
              x: 20, y: _photoTop, w: COL_W - 40, h: _photoH, r: 12,
              title: 'Your target light',
              desc: 'The light you\'re recreating — match this on set.',
              tipY: clampTip(Math.max(_vhMid, _photoTop + _photoH + 24)),
              arrow: 'up',
            },
            { // Step 1: Step lead + spec strip — the instructions
              x: 16, y: _bodyTop - 4, w: COL_W - 32, h: 64, r: 14,
              title: 'Step-by-step rebuild',
              desc: 'Each step tells you exactly what to place and where.',
              tipY: clampTip(Math.max(_vhMid, _bodyTop + 90)),
              arrow: 'up',
            },
            { // Step 2: Step dots — navigation
              x: COL_CX - 115, y: _dotsTop - 6, w: 230, h: 28, r: 14,
              title: 'Swipe or tap to navigate',
              desc: 'Move between setup steps at your own pace.',
              tipY: clampTip(Math.min(_vhMid, _dotsTop - 180)),
              arrow: 'down',
            },
            { // Step 3: Capture button — the action
              x: COL_CX - 155, y: _ctaTop - 4, w: 310, h: 56, r: 28,
              title: 'Fire when it matches',
              desc: 'Tap Capture once your light matches the reference.',
              tipY: clampTip(Math.min(_vhMid, _ctaTop - 180)),
              arrow: 'down',
            },
          ];
          const _s = _spots[cockpitTeachStep] || _spots[0];
          // Clamp spotlight Y to viewport
          _s.y = Math.max(0, Math.min(_vh - _sb - _s.h, _s.y));
          const _cx = _s.x + _s.w / 2;
          const _cy = _s.y + _s.h / 2;
          const _rx = _s.w / 2 + 14;
          const _ry = _s.h / 2 + 14;
          // Step accent: warm gold → steel → indigo → green
          const _colors = [
            'rgba(200,155,69,1)',    // warm gold (photo)
            'rgba(132,158,184,1)',   // steel (specs)
            'rgba(107,148,245,1)',   // indigo (nav)
            'rgba(72,186,136,1)',    // green (capture)
          ];
          const _sc = _colors[cockpitTeachStep] || _colors[0];

          // Arrow geometry — card shifted left for down-arrows, arrow targets spotlight edge
          const _cardLeft = 24;
          const _cardRight = 24;
          const _cardW = COL_W - _cardLeft - _cardRight;
          const _cardCX = _cardLeft + _cardW / 2;
          const _cardEdgeY = _s.arrow === 'up' ? _s.tipY : _s.tipY + 72;
          // Arrow tip lands at spotlight edge (bottom for up-arrows, top for down)
          const _tipYA = _s.arrow === 'up' ? (_s.y + _s.h) : _s.y;
          const _svgTop = Math.min(_tipYA, _cardEdgeY) - 10;
          const _svgBot = Math.max(_tipYA, _cardEdgeY) + 10;
          const _svgH = _svgBot - _svgTop;
          const _startLY = _cardEdgeY - _svgTop;
          const _endLY = _tipYA - _svgTop;
          // Natural arc: card is left-offset, spotlight centered — modest rightward curve
          const _cpOffset = _s.arrow === 'up' ? 30 : 20;
          const _cpX = (_cardCX + _cx) / 2 + _cpOffset;
          const _cpY1 = _startLY + (_endLY - _startLY) * 0.3;
          const _cpY2 = _startLY + (_endLY - _startLY) * 0.7;
          const _curvePath = `M${_cardCX} ${_startLY} C${_cpX} ${_cpY1}, ${_cpX} ${_cpY2}, ${_cx} ${_endLY}`;
          const _aSize = 8;
          const _aDir = _s.arrow === 'up' ? -1 : 1;
          // Chevron centered on endpoint: tip extends past, arms behind
          const _aHalf = _aSize / 2;
          const _aPath = `M${_cx - _aSize} ${_endLY - _aHalf * _aDir} L${_cx} ${_endLY + _aHalf * _aDir} L${_cx + _aSize} ${_endLY - _aHalf * _aDir}`;
          const _curveLen = Math.hypot(_cx - _cardCX, _endLY - _startLY) * 1.4;

          // Step icons
          const _icons = [
            // 0: camera/viewfinder (photo target)
            <svg key="i0" width="18" height="18" viewBox="0 0 32 32" fill="none">
              <rect x="4" y="8" width="24" height="18" rx="3" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" fill="none" />
              <path d="M12 8V6a2 2 0 012-2h4a2 2 0 012 2v2" stroke={_sc.replace(/[\d.]+\)$/, '0.50)')} strokeWidth="1.5" />
              <circle cx="16" cy="17" r="4.5" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" fill="none" />
              <circle cx="16" cy="17" r="1.5" fill={_sc.replace(/[\d.]+\)$/, '0.45)')} />
            </svg>,
            // 1: list/steps (rebuild instructions)
            <svg key="i1" width="18" height="18" viewBox="0 0 32 32" fill="none">
              <line x1="12" y1="9" x2="26" y2="9" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" />
              <line x1="12" y1="16" x2="26" y2="16" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" />
              <line x1="12" y1="23" x2="26" y2="23" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" />
              <circle cx="7" cy="9" r="2" fill={_sc.replace(/[\d.]+\)$/, '0.45)')} />
              <circle cx="7" cy="16" r="2" fill={_sc.replace(/[\d.]+\)$/, '0.45)')} />
              <circle cx="7" cy="23" r="2" fill={_sc.replace(/[\d.]+\)$/, '0.45)')} />
            </svg>,
            // 2: arrows left-right (swipe nav)
            <svg key="i2" width="18" height="18" viewBox="0 0 32 32" fill="none">
              <path d="M10 16H22" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" />
              <path d="M7 16l4-4M7 16l4 4" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M25 16l-4-4M25 16l-4 4" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>,
            // 3: shutter/capture (fire)
            <svg key="i3" width="18" height="18" viewBox="0 0 32 32" fill="none">
              <circle cx="16" cy="16" r="12" stroke={_sc.replace(/[\d.]+\)$/, '0.30)')} strokeWidth="1.6" fill="none" />
              <circle cx="16" cy="16" r="8" stroke={_sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" fill="none" />
              <circle cx="16" cy="16" r="4" fill={_sc.replace(/[\d.]+\)$/, '0.35)')} />
            </svg>,
          ];

          return (
            <div
              onClick={advanceCockpitTeach}
              style={{
                position: 'absolute', inset: 0, zIndex: 50,
                cursor: 'pointer',
                WebkitTapHighlightColor: 'transparent',
                animation: cockpitTeachStep >= 4 ? 'ckTeachOut 0.5s ease forwards' : 'ckTeachIn 0.6s ease both',
              }}
            >
              {/* Scrim */}
              <div style={{
                position: 'absolute', inset: 0,
                background: `radial-gradient(ellipse ${_rx * 2}px ${_ry * 2}px at ${_cx}px ${_cy}px, transparent 0%, transparent 38%, rgba(0,0,0,0.42) 50%, rgba(0,0,0,0.62) 66%, rgba(0,0,0,0.72) 100%)`,
                transition: 'background 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
              }} />

              {/* Volumetric bloom */}
              <div style={{
                position: 'absolute',
                left: _cx - 100, top: _cy - 100,
                width: 200, height: 200,
                borderRadius: '50%',
                background: `radial-gradient(circle, ${_sc.replace(/[\d.]+\)$/, '0.06)')} 0%, ${_sc.replace(/[\d.]+\)$/, '0.02)')} 40%, transparent 70%)`,
                pointerEvents: 'none',
                animation: 'ckTeachBloom 3s ease-in-out infinite',
                transition: 'left 0.55s cubic-bezier(0.4,0,0.2,1), top 0.55s cubic-bezier(0.4,0,0.2,1)',
              }} />

              {/* Outer glow ring */}
              <div style={{
                position: 'absolute',
                left: _s.x - 14, top: _s.y - 14,
                width: _s.w + 28, height: _s.h + 28,
                borderRadius: _s.r ? _s.r + 14 : 14,
                border: `1px solid ${_sc.replace(/[\d.]+\)$/, '0.12)')}`,
                boxShadow: `0 0 44px ${_sc.replace(/[\d.]+\)$/, '0.12)')}, 0 0 18px ${_sc.replace(/[\d.]+\)$/, '0.06)')}, inset 0 0 20px ${_sc.replace(/[\d.]+\)$/, '0.05)')}`,
                pointerEvents: 'none',
                animation: 'ckTeachPulse 2.4s ease-in-out infinite',
                transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
              }} />

              {/* Inner spotlight ring */}
              <div style={{
                position: 'absolute',
                left: _s.x - 3, top: _s.y - 3,
                width: _s.w + 6, height: _s.h + 6,
                borderRadius: _s.r ? _s.r + 3 : 3,
                border: `1.5px solid ${_sc.replace(/[\d.]+\)$/, '0.50)')}`,
                boxShadow: `0 0 20px ${_sc.replace(/[\d.]+\)$/, '0.22)')}, 0 0 6px ${_sc.replace(/[\d.]+\)$/, '0.12)')}, inset 0 0 10px ${_sc.replace(/[\d.]+\)$/, '0.08)')}`,
                pointerEvents: 'none',
                animation: 'ckTeachPulse 2.4s ease-in-out 0.2s infinite',
                transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
              }} />

              {/* Glass tooltip card */}
              <div key={cockpitTeachStep} style={{
                position: 'absolute',
                top: _s.tipY,
                left: _cardLeft, right: _cardRight,
                animation: 'ckTeachCard 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) both',
              }}>
                {/* Animated conic border sweep */}
                <div style={{
                  position: 'absolute', inset: -1,
                  borderRadius: 15,
                  background: `conic-gradient(from var(--teach-border-angle, 0deg), ${_sc.replace(/[\d.]+\)$/, '0.00)')}, ${_sc.replace(/[\d.]+\)$/, '0.18)')}, ${_sc.replace(/[\d.]+\)$/, '0.00)')}, ${_sc.replace(/[\d.]+\)$/, '0.10)')}, ${_sc.replace(/[\d.]+\)$/, '0.00)')})`,
                  animation: 'ckTeachBorder 4s linear infinite',
                  opacity: 0.7,
                  pointerEvents: 'none',
                }} />
                <div style={{
                  position: 'relative',
                  padding: '24px 28px 20px',
                  borderRadius: 18,
                  backgroundColor: 'rgba(10,11,14,0.92)',
                  border: `1px solid ${_sc.replace(/[\d.]+\)$/, '0.08)')}`,
                  boxShadow: [
                    '0 8px 32px rgba(0,0,0,0.55)',
                    '0 2px 8px rgba(0,0,0,0.35)',
                    `0 0 0 0.5px ${_sc.replace(/[\d.]+\)$/, '0.06)')}`,
                    'inset 0 1px 0 rgba(255,255,255,0.07)',
                    'inset 0 -1px 0 rgba(0,0,0,0.2)',
                  ].join(', '),
                  backdropFilter: 'blur(20px) saturate(1.3)',
                  WebkitBackdropFilter: 'blur(20px) saturate(1.3)',
                }}>
                  {/* Two-row: big text on top, icon + action on bottom */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    <div>
                      <p style={{
                        margin: 0, fontSize: 22, fontWeight: 800, lineHeight: '26px',
                        color: 'rgba(245,247,250,0.96)', letterSpacing: '-0.4px',
                        ...FONT_SMOOTH,
                      }}>{_s.title}</p>
                      <p style={{
                        margin: '6px 0 0', fontSize: 16, fontWeight: 500, lineHeight: '22px',
                        color: 'rgba(184,191,199,0.72)', ...FONT_SMOOTH,
                      }}>{_s.desc}</p>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {/* Icon badge */}
                    <div style={{
                      width: 52, height: 52, flexShrink: 0,
                      borderRadius: 14,
                      background: `linear-gradient(145deg, ${_sc.replace(/[\d.]+\)$/, '0.14)')} 0%, ${_sc.replace(/[\d.]+\)$/, '0.03)')} 100%)`,
                      border: `1px solid ${_sc.replace(/[\d.]+\)$/, '0.16)')}`,
                      boxShadow: `inset 0 1px 0 ${_sc.replace(/[\d.]+\)$/, '0.08)')}, 0 2px 6px rgba(0,0,0,0.25)`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      animation: 'ckTeachFloat 3s ease-in-out infinite',
                    }}>
                      {_icons[cockpitTeachStep]}
                    </div>

                    <div style={{ flex: 1 }} />
                    {/* Action pill */}
                    <div
                      onClick={(e) => { e.stopPropagation(); advanceCockpitTeach(); }}
                      style={{
                        flexShrink: 0,
                        padding: '8px 18px',
                        borderRadius: 10,
                        background: `linear-gradient(135deg, ${_sc.replace(/[\d.]+\)$/, '0.16)')} 0%, ${_sc.replace(/[\d.]+\)$/, '0.06)')} 100%)`,
                        border: `1px solid ${_sc.replace(/[\d.]+\)$/, cockpitTeachStep < 3 ? '0.18)' : '0.26)')}`,
                        boxShadow: `0 2px 8px rgba(0,0,0,0.3), inset 0 1px 0 ${_sc.replace(/[\d.]+\)$/, '0.06)')}`,
                        cursor: 'pointer',
                        transition: 'transform 0.15s ease, box-shadow 0.15s ease',
                      }}
                    >
                      <p style={{
                        margin: 0, fontSize: 16, fontWeight: 700, letterSpacing: '0.4px',
                        color: _sc.replace(/[\d.]+\)$/, cockpitTeachStep < 3 ? '0.90)' : '0.95)'),
                        ...FONT_SMOOTH,
                        whiteSpace: 'nowrap',
                      }}>{cockpitTeachStep < 3 ? 'Next →' : 'Got it →'}</p>
                    </div>
                    </div>{/* close bottom row */}
                  </div>{/* close two-row layout */}

                  {/* Progress track + skip */}
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
                        width: `${((cockpitTeachStep + 1) / 4) * 100}%`,
                        height: '100%', borderRadius: 2,
                        background: `linear-gradient(90deg, ${_sc.replace(/[\d.]+\)$/, '0.35)')}, ${_sc.replace(/[\d.]+\)$/, '0.60)')})`,
                        transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1), background 0.5s ease',
                        boxShadow: `0 0 6px ${_sc.replace(/[\d.]+\)$/, '0.20)')}`,
                      }} />
                    </div>
                    <span style={{
                      fontSize: 11, fontWeight: 600, letterSpacing: '0.5px',
                      color: _sc.replace(/[\d.]+\)$/, '0.35)'),
                      marginLeft: 8,
                      ...FONT_SMOOTH,
                    }}>{cockpitTeachStep + 1}/4</span>
                    <div style={{ flex: 1 }} />
                    {cockpitTeachStep < 3 && (
                      <button
                        onClick={(e) => { e.stopPropagation(); skipCockpitTeach(); }}
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0',
                          fontSize: 12, fontWeight: 600,
                          color: steel(0.24),
                          WebkitTapHighlightColor: 'transparent',
                          ...FONT_SMOOTH,
                        }}
                      >Skip</button>
                    )}
                  </div>
                </div>
              </div>

              {/* "Tap anywhere" hint */}
              <p style={{
                position: 'absolute', bottom: 14, left: 0, right: 0,
                textAlign: 'center', margin: 0,
                fontSize: 10, fontWeight: 500, letterSpacing: '0.5px',
                color: steel(0.22),
                ...FONT_SMOOTH,
                animation: 'ckTeachFade 0.6s ease 1s both',
                pointerEvents: 'none',
              }}>Tap anywhere to continue</p>

              {/* Draw-on arrow from card → spotlight */}
              <svg key={`ck-arrow-${cockpitTeachStep}`} style={{
                position: 'absolute', left: 0, top: _svgTop,
                width: COL_W, height: _svgH,
                pointerEvents: 'none', overflow: 'visible',
                filter: `drop-shadow(0 0 10px ${_sc.replace(/[\d.]+\)$/, '0.35)')})`,
              }}>
                {/* Glow trail */}
                <path d={_curvePath} stroke={_sc.replace(/[\d.]+\)$/, '0.12)')}
                  strokeWidth="8" strokeLinecap="round" fill="none"
                  strokeDasharray={_curveLen}
                  strokeDashoffset={_curveLen}
                  style={{ animation: `ckTeachDraw 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.2s forwards` }} />
                {/* Main stroke */}
                <path d={_curvePath} stroke={_sc.replace(/[\d.]+\)$/, '0.75)')}
                  strokeWidth="2.5" strokeLinecap="round" fill="none"
                  strokeDasharray={_curveLen}
                  strokeDashoffset={_curveLen}
                  style={{ animation: `ckTeachDraw 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.25s forwards` }} />
                {/* Highlight edge */}
                <path d={_curvePath} stroke="rgba(255,255,255,0.12)"
                  strokeWidth="1" strokeLinecap="round" fill="none"
                  strokeDasharray={_curveLen}
                  strokeDashoffset={_curveLen}
                  style={{ animation: `ckTeachDraw 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.3s forwards` }} />
                {/* Arrowhead — slides from card base along curve to endpoint */}
                <style>{`
                  @keyframes ckTeachArrowSlide${cockpitTeachStep} {
                    0%   { opacity: 0.4; transform: translate(${_cardCX - _cx}px, ${_startLY - _endLY}px) scale(0.7); }
                    40%  { opacity: 1; }
                    100% { opacity: 1; transform: translate(0, 0) scale(1); }
                  }
                `}</style>
                <g style={{
                  opacity: 0,
                  animation: `ckTeachArrowSlide${cockpitTeachStep} 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.2s forwards`,
                }}>
                  <g style={{ animation: 'ckTeachArrowBounce 1.4s ease-in-out 1.1s infinite' }}>
                    <circle cx={_cx} cy={_endLY} r="12" fill={_sc.replace(/[\d.]+\)$/, '0.08)')} />
                    <path d={_aPath} stroke={_sc.replace(/[\d.]+\)$/, '0.95)')}
                      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                    <path d={_aPath} stroke="rgba(255,255,255,0.22)"
                      strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  </g>
                </g>
              </svg>
            </div>
          );
        })()}

        {/* Cockpit teach keyframes */}
        <style>{`
          @keyframes ckTeachIn {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
          @keyframes ckTeachOut {
            from { opacity: 1; }
            to   { opacity: 0; pointer-events: none; }
          }
          @keyframes ckTeachFade {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          @keyframes ckTeachPulse {
            0%   { transform: scale(1); opacity: 0.85; }
            50%  { transform: scale(1.06); opacity: 1; }
            100% { transform: scale(1); opacity: 0.85; }
          }
          @keyframes ckTeachFloat {
            0%   { transform: translateY(0); }
            50%  { transform: translateY(-3px); }
            100% { transform: translateY(0); }
          }
          @keyframes ckTeachCard {
            0%   { opacity: 0; transform: translateY(16px) scale(0.96); }
            60%  { opacity: 1; transform: translateY(-3px) scale(1.01); }
            80%  { transform: translateY(1px) scale(1.0); }
            100% { opacity: 1; transform: translateY(0) scale(1); }
          }
          @keyframes ckTeachDraw {
            to { stroke-dashoffset: 0; }
          }
          /* ckTeachArrowSlideN keyframes are generated inline per step */
          @keyframes ckTeachArrowBounce {
            0%, 100% { transform: translateY(0); }
            50%      { transform: translateY(3px); }
          }
          @keyframes ckTeachBloom {
            0%   { transform: scale(1); opacity: 0.7; }
            50%  { transform: scale(1.15); opacity: 1; }
            100% { transform: scale(1); opacity: 0.7; }
          }
          @property --teach-border-angle {
            syntax: '<angle>';
            initial-value: 0deg;
            inherits: false;
          }
          @keyframes ckTeachBorder {
            to { --teach-border-angle: 360deg; }
          }
        `}</style>
      </div>

      {/* Hero zoom — long-press the cockpit photo to enter fullscreen */}
      <ZoomableHeroOverlay
        src={imagePreview}
        isOpen={heroZoomed}
        onClose={() => setHeroZoomed(false)}
      />

      {/* Outcome capture — every cockpit session must produce a signal */}
      <NailedItOverlay
        isOpen={outcomeOpen}
        onSelect={handleOutcomePick}
        onDismiss={handleOutcomeDismiss}
      />

      {shareStatus === 'clipboard_fail' && shareUrl && createPortal(
        <>
          <div onClick={() => { setShareStatus(null); setShareUrl(null); setModalCopied(false); }} style={{
            position: 'fixed', inset: 0, zIndex: 99998,
            background: 'rgba(0,0,0,0.65)',
          }} />
          <div style={{
            position: 'fixed', left: 20, right: 20, top: '50%', transform: 'translateY(-50%)',
            zIndex: 99999,
            background: 'rgba(18,22,30,0.98)', border: '1px solid rgba(200,155,60,0.30)',
            borderRadius: 14, padding: '20px 20px 16px',
            boxShadow: '0 12px 40px rgba(0,0,0,0.70)',
          }}>
            <p style={{ margin: '0 0 10px', fontSize: 14, color: 'rgba(200,155,60,0.80)', fontWeight: 700, letterSpacing: '1px',
              WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale' }}>
              SHARE THIS SESSION
            </p>
            {navigator.share && (
              <button
                onClick={async () => {
                  try {
                    await navigator.share({ title: 'Shoot Session', text: 'Join my lighting setup', url: shareUrl });
                    setModalCopied(true);
                    setTimeout(() => { setModalCopied(false); setShareStatus('shared'); setShareUrl(null); setTimeout(() => setShareStatus(null), 2000); }, 1000);
                  } catch {}
                }}
                style={{
                  width: '100%', padding: '14px', marginBottom: 12,
                  borderRadius: 10, border: 'none', cursor: 'pointer',
                  background: 'linear-gradient(141.71deg, #1a2218 0%, #122016 100%)',
                  boxShadow: '4px 4px 12px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.07)',
                  fontSize: 15, fontWeight: 700, letterSpacing: '1px',
                  color: 'rgba(72,186,136,0.90)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  WebkitTapHighlightColor: 'transparent',
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="rgba(72,186,136,0.85)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8" /><polyline points="16 6 12 2 8 6" /><line x1="12" y1="2" x2="12" y2="15" />
                </svg>
                SHARE LINK
              </button>
            )}
            <div
              onClick={() => {
                try {
                  const ta = document.createElement('textarea');
                  ta.value = shareUrl;
                  ta.style.cssText = 'position:fixed;left:0;top:0;opacity:0;';
                  document.body.appendChild(ta);
                  ta.focus(); ta.select();
                  const ok = document.execCommand('copy');
                  document.body.removeChild(ta);
                  if (ok) {
                    setModalCopied(true);
                    setTimeout(() => { setModalCopied(false); setShareStatus('shared'); setShareUrl(null); setTimeout(() => setShareStatus(null), 2000); }, 1000);
                  }
                } catch {}
              }}
              style={{
                fontSize: 16,
                color: modalCopied ? 'rgba(72,186,136,0.95)' : 'rgba(160,185,215,0.85)',
                wordBreak: 'break-all',
                lineHeight: 1.6, cursor: 'pointer', padding: '12px 14px',
                background: modalCopied ? 'rgba(72,186,136,0.10)' : 'rgba(90,120,160,0.08)',
                borderRadius: 10,
                border: modalCopied ? '1px solid rgba(72,186,136,0.35)' : '1px solid rgba(90,120,160,0.18)',
                fontFamily: 'monospace',
                userSelect: 'all', WebkitUserSelect: 'all',
                transition: 'all 0.25s ease',
                textAlign: 'center',
              }}
            >
              {modalCopied ? '\u2713 Copied!' : shareUrl}
            </div>
            <p style={{ margin: '10px 0 0', fontSize: 14,
              color: modalCopied ? 'rgba(72,186,136,0.55)' : 'rgba(140,160,185,0.50)',
              transition: 'color 0.25s ease',
              WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale' }}>
              {modalCopied ? 'Closing...' : 'Tap to copy \u00b7 long-press to select \u00b7 tap outside to close'}
            </p>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

// ─── Photographer body ──────────────────────────────────────────────────────
function PhotographerBody({ step, imagePreview, modName, position, distance,
  heightDisplay, angleDeg, pattern, confidence, cct, result, stepKey, mode, heroFitMode, onToggleFit, heroPressHandlers, vfHeight, hidePhoto }) {
  const dk = hidePhoto; // desktop flag — scale up text for wider column
  return (
    <>
      {/* Compact spec strip — one-line summary of key light setup */}
      <div style={{ padding: dk ? '16px 28px 0' : '12px 20px 0', position: 'relative', zIndex: 1 }}>
        <div style={{
          backgroundColor: C.panelBg, borderRadius: dk ? 14 : 12,
          boxShadow: `${PANEL_SHADOW}, ${PANEL_BEVEL}`,
          padding: dk ? '12px 18px' : '10px 14px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <p style={{ margin: 0, fontSize: dk ? 16 : 14, fontWeight: 700, color: C.textPrimary,
            letterSpacing: '0.2px', ...FONT_SMOOTH,
            flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {[
              angleDeg != null ? `${Math.round(angleDeg)}°` : position,
              distance,
              heightDisplay,
            ].filter(v => v && v !== '—').join(' · ')}
          </p>
          <p style={{ margin: 0, fontSize: dk ? 14 : 13, fontWeight: 600,
            color: confidence >= 70 ? C.confHigh : C.confLow,
            letterSpacing: '0.5px', ...FONT_SMOOTH,
            flexShrink: 0, marginLeft: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            maxWidth: '48%' }}>
            {confidence}% · {pattern}
          </p>
        </div>
      </div>

      {imagePreview && !hidePhoto && (
        <div
          {...(heroPressHandlers || {})}
          style={{ padding: '10px 20px 0', position: 'relative', zIndex: 1,
            display: 'flex', justifyContent: 'center', cursor: 'zoom-in', WebkitTapHighlightColor: 'transparent' }}
        >
          <ReferenceWithOverlay
            imagePreview={imagePreview}
            result={result}
            stepKey={stepKey}
            position={position}
            angleDeg={angleDeg}
            distance={distance}
            maxHeight={vfHeight}
            mode="photographer"
            heightDisplay={heightDisplay}
            modName={modName}
          heroFitMode={heroFitMode}
          onToggleFit={onToggleFit}
          />
        </div>
      )}

      <div style={{ padding: dk ? '14px 28px 0' : '10px 24px 0', position: 'relative', zIndex: 1, textAlign: 'center' }}>
        {step.title && (
          <p style={{ margin: 0, fontSize: 10, fontWeight: 700,
            color: steel(0.45), letterSpacing: '1.5px', textTransform: 'uppercase', ...FONT_SMOOTH }}>
            {step.title}
          </p>
        )}
        <p style={{ margin: step.title ? '4px 0 0' : 0, fontSize: dk ? 42 : 36, fontWeight: 800,
          color: C.textPrimary, letterSpacing: '-0.5px', ...FONT_SMOOTH,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {step.lead}
        </p>
        {step.subLead && (
          <p style={{ margin: dk ? '6px 0 0' : '4px 0 0', fontSize: 14, fontWeight: 500,
            color: C.textSub, letterSpacing: '0.3px', ...FONT_SMOOTH }}>
            {step.subLead}
          </p>
        )}
      </div>

      {step.coach?.lookFor?.[0] && (
        <div style={{ padding: dk ? '8px 28px 0' : '6px 24px 0', position: 'relative', zIndex: 1 }}>
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            padding: '8px 12px',
            borderRadius: 8,
            backgroundColor: 'rgba(72,186,136,0.04)',
            border: '1px solid rgba(72,186,136,0.10)',
          }}>
            <span style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: 'rgba(72,186,136,0.6)', flexShrink: 0, marginTop: 5 }} />
            <p style={{ margin: 0, fontSize: 12, fontWeight: 500, color: steel(0.58), lineHeight: 1.4, ...FONT_SMOOTH }}>
              {step.coach.lookFor[0]}
            </p>
          </div>
        </div>
      )}

      <CoachingDisclosure coach={step.coach} variant="photographer" />
    </>
  );
}

// ─── Coaching disclosure — collapsed toggle for photographer, expanded for learning ──
function CoachingDisclosure({ coach, variant = 'photographer' }) {
  const isLearning = variant === 'learning';
  const [open, setOpen] = useState(isLearning);
  if (!coach) return null;
  const label = isLearning ? 'NOT LOOKING RIGHT?' : 'TROUBLESHOOTING';
  const labelHide = isLearning ? 'HIDE TROUBLESHOOTING' : 'HIDE';
  return (
    <div style={{ padding: '10px 20px 0', position: 'relative', zIndex: 1 }}>
      <button
        onClick={() => { setOpen(o => !o); tapHaptic(); }}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          background: open ? 'rgba(214,123,78,0.08)' : 'rgba(255,255,255,0.03)',
          border: `1px solid ${open ? 'rgba(214,123,78,0.2)' : 'rgba(255,255,255,0.06)'}`,
          borderRadius: 8,
          cursor: 'pointer',
          padding: '8px 16px',
          margin: '0 auto',
          width: '100%',
          maxWidth: 280,
          WebkitTapHighlightColor: 'transparent',
          transition: 'background 0.2s ease, border-color 0.2s ease',
        }}
      >
        <span style={{
          fontSize: 12, fontWeight: 700,
          color: open ? 'rgba(214,123,78,0.9)' : steel(0.6),
          letterSpacing: '1px', ...FONT_SMOOTH,
          transition: 'color 0.2s ease',
        }}>
          {open ? labelHide : label}
        </span>
        <span style={{
          fontSize: 11,
          color: open ? 'rgba(214,123,78,0.7)' : steel(0.45),
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
          transition: 'transform 0.2s ease, color 0.2s ease',
          ...FONT_SMOOTH,
        }}>▾</span>
      </button>
      {open && <CoachingPanel coach={coach} variant={variant} />}
    </div>
  );
}

// ─── Coaching panel ─────────────────────────────────────────────────────────
// Per-step visual cues + troubleshooting fixes, pulled from PATTERN_COACHING.
// Shown in Photographer (compact) and Learning (spacious) modes. The panel
// is intentionally terse: bullets, not prose. Fixes render as symptom → fix
// so the photographer can scan for the symptom they're seeing.
function CoachingPanel({ coach, variant = 'photographer' }) {
  if (!coach) return null;
  const isLearning = variant === 'learning';
  const pad = isLearning ? '14px 16px' : '10px 12px';
  const labelFs = isLearning ? 10 : 9;
  const itemFs = isLearning ? 12 : 11;
  const symptomFs = isLearning ? 11 : 10;
  const colGap = isLearning ? 14 : 10;

  return (
    <div style={{
      padding: isLearning ? '14px 20px 0' : '12px 20px 0',
      position: 'relative', zIndex: 1,
    }}>
      <div style={{
        backgroundColor: C.panelBg,
        borderRadius: 10,
        boxShadow: `inset 0px 0px 0px 1px rgba(255,255,255,0.03), ${PANEL_BEVEL}`,
        padding: pad,
        display: 'flex', gap: colGap,
      }}>
        {/* LOOK FOR — visual cues */}
        {coach.lookFor && coach.lookFor.length > 0 && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: labelFs, fontWeight: 800,
              color: '#48ba88', letterSpacing: '1.2px', ...FONT_SMOOTH }}>
              LOOK FOR
            </p>
            <ul style={{ margin: '6px 0 0', padding: 0, listStyle: 'none' }}>
              {coach.lookFor.map((cue, i) => (
                <li key={i} style={{
                  fontSize: itemFs, fontWeight: 500,
                  color: C.textSub, lineHeight: 1.4,
                  marginTop: i === 0 ? 0 : 5,
                  paddingLeft: 10, position: 'relative',
                  ...FONT_SMOOTH,
                }}>
                  <span style={{
                    position: 'absolute', left: 0, top: isLearning ? 5 : 4,
                    width: 3, height: 3, borderRadius: 2,
                    backgroundColor: 'rgba(72,186,136,0.7)',
                  }} />
                  {cue}
                </li>
              ))}
            </ul>
          </div>
        )}
        {/* FIXES — symptom → adjustment */}
        {coach.fixes && coach.fixes.length > 0 && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: labelFs, fontWeight: 800,
              color: KEY_ACCENT, letterSpacing: '1.2px', ...FONT_SMOOTH }}>
              FIXES
            </p>
            <ul style={{ margin: '6px 0 0', padding: 0, listStyle: 'none' }}>
              {coach.fixes.map(([symptom, fix], i) => (
                <li key={i} style={{
                  marginTop: i === 0 ? 0 : 6,
                  lineHeight: 1.35,
                }}>
                  <p style={{ margin: 0, fontSize: symptomFs, fontWeight: 700,
                    color: KEY_ACCENT, ...FONT_SMOOTH }}>
                    {symptom}
                  </p>
                  <p style={{ margin: '1px 0 0', fontSize: itemFs, fontWeight: 500,
                    color: C.textSub, ...FONT_SMOOTH }}>
                    → {fix}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function SpecCell({ label, value, sub }) {
  return (
    <div>
      <p style={{ margin: 0, fontSize: 12, fontWeight: 600,
        color: steel(0.45), letterSpacing: '0.8px', ...FONT_SMOOTH }}>
        {label}
      </p>
      <p style={{ margin: '2px 0 0', fontSize: 14, fontWeight: 700,
        color: C.textPrimary, letterSpacing: '-0.1px', ...FONT_SMOOTH,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {value}
      </p>
      {sub && (
        <p style={{ margin: '1px 0 0', fontSize: 12, fontWeight: 500,
          color: steel(0.45), letterSpacing: '0.1px', ...FONT_SMOOTH,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {sub}
        </p>
      )}
    </div>
  );
}

// ─── Assistant body — single HUGE command ──────────────────────────────────
function AssistantBody({ step }) {
  return (
    <div style={{
      padding: '24px 24px 0', position: 'relative', zIndex: 1,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', flex: '0 0 auto',
    }}>
      <p style={{
        margin: 0, fontSize: 12, fontWeight: 700,
        color: steel(0.75), letterSpacing: '2.0px', ...FONT_SMOOTH,
      }}>
        {step.verb}
      </p>
      <p style={{
        margin: '24px 0 0', fontSize: 56, fontWeight: 900,
        color: C.textPrimary, letterSpacing: '-2.0px',
        lineHeight: 1.0, textAlign: 'center',
        textShadow: '0px 2px 8px rgba(0,0,0,0.8)',
        ...FONT_SMOOTH,
      }}>
        {step.command}
      </p>
      {step.subCommand && (
        <p style={{
          margin: '16px 0 0', fontSize: 22, fontWeight: 700,
          color: steel(0.6), letterSpacing: '0.5px',
          textAlign: 'center', ...FONT_SMOOTH,
        }}>
          {step.subCommand}
        </p>
      )}
      {/* C-3: Assistant mode is pure command — no coaching. The photographer
           gives verbal cues if adjustment is needed. */}
    </div>
  );
}

// ─── Learning body — narrative lead + WHY callout + big reference ──────────
function LearningBody({ step, imagePreview, result, stepKey, position, angleDeg, distance, pattern, mode, heightDisplay, modName, heroFitMode, onToggleFit, heroPressHandlers, vfHeight, hidePhoto }) {
  const dk = hidePhoto; // desktop flag
  return (
    <>
      {imagePreview && !hidePhoto && (
        <div
          {...(heroPressHandlers || {})}
          style={{ padding: '12px 20px 0', position: 'relative', zIndex: 1,
            display: 'flex', justifyContent: 'center', cursor: 'zoom-in', WebkitTapHighlightColor: 'transparent' }}
        >
          <ReferenceWithOverlay
            imagePreview={imagePreview}
            result={result}
            stepKey={stepKey}
            position={position}
            angleDeg={angleDeg}
            distance={distance}
            pattern={pattern}
            maxHeight={vfHeight}
            mode="learning"
            heightDisplay={heightDisplay}
            modName={modName}
            heroFitMode={heroFitMode}
            onToggleFit={onToggleFit}
          />
        </div>
      )}

      <div style={{ padding: dk ? '22px 28px 0' : '18px 22px 0', position: 'relative', zIndex: 1 }}>
        <p style={{ margin: 0, fontSize: dk ? 12 : 12, fontWeight: 700,
          color: steel(0.75), letterSpacing: '1.2px',
          textAlign: 'center', ...FONT_SMOOTH }}>
          {step.title}
        </p>
        <p style={{ margin: dk ? '10px 0 0' : '8px 0 0', fontSize: dk ? 20 : 18, fontWeight: 700,
          color: C.textPrimary, letterSpacing: '-0.2px',
          lineHeight: 1.35, textAlign: 'center', ...FONT_SMOOTH }}>
          {step.lead}
        </p>
      </div>

      {/* WHY callout — gated by explanationDepth setting.
           brief: hidden entirely. standard: show. technical: show + raw signals would go here. */}
      {step.why && (() => { try { return (loadSettings().explanationDepth || 'standard') !== 'brief'; } catch { return true; } })() && (
        <div style={{ padding: dk ? '18px 28px 0' : '14px 20px 0', position: 'relative', zIndex: 1 }}>
          <div style={{
            backgroundColor: 'rgba(18,19,22,0.85)',
            borderRadius: dk ? 14 : 12,
            border: `1px solid rgba(200,155,69,0.12)`,
            boxShadow: PANEL_BEVEL,
            padding: dk ? '16px 20px' : '12px 16px',
          }}>
            <p style={{ margin: 0, fontSize: dk ? 12 : 11, fontWeight: 700,
              color: steel(0.75), letterSpacing: '1.4px', ...FONT_SMOOTH }}>
              WHY THIS MATTERS
            </p>
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {step.why.split('. ').filter(Boolean).map((sentence, i, arr) => (
                <p key={i} style={{
                  margin: 0,
                  fontSize: dk ? 14 : 14,
                  fontWeight: i === 0 ? 600 : 400,
                  color: i === 0 ? C.textPrimary : C.textSub,
                  lineHeight: 1.55,
                  ...FONT_SMOOTH,
                }}>
                  {sentence}{i < arr.length - 1 ? '.' : ''}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}

      <CoachingDisclosure coach={step.coach} variant="learning" />
    </>
  );
}

// ─── Reference photo with per-step catchlight / key-light overlays ─────────
// Role-aware: Photographer gets minimal clinical markers; Learning gets
// labeled educational annotations. Assistant never renders a photo at all.
function ReferenceWithOverlay({ imagePreview, result, stepKey, position, angleDeg, distance, pattern, mode = 'photographer', maxHeight = 300, fullWidth = false, heightDisplay = '—', modName = '', heroFitMode = 'contain', onToggleFit }) {
  const imgDim = result?._raw?.image_dimensions
    || result?._raw?.description?.size
    || { width: 1177, height: 1592 };
  const W = imgDim.width || 1177;
  const H = imgDim.height || 1592;

  const catchlights = result?._raw?.cv?.catchlights?.catchlights
    || result?._raw?.description?.vision?.catchlights?.catchlights
    || [];
  const faceGeom = result?._raw?.cv?.catchlights?.face_geometry
    || result?._raw?.description?.vision?.catchlights?.face_geometry
    || {};
  const signals = result?._raw?.signal_diagnostics?.signals || {};

  // Presence flags — the engine produces nose_tip/chin/forehead_top only on
  // the MediaPipe landmark path. On the estimated-from-face-box fallback path
  // those are absent, so we must synthesize them from what's available or
  // suppress the overlay that depends on them.
  const hasEyes = !!(faceGeom.left_eye_center && faceGeom.right_eye_center);
  const leftEye = faceGeom.left_eye_center || [W * 0.45, H * 0.4];
  const rightEye = faceGeom.right_eye_center || [W * 0.55, H * 0.4];
  const chin = faceGeom.chin || [W / 2, H * 0.7];
  const foreheadTop = faceGeom.forehead_top || [W / 2, H * 0.3];
  // Derived nose tip: prefer engine landmark. Fallback: eye midpoint shifted
  // down by ~1.1× interocular distance (face-proportion heuristic). Only
  // synthesize when we actually have both eye centers.
  const noseTip = (() => {
    if (faceGeom.nose_tip) return faceGeom.nose_tip;
    if (!hasEyes) return null;
    const midX = (leftEye[0] + rightEye[0]) / 2;
    const midY = (leftEye[1] + rightEye[1]) / 2;
    if (faceGeom.chin) {
      return [midX, midY + (chin[1] - midY) * 0.55];
    }
    const eyeDist = Math.hypot(rightEye[0] - leftEye[0], rightEye[1] - leftEye[1]);
    return [midX, midY + eyeDist * 1.1];
  })();

  // Pick primary key catchlight (highest intensity × size). Track by index so
  // `catchlights[primaryIdx] === primaryKey` lets downstream strict-equality
  // checks identify the primary (a spread copy would break reference equality).
  const primaryIdx = (() => {
    let bestIdx = -1;
    let bestScore = -1;
    catchlights.forEach((c, i) => {
      const score = (c.intensity || 0) * (c.size_ratio || 0);
      if (score > bestScore) { bestScore = score; bestIdx = i; }
    });
    return bestIdx;
  })();
  const primaryKey = primaryIdx >= 0 ? catchlights[primaryIdx] : null;

  // ── Snap catchlight anchor to nearest eye center ──────────────────────
  // Engine catchlight detection can land ~10-15px from the actual iris
  // center. When a catchlight is within SNAP_THRESHOLD of an eye center,
  // snap the rendering anchor to the eye center so the ring sits
  // precisely on the catchlight reflection the photographer sees.
  // When no catchlights are detected, snappedAnchor is null and the
  // overlay arrows do not render — we never synthesize a fake anchor
  // from face geometry because that would present inferred data as
  // observed catchlight evidence.
  const SNAP_THRESHOLD = 35; // px in original image space
  const snappedAnchor = (() => {
    if (!primaryKey) return null;
    const cx = primaryKey.abs_cx;
    const cy = primaryKey.abs_cy;
    const eyes = [];
    if (faceGeom.left_eye_center) eyes.push(faceGeom.left_eye_center);
    if (faceGeom.right_eye_center) eyes.push(faceGeom.right_eye_center);
    if (eyes.length === 0) return { x: cx, y: cy };
    let nearest = null;
    let nearestDist = Infinity;
    for (const eye of eyes) {
      const d = Math.hypot(cx - eye[0], cy - eye[1]);
      if (d < nearestDist) { nearestDist = d; nearest = eye; }
    }
    if (nearestDist <= SNAP_THRESHOLD && nearest) {
      return { x: nearest[0], y: nearest[1] };
    }
    return { x: cx, y: cy };
  })();

  // Clock string → unit vector (SVG screen coords, y-down; 12 = up)
  // Parse hour portion (e.g. "1 o'clock" or "1:30 o'clock")
  const catchlightClockHr = (() => {
    const m = (position || '').match(/(\d+)(?::(\d+))?\s*o'?clock/i);
    if (!m) return null;
    return parseInt(m[1]) + (m[2] ? parseInt(m[2]) / 60 : 0);
  })();

  // Resolution guard: when the iris is < 15px radius, the catchlight
  // centroid is at its positioning floor — a 1–2px shift flips the clock
  // direction.  Fall back to angleDeg (shadow-geometry-derived, robust at
  // any resolution).  Also cross-check: if catchlight clock and angleDeg
  // disagree by > 90°, prefer angleDeg.
  const _eyeDist = Math.hypot(rightEye[0] - leftEye[0], rightEye[1] - leftEye[1]) || (W * 0.18);
  const irisR = primaryKey?.enc_r_px
    ? primaryKey.enc_r_px / (primaryKey.size_ratio || 0.15)
    : _eyeDist * 0.22;
  const lowResIris = irisR < 15;

  const angleClockHr = (() => {
    if (typeof angleDeg !== 'number') return null;
    const h = (12 - angleDeg / 30 + 12) % 12;
    return h === 0 ? 12 : h;
  })();

  const clockHour = (() => {
    // If no catchlight clock available, use angleDeg-derived
    if (catchlightClockHr == null) return angleClockHr ?? 1;
    // Low-res iris: trust shadow geometry over catchlight position
    if (lowResIris && angleClockHr != null) return angleClockHr;
    // Cross-check: catchlight vs shadow geometry
    if (angleClockHr != null) {
      const diff = Math.abs(((catchlightClockHr - angleClockHr + 6) % 12) - 6);
      if (diff > 3) return angleClockHr; // >90° disagreement → prefer shadow
    }
    return catchlightClockHr;
  })();

  const clockVec = (() => {
    const angle = ((clockHour % 12) * 30 - 90) * Math.PI / 180;
    return { dx: Math.cos(angle), dy: Math.sin(angle) };
  })();

  // Face centroid (used for sizing & fallback arrow origin)
  const faceCx = (leftEye[0] + rightEye[0]) / 2;
  const faceCy = (foreheadTop[1] + chin[1]) / 2 - (chin[1] - foreheadTop[1]) * 0.25;
  const padding = Math.min(W, H) * 0.12;

  // Key-light arrow ANCHORS AT THE CATCHLIGHT (not face center).
  // This visually communicates: the catchlight in the eye IS the observable
  // evidence of where the key light is coming from. The arrow shows the
  // direction the light travels OUTWARD from that reflection point.
  const anchorX = snappedAnchor ? snappedAnchor.x : faceCx;
  const anchorY = snappedAnchor ? snappedAnchor.y : faceCy;

  const maxArrowLen = Math.min(
    clockVec.dx > 0 ? (W - padding - anchorX) / Math.max(0.001, clockVec.dx) : Infinity,
    clockVec.dx < 0 ? (anchorX - padding) / Math.max(0.001, -clockVec.dx) : Infinity,
    clockVec.dy > 0 ? (H - padding - anchorY) / Math.max(0.001, clockVec.dy) : Infinity,
    clockVec.dy < 0 ? (anchorY - padding - Math.min(W, H) * 0.08) / Math.max(0.001, -clockVec.dy) : Infinity
  );
  const arrowLen = Math.min(Math.min(W, H) * 0.28, maxArrowLen);
  // Arrow starts AT the primary catchlight center so the visual anchor is
  // unambiguous. The bright dot + ring render on top of the line, so the
  // overlap reads as "the line emerges from this catchlight."
  const arrowStartX = anchorX;
  const arrowStartY = anchorY;
  // Clamp arrow endpoint to stay well within viewBox
  const _margin = padding * 2.5;
  const arrowEndX = Math.max(_margin, Math.min(W - _margin, anchorX + clockVec.dx * arrowLen));
  const arrowEndY = Math.max(_margin, Math.min(H - _margin, anchorY + clockVec.dy * arrowLen));

  // Nose shadow: opposite direction of light, shorter
  const shadowLen = Math.min(W, H) * 0.14;
  const _rawShadowEndX = noseTip ? noseTip[0] - clockVec.dx * shadowLen : 0;
  const _rawShadowEndY = noseTip ? noseTip[1] - clockVec.dy * shadowLen + shadowLen * 0.5 : 0;
  const shadowEndX = Math.max(_margin, Math.min(W - _margin, _rawShadowEndX));
  const shadowEndY = Math.max(_margin, Math.min(H - _margin, _rawShadowEndY));

  const isLearning = mode === 'learning';

  // Distinct colors for the two concepts:
  //   catchColor — bright warm white; represents the reflection IN the eye
  //   keyColor   — amber; represents the inferred direction of the key light
  const catchColor = '#f5e4b8';
  const keyColor = steel(0.75);
  const distColor = '#48ba88';
  const shadowColor = '#6ea8d1';

  // ── Face-relative sizing ───────────────────────────────────────────────
  // Scale all overlay elements to interocular distance so the ring fits
  // the eye whether the source image is 236px or 4000px wide.
  const iod = _eyeDist;
  // Face-relative sizing — scale to interocular distance so overlays fit
  // the eye proportionally across image sizes. Capped to prevent runaway
  // label sizes on upscaled images (IOD 300-500px after 2048px upscale).
  const strokeBase = Math.min(5,  Math.max(2, iod * 0.022));
  const fontBase   = Math.min(56, Math.max(14, iod * 0.18));
  const ringR      = Math.min(22, Math.max(6, iod * 0.07));

  const showKey = stepKey === 'position' || stepKey === 'capture';
  const showDist = stepKey === 'distance' || stepKey === 'capture';
  const showShadow = stepKey === 'height' || stepKey === 'capture';
  // On the capture step every overlay system renders at once, so suppress
  // text labels to avoid stacking four callouts on one face. Visual markers
  // (rings, arrows) remain.
  const showLabels = isLearning;

  // Container matches the VF height from Home/Results. For landscape images
  // the width may exceed the screen — the parent's overflow:hidden clips it
  // and objectFit:cover + xMidYMid slice keep image & SVG aligned.
  // For portrait images, width < maxHeight so everything fits naturally.
  const containerH = maxHeight;
  const containerW = containerH * (W / H);

  return (
    <div style={{
      position: 'relative',
      width: fullWidth ? '100%' : Math.min(containerW, 390),
      height: fullWidth ? '100%' : containerH,
      borderRadius: fullWidth ? 0 : 12, overflow: 'hidden',
      backgroundColor: '#000',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <img src={imagePreview} alt="Reference"
        style={{ width: '100%', height: '100%', objectFit: heroFitMode, display: 'block', transition: 'object-fit 0.3s ease' }}
        onClick={() => { onToggleFit?.(); tapHaptic(); }}
      />
      {/* Fit mode toggle — bottom-right corner */}
      <button onClick={(e) => { e.stopPropagation(); onToggleFit?.(); tapHaptic(); }}
        style={{
          position: 'absolute', bottom: 8, right: 8, zIndex: 10,
          width: 28, height: 28, borderRadius: 6,
          background: 'rgba(0,0,0,0.55)', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
        }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(245,247,250,0.70)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          {heroFitMode === 'contain'
            ? <><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></>
            : <><path d="M4 14h6v6M14 4h6v6M10 14l-7 7M14 10l7-7"/></>
          }
        </svg>
      </button>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', overflow: 'hidden' }}>
        <defs>
          <clipPath id={`vb-${mode}`}><rect x={-fontBase * 1.5} y={-fontBase * 1.5} width={W + fontBase * 3} height={H + fontBase * 3} /></clipPath>
          <marker id={`kar-${mode}`} viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="5" markerHeight="5" orient="auto">
            <path d="M1,1 L10,5 L1,9 z" fill={keyColor} opacity="0.95" />
          </marker>
          <marker id={`sar-${mode}`} viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="4.5" markerHeight="4.5" orient="auto">
            <path d="M1,1 L10,5 L1,9 z" fill={shadowColor} opacity="0.85" />
          </marker>
          {/* Catchlight glow — tight bloom */}
          <filter id={`cg-${mode}`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation={ringR * 0.5} />
          </filter>
          {/* Shadow soft edge */}
          <filter id={`sb-${mode}`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation={strokeBase * 0.4} />
          </filter>
          {/* Key arrow gradient — fades like light falloff */}
          <linearGradient id={`kag-${mode}`}
            x1={arrowStartX} y1={arrowStartY} x2={arrowEndX} y2={arrowEndY}
            gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor={keyColor} stopOpacity="1.0" />
            <stop offset="70%" stopColor={keyColor} stopOpacity="0.65" />
            <stop offset="100%" stopColor={keyColor} stopOpacity="0.35" />
          </linearGradient>
          {/* Text drop shadow filter */}
          <filter id={`ts-${mode}`} x="-10%" y="-10%" width="120%" height="130%">
            <feDropShadow dx="0" dy={fontBase * 0.06} stdDeviation={fontBase * 0.08}
              floodColor="#000" floodOpacity="0.7" />
          </filter>
          {/* Shadow stroke falloff gradient — fades like real shadow softens */}
          {noseTip && (
            <linearGradient id={`sfg-${mode}`}
              x1={noseTip[0]} y1={noseTip[1]} x2={shadowEndX} y2={shadowEndY}
              gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor={shadowColor} stopOpacity="0.9" />
              <stop offset="50%" stopColor={shadowColor} stopOpacity="0.45" />
              <stop offset="100%" stopColor={shadowColor} stopOpacity="0.1" />
            </linearGradient>
          )}
          <style>{`
            @keyframes catchlightPulse-${mode} {
              0%, 100% { opacity: 0.3; }
              50% { opacity: 0.5; }
            }
            @keyframes keyArrowFlow-${mode} {
              0% { stroke-dashoffset: 0; }
              100% { stroke-dashoffset: ${iod * 0.17}; }
            }
            @keyframes overlayIn-${mode} {
              0% { opacity: 0; transform: scale(0.96); }
              100% { opacity: 1; transform: scale(1); }
            }
          `}</style>
        </defs>
        <g clipPath={`url(#vb-${mode})`}>

        {/* Step 1 / 4:
            CATCHLIGHT POSITION — bright dot + ring on each eye (the reflection)
            KEY LIGHT ANGLE    — dashed arrow originating from the primary
                                 catchlight, extending outward toward the light */}
        {showKey && catchlights.map((c, i) => {
          const isPrimary = c === primaryKey;
          // Use snapped eye-center coords for primary catchlight rendering
          const cx = isPrimary && snappedAnchor ? snappedAnchor.x : c.abs_cx;
          const cy = isPrimary && snappedAnchor ? snappedAnchor.y : c.abs_cy;
          return (
            <g key={`c${i}`} style={stepKey === 'capture' ? { opacity: 0.8 } : undefined}>
              {isPrimary && (
                <circle cx={cx} cy={cy} r={ringR * 0.9}
                  fill={catchColor} filter={`url(#cg-${mode})`}
                  style={{ animation: `catchlightPulse-${mode} 2.8s ease-in-out infinite` }} />
              )}
              <circle cx={cx} cy={cy} r={strokeBase * 0.8}
                fill={catchColor} opacity={isPrimary ? 1 : 0.8} />
              <circle cx={cx} cy={cy} r={ringR}
                fill="none" stroke={catchColor} strokeWidth={strokeBase * 0.6}
                opacity={isPrimary ? 0.95 : 0.6} />
              {isLearning && isPrimary && !showDist && (
                <circle cx={cx} cy={cy} r={ringR * 1.4}
                  fill="none" stroke={catchColor} strokeWidth={strokeBase * 0.18}
                  opacity="0.18" />
              )}
            </g>
          );
        })}
        {showKey && (
          <g style={stepKey === 'capture' ? { opacity: 0.75 } : undefined}>
            <line x1={arrowStartX} y1={arrowStartY} x2={arrowEndX} y2={arrowEndY}
              stroke={`url(#kag-${mode})`} strokeWidth={strokeBase * 2}
              opacity="0.18" filter={`url(#cg-${mode})`} strokeLinecap="round" />
            <line x1={arrowStartX} y1={arrowStartY} x2={arrowEndX} y2={arrowEndY}
              stroke={`url(#kag-${mode})`} strokeWidth={strokeBase * 1}
              markerEnd={`url(#kar-${mode})`}
              strokeDasharray={isLearning ? `${iod * 0.10} ${iod * 0.07}` : `${iod * 0.07} ${iod * 0.04}`}
              strokeLinecap="round"
              style={isLearning ? { animation: `keyArrowFlow-${mode} 6s linear infinite` } : undefined} />
            {showLabels && (() => {
              // ── Zone-based label placement ──────────────────────────────
              // The arrow extends from the catchlight outward. Place the KEY
              // label stack in the CORNER nearest the arrow tip so it stays
              // clear of the face. Use the arrow direction to pick the corner.
              const arrowGoesRight = clockVec.dx >= 0;
              const arrowGoesDown  = clockVec.dy >= 0;
              // Anchor in the corner the arrow points toward
              const cornerX = arrowGoesRight ? W - padding : padding;
              const cornerY = arrowGoesDown  ? H - padding * 1.5 : padding * 2.5;
              const anchor  = arrowGoesRight ? 'end' : 'start';

              const primary = angleDeg != null ? `KEY · ${Math.round(angleDeg)}°` : 'KEY LIGHT';
              const tr = targetRangeFor(pattern);
              const secondary = tr
                ? `${(pattern || '').toUpperCase()} TARGET ${tr}`
                : `FROM ${(position || '').toUpperCase()}`;
              const heightLabel = heightDisplay && heightDisplay !== '—' ? `↕ ${heightDisplay.toUpperCase()}` : null;

              // On capture step compress to single line (all overlays visible)
              const isCapture = stepKey === 'capture';

              // Stack direction: labels grow DOWN from top corners, UP from bottom
              const stackDir = arrowGoesDown ? -1 : 1;
              const _ly = arrowGoesDown
                ? Math.min(H - padding, cornerY)
                : Math.max(padding + fontBase, cornerY);

              return (
                <>
                  <text x={cornerX} y={_ly} textAnchor={anchor}
                    fontSize={fontBase * (isCapture ? 0.7 : 1)} fontWeight="900" fill={keyColor}
                    letterSpacing="1.5" fontFamily="Inter, system-ui, sans-serif"
                    filter={`url(#ts-${mode})`}>
                    {primary}
                  </text>
                  {!isCapture && (
                    <text x={cornerX} y={_ly + stackDir * fontBase * 0.52} textAnchor={anchor}
                      fontSize={fontBase * 0.42} fontWeight="700" fill={keyColor}
                      letterSpacing="1" fontFamily="Inter, system-ui, sans-serif"
                      filter={`url(#ts-${mode})`}>
                      {secondary}
                    </text>
                  )}
                  {!isCapture && heightLabel && (
                    <text x={cornerX} y={_ly + stackDir * fontBase * 0.92} textAnchor={anchor}
                      fontSize={fontBase * 0.38} fontWeight="700" fill={steel(0.7)}
                      letterSpacing="0.8" fontFamily="Inter, system-ui, sans-serif"
                      filter={`url(#ts-${mode})`}>
                      {heightLabel}
                    </text>
                  )}
                  {!isCapture && modName && modName !== 'Modifier' && (
                    <text x={cornerX} y={_ly + stackDir * fontBase * (heightLabel ? 1.28 : 0.92)} textAnchor={anchor}
                      fontSize={fontBase * 0.36} fontWeight="600" fill={steel(0.55)}
                      letterSpacing="0.6" fontFamily="Inter, system-ui, sans-serif"
                      filter={`url(#ts-${mode})`}>
                      {modName.toUpperCase()}
                    </text>
                  )}
                </>
              );
            })()}
            {/* CATCHLIGHT POSITION label — tags the reflection in the eye */}
            {showLabels && primaryKey && !showDist && stepKey !== 'capture' && (
              <text x={anchorX - ringR * 1.2} y={anchorY - ringR * 1.6}
                textAnchor="end"
                fontSize={fontBase * 0.42} fontWeight="800" fill={catchColor}
                letterSpacing="0.8" fontFamily="Inter, system-ui, sans-serif"
                filter={`url(#ts-${mode})`}>
                CATCHLIGHT @ {position || ''}
              </text>
            )}
          </g>
        )}

        {/* Step 2 / 4: distance rings at primary catchlight */}
        {showDist && primaryKey && (
          <g style={stepKey === 'capture' ? { opacity: 0.7 } : undefined}>
            <circle cx={anchorX} cy={anchorY}
              r={ringR * 2.2} fill="none" stroke={distColor}
              strokeWidth={strokeBase * 0.5} opacity="0.92"
              style={{ mixBlendMode: 'lighten' }} />
            <circle cx={anchorX} cy={anchorY}
              r={ringR * 3.2} fill="none" stroke={distColor}
              strokeWidth={strokeBase * 0.3} opacity="0.45"
              strokeDasharray={`${iod * 0.08} ${iod * 0.05}`} />
            {showLabels && (() => {
              // Place distance label on the OPPOSITE side from the key arrow
              // so they never collide. If key arrow goes right, distance goes left.
              const keyGoesRight = clockVec.dx >= 0;
              const _dx = keyGoesRight
                ? Math.max(padding, anchorX - ringR * 4)
                : Math.min(W - padding, anchorX + ringR * 4);
              const _anchor = keyGoesRight ? 'end' : 'start';
              const _dy = Math.max(fontBase * 1.5, Math.min(H - fontBase * 2, anchorY + ringR * 0.5));
              const isCapture = stepKey === 'capture';
              return (
                <>
                  <text x={_dx} y={_dy} textAnchor={_anchor}
                    fontSize={fontBase * (isCapture ? 0.52 : 0.72)} fontWeight="800" fill={distColor}
                    letterSpacing="1" fontFamily="Inter, system-ui, sans-serif"
                    filter={`url(#ts-${mode})`}>
                    {distance || 'DIST'}
                  </text>
                  {!isCapture && result?.sections?.modifier?.optDist && (
                    <text x={_dx} y={_dy + fontBase * 0.44} textAnchor={_anchor}
                      fontSize={fontBase * 0.34} fontWeight="600" fill={steel(0.55)}
                      letterSpacing="0.6" fontFamily="Inter, system-ui, sans-serif"
                      filter={`url(#ts-${mode})`}>
                      SWEET SPOT {result.sections.modifier.optDist.toUpperCase()}
                    </text>
                  )}
                </>
              );
            })()}
          </g>
        )}

        {/* Step 3 / 4: nose shadow vector */}
        {showShadow && noseTip && (
          <g style={stepKey === 'capture' ? { opacity: 0.65 } : undefined}>
            <line x1={noseTip[0]} y1={noseTip[1]} x2={shadowEndX} y2={shadowEndY}
              stroke={`url(#sfg-${mode})`} strokeWidth={strokeBase * 1.2} opacity="0.22"
              filter={`url(#sb-${mode})`} strokeLinecap="round" />
            <line x1={noseTip[0]} y1={noseTip[1]} x2={shadowEndX} y2={shadowEndY}
              stroke={`url(#sfg-${mode})`} strokeWidth={strokeBase * 0.7} opacity="0.90"
              markerEnd={`url(#sar-${mode})`} strokeLinecap="round"
              style={{ mixBlendMode: 'multiply' }} />
            <circle cx={noseTip[0]} cy={noseTip[1]} r={ringR * 0.5}
              fill={shadowColor} opacity="0.08" filter={`url(#sb-${mode})`} />
            <circle cx={noseTip[0]} cy={noseTip[1]} r={strokeBase * 0.6}
              fill={shadowColor} />
            {showLabels && (() => {
              // Place nose shadow label below the shadow endpoint, on the
              // opposite horizontal side from the key arrow to avoid collision.
              const keyGoesRight = clockVec.dx >= 0;
              const _sx = keyGoesRight
                ? Math.max(padding, shadowEndX - fontBase * 0.2)
                : Math.min(W - padding, shadowEndX + fontBase * 0.2);
              const _sAnchor = keyGoesRight ? 'end' : 'start';
              const _sy = Math.min(H - padding * 0.5, shadowEndY + fontBase * 0.6);
              const isCapture = stepKey === 'capture';
              return (
                <text x={_sx} y={_sy} textAnchor={_sAnchor}
                  fontSize={fontBase * (isCapture ? 0.38 : 0.48)} fontWeight="800" fill={shadowColor}
                  letterSpacing="0.8" fontFamily="Inter, system-ui, sans-serif"
                  filter={`url(#ts-${mode})`}>
                  NOSE SHADOW
                </text>
              );
            })()}
          </g>
        )}
        </g>{/* end clipPath group */}
      </svg>
    </div>
  );
}
