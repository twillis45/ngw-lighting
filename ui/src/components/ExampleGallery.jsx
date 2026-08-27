import { useEffect, useState } from 'react';

/**
 * Public accuracy gallery.
 *
 * This is the "prove it works before signup" surface, so it shows the engine's
 * read against human-verified ground truth on every entry -- misses included.
 * It reports the strict number (exact matches) alongside the broad one; a
 * buyer-facing accuracy claim that quotes only the generous figure is a lie of
 * omission, and the two are far apart on this corpus.
 */
export default function ExampleGallery({ onUploadClick }) {
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

  // Say nothing rather than show an empty proof surface.
  if (failed || !data || !data.entries?.length) return null;

  const { scored, hits, exact, entries } = data;

  return (
    <div className="hp-section hp-gallery" data-testid="example-gallery">
      <h2 className="hp-section__title">Every read, scored against the truth</h2>
      <p className="hp-section__sub">
        {scored > 0 ? (
          <>
            <strong>{exact} of {scored}</strong> matched the expected pattern exactly;{' '}
            <strong>{hits} of {scored}</strong> fell within the accepted range.
            Misses are shown too.
          </>
        ) : 'Reference reads are being regenerated.'}
      </p>

      <div className="hp-gallery__scroll">
        {entries.map(item => {
          const v = item.verdict || {};
          const state = v.match == null ? 'none' : v.exact ? 'exact' : v.match ? 'near' : 'miss';
          return (
            <button
              key={item.id}
              type="button"
              className="hp-gallery__item"
              onClick={onUploadClick}
              data-testid={`gallery-item-${item.id}`}
            >
              <img
                className="hp-gallery__thumb"
                src={item.thumbnail_url}
                alt={`Reference photo — expected ${v.expected || 'unknown'} lighting`}
                loading="lazy"
              />
              <div className="hp-gallery__label">{v.expected || item.pattern}</div>
              <div className={`hp-gallery__verdict hp-gallery__verdict--${state}`}>
                {state === 'exact' && 'exact match'}
                {state === 'near' && `read ${v.read}`}
                {state === 'miss' && `missed — read ${v.read}`}
                {state === 'none' && 'no read'}
              </div>
            </button>
          );
        })}
      </div>

      <p className="hp-gallery__foot">Tap any photo to analyze one of your own.</p>
    </div>
  );
}
