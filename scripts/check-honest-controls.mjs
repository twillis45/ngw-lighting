#!/usr/bin/env node
/**
 * Honest-controls gate — every control must do what its label promises.
 *
 * Written 8/28/2026 after the stage-4 Nielsen pass found five controls that
 * rendered perfectly and lied about their behavior. The visual and geometry
 * passes could not catch these by construction: a dead button measures as a
 * correctly sized, correctly positioned, fully accessible tap target.
 *
 * Two arms:
 *   1. Source assertions — the wiring that makes each control honest.
 *   2. A live link check — every outbound URL must not 404.
 *
 * Run: node scripts/check-honest-controls.mjs
 * Skip the network arm with:  NO_NET=1 node scripts/check-honest-controls.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const read = p => readFileSync(join(here, '..', p), 'utf8');

let failures = 0;
const check = (name, cond, got) => {
  if (cond) console.log(`  ok   ${name}`);
  else { console.log(`  FAIL ${name}${got !== undefined ? ` -- got ${JSON.stringify(got)}` : ''}`); failures++; }
};

// ── P1 #3 — the public proof surface must not render engine slugs ──────────
console.log('AccuracyScreen — no raw enum slugs on the public proof surface');
{
  const src = read('ui/src/screens/studio/_core/AccuracyScreen.jsx');
  check('imports the canonical prettify helper', /import prettify from/.test(src));
  const rawLabel = /\{\s*e\.verdict\?\.expected\s*\|\|\s*e\.pattern\s*\}/.test(src);
  check('label is not the raw expected value', !rawLabel);
  check('label routes through prettify',
        /prettify\(e\.verdict\?\.expected \|\| e\.pattern/.test(src));
  check('alt text routes through prettify',
        /alt=\{`Reference — expected \$\{prettify\(/.test(src));
}

// ── P1 #2 — a control labeled "Retry" must re-send the same photo ──────────
console.log('\nFallbackReveal — "Retry" re-sends; it does not discard the photo');
{
  const src = read('ui/src/screens/Day1DemoApp.jsx');
  check('a rerun handler exists', /const handleRerun = \(\) => \{/.test(src));
  check('rerun re-sends the held file', /handleAnalyze\(imageFile, imagePreview, exifData\)/.test(src));
  check('rerun falls back when no file is held', /if \(!imageFile\) return handleRetry\(\)/.test(src));
  check('error screen is wired to it', /onRerun=\{handleRerun\}/.test(src));
  check('error screen reports whether a rerun is possible', /canRerun=\{!!imageFile\}/.test(src));
  check('the click routes to rerun when possible', /if \(doesRerun\) onRerun\(\);/.test(src));
  // Every scenario whose button says "Retry" must be marked rerun.
  const scenarios = src.split('\n').filter(l => /retry: '/.test(l) && /tone: TONE\./.test(l));
  check('found the scenario table', scenarios.length >= 6, scenarios.length);
  for (const line of scenarios) {
    const label = line.match(/retry: '([^']+)'/)[1];
    const kicker = (line.match(/kicker: '([^']+)'/) || [, '?'])[1];
    if (label === 'Retry') check(`"${kicker}" (labeled Retry) is marked rerun`, /rerun: true/.test(line));
    else check(`"${kicker}" (labeled ${label}) is NOT marked rerun`, !/rerun: true/.test(line));
  }
  check('label degrades when no file is held',
        /const actionLabel = \(!!rerun && !doesRerun\) \? 'New Photo' : retryLabel;/.test(src));
  check('the rendered label uses actionLabel', /\{actionLabel\.toUpperCase\(\)\}/.test(src));
  check('the raw retryLabel is not rendered', !/\{retryLabel\.toUpperCase\(\)\}/.test(src));
}

// ── P1 #4 — "Back" navigates; it must not destroy the user's work ──────────
console.log('\nResultScreen — "Back" navigates, it does not destroy');
{
  const src = read('ui/src/screens/Day1DemoApp.jsx');
  check('a non-destructive result-back exists', /const handleResultBack = \(\) => \{/.test(src));
  const body = src.split('const handleResultBack = () => {')[1].split('};')[0];
  check('it does not null the photo', !/setImageFile\(null\)/.test(body));
  check('it does not null the result', !/setResult\(null\)/.test(body));
  const resultProps = src.split('<ResultScreen')[1].split('/>')[0];
  check('ResultScreen back is not handleRetry', !/onRetry=\{handleRetry\}/.test(resultProps));
  check('ResultScreen back is handleResultBack', /onRetry=\{handleResultBack\}/.test(resultProps));
}

// ── P1 #5 — every outbound link must resolve ───────────────────────────────
console.log('\nOutbound links — no control may open a 404');
{
  const src = read('ui/src/screens/studio/_deferred/Day1SettingsScreen.jsx');
  check('the dead help constant is gone', !/HELP_URL/.test(src));
  check('no row still promises a help page', !/Help & FAQ/.test(src));

  const urls = [...src.matchAll(/'(https:\/\/[^']+)'/g)].map(m => m[1]);
  check('found outbound URLs to check', urls.length > 0, urls.length);
  if (process.env.NO_NET) {
    console.log('  skip network arm (NO_NET=1)');
  } else {
    for (const u of urls) {
      // curl, not fetch: node 16 has no global fetch and this gate must not
      // acquire a dependency to check four links.
      let code;
      try {
        code = execFileSync('curl',
          ['-sSL', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '20', u],
          { encoding: 'utf8' }).trim();
      } catch (e) { code = `ERR ${e.message}`; }
      check(`${u} resolves`, code === '200', code);
    }
  }
}

console.log(failures === 0 ? '\nPASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
