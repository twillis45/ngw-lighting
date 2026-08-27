/**
 * lightingEvidence — turn an analysis payload into the OBSERVATIONS behind a read.
 *
 * Why this exists (review board, 2026-08-27):
 *
 * The result screen graded itself — "Confident" / "Tentative" / "Uncertain" —
 * on a number that does not track correctness. Measured over the reference
 * corpus: reads labelled "Tentative" were right 100% of the time, "Uncertain"
 * 83%, "Confident" 89%. Correlation between the score and being right: +0.035.
 *
 * A false "Uncertain" is not a harmless hedge. It teaches a photographer to
 * discount the label, so the warning is already spent on the day the engine is
 * genuinely lost. The board's ruling was to stop grading and start showing:
 * catchlight position is the strongest key-direction signal we have, and a
 * working photographer can check it against the photo in one glance.
 *
 * Pure function, no React — verified by scripts/check-lighting-evidence.mjs.
 */

/** Plain-language reasons the engine had less to work with. observability.ambiguity_flags. */
const AMBIGUITY_TEXT = {
  // Same wording as LIMIT_TEXT.bw_processing on purpose: both flags mean the
  // same thing to a photographer, and the dedupe below is by string.
  bw_limits_color_cues: 'Black and white — color temperature and gel cues are unavailable',
  low_signal_coverage:  'Fewer usable signals than normal in this frame',
  face_occluded:        'Part of the face is covered',
  multi_face:           'More than one face — the read follows the largest',
};

/** "reference_read says 'butterfly' but lighting_inference says 'loop'"
 *  -> butterfly vs loop. Internal resolver names are never shown to a
 *  photographer; what matters is that two reads disagreed, and on what. */
const DISAGREE_RE = /says\s+'([^']+)'\s+but\s+.*?says\s+'([^']+)'/;

function prettyPattern(p) {
  return String(p || '').replace(/_/g, ' ');
}

/** Plain-language reasons a read was constrained. Keys are edge_case_flags. */
const LIMIT_TEXT = {
  bw_processing:        'Black and white — color temperature and gel cues are unavailable',
  blown_highlights:     'Highlights are clipped — the brightest falloff is unrecoverable',
  extreme_low_key:      'Most of the frame is in shadow — fewer mid-tones to read direction from',
  mixed_color_temperature: 'Mixed color temperature — sources may be fighting',
  outdoor_foliage_shadows: 'Dappled foliage shadows can imitate modifier patterns',
  window_light_gradient:   'Window gradient across the face can imitate a large modifier',
  no_face:              'No face detected — pattern geometry could not be measured',
};

/**
 * @param {object} data  analysis payload (authoritative_*, lighting_inference, edge_case_flags)
 * @returns {{observations: Array<{label:string, value:string, detail?:string}>,
 *            limits: string[]}}
 */
export function buildLightingEvidence(data) {
  const li = (data && data.lighting_inference) || {};
  const ci = li.catchlight_intelligence || {};
  const pk = ci.primary_key || null;
  const mod = ci.modifier || null;

  const observations = [];

  // Catchlight first — CLAUDE.md analysis order: catchlight position is the
  // strongest key-direction signal, and it is the one a photographer can
  // verify against the photo without trusting us.
  if (pk && pk.position) {
    observations.push({
      label: 'Catchlight',
      value: `${pk.position}${pk.eye ? `, ${pk.eye} eye` : ''}`,
      detail: pk.shape ? `${pk.shape} reflection` : undefined,
    });
  }

  if (li.key_position_text) {
    observations.push({ label: 'Key direction', value: li.key_position_text });
  }

  // Source size, stated physically rather than as a product name.
  if (mod && (mod.size_estimate || mod.label)) {
    observations.push({
      label: 'Source size',
      value: mod.size_estimate || mod.label,
      detail: mod.physical_meaning
        // Trim the internal area maths; keep the part a photographer acts on.
        ? String(mod.physical_meaning).split('—').pop().trim()
        : undefined,
    });
  }

  if (li.light_count) {
    observations.push({
      label: 'Lights',
      value: `${li.light_count} source${li.light_count === 1 ? '' : 's'}`,
      detail: li.fill_method_text && li.fill_method_text !== 'none'
        ? `${li.fill_method_text} fill` : undefined,
    });
  }

  const flags = (data && data.edge_case_flags) || {};
  const limits = Object.keys(LIMIT_TEXT)
    .filter(k => flags[k])
    .map(k => LIMIT_TEXT[k]);

  // The engine already records where it was unsure -- which readings
  // disagreed, what was ambiguous, how much signal it had. It reached the
  // API and nothing displayed it. Showing it is the difference between a
  // read a photographer can weigh and one they have to take on faith.
  const obs = (data && data.observability) || {};

  for (const f of obs.ambiguity_flags || []) {
    const text = AMBIGUITY_TEXT[f];
    if (text && !limits.includes(text)) limits.push(text);
  }

  const disagreements = [];
  for (const c of obs.contradictions || []) {
    const m = DISAGREE_RE.exec(String(c));
    if (m && m[1] !== m[2]) {
      const pair = `${prettyPattern(m[1])} vs ${prettyPattern(m[2])}`;
      if (!disagreements.includes(pair)) disagreements.push(pair);
    }
  }

  // The runner-up, and whether the engine actually separated its top two.
  //
  // MEASURED over the 34-image corpus (2026-08-27), and the first signal
  // found that tracks correctness at all:
  //
  //     credibility gap >  0  ->  n=11, 11 correct  (100%)
  //     credibility gap <= 0  ->  n=14,  9 correct  ( 64%)
  //
  // Every error in the corpus sits in the second group. The stated
  // confidence does not do this -- the wrong answers there carry 0.87,
  // 0.89 and 0.94.
  //
  // This is NOT a decline trigger. Declining on gap <= 0 would discard 9
  // correct reads to catch 5 errors. It is a qualifier: when the engine
  // could not separate its top two, say so and name what was close, so a
  // photographer weighs it instead of taking it on faith. n=25, so "100%"
  // means "not observed wrong in 11 tries", not "never wrong".
  const credible = (obs.candidate_credibility_summary || [])
    .filter(c => c && c.pattern)
    .slice(0, 3);
  const runnerUp = credible.length > 1
    ? { pattern: prettyPattern(credible[1].pattern), credibility: credible[1].credibility }
    : null;
  const separated = credible.length > 1
    ? (credible[0].credibility - credible[1].credibility) > 0
    : null;

  const cov = obs.signal_coverage || null;
  const coverage = cov && typeof cov.signals_available === 'number'
    ? {
        available: cov.signals_available,
        total: cov.signals_total,
        strength: cov.overall_strength,
        weak: cov.weak_signals || [],
      }
    : null;

  return { observations, limits, disagreements, runnerUp, separated, coverage };
}

/**
 * Whether a numeric score is worth showing at all.
 *
 * Only the top band measured as meaningfully separable (>=80 -> 89% correct;
 * everything below sat at 83-100% with no ordering). Below the threshold the
 * number is noise wearing the costume of precision, so we show observations
 * instead. Thresholds are MEASURED -- see the module docstring.
 */
export function scoreIsMeaningful(confidence0to100) {
  return typeof confidence0to100 === 'number' && confidence0to100 >= 80;
}
