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
      recorded: q('#stages .mk.passed, #stages .mk.skipped').length,
      // AMENDED 2026-09-02, tracking path-artifact section 5. This used to
      // assert that NO recorded marker was interactive. That is now backwards.
      // The distinction is handled vs OWED, not recorded vs open:
      //   a recorded PASS  -> checkbox, checked AND disabled
      //   a recorded NOT RUN / NOT RECORDED / OWED -> a LIVE checkbox, because
      //     it is open work wearing a recorded label
      // Only "not applicable" and "the spine defines no gate" get no box.
      passesNotTicked: q('#stages .mk.passed').filter(e => {
        const box = e.closest('.it')?.querySelector('[role=checkbox],input[type=checkbox]');
        if (!box) return true;                       // a pass with no box at all
        const checked = box.getAttribute('aria-checked') === 'true' || box.checked === true;
        return !checked;
      }).length,
      passesViewerCanUntick: q('#stages .mk.passed').filter(e => {
        const box = e.closest('.it')?.querySelector('[role=checkbox],input[type=checkbox]');
        if (!box) return false;
        return box.getAttribute('aria-disabled') !== 'true' && box.disabled !== true;
      }).length,
      owedWithoutLiveBox: q('#stages .it').filter(el => {
        if (!/NOT RUN|NEVER RUN|NOT RECORDED|\bOWED\b/.test(el.textContent || '')) return false;
        const box = el.querySelector('[role=checkbox],input[type=checkbox]');
        if (!box) return true;                       // owed work as dead text
        return box.getAttribute('aria-disabled') === 'true' || box.disabled === true;
      }).length,
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
  if (m.stages !== EXPECTED_STAGES) fail.push(`${theme}: rendered ${m.stages} stages, expected ${EXPECTED_STAGES} (script threw? state empty?)`);
  if (m.recorded === 0) fail.push(`${theme}: no recorded markers rendered with localStorage empty -- a passed gate would look untouched`);
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
console.log(`\n✓ Artifact renders: ${seen.light.stages} stages, ${seen.light.recorded} recorded markers, Recorded ${seen.light.recordedDate}, no JS errors, no theme drift.\n`);
