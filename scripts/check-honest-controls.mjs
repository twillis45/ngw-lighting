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
import { readFileSync, readdirSync } from 'node:fs';
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
// REWRITTEN 2026-08-31. The first version read ONE file — the Studio settings
// screen — and passed while the LEGACY screen shipped the same three dead URLs
// it had just been written to catch. /help, /privacy and /terms all 404'd from
// ui/src/screens/SettingsScreen.jsx for two more days.
//
// Same failure as the no-op sweep before it: a gate scoped to where the bug was
// found rather than to where the bug can live. It now enumerates every source
// file and checks every outbound URL it finds.
console.log('\nOutbound links — no control anywhere may open a 404');
{
  const walkAll = (d, out = []) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const f = join(d, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walkAll(f, out); }
      else if (/\.(jsx?|mjs)$/.test(e.name)) out.push(f);
    }
    return out;
  };
  const srcFiles = walkAll(join(here, '..', 'ui/src'));
  check('enumerated the source tree for links', srcFiles.length > 50, srcFiles.length);

  // Collect every literal http(s) URL, with the file that holds it.
  const found = new Map();
  for (const f of srcFiles) {
    const rel = f.slice(f.indexOf('ui/src'));
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(/['"`](https?:\/\/[^'"`\s${}]+)['"`]/g)) {
      const u = m[1].replace(/[.,)]+$/, '');
      // Skip schema/namespace URLs and anything templated.
      if (/w3\.org|schema\.org|localhost|127\.0\.0\.1|example\.(com|invalid)/.test(u)) continue;
      // A URL carrying userinfo (user@host) is an ingest endpoint or a
      // credentialled service URL — a Sentry DSN, for instance — never
      // something a control opens for a person. This gate asks "does a link a
      // user can click resolve", so those are out of scope by definition
      // rather than because checking them was inconvenient: a DSN answers 404
      // to GET by design and always will.
      if (/^https?:\/\/[^/]*@/.test(u)) continue;
      if (!found.has(u)) found.set(u, rel);
    }
  }
  check('found outbound URLs to check', found.size > 0, found.size);

  if (process.env.NO_NET) {
    console.log('  skip network arm (NO_NET=1)');
  } else {
    for (const [u, rel] of found) {
      let code;
      try {
        code = execFileSync('curl',
          ['-sSL', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '20', u],
          { encoding: 'utf8' }).trim();
      } catch (e) { code = `ERR ${e.message}`; }
      check(`${u}  (${rel})`, code === '200' || code === '403', code);
    }
  }
}

// ── Structural: no control anywhere may be wired to a no-op ───────────────
// The named findings above are the five we happened to know about. This is the
// gate that catches the sixth. It enumerates the source tree rather than
// checking a list, so a dead control added next month fails without anyone
// remembering this rule exists.
console.log('\nWhole surface — no control wired to a no-op handler');
{
  const walk = (d, out = []) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const f = join(d, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walk(f, out); }
      else if (/\.jsx?$/.test(e.name)) out.push(f);
    }
    return out;
  };
  const files = walk(join(here, '..', 'ui/src'));
  check('enumerated the source tree', files.length > 50, files.length);

  // REWRITTEN 2026-08-30. The first version was regexes over raw source and was
  // FALSE-GREEN by construction, which an adversarial audit proved by planting
  // three live dead buttons in a clean tree and watching the script print PASS.
  // Four holes, and the first is the one that matters:
  //
  //   1. Any comment in the handler body broke the character class — and a
  //      `// TODO: wire this up` comment is EXACTLY what the three dead login
  //      buttons had. The check could not see the only form it had ever needed
  //      to catch.
  //   2. An empty useCallback body was skipped by an `if (body.trim())` guard.
  //   3. Plain (non-useCallback) arrow handlers were invisible to both regexes.
  //   4. The inline `onClick={() => {}}` idiom it did match occurs ZERO times
  //      in this codebase, while `onClick={handleX}` occurs 159 times.
  //
  // So it is a scanner now, not a regex. Comments are stripped first, then
  // handler bodies are found by walking braces, which is the only way to read a
  // body reliably.

  /** Remove comments and string bodies so neither can hide or fake a match. */
  const strip = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
    .replace(/'(?:[^'\\\n]|\\.)*'/g, "''")
    .replace(/"(?:[^"\\\n]|\\.)*"/g, '""');

  /** From the index of a '{', return the body up to its matching '}'. */
  const body = (src, open) => {
    let depth = 0;
    for (let i = open; i < src.length; i++) {
      if (src[i] === '{') depth++;
      else if (src[i] === '}' && --depth === 0) return src.slice(open + 1, i);
    }
    return null;
  };

  // A body is INERT if nothing survives removing feedback-only calls. Feedback
  // is the poison here, not the absence of code: a handler that fires a POSITIVE
  // haptic and then returns tells the user their tap worked when it did not.
  const FEEDBACK = /\b\w*(?:[Hh]aptic|[Ss]ound|[Vv]ibrate)\s*\([^)]*\)\s*;?/g;
  const isInert = (b) => b.replace(FEEDBACK, ' ').replace(/[\s;]/g, '') === '';

  // Both declaration forms, useCallback or plain arrow, named or inline.
  const DECL = /(?:const\s+(\w+)\s*=\s*(?:useCallback\s*\(\s*)?|on(?:Click|Press|Submit)\s*=\s*\{\s*)\([^)]*\)\s*=>\s*\{/g;

  const EMPTY_ONCHANGE = /onChange=\{\(\)\s*=>\s*\{\s*\}\}/g;

  const offenders = [];
  for (const f of files) {
    const src = strip(readFileSync(f, 'utf8'));
    const rel = f.slice(f.indexOf('ui/src'));
    for (const m of src.matchAll(DECL)) {
      const b = body(src, m.index + m[0].length - 1);
      if (b === null || !isInert(b)) continue;
      const name = m[1] || '(inline handler)';
      // A named declaration only matters if something actually wires it up.
      if (m[1] && !new RegExp(`on(?:Click|Press|Submit)\\s*=\\s*\\{\\s*${m[1]}\\b`).test(src)) continue;
      offenders.push(`${rel}: ${name} does nothing${/[Hh]aptic|[Ss]ound/.test(b) ? ' but fire feedback' : ''}`);
    }
  }
  check('no no-op controls anywhere in ui/src',
        offenders.length === 0, offenders.slice(0, 8));

  // Justify the onChange exclusion: every no-op onChange must sit under an
  // element that carries a real onClick, i.e. the control genuinely acts.
  const unjustified = [];
  for (const f of files) {
    const src = readFileSync(f, 'utf8');
    const rel = f.slice(f.indexOf('ui/src'));
    const lines = src.split('\n');
    lines.forEach((ln, i) => {
      if (!EMPTY_ONCHANGE.test(ln)) return;
      EMPTY_ONCHANGE.lastIndex = 0;
      // Resolve the element the onChange actually belongs to. A lookback window
      // alone credited a wrapper's onClick to a different control entirely — a
      // planted no-op onChange on a <span> passed this check until it did not.
      let tag = null, j = i;
      while (j >= 0 && j > i - 12) {
        const m = lines[j].match(/<([A-Za-z][\w.]*)/);
        if (m) { tag = m[1]; break; }
        j--;
      }
      // The controlled-input idiom exists only for real form elements. A no-op
      // onChange on anything else is not plumbing — onChange does not even fire
      // there — so it is a dead control.
      if (!['input', 'select', 'textarea'].includes(tag)) {
        unjustified.push(`${rel}:${i + 1} — no-op onChange on <${tag}>, not a form element`);
        return;
      }
      // NOT CHECKED, deliberately: whether the owning <input> really has a
      // wrapper onClick behind it. A lookback window cannot answer that — in a
      // dense list render it finds SOME onClick and calls it justified. It was
      // red-proofed by deleting the real wrapper onClick and the check stayed
      // green, so it is removed rather than shipped as a green assertion that
      // never fails. A no-op onChange on a real form element is left to review.
    });
  }
  check('no no-op onChange outside a real form element',
        unjustified.length === 0, unjustified);

  // The three that started this, by name — belt and braces, because a regex
  // that stops matching is indistinguishable from a clean tree.
  const login = read('ui/src/screens/studio/_adjacent/StudioLoginScreen.jsx');
  for (const dead of ['handleAppleSignIn', 'handleGoogleSignIn'])
    check(`${dead} is gone from the login screen`, !login.includes(dead));
  check('forgot password routes somewhere real', /setMode\('forgot'\)/.test(login));
  check('provider buttons are gated on server state', /googleReady && \(<>/.test(login));
  check('provider state fails closed', /\.catch\(\(\) => \{ \/\* no provider button \*\//.test(login));
}

// ── Contact addresses must be on a domain we actually own and read ─────────
// SUPPORT_EMAIL was hello@noguesswork.com — the WRONG DOMAIN — in TWO settings
// screens. It survived a check on 2026-08-29 because noguesswork.com has live
// Outlook MX, so "does mail resolve" answered yes. The right question was
// "is this the company's domain", which nobody asked.
console.log('\nContact addresses — right domain, and a mailbox someone reads');
{
  const walkSrc = (d, out = []) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const f = join(d, e.name);
      if (e.isDirectory()) { if (e.name !== 'node_modules') walkSrc(f, out); }
      else if (/\.(jsx?|mjs)$/.test(e.name)) out.push(f);
    }
    return out;
  };
  const bad = [];
  const sendOnly = [];
  for (const f of walkSrc(join(here, '..', 'ui/src'))) {
    const rel = f.slice(f.indexOf('ui/src'));
    const code = readFileSync(f, 'utf8')
      .split('\n').filter(l => !l.trim().startsWith('//')).join('\n');
    for (const m of code.matchAll(/['"`]([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})['"`]/g)) {
      const addr = m[1].toLowerCase();
      if (/example\.(com|invalid)|@localhost|you@/.test(addr)) continue;
      // noguesswork.com is NOT the company domain. noguessworksystems.com is.
      if (/@noguesswork\.com$/.test(addr)) bad.push(`${rel}: ${addr}`);
      // hello@ is the Resend SENDING identity, not a monitored mailbox — a
      // support link pointing there means replies land nowhere.
      else if (addr === 'hello@noguessworksystems.com') sendOnly.push(`${rel}: ${addr}`);
    }
  }
  check('no address on the wrong domain (noguesswork.com)', bad.length === 0, bad);
  check('no support link points at the send-only FROM_EMAIL', sendOnly.length === 0, sendOnly);
}

console.log(failures === 0 ? '\nPASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
