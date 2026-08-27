#!/usr/bin/env node
/**
 * Verifies buildLightingEvidence against a REAL captured /api/analyze payload.
 *
 * There is no JS test runner in this repo and one function does not justify
 * adding a permanent dependency, so this is a plain node assertion script.
 * Run: node scripts/check-lighting-evidence.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { buildLightingEvidence, scoreIsMeaningful }
  from '../ui/src/screens/studio/_shared/lightingEvidence.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(readFileSync(
  join(here, '../ui/src/screens/studio/_shared/__fixtures__/read-rembrandt.json'), 'utf8'));

let failures = 0;
const check = (name, cond, got) => {
  if (cond) { console.log(`  ok   ${name}`); }
  else { console.log(`  FAIL ${name}${got !== undefined ? ` -- got ${JSON.stringify(got)}` : ''}`); failures++; }
};

console.log('buildLightingEvidence — real payload (rembrandt_classic)');
const { observations, limits } = buildLightingEvidence(fixture);

check('produces observations', observations.length > 0, observations.length);

const catch_ = observations.find(o => o.label === 'Catchlight');
check('leads with the catchlight (strongest key-direction signal)',
  observations[0]?.label === 'Catchlight', observations[0]?.label);
check('catchlight carries a clock position',
  !!catch_ && /o'clock/.test(catch_.value), catch_?.value);

check('reports source size physically, not as a product name',
  observations.some(o => o.label === 'Source size'), observations.map(o => o.label));

// This fixture is a B&W frame; the engine flagged bw_processing.
check('surfaces what limited the read',
  limits.some(l => /black and white/i.test(l)), limits);

// The engine records where it was unsure. It reached the API and nothing
// displayed it; these assert it now survives into the readout.
const d = buildLightingEvidence(fixture);
check('surfaces that two readings disagreed',
  d.disagreements.length > 0 && /vs/.test(d.disagreements[0]), d.disagreements);
check('names the runner-up pattern',
  !!d.runnerUp && !!d.runnerUp.pattern, d.runnerUp);
check('reports signal coverage',
  !!d.coverage && typeof d.coverage.available === 'number', d.coverage);
check('does not leak internal resolver names to the photographer',
  !d.disagreements.some(x => /reference_read|lighting_inference|cue_inference/.test(x)),
  d.disagreements);
check('does not repeat the same limitation twice',
  new Set(d.limits).size === d.limits.length, d.limits);

console.log('\nscoreIsMeaningful — only the band measured as separable');
check('80 is shown', scoreIsMeaningful(80) === true);
check('79 is withheld', scoreIsMeaningful(79) === false);
check('null is withheld', scoreIsMeaningful(null) === false);

console.log('\nempty/degenerate input must not throw');
for (const bad of [undefined, null, {}, { lighting_inference: null }]) {
  const r = buildLightingEvidence(bad);
  check(`handles ${JSON.stringify(bad)}`, Array.isArray(r.observations) && Array.isArray(r.limits));
}

console.log(failures === 0 ? '\nPASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
