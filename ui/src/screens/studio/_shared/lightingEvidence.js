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

  return { observations, limits };
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
