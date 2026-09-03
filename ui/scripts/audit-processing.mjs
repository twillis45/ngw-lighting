// Processing audit screenshot capture.
// Writes to review-artifacts/2026-05-05-processing-audit/.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, '..', '..', 'review-artifacts', '2026-05-05-processing-audit');

const SIZES = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'desktop-1728', width: 1728, height: 1050 },
  { name: 'mobile-390',   width: 390,  height: 844 },
];

const URLS = [
  // Live app — likely auth gate but capture anyway.
  { tag: 'live-home',                url: 'http://localhost:5174/' },
  // Day1 deep link with ?day1_screen=processing (DEV-only path).
  { tag: 'live-day1-processing',     url: 'http://localhost:5174/?day1=1&day1_screen=processing' },
  // Static legacy LoadingScreen mock + Studio Matte ProcessingScreen mock.
  { tag: 'mock-loading-legacy',      url: `file://${path.join(OUT, 'mock-loading-legacy.html')}` },
  { tag: 'mock-processing-studio',   url: `file://${path.join(OUT, 'mock-processing-studio.html')}` },
];

const browser = await chromium.launch();
for (const url of URLS) {
  for (const size of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    try {
      await page.goto(url.url, { waitUntil: 'networkidle', timeout: 15000 });
    } catch (e) {
      console.log(`! ${url.tag} @ ${size.name}: ${e.message}`);
    }
    // Let any animation breathe
    await page.waitForTimeout(900);
    const file = path.join(OUT, `${url.tag}--${size.name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`+ ${file}`);
    await ctx.close();
  }
}
await browser.close();
console.log('\nDone.');
