/**
 * AccuracyScreen — the public proof surface, in the Studio shell.
 *
 * Gate Zero G0.3: a photographer must be able to audit the accuracy claim
 * before signing up. This shows every scored reference read against
 * human-verified ground truth, MISSES INCLUDED, with the strict number next
 * to the generous one.
 *
 * The two figures are far apart on this corpus. Publishing only the generous
 * one would be a lie of omission, so both are always shown with the
 * denominator, read live from /api/gallery rather than hardcoded.
 *
 * 2026-08-29 — TWO corrections, both measured:
 *
 * 1. `reflector_fill` is an approved entry, a genuine MISS, and was absent
 *    from this page only because its thumbnail file did not exist — the
 *    source is a PNG named image.jpg, so the JPEG writer had failed on it
 *    silently. A missing file was dropping a failure out of the denominator
 *    and lifting the published within-range rate from 90% to 93%. Thumbnail
 *    generated; the miss is now shown, which is this page's whole premise.
 *
 * 2. The reference set is SMALL. Median long edge 711px, range 249-3888, and
 *    only 1 of 34 images is above the 2048px threshold at which the pipeline
 *    stops upscaling internally. A photographer's camera file is several
 *    thousand pixels, so it takes a different code path — one this corpus
 *    barely exercises. That limit is now stated on the page. Do not remove it
 *    without measuring accuracy on camera-sized files first.
 */
import { useEffect, useState } from 'react';
import { steel } from '../../../theme/studioMatte';
import prettify from '../../../utils/prettify';

const FONT_SMOOTH = {
  WebkitFontSmoothing: 'antialiased',
  MozOsxFontSmoothing: 'grayscale',
  textRendering: 'geometricPrecision',
};

const VERDICT = {
  exact: { label: 'exact',  color: 'rgba(140,218,160,0.85)' },
  near:  { label: 'within', color: steel(0.62) },
  miss:  { label: 'missed', color: 'rgba(217,119,87,0.85)' },
  none:  { label: 'no read', color: steel(0.40) },
};

function verdictOf(v) {
  if (!v || v.match == null) return 'none';
  if (v.exact) return 'exact';
  return v.match ? 'near' : 'miss';
}

export default function AccuracyScreen({ onBack }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    fetch('/api/gallery')
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then(d => { if (live) setData(d); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  const entries = data?.entries || [];

  return (
    <div style={{
      position: 'relative', width: '100%', minHeight: '100%',
      background: '#000', color: 'rgba(245,247,250,0.95)',
      // Respect the notch/status bar — verified on iPhone 17 Pro Max,
      // where a flat 22px top pad put '← Back' under the clock.
      // Clear the notch/status bar. env() alone returns 0 without
      // viewport-fit=cover, so max() guarantees a floor either way --
      // verified on iPhone 17 Pro Max, where 22px put '← Back' under the clock.
      padding: 'max(env(safe-area-inset-top, 0px) + 22px, 68px) 20px max(env(safe-area-inset-bottom, 0px) + 40px, 56px)',
      overflowY: 'auto', ...FONT_SMOOTH,
    }} data-testid="accuracy-screen">
      <button
        type="button"
        onClick={onBack}
        data-testid="accuracy-back"
        style={{
          background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          color: steel(0.55), fontSize: 13, fontWeight: 600, letterSpacing: '0.3px',
          marginBottom: 18, ...FONT_SMOOTH,
        }}
      >← Back</button>

      <h1 style={{
        fontSize: 26, fontWeight: 800, letterSpacing: '-0.5px', lineHeight: 1.12,
        margin: '0 0 8px', color: 'rgba(245,247,250,0.97)', ...FONT_SMOOTH,
      }}>Every read, scored</h1>

      {failed || !data ? (
        <p style={{ fontSize: 13.5, color: steel(0.55), margin: 0, lineHeight: 1.5 }}>
          {failed ? 'Reference reads are unavailable right now.' : 'Loading…'}
        </p>
      ) : (
        <>
          <p style={{ fontSize: 13.5, color: steel(0.68), margin: '0 0 4px', lineHeight: 1.55 }}>
            {/* Was "verified by hand". Claim ledger #4, UNPROVEN: 32 of 34
                entries carry photographer:"benchmark_verified" — a placeholder
                string, not a person — and source_type:"found_online". Nothing
                records who verified an entry, when, or how. The honest sentence
                is what we can show: the expected pattern is recorded, and every
                read is scored against it in the open. Restore the stronger
                wording only once per-entry provenance exists. */}
            Against a reference set with recorded expected patterns.
            <strong style={{ color: 'rgba(245,247,250,0.92)' }}> {data.exact} of {data.scored}</strong> matched
            the expected pattern exactly;
            <strong style={{ color: 'rgba(245,247,250,0.92)' }}> {data.hits} of {data.scored}</strong> fell
            within the accepted range.
          </p>
          <p style={{ fontSize: 11.5, color: steel(0.42), margin: '0 0 8px', lineHeight: 1.5 }}>
            Misses are shown. A proof page that hides its failures is not proof.
          </p>
          {/* The denominator is only half the claim. A reader is entitled to
              know what the reference set IS before deciding what the number
              means for their own files. Measured 2026-08-29: median long edge
              711px, range 249–3888, 1 of 34 above 2048px. */}
          <p style={{ fontSize: 11.5, color: steel(0.42), margin: '0 0 20px', lineHeight: 1.5 }}>
            These reference images are small — a median long edge of 711 pixels.
            Your camera files are several thousand, and we have not yet scored
            the engine on files that size. Read this as a floor, not a forecast.
          </p>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))',
            gap: 12,
          }} data-testid="accuracy-grid">
            {entries.map(e => {
              const state = verdictOf(e.verdict);
              const v = VERDICT[state];
              return (
                <div key={e.id} data-testid="accuracy-tile" style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  <img
                    src={e.thumbnail_url}
                    alt={`Reference — expected ${prettify(e.verdict?.expected, { title: true }) || 'unknown'} lighting`}
                    loading="lazy"
                    style={{
                      width: '100%', aspectRatio: '1 / 1', objectFit: 'cover',
                      display: 'block', background: '#0A0B0D',
                      border: `1px solid ${steel(0.14)}`,
                    }}
                  />
                  <span style={{
                    fontSize: 11, fontWeight: 600, color: 'rgba(245,247,250,0.88)',
                    lineHeight: 1.25, ...FONT_SMOOTH,
                  }}>{prettify(e.verdict?.expected || e.pattern, { title: true })}</span>
                  <span style={{
                    fontSize: 9.5, fontWeight: 600, letterSpacing: '0.6px',
                    textTransform: 'uppercase', color: v.color, ...FONT_SMOOTH,
                  }}>
                    {v.label}
                    {state === 'miss' && e.verdict?.read ? ` · read ${e.verdict.read}` : ''}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
