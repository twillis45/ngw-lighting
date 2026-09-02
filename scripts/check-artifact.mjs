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
      // A recorded marker the viewer can toggle is not a record.
      recordedInteractive: q('#stages .mk.passed, #stages .mk.skipped')
        .filter(e => e.getAttribute('role') === 'checkbox' || e.tagName === 'INPUT').length,
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
  if (m.recordedInteractive > 0) fail.push(`${theme}: ${m.recordedInteractive} recorded marker(s) are interactive -- a record is not the viewer's to toggle`);
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
