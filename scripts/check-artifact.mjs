#!/usr/bin/env node
/**
 * Artifact render gate.
 *
 * path-artifact step 3 requires every republish to be rendered headless and
 * measured: "A page whose cards are built by script fails silently and
 * completely if the script throws, and reading the source will not tell you."
 *
 * That was true here. reverse-the-light.html builds all 11 stage cards from a
 * JSON blob at runtime, so the source carries two `class="stage` and the page
 * carries eleven. Only a render can tell them apart.
 *
 * Until 2026-09-02 the script that did this lived as an untracked dotfile in
 * the repo root, and it only console.log'd -- it never exited non-zero, so it
 * could not fail. It was a recorder, not a gate.
 *
 * Usage: node scripts/check-artifact.mjs <hydrated-artifact.html>
 *
 * Point it at a HYDRATED artifact (a published copy), never at
 * docs/artifact/reverse-the-light.html -- that file is the template and still
 * carries the literal __STATE__ placeholder, so JSON.parse throws by design.
 */
import puppeteer from 'puppeteer';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const target = process.argv[2];
if (!target) { console.error('usage: node scripts/check-artifact.mjs <hydrated-artifact.html>'); process.exit(2); }
const path = resolve(target);
if (!existsSync(path)) { console.error(`No such file: ${path}`); process.exit(2); }

const EXPECTED_STAGES = 11;   // the spine is stages 0..10. A structural fact.
const fail = [];

const browser = await puppeteer.launch({ headless: 'new' });
const seen = {};

for (const theme of ['light', 'dark']) {
  const page = await browser.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(`${theme}: ${e.message}`));
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
  await page.setViewport({ width: 390, height: 900 });
  // localStorage starts EMPTY on purpose. path-artifact section 5: if a stage
  // reads PASSED but its items render untouched, the page contradicts its own
  // verdict -- and a first-time viewer is exactly who sees that.
  await page.goto('file://' + path, { waitUntil: 'networkidle0' });
  await new Promise(r => setTimeout(r, 700));

  const m = await page.evaluate(() => {
    const q = s => [...document.querySelectorAll(s)];
    const boxes = q('#stages [role=checkbox]');
    return {
      stages:   document.querySelector('#stages')?.children.length ?? 0,
      // REWRITTEN 2026-09-03. The previous version keyed off `.mk.passed`
      // SPANS. The moment the page was brought in line with the amended rule
      // those spans became <button class="box rec">, so every filter matched
      // ZERO elements and every assertion passed vacuously. The gate reported
      // green on a page it had stopped inspecting -- the same false-zero shape
      // it exists to catch. Any count that can legitimately be zero now has a
      // presence check in front of it.
      recordedPasses: q('#stages .box.rec').length,
      passesNotTicked: q('#stages .box.rec')
        .filter(b => b.getAttribute('aria-checked') !== 'true').length,
      passesViewerCanUntick: q('#stages .box.rec')
        .filter(b => b.getAttribute('aria-disabled') === 'true' || b.disabled ? false : true).length,
      owedBoxes: q('#stages .box.owed').length,
      owedWithoutLiveBox: q('#stages .box.owed')
        .filter(b => b.disabled || b.getAttribute('aria-disabled') === 'true').length
        // plus any NOT RUN text carrying no box at all
        + q('#stages .it').filter(el =>
            /NOT RUN|NEVER RUN|NOT RECORDED/.test(el.textContent || '') &&
            !el.querySelector('.box')).length,
      notApplicable: q('#stages .mk').length,
      open:   boxes.filter(b => b.getAttribute('aria-disabled') !== 'true' && !b.disabled).length,
      locked: boxes.filter(b => b.getAttribute('aria-disabled') === 'true' || b.disabled).length,
      hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      // innerText returns RENDERED text, and .kick sets text-transform:uppercase,
      // so the page reads "RECORDED 2026-08-28". Case-sensitive matching here
      // produced a false failure on a page that was correct.
      recordedDate: (document.body.innerText.match(/Recorded\s+(\d{4}-\d{2}-\d{2})/i) || [])[1] || null,
    };
  });

  if (errs.length) fail.push(...errs.map(e => `JS error on load -- ${e}`));

  // ── Section 6, driven rather than assumed ────────────────────────────────
  // "The test: tick two boxes, toggle on, and assert every NOT RUN item is
  // still visible. If that assertion is missing, the toggle is not verified."
  //
  // This is the case where sections 5 and 6 collide: section 5 (amended 9/2)
  // gives an owed item a LIVE checkbox, and a ticked owed item then satisfies
  // section 6's own definition of "completed". Resolved in favour of 6 -- a
  // tick is the reader's working note, and only a gate record retires an
  // obligation -- so this drives the real UI to prove it, instead of trusting
  // that the filter reads the way it looks like it reads.
  const hideDone = await page.evaluate(() => {
    const owed = Array.from(document.querySelectorAll('#stages .box.owed'));
    const open = Array.from(document.querySelectorAll('#stages .box:not(.owed):not(.rec):not([disabled])'));
    if (!owed.length) return { skipped: 'no owed item on this page' };
    owed[0].click();                 // tick the OWED item itself
    open.slice(0, 2).forEach(b => b.click());   // and two ordinary open ones
    const btn = document.getElementById('hidedone');
    if (!btn) return { noToggle: true };
    btn.click();
    return {
      pressed:      btn.getAttribute('aria-pressed'),
      owedVisible:  document.querySelectorAll('#stages .box.owed').length,
      openTicked:   open.slice(0, 2).length,
    };
  });
  if (hideDone.noToggle) fail.push(`${theme}: no "Hide completed" toggle -- required on every path artifact`);
  else if (!hideDone.skipped) {
    if (hideDone.pressed !== 'true') fail.push(`${theme}: "Hide completed" did not engage (aria-pressed=${hideDone.pressed})`);
    if (hideDone.owedVisible === 0) fail.push(`${theme}: a TICKED owed item was hidden by "Hide completed" -- section 6 says a NOT RUN item is never hidden, and an artifact that can hide its own unmet obligations is the failure both rules exist to prevent`);
  }
  // The clicks above PERSIST to localStorage, and the two themes share an
  // origin -- so without this the dark run inherits a ticked, hidden state and
  // its measurements are contaminated. That is precisely what happened on the
  // first run of this check: dark reported recordedPasses=0 and was read as a
  // theme-drift bug rather than as test pollution.
  await page.evaluate(() => { try { localStorage.clear(); } catch (_) {} });
  if (m.stages !== EXPECTED_STAGES) fail.push(`${theme}: rendered ${m.stages} stages, expected ${EXPECTED_STAGES} (script threw? state empty?)`);
  // Presence checks FIRST. Without them the three assertions below are
  // satisfied by an empty NodeList, which is how this gate went vacuous.
  if (m.recordedPasses === 0) fail.push(`${theme}: zero recorded-pass controls found (.box.rec) -- either the page renders none, or this gate's selector has gone stale and every assertion below it is vacuous`);
  if (m.owedBoxes === 0 && m.owedWithoutLiveBox === 0) fail.push(`${theme}: zero owed controls found (.box.owed) -- a NOT RUN item must render as a LIVE checkbox, and its absence here usually means the selector drifted`);
  if (m.passesNotTicked > 0) fail.push(`${theme}: ${m.passesNotTicked} recorded PASS item(s) do not read as ticked with storage cleared -- the page contradicts its own verdict for a first-time viewer`);
  if (m.passesViewerCanUntick > 0) fail.push(`${theme}: ${m.passesViewerCanUntick} recorded PASS item(s) are togglable -- a fact from the gate record is not the viewer's to change`);
  if (m.owedWithoutLiveBox > 0) fail.push(`${theme}: ${m.owedWithoutLiveBox} NOT RUN/OWED item(s) have no live checkbox -- unmet obligations rendered as dead text is the defect that cost the-rooms seventeen findings`);
  if (m.hscroll > 0) fail.push(`${theme}: page scrolls horizontally by ${m.hscroll}px`);
  if (!m.recordedDate) fail.push(`${theme}: no "Recorded <date>" stamp found -- staleness cannot be checked mechanically`);

  seen[theme] = m;
  console.log(`  ${theme.padEnd(5)} ${JSON.stringify(m)}`);
  await page.close();
}
await browser.close();

for (const k of Object.keys(seen.light)) {
  if (JSON.stringify(seen.light[k]) !== JSON.stringify(seen.dark[k])) {
    fail.push(`theme drift on "${k}": light=${seen.light[k]} dark=${seen.dark[k]}`);
  }
}

if (fail.length) {
  console.error(`\n✗ Artifact render gate FAILED (${fail.length}):`);
  fail.forEach(f => console.error(`    • ${f}`));
  console.error('\nThis page builds its cards at runtime. A failure here means viewers see a broken page.\n');
  process.exit(1);
}
console.log(`\n✓ Artifact renders: ${seen.light.stages} stages, ${seen.light.recordedPasses} recorded passes, ${seen.light.owedBoxes} owed, Recorded ${seen.light.recordedDate}, no JS errors, no theme drift.\n`);
