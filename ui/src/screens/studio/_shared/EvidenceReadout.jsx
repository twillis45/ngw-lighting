/**
 * EvidenceReadout — what the engine saw, instead of how sure it says it is.
 *
 * Shown in place of a confidence grade below the one band that measured as
 * separable. See lightingEvidence.js for the numbers; in short, reads labelled
 * "Uncertain" were right 83% of the time and reads labelled "Tentative" 100%,
 * so the grade was teaching photographers to ignore it.
 *
 * A catchlight at 10 o'clock is checkable against the photo in a glance. A
 * percentage is not checkable at all.
 */
import { steel } from '../../../theme/studioMatte';

const FONT_SMOOTH = {
  WebkitFontSmoothing: 'antialiased',
  MozOsxFontSmoothing: 'grayscale',
  textRendering: 'geometricPrecision',
};

export default function EvidenceReadout({ evidence, compact = false }) {
  if (!evidence) return null;
  const { observations = [], limits = [], disagreements = [], runnerUp = null, coverage = null } = evidence;
  if (observations.length === 0 && limits.length === 0 && disagreements.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 7 : 9, marginTop: 6 }}>
      {observations.length > 0 && (
        <>
          <span style={{
            fontSize: 9, fontWeight: 600, letterSpacing: '1.1px',
            textTransform: 'uppercase', color: steel(0.46), ...FONT_SMOOTH,
          }}>What the engine saw</span>

          {observations.map(o => (
            <div key={o.label} style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
              <span style={{
                flex: '0 0 78px', fontSize: 10, fontWeight: 500, letterSpacing: '0.3px',
                color: steel(0.52), ...FONT_SMOOTH,
              }}>{o.label}</span>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                <span style={{
                  fontSize: compact ? 12 : 13, fontWeight: 600, letterSpacing: '0.1px',
                  color: 'rgba(245,247,250,0.90)', ...FONT_SMOOTH,
                }}>{o.value}</span>
                {o.detail && (
                  <span style={{
                    fontSize: 11, fontWeight: 500, color: steel(0.60),
                    lineHeight: 1.35, ...FONT_SMOOTH,
                  }}>{o.detail}</span>
                )}
              </span>
            </div>
          ))}
        </>
      )}

      {/* Where the engine was unsure. It records this and always has; it
          simply was not shown. A read a photographer can weigh beats one
          they have to take on faith. */}
      {(disagreements.length > 0 || runnerUp) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 2 }}>
          <span style={{
            fontSize: 9, fontWeight: 600, letterSpacing: '1.1px',
            textTransform: 'uppercase', color: steel(0.40), ...FONT_SMOOTH,
          }}>Where it was not certain</span>
          {disagreements.map(d => (
            <span key={d} style={{
              fontSize: 11, fontWeight: 500, color: steel(0.62),
              lineHeight: 1.4, ...FONT_SMOOTH,
            }}>Two readings disagreed — {d}</span>
          ))}
          {runnerUp && (
            <span style={{
              fontSize: 11, fontWeight: 500, color: steel(0.58),
              lineHeight: 1.4, ...FONT_SMOOTH,
            }}>Next most credible: {runnerUp.pattern}</span>
          )}
          {coverage && coverage.weak && coverage.weak.length > 0 && (
            <span style={{
              fontSize: 11, fontWeight: 500, color: steel(0.52),
              lineHeight: 1.4, ...FONT_SMOOTH,
            }}>
              {coverage.available} of {coverage.total} signals usable
            </span>
          )}
        </div>
      )}

      {limits.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 2 }}>
          <span style={{
            fontSize: 9, fontWeight: 600, letterSpacing: '1.1px',
            textTransform: 'uppercase', color: steel(0.40), ...FONT_SMOOTH,
          }}>What limited this read</span>
          {limits.map(l => (
            <span key={l} style={{
              fontSize: 11, fontWeight: 500, color: steel(0.58),
              lineHeight: 1.4, ...FONT_SMOOTH,
            }}>{l}</span>
          ))}
        </div>
      )}
    </div>
  );
}
