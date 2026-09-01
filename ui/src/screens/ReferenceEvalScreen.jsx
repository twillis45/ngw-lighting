import { useState, useEffect, useRef } from 'react';
import { useAppState, useDispatch } from '../context/AppContext';
import { uploadReferenceImage } from '../api';
import { RECIPES } from '../data/recipes';
import DiagramCard from '../cards/DiagramCard';
import CollapsibleCard from '../cards/CollapsibleCard';
import ZoomOverlay from '../cards/ZoomOverlay';
import usePaywall, { resolveUserEmail } from '../hooks/usePaywall';
import { trackEvent } from '../data/analytics';
import { getToken } from '../data/authApi';
import { resolveError } from '../lib/errors';

// ── Pattern / mood option lists — fallback defaults (overridden by /api/config) ─

const DEFAULT_MOOD_OPTIONS = [
  { value: 'beauty',    label: 'Beauty' },
  { value: 'cinematic', label: 'Cinematic' },
  { value: 'corporate', label: 'Corporate' },
  { value: 'editorial', label: 'Editorial' },
  { value: 'natural',   label: 'Natural' },
  { value: 'high_key',  label: 'High Key' },
  { value: 'low_key',   label: 'Low Key' },
];

const DEFAULT_PATTERN_OPTIONS = [
  'rembrandt', 'loop', 'butterfly', 'split', 'flat', 'broad',
  'short', 'rim', 'ring_light', 'high_key', 'low_key',
  'projected', 'silhouette_key', 'natural_window', 'dramatic_key', 'three_point',
];

const DEFAULT_ISSUE_TYPES = [
  { value: 'wrong_pattern',  label: 'Pattern identified incorrectly' },
  { value: 'wrong_mood',     label: 'Mood / style misidentified' },
  { value: 'no_face',        label: 'No face found / wrong subject' },
  { value: 'confidence_low', label: 'Confidence feels too high' },
  { value: 'other',          label: 'Something else is off' },
];

// ── Admin: submit ground truth ─────────────────────────────────────────────

// Option constants for correction form
const SHADOW_PATTERN_OPTIONS = ['rembrandt', 'loop', 'butterfly', 'split', 'flat', 'broad', 'short', 'rim', 'ring_light', 'high_key', 'low_key', 'projected', 'silhouette_key', 'natural_window', 'dramatic_key', 'three_point', 'beauty_dish', 'unknown'];
const SOURCE_DIRECTION_OPTIONS = ['left-45', 'right-45', 'left-90', 'right-90', 'front', 'top', 'left-135', 'right-135', 'overhead', 'unknown'];
const FILL_OPTIONS = ['none', 'subtle', 'moderate', 'strong', 'unknown'];
const LIGHTING_FAMILY_OPTIONS = ['broad', 'narrow', 'front', 'split', 'rim', 'high_key', 'low_key', 'beauty', 'unknown'];
const ENVIRONMENT_OPTIONS = ['studio', 'indoor_natural', 'outdoor', 'mixed', 'unknown'];

async function submitGroundTruth({
  imagePath, expectedPattern, expectedMood, lightCount, notes,
  shadowPattern, sourceDirection, fillPresence, lightingFamily, environment,
}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const corrections = {};
  if (lightCount)      corrections.light_count      = parseInt(lightCount, 10);
  if (shadowPattern)   corrections.shadow_pattern   = shadowPattern;
  if (sourceDirection) corrections.source_direction = sourceDirection;
  if (fillPresence)    corrections.fill_presence    = fillPresence;
  if (lightingFamily)  corrections.lighting_family  = lightingFamily;
  if (environment)     corrections.environment      = environment;
  if (notes)           corrections.notes            = notes;
  const res = await fetch('/api/admin/image-labels', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      image_path: imagePath,
      expected_pattern: expectedPattern || null,
      expected_mood: expectedMood || null,
      corrections: Object.keys(corrections).length ? corrections : null,
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Server error (${res.status})`);
  }
  return res.json();
}

// ── Admin correction panel ─────────────────────────────────────────────────

function AdminCorrectionPanel({ analysis, imagePath, onNavigateLab, patternOptions = DEFAULT_PATTERN_OPTIONS, moodOptions = DEFAULT_MOOD_OPTIONS }) {
  const [open, setOpen]         = useState(false);
  const [pattern, setPattern]   = useState('');
  const [mood, setMood]         = useState('');
  const [lightCount, setLightCount] = useState('');
  const [shadowPattern, setShadowPattern]   = useState('');
  const [sourceDirection, setSourceDirection] = useState('');
  const [fillPresence, setFillPresence]     = useState('');
  const [lightingFamily, setLightingFamily] = useState('');
  const [environment, setEnvironment]       = useState('');
  const [notes, setNotes]       = useState('');
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [err, setErr]           = useState(null);

  const rs          = analysis?.description?.referenceAnalysis?.recreation_setup;
  const lightingRead = analysis?.description?.referenceAnalysis?.image_read || {};

  // Pre-fill fields with detected values when panel opens
  useEffect(() => {
    if (open) {
      setPattern(analysis?.classification?.lightingPattern || '');
      setMood(analysis?.classification?.mood || '');
      setLightCount(rs?.light_count != null ? String(rs.light_count) : '');
      setShadowPattern(lightingRead.shadow_pattern || '');
      setSourceDirection(lightingRead.source_direction || '');
      setFillPresence(lightingRead.fill_presence || '');
      setLightingFamily(lightingRead.lighting_family || '');
      setEnvironment(lightingRead.environment || analysis?.description?.referenceAnalysis?.environment || '');
      setNotes('');
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave() {
    setSaving(true);
    setErr(null);
    try {
      await submitGroundTruth({
        imagePath,
        expectedPattern: pattern,
        expectedMood: mood,
        lightCount,
        shadowPattern,
        sourceDirection,
        fillPresence,
        lightingFamily,
        environment,
        notes,
      });
      setSaved(true);
      setOpen(false);
      trackEvent('admin_ground_truth_saved', { imagePath, pattern, mood });
      setTimeout(() => setSaved(false), 4000);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ref-correction ref-correction--admin" style={{ display: 'contents' }}>
      <button
        className="btn btn--ghost btn--sm"
        onClick={() => setOpen(v => !v)}
        type="button"
        style={{ fontSize: 11 }}
      >
        {saved ? '✓ Saved' : open ? 'Cancel' : 'Correct'}
      </button>

      {open && (
        <div className="ref-correction__form" style={{ width: '100%', flexBasis: '100%' }}>
          <p className="ref-correction__form-intro">
            Override detected values. Pre-filled from current analysis — change only what's wrong.
          </p>

          {/* Pattern + Mood */}
          <div className="ref-correction__fields">
            <div className="ref-correction__field">
              <label className="ref-correction__label">Pattern</label>
              <select className="ref-correction__select" value={pattern} onChange={e => setPattern(e.target.value)}>
                <option value="">— as detected —</option>
                {patternOptions.map(p => (
                  <option key={p} value={p}>{p.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <div className="ref-correction__field">
              <label className="ref-correction__label">Mood</label>
              <select className="ref-correction__select" value={mood} onChange={e => setMood(e.target.value)}>
                <option value="">— as detected —</option>
                {moodOptions.map(m => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Light Count */}
          <div className="ref-correction__field" style={{ maxWidth: 140 }}>
            <label className="ref-correction__label">Light Count</label>
            <input
              type="number"
              className="ref-correction__select"
              min="1" max="8"
              placeholder="# of lights"
              value={lightCount}
              onChange={e => setLightCount(e.target.value)}
            />
          </div>

          {/* Shadow Pattern + Source Direction */}
          <div className="ref-correction__fields">
            <div className="ref-correction__field">
              <label className="ref-correction__label">Shadow Pattern</label>
              <select className="ref-correction__select" value={shadowPattern} onChange={e => setShadowPattern(e.target.value)}>
                <option value="">— as detected —</option>
                {SHADOW_PATTERN_OPTIONS.map(o => (
                  <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <div className="ref-correction__field">
              <label className="ref-correction__label">Source Direction</label>
              <select className="ref-correction__select" value={sourceDirection} onChange={e => setSourceDirection(e.target.value)}>
                <option value="">— as detected —</option>
                {SOURCE_DIRECTION_OPTIONS.map(o => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Fill Presence + Lighting Family + Environment */}
          <div className="ref-correction__fields">
            <div className="ref-correction__field">
              <label className="ref-correction__label">Fill Presence</label>
              <select className="ref-correction__select" value={fillPresence} onChange={e => setFillPresence(e.target.value)}>
                <option value="">— as detected —</option>
                {FILL_OPTIONS.map(o => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
            <div className="ref-correction__field">
              <label className="ref-correction__label">Lighting Family</label>
              <select className="ref-correction__select" value={lightingFamily} onChange={e => setLightingFamily(e.target.value)}>
                <option value="">— as detected —</option>
                {LIGHTING_FAMILY_OPTIONS.map(o => (
                  <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <div className="ref-correction__field">
              <label className="ref-correction__label">Environment</label>
              <select className="ref-correction__select" value={environment} onChange={e => setEnvironment(e.target.value)}>
                <option value="">— as detected —</option>
                {ENVIRONMENT_OPTIONS.map(o => (
                  <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="ref-correction__field">
            <label className="ref-correction__label">Notes (optional)</label>
            <textarea
              className="ref-correction__textarea"
              rows={2}
              placeholder="What's wrong? What should the correct answer be?"
              value={notes}
              onChange={e => setNotes(e.target.value)}
            />
          </div>
          {err && <p className="ref-correction__error">{err}</p>}
          <button
            className="btn btn--primary btn--sm"
            onClick={handleSave}
            disabled={saving}
            style={{ alignSelf: 'flex-start' }}
          >
            {saving ? 'Saving…' : 'Save Ground Truth'}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Admin: all VLM data + narrative ────────────────────────────────────────

function AdminVLMPanel({ analysis }) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  if (!analysis) return null;

  const cls = analysis.classification || {};
  const li  = analysis.lightingIntelligence || null;
  const pex = li?.perceptionExplanation || null;
  const candidates = analysis.patternCandidates || null;
  const refA = analysis.description?.referenceAnalysis || null;

  // Format 0–1 score as percentage string
  function pct(v) {
    if (v == null) return '—';
    const n = v > 1 ? v : v * 100;
    return `${Math.round(n)}%`;
  }

  const rowStyle = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    padding: '5px 0', borderBottom: '1px solid var(--color-border-subtle)',
    gap: 8, fontSize: 'var(--text-xs)',
  };
  const labelStyle = { color: 'var(--color-text-dim)', flexShrink: 0, minWidth: 130 };
  const valueStyle = { color: 'var(--color-text)', textAlign: 'right', wordBreak: 'break-word' };

  function Section({ title, children }) {
    return (
      <div style={{ marginBottom: 'var(--space-sm)' }}>
        <div style={{
          fontSize: 'var(--text-xs)', fontWeight: 'var(--weight-semibold)',
          color: 'var(--color-accent)', textTransform: 'uppercase',
          letterSpacing: 'var(--tracking-widest)', marginBottom: 6, marginTop: 10,
        }}>{title}</div>
        {children}
      </div>
    );
  }

  function DataRow({ label, value }) {
    if (value == null || value === '' || value === 'unknown') return null;
    const display = Array.isArray(value) ? value.join(', ') : String(value);
    return (
      <div style={rowStyle}>
        <span style={labelStyle}>{label}</span>
        <span style={valueStyle}>{display}</span>
      </div>
    );
  }

  return (
    <div className="ref-correction ref-correction--admin" style={{ display: 'contents' }}>
      <button
        className="btn btn--ghost btn--sm"
        onClick={() => setOpen(v => !v)}
        type="button"
        style={{ fontSize: 11 }}
      >
        {open ? 'Hide VLM' : 'VLM'}
      </button>

      {open && (
        <div style={{ marginTop: 'var(--space-sm)', fontSize: 'var(--text-xs)', width: '100%', flexBasis: '100%' }}>

          {/* ── Classification scores ── */}
          <Section title="Classification">
            <DataRow label="Pattern"         value={cls.lightingPattern} />
            <DataRow label="Reliability"     value={pct(cls.reliabilityScore ?? cls.confidence)} />
            <DataRow label="Confidence raw"  value={cls.confidence != null ? String(cls.confidence) : null} />
            <DataRow label="Pattern source"  value={cls.patternSource} />
            <DataRow label="Mood detected"   value={cls.mood} />
            <DataRow label="Light count"     value={cls.lightCount != null ? String(cls.lightCount) : null} />
            <DataRow label="Color temp"      value={cls.colorTemperature} />
            <DataRow label="CCT (K)"         value={cls.colorTemperatureKelvin != null ? `${cls.colorTemperatureKelvin} K` : null} />
            <DataRow label="Suggested recipe" value={cls.suggestedRecipe} />
          </Section>

          {/* ── Pattern candidates ── */}
          {candidates && Object.keys(candidates).length > 0 && (
            <Section title="Pattern Candidates">
              {Object.entries(candidates).map(([classifier, result]) => {
                if (!result) return null;
                const pat   = result.pattern || result.lightingPattern || '—';
                const score = result.score ?? result.confidence ?? result.reliabilityScore;
                const src   = result.source || result.patternSource || null;
                return (
                  <div key={classifier} style={rowStyle}>
                    <span style={labelStyle}>{classifier}</span>
                    <span style={valueStyle}>
                      {pat}
                      {score != null && <span style={{ color: 'var(--color-text-dim)', marginLeft: 4 }}>· {pct(score)}</span>}
                      {src && <span style={{ color: 'var(--color-text-dim)', marginLeft: 4 }}>· {src}</span>}
                    </span>
                  </div>
                );
              })}
            </Section>
          )}

          {/* ── Lighting Intelligence ── */}
          {li && (
            <Section title="Lighting Intelligence">
              <DataRow label="Light count"      value={li.lightCount != null ? String(li.lightCount) : null} />
              <DataRow label="Key position"     value={li.keyPosition} />
              <DataRow label="Detected modifier" value={li.detectedModifier} />
              <DataRow label="Ambient"          value={li.ambientConditions || li.detectedEnvironment} />
              <DataRow label="Detected CCT"     value={li.detectedCCT != null ? `${li.detectedCCT} K` : null} />
            </Section>
          )}

          {/* ── Perception Explanation ── */}
          {pex && (
            <Section title="Perception Explanation">
              {pex.patternReasoning && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ ...labelStyle, marginBottom: 4 }}>Pattern reasoning</div>
                  <div style={{ color: 'var(--color-text)', lineHeight: 1.55 }}>{pex.patternReasoning}</div>
                </div>
              )}
              {pex.supportingSignals?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ ...labelStyle, color: 'var(--color-success)', marginBottom: 4 }}>
                    Supporting signals ({pex.supportingSignals.length})
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.6 }}>
                    {pex.supportingSignals.map((s, i) => (
                      <li key={i} style={{ color: 'var(--color-text-secondary)', marginBottom: 2 }}>
                        {typeof s === 'string' ? s : (s.signal || s.description || JSON.stringify(s))}
                        {s.weight != null && <span style={{ color: 'var(--color-text-dim)', marginLeft: 4 }}>({s.weight})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {pex.contradictingSignals?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ ...labelStyle, color: 'var(--color-error)', marginBottom: 4 }}>
                    Contradicting signals ({pex.contradictingSignals.length})
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.6 }}>
                    {pex.contradictingSignals.map((s, i) => (
                      <li key={i} style={{ color: 'var(--color-text-secondary)', marginBottom: 2 }}>
                        {typeof s === 'string' ? s : (s.signal || s.description || JSON.stringify(s))}
                        {s.weight != null && <span style={{ color: 'var(--color-text-dim)', marginLeft: 4 }}>({s.weight})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          )}

          {/* ── VLM Narrative fields not shown in user cards ── */}
          {refA?.image_read && (() => {
            const ir = refA.image_read;
            const extraFields = [
              ['Full narrative',        ir.narrative],
              ['Aspect ratio',          ir.aspect_ratio],
              ['Tonal contrast',        ir.tonal_contrast],
              ['Skin tone confidence',  ir.skin_tone_confidence != null ? pct(ir.skin_tone_confidence) : null],
              ['Subject count',         ir.subject_count != null ? String(ir.subject_count) : null],
              ['Mixed skin tones',      ir.skin_tone_mixed != null ? String(ir.skin_tone_mixed) : null],
              ['All skin tones',        ir.subject_skin_tones],
              ['Shot type',             ir.shot_type],
              ['Camera angle',          ir.camera_angle],
              ['Depth of field',        ir.depth_of_field],
              ['BG texture',            ir.background_texture],
              ['Catchlight shape',      ir.catchlight_shape],
              ['Catchlight position',   ir.catchlight_position],
              ['Shadow hardness',       ir.shadow_hardness],
              ['Shadow direction',      ir.shadow_direction],
              ['Specular highlights',   ir.specular_highlights],
            ].filter(([, v]) => v != null && v !== '' && v !== 'unknown' && !(Array.isArray(v) && v.length === 0));
            if (!extraFields.length) return null;
            return (
              <Section title="Image Read — Extended">
                {extraFields.map(([label, value]) => (
                  <DataRow key={label} label={label} value={value} />
                ))}
              </Section>
            );
          })()}

          {refA?.lighting_read && (() => {
            const lr = refA.lighting_read;
            const extraFields = [
              ['Contrast ratio',         lr.contrast_ratio],
              ['Exposure latitude',      lr.exposure_latitude],
              ['Catchlight quality',     lr.catchlight_quality],
              ['Background separation', lr.background_separation],
              ['Gradient falloff',       lr.gradient_falloff],
              ['Modifier confidence',    lr.modifier_confidence != null ? pct(lr.modifier_confidence) : null],
              ['Modifier hint',          lr.modifier_hint],
              ['Setup confidence',       lr.setup_confidence != null ? pct(lr.setup_confidence) : null],
              ['Environment type',       lr.environment_type],
              ['Ambient contribution',   lr.ambient_contribution],
            ].filter(([, v]) => v != null && v !== '' && v !== 'unknown');
            if (!extraFields.length) return null;
            return (
              <Section title="Lighting Read — Extended">
                {extraFields.map(([label, value]) => (
                  <DataRow key={label} label={label} value={value} />
                ))}
              </Section>
            );
          })()}

          {/* ── Raw JSON dump ── */}
          <Section title="Raw Analysis JSON">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setRawOpen(v => !v)}
              style={{ fontSize: 'var(--text-xs)', marginBottom: rawOpen ? 8 : 0 }}
            >
              {rawOpen ? 'Hide raw JSON' : 'Show raw JSON'}
            </button>
            {rawOpen && (
              <pre style={{
                fontSize: 10, lineHeight: 1.4, overflowX: 'auto',
                background: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: 10, margin: 0,
                color: 'var(--color-text-secondary)',
                maxHeight: 400, overflowY: 'auto',
              }}>
                {JSON.stringify(analysis, null, 2)}
              </pre>
            )}
          </Section>

        </div>
      )}
    </div>
  );
}

// ── User: report analysis issue ────────────────────────────────────────────

function UserCorrectionForm({ analysis, referenceImagePreview, issueTypes = DEFAULT_ISSUE_TYPES, moodOptions = DEFAULT_MOOD_OPTIONS }) {
  const [open, setOpen]     = useState(false);
  const [issue, setIssue]   = useState('');
  const [note, setNote]     = useState('');
  const [sent, setSent]     = useState(false);

  function handleSubmit() {
    trackEvent('ANALYSIS_CORRECTION_SUBMITTED', {
      issue_type: issue,
      note: note.trim() || null,
      detected_pattern: analysis?.classification?.lightingPattern,
      detected_mood: analysis?.classification?.mood,
      confidence: analysis?.classification?.confidence,
    });
    setSent(true);
    setOpen(false);
  }

  if (sent) {
    return (
      <div className="ref-correction ref-correction--thanks">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)"
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        Thanks — we'll use this to improve the engine.
      </div>
    );
  }

  return (
    <div className="ref-correction ref-correction--user">
      {!open ? (
        <button
          className="ref-correction__trigger"
          onClick={() => setOpen(true)}
          type="button"
        >
          Analysis doesn't look right?
        </button>
      ) : (
        <div className="ref-correction__form">
          <p className="ref-correction__form-intro">What seems off?</p>
          <div className="ref-correction__radio-group">
            {issueTypes.map(it => (
              <label key={it.value} className="ref-correction__radio-row">
                <input
                  type="radio"
                  name="issue_type"
                  value={it.value}
                  checked={issue === it.value}
                  onChange={() => setIssue(it.value)}
                />
                <span>{it.label}</span>
              </label>
            ))}
          </div>
          <textarea
            className="ref-correction__textarea"
            rows={2}
            placeholder="Anything to add? (optional)"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
          <div className="ref-correction__form-actions">
            <button
              className="btn btn--primary btn--sm"
              onClick={handleSubmit}
              disabled={!issue}
            >
              Submit
            </button>
            <button
              className="btn btn--ghost btn--sm"
              onClick={() => setOpen(false)}
              type="button"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Inline analysis overlay (replaces old ScanStatus) ──────────────────────

const SCAN_PHASES = [
  'Reading the light\u2026',
  'Analyzing shadows\u2026',
  'Resolving shadow geometry\u2026',
  'Identifying setup\u2026',
  'Evaluating mood\u2026',
  'Checking modifiers\u2026',
];
const SCAN_INTERVAL = 3200;

/** Image overlay — thick scan line + animated slashes at bottom.  Absolutely positioned over the image. */
function ScanImageOverlay() {
  return (
    <div className="ref-analyze-overlay">
      <div className="ref-analyze-overlay__scan-line" />
      <div className="ref-analyze-overlay__scan-accent" />
      <div className="ref-analyze-overlay__fade" />
      <div className="ref-analyze-overlay__slashes" aria-hidden="true">
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} className="ref-analyze-overlay__slash" style={{ '--slash-i': i }} />
        ))}
      </div>
    </div>
  );
}

/** Status bar — rotating phase text + progress dots.  Normal flow element below the image. */
function ScanStatusBar() {
  const [phaseIdx, setPhaseIdx] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setPhaseIdx(i => (i + 1) % SCAN_PHASES.length), SCAN_INTERVAL);
    return () => clearInterval(id);
  }, []);
  const activeDot = phaseIdx < 2 ? 0 : phaseIdx < 4 ? 1 : 2;
  return (
    <div className="ref-analyze-status-bar">
      <p className="ref-analyze-status-bar__text" key={phaseIdx}>{SCAN_PHASES[phaseIdx]}</p>
      <div className="ref-analyze-status-bar__dots">
        {[0, 1, 2].map(i => (
          <span key={i} className={`ref-analyze-status-bar__dot${i === activeDot ? ' ref-analyze-status-bar__dot--active' : ''}`} />
        ))}
      </div>
    </div>
  );
}

// ── Color palette panel with harmony picker ─────────────────────────────────

const HARMONY_LABELS = {
  analogous:          'Analogous',
  complementary:      'Complementary',
  split_complementary:'Split-Complementary',
  triadic:            'Triadic',
  monochromatic:      'Monochromatic',
  neutral:            'Neutral',
  warm_cool_split:    'Warm/Cool Split',
};

function ColorPalettePanel({ colorPalette: cp }) {
  // Build the full list of available harmony views
  const primary = cp.color_harmony && cp.color_harmony !== 'unknown' ? cp.color_harmony : null;
  const alts = (cp.alternate_harmonies || []).filter(h => h && h !== 'unknown' && h !== primary);
  // warm_cool_split is also surfaced separately — include it if not already
  if (cp.warm_cool_split && !alts.includes('warm_cool_split') && primary !== 'warm_cool_split') {
    alts.push('warm_cool_split');
  }
  const allHarmonies = [primary, ...alts].filter(Boolean);
  const [activeHarmony, setActiveHarmony] = useState(primary || null);

  return (
    <div style={{ marginTop: 'var(--space-md)', borderTop: '1px solid var(--border-faint)', paddingTop: 'var(--space-md)' }}>

      {/* palette_character — headline */}
      {cp.palette_character && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="ref-analysis__label">Color Character</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text)', lineHeight: 1.5 }}>
            {cp.palette_character}
          </div>
        </div>
      )}

      {/* Harmony picker — pill tabs, shown when more than one harmony exists */}
      {allHarmonies.length > 0 && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="ref-analysis__label" style={{ marginBottom: 5 }}>Color Harmony</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {allHarmonies.map(h => (
              <button
                key={h}
                type="button"
                onClick={() => setActiveHarmony(h)}
                style={{
                  fontSize: 'var(--text-xs)',
                  fontWeight: activeHarmony === h ? 'var(--weight-semibold)' : 'var(--weight-normal)',
                  color: activeHarmony === h ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  background: activeHarmony === h ? 'var(--color-accent-subtle)' : 'var(--color-surface-elevated)',
                  border: activeHarmony === h ? '1px solid var(--color-accent-subtle-border)' : '1px solid transparent',
                  borderRadius: 'var(--radius-full)',
                  padding: '3px 10px',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  textTransform: 'capitalize',
                  letterSpacing: 'var(--tracking-wide)',
                }}
              >
                {HARMONY_LABELS[h] || h.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Light temperature */}
      {(cp.color_temperature_key || cp.color_temperature_shadows) && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="ref-analysis__label">Light Temperature</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text)', lineHeight: 1.5 }}>
            {cp.color_temperature_key && <span>Key: {cp.color_temperature_key}</span>}
            {cp.color_temperature_key && cp.color_temperature_shadows && (
              <span style={{ color: 'var(--color-text-dim)', margin: '0 6px' }}>·</span>
            )}
            {cp.color_temperature_shadows && <span>Shadows: {cp.color_temperature_shadows}</span>}
          </div>
        </div>
      )}

      {/* Color swatches — harmony-aware colored chips */}
      {(() => {
        // harmony_swatches holds hex codes for the selected harmony;
        // fall back to all dominant_colors (paired with their hexes) when no harmony data.
        const harmonyHexes = activeHarmony && cp.harmony_swatches?.[activeHarmony]?.length > 0
          ? cp.harmony_swatches[activeHarmony]
          : null;

        // Build display list: [{hex, name}] — hex may be absent for old analysis results
        let chips;
        if (harmonyHexes) {
          // Harmony mode: hexes only (from harmony_swatches). Find matching name if possible.
          const hexToName = {};
          (cp.dominant_color_hexes || []).forEach((h, i) => {
            if (h) hexToName[h.toLowerCase()] = cp.dominant_colors?.[i] || '';
          });
          chips = harmonyHexes.map(h => ({ hex: h, name: hexToName[h?.toLowerCase()] || '' }));
        } else {
          // All-colors mode: pair dominant_colors with their hexes
          chips = (cp.dominant_colors || []).map((name, i) => ({
            hex: cp.dominant_color_hexes?.[i] || null,
            name,
          }));
        }

        if (!chips.length) return null;

        const label = harmonyHexes
          ? `${HARMONY_LABELS[activeHarmony] || activeHarmony.replace(/_/g, ' ')} Palette`
          : 'Detected Colors';

        return (
          <div style={{ marginBottom: 'var(--space-sm)' }}>
            <div className="ref-analysis__label">{label}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {chips.map(({ hex, name }, i) => (
                <div key={i} title={name || hex || ''} style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                }}>
                  {hex ? (
                    <div style={{
                      width: 36, height: 36,
                      borderRadius: 'var(--radius-sm)',
                      background: hex,
                      border: '1px solid rgba(255,255,255,0.10)',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.35)',
                    }} />
                  ) : (
                    /* fallback: text chip when no hex available */
                    <span style={{
                      fontSize: 'var(--text-xs)',
                      color: 'var(--color-text-secondary)',
                      background: 'var(--color-surface-elevated)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '2px 7px',
                    }}>{name}</span>
                  )}
                  {hex && name && (
                    <span style={{
                      fontSize: 10, color: 'var(--color-text-dim)',
                      maxWidth: 40, textAlign: 'center',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      lineHeight: 1.2,
                    }}>{name}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Contrasting pairs — filter to active harmony when possible */}
      {cp.contrasting_pairs?.length > 0 && (() => {
        // Each pair string typically includes a parenthetical harmony label.
        // e.g. "red vs teal (complementary)" — try to match active harmony.
        const harmonyKey = activeHarmony || '';
        const harmonyWords = harmonyKey.replace(/_/g, ' ').toLowerCase().split(' ');
        const filtered = cp.contrasting_pairs.filter(p =>
          harmonyWords.some(w => w.length > 3 && p.toLowerCase().includes(w))
        );
        // If filter yields results, show only those; otherwise fall back to all
        const pairs = filtered.length > 0 ? filtered : cp.contrasting_pairs;
        return (
          <div style={{ marginBottom: 'var(--space-sm)' }}>
            <div className="ref-analysis__label">Color Contrasts</div>
            {pairs.map((pair, i) => (
              <div key={i} style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
                {pair}
              </div>
            ))}
          </div>
        );
      })()}

      {/* Color grading notes */}
      {cp.color_grading_notes && (
        <div>
          <div className="ref-analysis__label">Grading Notes</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            {cp.color_grading_notes}
          </div>
        </div>
      )}
    </div>
  );
}


function ColorPalettePanelToggle({ colorPalette }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 'var(--space-sm)' }}>
      <button
        type="button"
        className="ref-analysis__expand-btn"
        onClick={() => setOpen(v => !v)}
        style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--color-text-dim)',
          background: 'none',
          border: 'none',
          padding: '4px 0',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <svg
          width="11" height="11" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
        {open ? 'Hide color analysis' : 'See detailed color analysis'}
      </button>
      {open && <ColorPalettePanel colorPalette={colorPalette} />}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Main screen
// ═══════════════════════════════════════════════════════════════════════════

export default function ReferenceEvalScreen() {
  const { referenceImage, referenceImages, user, refAnalysis: storedAnalysis } = useAppState();
  const dispatch = useDispatch();
  const userEmail = resolveUserEmail(user);
  const { isAdmin } = usePaywall(userEmail);

  const imageCount = referenceImages?.length || (referenceImage ? 1 : 0);

  const fileRef = useRef(null);
  const [loading, setLoading]           = useState(true);
  const [analysis, setAnalysis]         = useState(null);
  const [perImageAnalysis, setPerImageAnalysis] = useState({}); // { index: analysis }
  const [selectedMood, setSelectedMood] = useState(null);
  const [error, setError]               = useState(null);  // { code, message, hint }
  function makeError(err) {
    return resolveError(err, 'REF_EVAL');
  }
  const [zoomSrc, setZoomSrc]           = useState(null);

  // Option lists from the truth layer — fall back to defaults while loading
  const [moodOptions, setMoodOptions]       = useState(DEFAULT_MOOD_OPTIONS);
  const [patternOptions, setPatternOptions] = useState(DEFAULT_PATTERN_OPTIONS);
  const [issueTypes, setIssueTypes]         = useState(DEFAULT_ISSUE_TYPES);

  // Derived label map — stays in sync with API-fetched moodOptions
  const moodLabels = Object.fromEntries(moodOptions.map(m => [m.value, m.label]));

  useEffect(() => {
    fetch('/api/config', { headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {} })
      .then(r => r.ok ? r.json() : null)
      .then(cfg => {
        if (!cfg) return;
        if (cfg.moods?.length)       setMoodOptions(cfg.moods);
        if (cfg.patterns?.length)    setPatternOptions(cfg.patterns);
        if (cfg.issue_types?.length) setIssueTypes(cfg.issue_types);
      })
      .catch(() => { /* keep defaults on network error */ });
  }, []);

  useEffect(() => {
    const images = referenceImages?.length ? referenceImages : (referenceImage ? [referenceImage] : []);
    if (!images[0]?.file) {
      // Dev demo: if analysis was pre-populated in app state (e.g. via ?_demo=ref_eval),
      // hydrate local state from it instead of showing the error banner.
      if (storedAnalysis) {
        // ?_loading=1 freezes the loading overlay for visual testing
        const holdLoading = new URLSearchParams(window.location.search).get('_loading') === '1';
        if (!holdLoading) {
          setAnalysis(storedAnalysis);
          setSelectedMood(storedAnalysis?.classification?.mood || null);
          setLoading(false);
        }
      } else {
        setLoading(false);
        setError(makeError('No image selected'));
      }
      return;
    }

    let cancelled = false;
    // Upload all images in parallel, use first result as primary analysis
    Promise.all(
      images.map((img, idx) =>
        uploadReferenceImage(img.file)
          .then(result => ({ idx, img, result, error: null }))
          .catch(err => ({ idx, img, result: null, error: err }))
      )
    ).then(outcomes => {
      if (cancelled) return;
      // Update referenceImages with server paths
      const updated = images.map((img, idx) => {
        const outcome = outcomes[idx];
        return outcome.result
          ? { ...img, serverPath: outcome.result.path }
          : img;
      });
      dispatch({ type: 'SET_REFERENCE_IMAGES', payload: updated });

      // Collect per-image analyses
      const analyses = {};
      outcomes.forEach(o => {
        if (o.result?.analysis) analyses[o.idx] = o.result.analysis;
      });
      setPerImageAnalysis(analyses);

      // Use the first successful analysis as the primary
      const primary = outcomes.find(o => o.result?.analysis);
      if (primary) {
        setAnalysis(primary.result.analysis);
        setSelectedMood(primary.result.analysis?.classification?.mood || null);
        dispatch({ type: 'SET_REF_ANALYSIS', analysis: primary.result.analysis });
      } else {
        // All uploads failed — surface the real error (e.g. 401, network) not a generic string
        const firstErr = outcomes.find(o => o.error)?.error;
        setError(makeError(firstErr || 'Could not analyze image'));
      }

      // Multi-image consensus removed 2026-08-31 — it called a route that does
      // not exist, swallowed the 404, and stored the result somewhere nothing
      // read. See ui/src/api.js.
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleConfirm() {
    const mood = selectedMood || 'natural';
    // Store the full analysis so SetupWizard can pass it to shoot-match as priorAnalysis.
    // This prevents shoot-match from re-deriving a different pattern and ensures
    // the setup recommendation is anchored to what ref eval detected.
    if (analysis) {
      dispatch({ type: 'SET_REF_ANALYSIS', analysis });
    }
    dispatch({ type: 'SET_MOOD', mood });
    dispatch({ type: 'SET_INTENT', intent: 'ref_match' });
  }

  function handleBack() {
    dispatch({ type: 'CLEAR_REFERENCE_IMAGE' });
    dispatch({ type: 'GO_BACK' });
  }

  function handleAnalyzeAnother() {
    fileRef.current?.click();
  }

  async function handleFileSelected(e) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    if (fileRef.current) fileRef.current.value = '';

    const newImages = files.map(f => ({
      file: f,
      preview: URL.createObjectURL(f),
      serverPath: null,
    }));
    // Append to existing images
    const allImages = [...(referenceImages || []), ...newImages];
    dispatch({ type: 'SET_REFERENCE_IMAGES', payload: allImages });
    setError(null);
    setLoading(true);

    // Upload only the newly added images
    try {
      const outcomes = await Promise.all(
        newImages.map((img, i) =>
          uploadReferenceImage(img.file)
            .then(result => ({ img, result, error: null }))
            .catch(err => ({ img, result: null, error: err }))
        )
      );

      // Update images with server paths
      const updatedNew = newImages.map((img, i) => {
        const outcome = outcomes[i];
        return outcome.result ? { ...img, serverPath: outcome.result.path } : img;
      });
      const merged = [...(referenceImages || []), ...updatedNew];
      dispatch({ type: 'SET_REFERENCE_IMAGES', payload: merged });

      // Collect per-image analyses for new images
      const newAnalyses = { ...perImageAnalysis };
      const baseIdx = (referenceImages || []).length;
      outcomes.forEach((o, i) => {
        if (o.result?.analysis) newAnalyses[baseIdx + i] = o.result.analysis;
      });
      setPerImageAnalysis(newAnalyses);

      // Use the first new successful analysis as primary (if we didn't have one)
      const firstSuccess = outcomes.find(o => o.result?.analysis);
      if (firstSuccess) {
        setAnalysis(firstSuccess.result.analysis);
        setSelectedMood(firstSuccess.result.analysis?.classification?.mood || null);
      } else if (outcomes.every(o => o.error)) {
        const firstErr = outcomes.find(o => o.error)?.error;
        setError(makeError(firstErr || 'Could not analyze image'));
      }

    } catch (err) {
      setError(makeError(err));
    } finally {
      setLoading(false);
    }
  }

  function handleOpenLab() {
    if (referenceImage) {
      dispatch({ type: 'SET_LAB_PENDING_IMAGE', payload: referenceImage });
    }
    dispatch({ type: 'NAVIGATE', screen: 'lab' });
  }

  const classification    = analysis?.classification;
  const palette           = analysis?.palette?.overall || [];
  const recipeName        = classification?.suggestedRecipe
    ? RECIPES.find(r => r.id === classification.suggestedRecipe)?.name
    : null;
  const subject           = analysis?.description?.subject;
  const refAnalysis       = analysis?.description?.referenceAnalysis;
  const imageRead         = refAnalysis?.image_read;
  const lightingRead      = refAnalysis?.lighting_read;
  const recreationSetup   = refAnalysis?.recreation_setup;
  const colorPalette      = refAnalysis?.color_palette;

  // ── Signal quality helper ──────────────────────────────────────────────
  function getSignals() {
    const signals = [];
    const sr = analysis?.signalReliability;

    // Face detection
    const faceOk = sr?.faceDetected;
    signals.push({
      label: 'Face detection',
      detail: faceOk ? (imageRead?.subject_count > 1 ? `${imageRead.subject_count} subjects` : 'Detected') : 'Not detected',
      status: faceOk ? 'green' : 'amber',
    });

    // Catchlight quality
    const catchOk = sr?.catchlightDetected;
    signals.push({
      label: 'Catchlight quality',
      detail: catchOk
        ? (lightingRead?.catchlight_shape || lightingRead?.catchlight_position || 'Present')
        : 'Not found',
      status: catchOk ? 'green' : 'amber',
    });

    // Shadow edge
    const shadowQuality = sr?.shadowEdgeQuality || 'unknown';
    const shadowOk = shadowQuality === 'strong' || shadowQuality === 'moderate';
    signals.push({
      label: 'Shadow edge',
      detail: shadowQuality !== 'unknown' ? shadowQuality.charAt(0).toUpperCase() + shadowQuality.slice(1) : 'Unknown',
      status: shadowOk ? 'green' : 'amber',
    });

    // Background separation
    const bgRel = imageRead?.background_relationship;
    const bgOk = bgRel && bgRel !== 'unknown' && !bgRel.toLowerCase().includes('merged') && !bgRel.toLowerCase().includes('cluttered');
    signals.push({
      label: 'Background separation',
      detail: bgRel && bgRel !== 'unknown' ? bgRel : 'Unknown',
      status: bgOk ? 'green' : 'amber',
    });

    return signals;
  }

  // ── Confidence as integer 0-100 ─────────────────────────────────────────
  const confidencePct = classification?.confidence != null
    ? Math.round(classification.confidence > 1 ? classification.confidence : classification.confidence * 100)
    : null;

  return (
    <div className="screen ref-eval-screen">

      {/* Hidden file input for "Analyze another" */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

      {/* 1. Title bar */}
      <h2 className="screen-heading" style={{ padding: '0 var(--space-md)', marginBottom: 'var(--space-xs)' }}>Reference Analysis</h2>

      {/* Zoom overlay */}
      {zoomSrc && <ZoomOverlay src={zoomSrc} alt="Reference photo" onClose={() => setZoomSrc(null)} />}

      {/* 2. Reference Photo Zone */}
      {referenceImage?.preview && (
        <div className="ref-photo-zone">
          <div className={`ref-eval__preview-wrap${loading ? ' ref-eval__preview-wrap--analyzing' : ''}`}>
            <div
              className={`ref-eval__img-stage${loading ? ' ref-eval__img-stage--analyzing' : ''}`}
              onClick={() => !loading && setZoomSrc(referenceImage.preview)}
            >
              <img
                src={referenceImage.preview}
                alt="Reference photo"
                className={`ref-eval__img${loading ? ' ref-eval__img--blurred' : ''}`}
              />
              {loading && <ScanImageOverlay />}
            </div>
            {loading && <ScanStatusBar />}
          </div>
          {!loading && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' }}>
              <span style={{ fontSize: 9, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Reference Photo</span>
              <span
                style={{ fontSize: 9, fontWeight: 500, color: 'var(--color-text-secondary)', cursor: 'pointer' }}
                onClick={() => setZoomSrc(referenceImage.preview)}
              >
                Tap to expand
              </span>
            </div>
          )}
        </div>
      )}

      {/* Narrative — first sentence visible, rest collapsible */}
      {!loading && imageRead?.narrative && (() => {
        const firstSentence = imageRead.narrative.split(/(?<=[.!?])\s+/)[0] || imageRead.narrative;
        const rest = imageRead.narrative.slice(firstSentence.length).trim();
        const hasMore = rest || imageRead.pose_notes || imageRead.scene_description;
        return (
          <div className="ref-hero__narrative">
            <span className="ref-hero__narrative-label">At a Glance</span>
            <p className="ref-hero__narrative-text">{firstSentence}</p>
            {hasMore && (
              <details style={{ marginTop: 0 }}>
                <summary style={{ cursor: 'pointer', listStyle: 'none', fontSize: 11, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span>More</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                </summary>
                {rest && <p className="ref-hero__narrative-text" style={{ marginTop: 4 }}>{rest}</p>}
                {(imageRead.pose_notes || imageRead.scene_description) && (
                  <p className="ref-hero__narrative-action">
                    {imageRead.pose_notes || imageRead.scene_description}
                  </p>
                )}
              </details>
            )}
          </div>
        );
      })()}

      {/* Error state */}
      {error && !loading && (
        <div className="ref-eval__error">
          <p className="ref-eval__error-msg">{error.message || String(error)}</p>
          {error.code && (
            <p className="ref-eval__error-code">{error.code}</p>
          )}
          {error.hint && (
            <p className="ref-eval__error-hint">{error.hint}</p>
          )}
          <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'center', flexWrap: 'wrap', marginTop: 'var(--space-sm)' }}>
            <button className="btn btn--ghost btn--sm" onClick={handleAnalyzeAnother}>
              Try another image
            </button>
            <button className="btn btn--primary btn--sm" onClick={handleBack}>
              Go Back
            </button>
          </div>
        </div>
      )}

      {/* Analysis results */}
      {!loading && analysis && (
        <>
          {/* 3. Detected Pattern Card */}
          <div className="ref-pattern-card" style={{ padding: '0 var(--space-md)' }}>
            <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Detected Pattern</div>
            <div style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 12,
              padding: 16,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <span style={{ fontSize: 18, fontWeight: 600, color: 'var(--color-text)' }}>
                  {classification?.patternLabel || classification?.lightingPattern?.replace(/[-_]/g, ' ') || 'Unknown'}
                </span>
                {confidencePct != null && (
                  <span style={{
                    background: '#2e4033',
                    color: '#48ba88',
                    fontSize: 10,
                    fontWeight: 500,
                    padding: '3px 8px',
                    borderRadius: 'var(--radius-sm)',
                  }}>
                    {confidencePct}%
                  </span>
                )}
              </div>
              {confidencePct != null && (
                <div style={{ height: 6, borderRadius: 'var(--radius-xs)', background: 'var(--color-surface-elevated)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${confidencePct}%`, background: '#48ba88', borderRadius: 'var(--radius-xs)', transition: 'width 0.4s ease' }} />
                </div>
              )}
            </div>
          </div>

          {/* 4. Lighting Blueprint Grid */}
          <div className="ref-blueprint" style={{ padding: '0 var(--space-md)', marginTop: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Lighting Blueprint</div>
            <div style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 12,
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gridTemplateRows: '1fr 1fr',
              overflow: 'hidden',
            }}>
              {/* Top-left: Key Light Position */}
              <div style={{ padding: 14, borderRight: '1px solid var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', marginBottom: 4 }}>Key Light Position</div>
                {(() => {
                  const raw = lightingRead?.source_direction?.replace(/[-_]/g, ' ') || 'Unknown';
                  // Split "camera left, ~45 degrees, elevated" into main + sub
                  const parts = raw.split(',').map(s => s.trim());
                  const main = parts.length > 1 ? `${parts[1]} ${parts[0]}` : parts[0];
                  const sub = parts.length > 2 ? parts.slice(2).join(', ') : null;
                  return (
                    <>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', lineHeight: 1.3 }}>{main}</div>
                      {sub && <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 2 }}>{sub}</div>}
                    </>
                  );
                })()}
              </div>
              {/* Top-right: Light Ratio */}
              <div style={{ padding: 14, borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', marginBottom: 4 }}>Light Ratio</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', lineHeight: 1.3 }}>
                  {recreationSetup?.key_to_fill_ratio || (lightingRead?.light_count ? `${lightingRead.light_count}:1` : 'N/A')}
                </div>
                <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 2 }}>key : fill</div>
              </div>
              {/* Bottom-left: Subject Distance */}
              <div style={{ padding: 14, borderRight: '1px solid var(--color-border)' }}>
                <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', marginBottom: 4 }}>Subject Distance</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', lineHeight: 1.3 }}>
                  {recreationSetup?.subject_distance || '~6 ft'}
                </div>
                <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 2 }}>estimated</div>
              </div>
              {/* Bottom-right: Modifier */}
              <div style={{ padding: 14 }}>
                <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', marginBottom: 4 }}>Modifier</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', lineHeight: 1.3 }}>
                  {(() => {
                    const raw = lightingRead?.modifier_suggestion || recreationSetup?.modifier_suggestion || 'Unknown';
                    // Extract just the modifier name (e.g. "softbox" from "medium to large softbox (2x3...)")
                    const short = raw.split(/[,(]| or /)[0].trim().replace(/[-_]/g, ' ');
                    return short.charAt(0).toUpperCase() + short.slice(1);
                  })()}
                </div>
                {(recreationSetup?.modifier_size || lightingRead?.modifier_hint) && (
                  <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginTop: 2 }}>
                    {recreationSetup?.modifier_size || lightingRead?.modifier_hint || ''}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* 5. Signal Analysis Card */}
          <div className="ref-signals" style={{ padding: '0 var(--space-md)', marginTop: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Signal Analysis</div>
            <div style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 12,
              overflow: 'hidden',
            }}>
              {getSignals().map((sig, i, arr) => (
                <div
                  key={sig.label}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '12px 14px',
                    borderBottom: i < arr.length - 1 ? '1px solid var(--color-border)' : 'none',
                  }}
                >
                  <span style={{ fontSize: 13, color: 'var(--color-text)', flex: 1 }}>{sig.label}</span>
                  <span style={{ fontSize: 10, color: 'var(--color-text-secondary)', marginRight: 10, textAlign: 'right', maxWidth: '45%' }}>{sig.detail}</span>
                  <span style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: sig.status === 'green' ? '#48ba88' : '#d4a843',
                    flexShrink: 0,
                  }} />
                </div>
              ))}
            </div>
          </div>

          {/* 6. CTA Button */}
          <div className="ref-cta" style={{ padding: 'var(--space-md)', paddingBottom: 'calc(var(--space-xl) + env(safe-area-inset-bottom, 0px))' }}>
            <button
              onClick={handleConfirm}
              style={{
                width: '100%',
                height: 40,
                borderRadius: 'var(--radius-sm)',
                background: '#c8a96e',
                color: '#0a0b0e',
                fontSize: 14,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Use as Recipe Template
            </button>
          </div>

          {/* 7. Admin zone — consolidated */}
          {isAdmin && (
            <div style={{ marginTop: 16, background: '#12110f', borderRadius: 10, border: '1px solid #f59e3433', overflow: 'hidden' }}>
              <div style={{
                background: '#1f170a',
                padding: '6px 14px',
                fontSize: 10,
                fontWeight: 600,
                color: '#f59e34',
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                borderBottom: '1px solid #f59e3433',
              }}>
                Admin
              </div>

              <div style={{ display: 'flex', gap: 6, padding: '10px 12px', flexWrap: 'wrap' }}>
                <button className="btn btn--ghost btn--sm" onClick={handleOpenLab} style={{ fontSize: 11 }}>Lab</button>
                <button className="btn btn--ghost btn--sm" onClick={handleAnalyzeAnother} style={{ fontSize: 11 }}>Re-analyze</button>
                <AdminCorrectionPanel
                  analysis={analysis}
                  imagePath={referenceImage?.serverPath || referenceImage?.file?.name || ''}
                  onNavigateLab={handleOpenLab}
                  patternOptions={patternOptions}
                  moodOptions={moodOptions}
                />
                <AdminVLMPanel analysis={analysis} />
              </div>
            </div>
          )}
        </>
      )}

      {/* Fallback: no analysis, not loading */}
      {!loading && !analysis && !error && (
        <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--color-text-dim)' }}>
          <p>Could not analyze this image. You can still continue.</p>
          <div className="ref-cta" style={{ marginTop: 'var(--space-md)' }}>
            <button
              onClick={handleConfirm}
              style={{
                width: '100%',
                height: 40,
                borderRadius: 'var(--radius-sm)',
                background: '#c8a96e',
                color: '#0a0b0e',
                fontSize: 14,
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Use as Recipe Template
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
