/**
 * HomeScreen — Studio Matte design
 * Pixel-exact match to Figma: YQgGd8KZyZoXzZwJV7p4b6 / Studio Matte Theme / Home (1336:2)
 * Three button states: idle (no image) → alive (image ready) → pressed (analyzing)
 * All colors and pixel positions from Figma Token Palette — Studio Matte
 */
import { Fragment, useRef, useState, useEffect, useCallback } from 'react';
import { tapHaptic, selectHaptic, successHaptic, dropHaptic, warnHaptic, longPressHaptic, grainHaptic } from '../../../utils/haptics';
import { analyzeClickSound, softClickSound, imageDropSound, powerOnSound, navSlideSound, panelToggleSound } from '../../../utils/sounds';
import { loadSettings } from '../../../data/settingsStore';
import { fetchImageFromUrl } from '../../../data/labApi';
import { trackEvent } from '../../../data/analytics';
import { useDeviceTilt, glassReflectionTransform } from '../../../utils/useDeviceTilt';
import useStableViewport from '../../../utils/useStableViewport';
import { steel, C as SM_C, FONT_SMOOTH, VIEWFINDER_INNER_SHADOW, GLASS_REFLECTION, LENS_VIGNETTE,
         PANEL_SHADOW, PANEL_BEVEL, CTA_BG, CTA_SHADOW, CTA_BEVEL, KEY_ACCENT, SCREEN_BG,
         NAV_GHOST, NAV_BTN, NAV_DOT, IDENTITY_BADGE, VF_DITHER_NOISE, DITHER_STYLE } from '../../../theme/studioMatte';
import MatteBackground from '../_shared/MatteBackground';
import ViewfinderHUD from '../_shared/ViewfinderHUD';
import ExifStrip from '../_shared/ExifStrip';

// ─── Figma-exported assets (downloaded to project, valid indefinitely) ─────────
import analyzeTrackIdle    from '../../../assets/day1/analyze-track-idle.svg';
import analyzeTrackAlive   from '../../../assets/day1/analyze-track-alive.svg';
import analyzeTrackPressed from '../../../assets/day1/analyze-track-pressed.svg';
import ellipseBg  from '../../../assets/day1/ellipse-bg.svg';

// ─── Design tokens — studioMatte.js is single source of truth ────────────────
// HomeScreen-specific C extensions (textPrimary slightly more transparent than panel screens)
const C = {
  ...SM_C,
  textPrimary: 'rgba(245,247,250,0.88)',
  border:      'rgba(167,173,183,0.06)',
  glassSheen:  'rgba(178,191,209,0.07)',
};

export default function HomeScreen({ onAnalyze, hasLastResult, onViewLastResult, user, onLogout, onSettings, onRecipes, onSavedSetups, onBuildWizard, onMyKit, onSessionLog, onLookLibrary, onClientBrief, onVideoCapture, lastAnalysisTime, onAccuracy}) {
  const [imageFile,    setImageFile]    = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isPressed,    setIsPressed]    = useState(false);
  const [lcdOn,        setLcdOn]        = useState(false);
  const [isDragOver,   setIsDragOver]   = useState(false);
  const [showPrompt,   setShowPrompt]   = useState(true);
  const [viewfinderShake, setViewfinderShake] = useState(false);
  const [isUrlFetching,  setIsUrlFetching]  = useState(false);
  const [urlLoadError,   setUrlLoadError]   = useState(null);
  // ── EXIF readout — real camera data from the loaded photo ──
  const [exifData,       setExifData]       = useState(null);
  // ── Load confirmation flash — brief ring flare when photo accepted ──
  const [loadFlash,      setLoadFlash]      = useState(false);
  // Live device tilt drives the glass reflection layer so the viewfinder
  // reads as a real lit instrument when the phone moves.
  const tilt = useDeviceTilt();
  // ── Stealth panel state ──
  const [profileOpen, setProfileOpen]   = useState(false);
  // settingsOpen removed — sound/haptic toggles are now inline bottom icons.
  // statusToast removed — toggles moved to Settings
  // homeBarFlash removed — sign-out belongs in profile panel, not a stealth gesture
  // ── Shared viewport geometry (stableVH, safeBottom, isDesktop) ──
  const { stableVH, safeBottom, isDesktop } = useStableViewport();
  // Daylight brightness boost — reads from settings. Adds a CSS
  // filter to the root container that lifts steel opacities ~15% so the
  // UI is readable on bright outdoor screens.
  const [daylightMode] = useState(() => {
    try { const s = loadSettings(); return !!s.daylightMode; } catch { return false; }
  });
  const fileRef = useRef(null);
  const cameraRef = useRef(null);
  const longPressRef = useRef(null);
  // wellLongPressRef removed — illumination well eliminated
  const wordmarkLPRef = useRef(null);
  // homeBarLPRef removed — dangerous stealth sign-out eliminated
  // bgLongPressRef + bgLpFired removed — background LP eliminated

  // Power-on sound on first mount
  useEffect(() => { powerOnSound(); }, []);

  // ── Pre-warm on mount ──────────────────────────────────────────────────────
  // Apple principle: the moment a user decides to act, the product should
  // already be ready. On mount we:
  //   1) Prefetch the sample Rembrandt image so "Try a sample" is instant.
  //   2) Prefetch the ProcessingScreen chunk so the post-tap nav has no delay.
  //   3) Kick a low-priority analyze warmup (OPTIONS) so the backend container
  //      is spun up before the user ever lands on Processing.
  // All three are best-effort — failures are silently swallowed.
  useEffect(() => {
    // 1. Sample image — browser will cache it for the loadSample fetch().
    try {
      const img = new Image();
      img.src = '/ghost-rembrandt.jpg';
    } catch { /* ignore */ }
    // 2. ProcessingScreen chunk — dynamic import triggers Vite prefetch.
    import('./ProcessingScreen.jsx').catch(() => {});
    // 3. Backend warmup — cheap OPTIONS preflight.
    try {
      fetch('/api/analyze', { method: 'OPTIONS' }).catch(() => {});
    } catch { /* ignore */ }
  }, []);

  // Go fullscreen on the first touch — hides browser chrome on Android Chrome.
  // iOS Safari doesn't support requestFullscreen; the call is silently ignored.
  // Mobile-only: desktop users don't expect fullscreen from a tap.
  useEffect(() => {
    const isMobile = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    if (!isMobile) return;
    const go = () => {
      const el = document.documentElement;
      const req = el.requestFullscreen || el.webkitRequestFullscreen;
      if (req) req.call(el).catch(() => {});
    };
    document.addEventListener('touchstart', go, { once: true, passive: true });
    return () => document.removeEventListener('touchstart', go);
  }, []);

  // Breath audio removed — the analyze button animates visually via the
  // btnBreath CSS @keyframes only. No synth, no loops, no autoplay.

  // Hide tap prompt when image loaded; no auto-hide timeout (prompt stays until photo lands)
  useEffect(() => {
    if (imageFile) { setShowPrompt(false); return; }
    setShowPrompt(true);
  }, [imageFile]);

  const hasImage    = !!imageFile;
  const [isLandscape, setIsLandscape] = useState(false);
  const buttonState = !hasImage ? 'idle' : isPressed ? 'pressed' : 'alive';

  const trackSrc = { idle: analyzeTrackIdle, alive: analyzeTrackAlive, pressed: analyzeTrackPressed }[buttonState];

  // ── Stealth: clear image via long-press on viewfinder ──
  const clearImage = useCallback(() => {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(null);
    setImagePreview(null);
    setExifData(null);
    setIsLandscape(false);
    setShowPrompt(true);
    navSlideSound();
    longPressHaptic();
  }, [imagePreview]);

  const startViewfinderPress = useCallback((clientY) => {
    longPressRef.current = setTimeout(() => {
      if (hasImage) clearImage();
      longPressRef.current = null;
    }, 500);
  }, [hasImage, clearImage]);

  const endViewfinderPress = useCallback(() => {
    if (longPressRef.current) { clearTimeout(longPressRef.current); longPressRef.current = null; }
  }, []);

  // Illuminate LCD on touch, dim after interaction
  const handleViewfinderTouch = useCallback(() => {
    setLcdOn(true);
  }, []);

  useEffect(() => {
    if (imageFile && lcdOn) {
      const timer = setTimeout(() => setLcdOn(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [imageFile, lcdOn]);

  // Well mute toggle + startWellPress/endWellPress removed — well eliminated.
  // Haptic on/off is accessible via profile panel → Settings → HAPTIC row.

  // ── Stealth: wordmark long-press → profile panel ──
  const startWordmarkPress = useCallback(() => {
    wordmarkLPRef.current = setTimeout(() => {
      setProfileOpen(v => !v);
      panelToggleSound();
      longPressHaptic();
      wordmarkLPRef.current = null;
    }, 600);
  }, []);
  const endWordmarkPress = useCallback(() => {
    if (wordmarkLPRef.current) { clearTimeout(wordmarkLPRef.current); wordmarkLPRef.current = null; }
  }, []);

  // Home bar stealth sign-out removed — dangerous, undiscoverable, no confirmation.
  // Sign-out is accessible via wordmark → profile panel → Sign Out button.

  // Sound / haptic / daylight toggles live in Settings screen.

  // Close panels on outside tap or action
  const closePanels = useCallback(() => {
    if (profileOpen) {
      setProfileOpen(false);
      softClickSound();
      return true;
    }
    return false;
  }, [profileOpen]);

  // Cleanup timers
  useEffect(() => {
    return () => {
      if (wordmarkLPRef.current) clearTimeout(wordmarkLPRef.current);
    };
  }, []);

  // Block pull-to-refresh / document bounce on Android Chrome.
  // Scoped to the root container (not document) so settings panel and future
  // scrollable content still work. React synthetic touchmove is passive so
  // preventDefault() is silently ignored — this imperative listener is the fix.
  const rootRef = useRef(null);
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const prevent = (e) => { if (e.cancelable) e.preventDefault(); };
    el.addEventListener('touchmove', prevent, { passive: false });
    return () => el.removeEventListener('touchmove', prevent);
  }, []);

  // ── File loading with error rejection ──
  const rejectFile = useCallback(() => {
    setViewfinderShake(true);
    warnHaptic();
    setTimeout(() => setViewfinderShake(false), 400);
  }, []);

  // ── EXIF extraction — reads real camera metadata from JPEG files ──
  // Lightweight: parses only the EXIF IFD0 + ExifSubIFD tags we need.
  // Falls back silently (null exifData) for PNGs, WebP, or stripped JPEGs.
  const extractExif = useCallback(async (file) => {
    try {
      const buf = await file.slice(0, 128 * 1024).arrayBuffer();
      const view = new DataView(buf);
      // JPEG SOI + APP1 marker check
      if (view.getUint16(0) !== 0xFFD8) return null;
      let offset = 2;
      while (offset < view.byteLength - 4) {
        const marker = view.getUint16(offset);
        if (marker === 0xFFE1) break; // APP1
        offset += 2 + view.getUint16(offset + 2);
      }
      if (view.getUint16(offset) !== 0xFFE1) return null;
      const tiffStart = offset + 10; // skip marker(2) + length(2) + "Exif\0\0"(6)
      const le = view.getUint16(tiffStart) === 0x4949; // little-endian?
      const g16 = (o) => view.getUint16(tiffStart + o, le);
      const g32 = (o) => view.getUint32(tiffStart + o, le);
      const gR = (o) => { const n = g32(o); const d = g32(o + 4); return d ? n / d : 0; };
      // Walk IFD0
      // Read ASCII string from TIFF data at a given offset + count
      const gStr = (off, cnt) => {
        const chars = [];
        for (let j = 0; j < cnt; j++) {
          const c = view.getUint8(tiffStart + off + j);
          if (c === 0) break;
          chars.push(String.fromCharCode(c));
        }
        return chars.join('').trim();
      };
      const readIFD = (ifdOff) => {
        const tags = {};
        const count = g16(ifdOff);
        for (let i = 0; i < count; i++) {
          const eo = ifdOff + 2 + i * 12;
          const tag = g16(eo);
          const type = g16(eo + 2);
          const cnt = g32(eo + 4);
          const valOff = (type === 5 || type === 10) ? g32(eo + 8) : eo + 8; // RATIONAL → offset
          tags[tag] = { type, cnt, valOff, raw: g32(eo + 8) };
        }
        return tags;
      };
      const ifd0 = readIFD(g32(4));
      // ExifSubIFD pointer = tag 0x8769
      const exifPtr = ifd0[0x8769]?.raw;
      const exif = exifPtr ? readIFD(exifPtr) : {};
      // Camera model — IFD0 tag 0x0110 (ASCII string)
      let model = null;
      const modelTag = ifd0[0x0110];
      if (modelTag && modelTag.type === 2 && modelTag.cnt > 0) {
        const strOff = modelTag.cnt > 4 ? modelTag.raw : (modelTag.valOff);
        model = gStr(strOff, Math.min(modelTag.cnt, 64));
      }
      // Extract values
      const fNumber = exif[0x829D] ? gR(exif[0x829D].valOff) : null;       // FNumber
      const exposure = exif[0x829A] ? gR(exif[0x829A].valOff) : null;       // ExposureTime
      const iso = exif[0x8827] ? exif[0x8827].raw : null;                    // ISOSpeedRatings
      const focalLen = exif[0x920A] ? gR(exif[0x920A].valOff) : null;       // FocalLength
      if (!fNumber && !exposure && !iso && !model) return null;
      return {
        model: model || null,
        aperture: fNumber ? `f/${fNumber % 1 === 0 ? fNumber.toFixed(0) : fNumber.toFixed(1)}` : null,
        shutter: exposure ? (exposure >= 1 ? `${exposure}"` : `1/${Math.round(1 / exposure)}`) : null,
        iso: iso ? `${iso}` : null,
        focalLength: focalLen ? `${Math.round(focalLen)}mm` : null,
      };
    } catch { return null; }
  }, []);

  const loadFile = useCallback((file) => {
    if (!file || !file.type.startsWith('image/')) { rejectFile(); return; }
    // Revoke previous blob URL before creating a new one (prevents memory leak)
    setImagePreview(prev => { if (prev) URL.revokeObjectURL(prev); return null; });
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
    imageDropSound();
    dropHaptic();
    setShowPrompt(false);
    // Extract EXIF in background — non-blocking
    extractExif(file).then(data => setExifData(data)).catch(() => setExifData(null));
    // Load confirmation flash — brief ring flare
    setLoadFlash(true);
    setTimeout(() => setLoadFlash(false), 600);
  }, [rejectFile, extractExif]);

  // Ref keeps loadFromUrl's closure stable across Fast Refresh re-mounts
  // without forming a useCallback circular dependency on loadFile.
  const loadFileRef = useRef(loadFile);
  loadFileRef.current = loadFile;

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    loadFile(file);
    e.target.value = '';
  };

  // ── Try-a-sample affordance ────────────────────────────────────────────────
  // Fetches the ghost Rembrandt that's already being used as the idle-state
  // credibility demo, wraps it as a real File, and feeds it into the normal
  // analyze pipeline. Gives cold visitors a zero-commitment path to see the
  // full flow before importing their own photo.
  const [sampleLoading, setSampleLoading] = useState(false);

  // First-tap teach — one-time hint for cold visitors. Shown above the button
  // on the very first session; dismisses permanently the first time the user
  // loads a photo. Persisted to localStorage so it never reappears.
  const [showTeach, setShowTeach] = useState(() => {
    try { return localStorage.getItem('ngw_home_teach_seen') !== '1'; } catch { return false; }
  });
  // ── Spotlight coach-marks — first-time user walkthrough ──────────────
  // Points at REAL UI elements, not abstract slides.
  // Step 0: Spotlight on viewfinder — "Load your photo here"
  // Step 1: Spotlight on analyze button — "Tap to analyze the lighting"
  // Step 2: Spotlight on sample CTA — "Or try our sample photo"
  // Each step has a cutout spotlight + positioned tooltip.
  const [teachStep, setTeachStep] = useState(0);  // 0-2 = steps, 3 = done
  const [teachVisible, setTeachVisible] = useState(() => {
    try { return localStorage.getItem('ngw_home_teach_seen') !== '1'; } catch { return false; }
  });
  // ── Auto-demo: complete walkthrough → load sample → analyze automatically ──
  // "Show me" = the app demonstrates itself. "Skip" = user explores on their own.
  // State machine via ref: 'idle' → 'pending' → 'loaded' → 'done'
  const autoDemoRef = useRef('idle');

  const advanceTeach = useCallback(() => {
    setTeachStep(prev => {
      if (prev >= 2) {
        setTeachVisible(false);
        autoDemoRef.current = 'pending'; // trigger auto-demo
        try { localStorage.setItem('ngw_home_teach_seen', '1'); } catch { /* ignore */ }
        return 3;
      }
      return prev + 1;
    });
    tapHaptic();
  }, []);
  const skipTeach = useCallback(() => {
    setTeachVisible(false);
    setTeachStep(3);
    try { localStorage.setItem('ngw_home_teach_seen', '1'); } catch { /* ignore */ }
    // Skip does NOT trigger auto-demo
    tapHaptic();
  }, []);

  // Auto-demo step 1: overlay dissolved → load the sample photo
  useEffect(() => {
    if (autoDemoRef.current === 'pending' && teachStep === 3 && !teachVisible) {
      autoDemoRef.current = 'loading';
      const t = setTimeout(async () => {
        setSampleLoading(true);
        try {
          const res = await fetch('/ghost-rembrandt.jpg');
          if (!res.ok) throw new Error('sample fetch failed');
          const blob = await res.blob();
          const file = new File([blob], 'sample-rembrandt.jpg', { type: blob.type || 'image/jpeg' });
          autoDemoRef.current = 'loaded';
          loadFileRef.current(file);
        } catch {
          autoDemoRef.current = 'idle';
        } finally {
          setSampleLoading(false);
        }
      }, 600);
      return () => clearTimeout(t);
    }
  }, [teachStep, teachVisible]);

  // Phase-2 teach: brief tooltip on the analyze button after MANUAL photo load
  // during first session (not triggered during auto-demo)
  const [showBtnTeach, setShowBtnTeach] = useState(false);
  useEffect(() => {
    if (imageFile && showTeach && autoDemoRef.current === 'idle') {
      setShowTeach(false);
      setShowBtnTeach(true);
      try { localStorage.setItem('ngw_home_teach_seen', '1'); } catch { /* ignore */ }
      const t = setTimeout(() => setShowBtnTeach(false), 4000);
      return () => clearTimeout(t);
    }
  }, [imageFile, showTeach]);
  const loadSample = useCallback(async () => {
    if (sampleLoading) return;
    setSampleLoading(true);
    try {
      const res = await fetch('/ghost-rembrandt.jpg');
      if (!res.ok) throw new Error('sample fetch failed');
      const blob = await res.blob();
      const file = new File([blob], 'sample-rembrandt.jpg', { type: blob.type || 'image/jpeg' });
      loadFileRef.current(file);
    } catch (_err) {
      rejectFile();
    } finally {
      setSampleLoading(false);
    }
  }, [sampleLoading, rejectFile]);

  // Load an image from a remote URL (Dropbox, Google Drive, etc) via server proxy
  const loadFromUrl = useCallback(async (url) => {
    setIsUrlFetching(true);
    try {
      const blob = await fetchImageFromUrl(url);
      const filename = url.split('/').pop().split('?')[0] || 'image.jpg';
      const file = new File([blob], filename, { type: blob.type || 'image/jpeg' });
      loadFileRef.current(file);
    } catch (err) {
      console.warn('[HomeScreen] URL fetch failed:', err.message);
      rejectFile();
      setUrlLoadError("Couldn't load that link — save the photo to your device and load it from there.");
      setTimeout(() => setUrlLoadError(null), 3000);
    } finally {
      setIsUrlFetching(false);
    }
  }, [rejectFile]);

  // Clipboard paste — Cmd+V image workaround for private cloud images
  useEffect(() => {
    const handlePaste = (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) loadFile(file);
          return;
        }
      }
    };
    document.addEventListener('paste', handlePaste);
    return () => document.removeEventListener('paste', handlePaste);
  }, [loadFile]);

  // Drag & drop handlers
  const handleDragOver = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }, []);
  const handleDragLeave = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(false); }, []);
  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); setIsDragOver(false);
    // Prefer an actual File (local drag)
    const file = e.dataTransfer?.files?.[0];
    if (file) { loadFile(file); return; }
    // Fall back to URL (Dropbox web, Google Drive, image drag from browser)
    const url = e.dataTransfer?.getData('text/uri-list') || e.dataTransfer?.getData('text/plain') || '';
    if (url.startsWith('http')) { loadFromUrl(url); return; }
    // Check for img src in dragged HTML (some cloud apps pass text/html)
    const html = e.dataTransfer?.getData('text/html') || '';
    const srcMatch = html.match(/src=["']([^"']+)["']/i);
    if (srcMatch?.[1]?.startsWith('http')) loadFromUrl(srcMatch[1]);
  }, [loadFile, loadFromUrl]);

  const [localAnalyzing, setLocalAnalyzing] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  // Auto-demo step 2: sample photo landed in VF → auto-analyze after pause
  // (Must be after localAnalyzing declaration to avoid temporal dead zone)
  useEffect(() => {
    if (autoDemoRef.current === 'loaded' && imageFile && !localAnalyzing) {
      autoDemoRef.current = 'done';
      const t = setTimeout(() => {
        if (imageFile && onAnalyze) {
          setLocalAnalyzing(true);
          analyzeClickSound(); successHaptic();
          onAnalyze(imageFile, imagePreview, exifData);
        }
      }, 1400); // let user see the photo in VF before analysis starts
      return () => clearTimeout(t);
    }
  }, [imageFile, localAnalyzing, onAnalyze, imagePreview, exifData]);

  // ── Analyze-button long-press → recall last result ──
  // One button, one mental model. Tap = analyze / load photo; long-press (600ms)
  // when a prior result exists = jump back to that result. Replaces the former
  // top-right illumination well recall affordance.
  const btnLPRef = useRef(null);
  const btnLPFired = useRef(false);
  const startBtnLongPress = useCallback(() => {
    btnLPFired.current = false;
    if (!hasLastResult) return;
    btnLPRef.current = setTimeout(() => {
      btnLPRef.current = null;
      btnLPFired.current = true;
      if (onViewLastResult) {
        longPressHaptic();
        softClickSound();
        onViewLastResult();
      }
    }, 600);
  }, [hasLastResult, onViewLastResult]);
  const endBtnLongPress = useCallback(() => {
    if (btnLPRef.current) { clearTimeout(btnLPRef.current); btnLPRef.current = null; }
  }, []);

  // ── Button face interaction — ring/track stay fixed; only the face surface compresses ──
  // Hover: face darkens + inset shadow deepens — the surface skin sinks under the cursor
  // Press: maximum inset + tiny Y sink — tactile confirmation the mechanism fired
  // Release: fast spring snap-back on box-shadow; transform returns on spring easing
  // No whole-button scale — the outer ring/track never move; only the face face interior responds
  // idle:    sits at well floor  (Y  0)
  // alive:   rises above well    (Y -3px) — image loaded, button clearly elevated and ready
  // pressed: sinks into well     (Y +2px) — mechanism fires
  const btnTransform = buttonState === 'pressed'
    ? 'translateX(-50%) translateY(2px)'
    : buttonState === 'alive'
      ? 'translateX(-50%) translateY(-3px)'
      : 'translateX(-50%)';
  const btnTransition = buttonState === 'pressed'
    ? 'transform 0.06s cubic-bezier(0.25,0.46,0.45,0.94), background 0.06s ease, box-shadow 0.06s ease'
    : 'transform 0.28s cubic-bezier(0.34,1.56,0.64,1), background 0.18s ease, box-shadow 0.22s ease';

  // Label-only transform — adds Y drop to sell the surface sinking; ring uses btnTransform (no Y)
  const lblTransform = buttonState === 'pressed'
    ? 'translateX(-50%) translateY(3px)'
    : isHovered
      ? 'translateX(-50%) translateY(2px)'
      : buttonState === 'alive'
        ? 'translateX(-50%) translateY(-3px)'
        : 'translateX(-50%)';

  const handleAnalyze = () => {
    if (localAnalyzing) return; // double-tap guard
    if (imageFile && onAnalyze) {
      setLocalAnalyzing(true); // flash green ring before screen transitions
      analyzeClickSound(); successHaptic();
      onAnalyze(imageFile, imagePreview, exifData);
    }
  };

  // Reset localAnalyzing if we return to HomeScreen without unmounting
  // (e.g. error path or back-nav). Also resets on new image load.
  useEffect(() => {
    if (!imageFile) setLocalAnalyzing(false);
  }, [imageFile]);

  const handleButtonPress = () => {
    startBtnLongPress();
    if (hasImage) { setIsPressed(true); tapHaptic(); }
  };
  const handleButtonRelease = () => {
    endBtnLongPress();
    setIsPressed(false);
  };
  const handleButtonClick = () => {
    // If a long-press already fired (recall), swallow the click so we don't
    // accidentally also trigger analyze/photo-picker.
    if (btnLPFired.current) { btnLPFired.current = false; return; }
    if (hasImage) handleAnalyze();
    else fileRef.current?.click();
  };

  // ── Illumination state machine ──────────────────────────────────────────────
  // Priority: error > analyzing > loading > ready > hasResult > idle
  const uiState = urlLoadError              ? 'error'
                : (isUrlFetching || localAnalyzing) ? 'loading'
                : hasImage                  ? 'ready'
                : hasLastResult ? 'hasResult'
                : 'idle';
  // Visual state — collapses hasResult→idle when no image loaded.
  // When image IS loaded and a prior result exists → promote to hasResult so
  // ring, well LED, and label all reflect the "Re-analyze" ready state (green).
  const effectiveUiState = (!hasImage && uiState === 'hasResult') ? 'idle'
    : (hasImage && hasLastResult && uiState === 'ready') ? 'hasResult'
    : uiState;

  // Semantic colour tokens per state — Figma Analyze Button spec (r,g,b,a)
  // Idle/Ready/Pressed: rgba(107,148,245) blue-indigo;
  // Analyzing: rgba(72,186,136) green (analyzing = green across all screens);
  // Result Ready: rgba(71,186,135) green; Error: rgba(215,55,55) red.
  const STATE_COLORS = {
    idle:      { r:107, g:148, b:245, a:0.38 },  // blue-indigo — visible at rest on OLED
    loading:   { r: 72, g:186, b:136, a:0.76 },  // green (Analyzing)
    ready:     { r:107, g:148, b:245, a:0.85 },  // blue-indigo — bright
    hasResult: { r: 71, g:186, b:135, a:0.80 },  // green
    error:     { r:215, g: 55, b: 55, a:0.76 },  // red
  };
  const SC = STATE_COLORS[effectiveUiState];
  const ringBase  = `rgba(${SC.r},${SC.g},${SC.b},${SC.a})`;
  const ringBright= `rgba(${SC.r},${SC.g},${SC.b},${Math.min(SC.a + 0.22, 0.98).toFixed(2)})`;
  const ringGlow  = `rgba(${SC.r},${SC.g},${SC.b},${(SC.a * 0.60).toFixed(2)})`;
  const ringDim   = `rgba(${SC.r},${SC.g},${SC.b},0.20)`;

  // Ring box-shadow — directional arc (lit top-left, shadow bottom-right) + state glow.
  // Ring is now always visible (faint glow even at idle) so the button reads as an
  // instrument with a perimeter indicator, not a flat circle.
  const ringBoxShadow = buttonState === 'pressed'
    ? `0 0 0 1.5px ${ringDim}, 0 0 4px ${ringDim}`
    : [
        `0 0 0 1.5px ${ringBase}`,
        `-1px -1px 0 0 ${ringBright}`,
        `1px 1px 0 0 rgba(0,0,0,0.32)`,
        // Glow always present — idle gets a faint halo, active states get stronger
        effectiveUiState === 'idle'
          ? `0 0 6px rgba(${SC.r},${SC.g},${SC.b},0.12)`
          : `0 0 ${effectiveUiState === 'error' ? 14 : 12}px ${ringGlow}`,
        // Second outer glow layer for depth
        effectiveUiState !== 'idle'
          ? `0 0 ${effectiveUiState === 'error' ? 24 : 20}px rgba(${SC.r},${SC.g},${SC.b},0.10)`
          : '',
      ].filter(Boolean).join(', ');

  // Ring animation — pulse for loading, urgent flash for error, single flare on load accept
  const ringAnimation = loadFlash                      ? 'ringLoadAccept 0.6s ease-out forwards'
                      : effectiveUiState === 'loading' ? 'ringPulse 2.0s linear infinite'
                      : effectiveUiState === 'error'   ? 'ringFlash 1.1s linear infinite'
                      : 'none';

  // Activity dot removed — "too many lights". DOT_BG + dotGlow cleared.

  // ANALYZE label — Figma spec: Inter Medium 10px, off-white at varying opacity, centered inside button
  // First session with no photo: "Load a Photo" — imperative, unambiguous.
  // Once a photo is loaded (or returning user): "See the Light" — brand phrase.
  // A working pro picks up the meter and reads again; "Re-analyze" is software
  // language, not how a photographer thinks.
  // Mobile button is 136px — keep labels short. Desktop is 168px — can fit more.
  const analyzeLabel = uiState === 'loading' ? 'Working…'
    : uiState === 'error'                     ? 'Retry'
    : (!hasImage && showTeach)                 ? (isDesktop ? 'Load a Photo' : 'Load Photo')
    : (isDesktop ? 'See the Light' : 'Read Light');
  const analyzeText = isPressed
    ? 'rgba(235,235,237,0.22)'  // deepest — face fully compressed, label in shadow
    : isHovered
      ? { idle:'rgba(235,235,237,0.26)', loading:'rgba(235,235,237,0.55)', ready:'rgba(235,235,237,0.45)', hasResult:'rgba(235,235,237,0.48)', error:'rgba(235,235,237,0.48)' }[effectiveUiState]
      : { idle:'rgba(245,247,250,0.88)', loading:'rgba(245,247,250,0.97)', ready:'rgba(245,247,250,0.97)', hasResult:'rgba(245,247,250,0.97)', error:'rgba(245,247,250,0.97)' }[effectiveUiState];
  // Idle: faint self-illumination glow so label reads as an engraved backlit label even at rest.
  const analyzeGlow = isPressed ? 'none'
    : isHovered ? 'none'
    : effectiveUiState === 'idle'
      ? '0 0 8px rgba(185,200,220,0.18)'
      : `0 0 8px rgba(${SC.r},${SC.g},${SC.b},${(SC.a * 0.45).toFixed(2)})`;

  // Desktop media query listener — now handled by useStableViewport hook.

  // ── Responsive button geometry ──
  // Apple principle: the primary action should outweigh everything else on
  // screen. Bumped ~13% on mobile so the button is unmistakably the heaviest
  // element after the VF. Desktop retains its larger size.
  const BTN_D   = isDesktop ? 168 : 136;
  const WELL_D  = isDesktop ? 180 : 146;
  const TRK_D   = isDesktop ? 174 : 142;
  // stableVH + safeBottom now provided by useStableViewport hook.
  // ── Bottom-anchored analyze button ─────────────────────────────────────────
  // The button bottom edge is always a protected distance above the OS safe area.
  // On short phones (iPhone SE ≤667px), compress the offset so the button stays
  // fully visible. On tall phones, use the full 72px breathing room.
  //
  // Protected safe zone (bottom-up):
  //   1. safeBottom (OS home indicator / gesture area)
  //   2. BTN_OFFSET_FROM_BOTTOM (breathing room — scales with viewport)
  //   3. BTN_D (button diameter)
  //   4. VF_GAP (16px breathing above button well)
  //
  // Everything above the button (viewfinder) is the flexible layer.
  const BTN_OFFSET_FROM_BOTTOM = isDesktop ? 72
    : stableVH <= 600 ? 28    // very short phones (iPhone SE landscape, small Android)
    : stableVH <= 700 ? 40    // iPhone SE portrait (667px), compact phones
    : stableVH <= 780 ? 52    // standard iPhone (812px with some chrome)
    : 64;                     // tall modern phones (iPhone 15 Pro Max, S25 Ultra)
  // Safety clamp: button center must leave at least BTN_D/2 + 8px visible at bottom.
  // This prevents clipping even if stableVH measurement is slightly off.
  const rawBtnCY = stableVH - safeBottom - BTN_OFFSET_FROM_BOTTOM - Math.round(BTN_D / 2);
  const maxBtnCY = stableVH - safeBottom - BTN_D / 2 - 8; // absolute floor: 8px above safe area
  const BTN_CY = Math.min(rawBtnCY, maxBtnCY);
  const BTN_TOP  = BTN_CY - BTN_D  / 2;

  // ── Fluid viewfinder — fills the space between header and button zone ─────
  // The VF stretches from below the header down to a comfortable gap above
  // the button well. The button is bottom-anchored and the VF takes whatever
  // height remains. No fixed pixel height.
  //
  // Priority order when vertical space is tight:
  //   1. Button safe zone (protected, never clipped)
  //   2. Viewfinder (flexible, shrinks to min 200px)
  //   3. Header (compresses on very short phones)
  //   4. VF_GAP (breathing room, compresses last)
  //
  // VF_TOP compresses on short phones to give the button more room.
  const VF_TOP = isDesktop ? 100
    : stableVH <= 600 ? 60    // very short
    : stableVH <= 700 ? 72    // iPhone SE
    : 88;                     // standard+
  const WELL_TOP = BTN_CY - WELL_D / 2;
  const VF_GAP = stableVH <= 700 ? 10 : 16;
  const VF_HEIGHT = Math.max(200, WELL_TOP - VF_GAP - VF_TOP);
  const VF_BOTTOM = VF_TOP + VF_HEIGHT;
  const TRK_TOP  = BTN_CY - TRK_D  / 2;
  const LBL_FONT = isDesktop ? 14 : 13;
  const LBL_TOP  = BTN_CY - 9;   // ≈ half of 19px line-height; same formula for both sizes

  // Background long-press LCD toggle removed — undiscoverable, valueless.
  // LCD backlight auto-activates on viewfinder touch and auto-dims after 2s.

  const handleBodyTap = (e) => {
    if (e.target === e.currentTarget) closePanels();
  };

  // ── Desktop layout ──────────────────────────────────────────────────────
  // Profoto / Hasselblad / Capture One design philosophy:
  //   - The photograph IS the interface — everything else recedes
  //   - Centered composition with generous breathing room
  //   - Instrument-grade typography and materials
  //   - Tools are organized in inset panels, not flat lists
  //   - The primary action dominates the viewport
  //
  // Layout: centered single-column with max-width constraint.
  // The VF is a contained, elevated panel (not edge-to-edge void).
  // Below it: centered CTA + tools in a horizontal strip.

  // ── Desktop overlay — Studio Matte instrument panel (5 levels deep) ─────
  // Level 1: Centered composition with proper visual hierarchy
  // Level 2: Studio Matte material treatment on every surface
  // Level 3: Icons + warm amber accents for photography touchpoints
  // Level 4: Glass viewfinder with full overlay stack on loaded photo
  // Level 5: Tactile CTA with dome physics + state-colored LED ring
  const _D_VF = `min(72vh, 720px)`;
  const _D_AMBER = 'rgba(200,155,60,';  // warm amber base for accents

  const desktopRightPanel = isDesktop ? (
    <div style={{
      gridColumn: '1 / -1', gridRow: '1 / -1',
      position: 'relative', zIndex: 10,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      pointerEvents: 'none',
    }}>
      {/* ── Top bar — instrument header ── */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '20px 36px',
        pointerEvents: 'auto',
        background: 'linear-gradient(180deg, rgba(6,7,10,0.80) 0%, rgba(6,7,10,0.40) 60%, transparent 100%)',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <p style={{ margin: 0, fontWeight: 800, fontSize: 17, lineHeight: 1, color: C.textPrimary, letterSpacing: '-0.3px', ...FONT_SMOOTH }}>
            No Guesswork <span style={{ fontWeight: 600, fontSize: '0.88em', letterSpacing: '0.12em', color: steel(0.60) }}>Lighting</span>
          </p>
        </div>
        {user && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* User initial — machined monogram disc (matches home button style) */}
            <div style={{ position: 'relative' }}>
              {/* Well cavity */}
              <div style={{
                position: 'absolute', inset: -4, borderRadius: '50%',
                boxShadow: [
                  'inset 4px 4px 10px rgba(0,0,0,0.85)',
                  'inset 2px 2px 5px rgba(0,0,0,0.65)',
                  'inset -1px -1px 2px rgba(255,255,255,0.012)',
                  '-1px -1px 1px rgba(255,255,255,0.03)',
                  '2px 3px 8px rgba(0,0,0,0.45)',
                ].join(', '),
                pointerEvents: 'none',
              }} />
              <button onClick={() => { onSettings?.(); softClickSound(); tapHaptic(); }}
                className="sm-btn-lift"
                title={`${user.username || user.email || ''} — Settings`}
                aria-label="Settings"
                style={{
                  position: 'relative',
                  width: 36, height: 36, borderRadius: '50%',
                  background: CTA_BG, border: 'none', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: [
                    '8px 8px 22px rgba(0,0,0,0.72)',
                    '4px 4px 10px rgba(0,0,0,0.55)',
                    '1px 2px 4px rgba(0,0,0,0.38)',
                    '-1px -1px 2px rgba(255,255,255,0.06)',
                    'inset 0 1.5px 0 rgba(255,255,255,0.14)',
                    'inset 1px 0 0 rgba(255,255,255,0.07)',
                    'inset -1px -1px 0 rgba(0,0,0,0.40)',
                  ].join(', '),
                  WebkitTapHighlightColor: 'transparent',
                }}>
                <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '-0.3px', color: steel(0.65), ...FONT_SMOOTH }}>
                  {(user.username || user.email || 'U')[0].toUpperCase()}
                </span>
                {/* Gear badge — settings affordance */}
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={steel(0.30)} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  style={{ position: 'absolute', bottom: 1, right: 1 }}>
                  <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
                </svg>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── EMPTY STATE ── */}
      {!hasImage && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pointerEvents: 'auto' }}>
          {/* Hero — brand statement. Typography: bold weight for the brand claim,
              regular weight for the supporting line. All Inter, all antialiased. */}
          <p style={{
            margin: '0 0 6px', fontWeight: 700, fontSize: 30, lineHeight: '36px',
            color: 'rgba(245,247,250,0.90)', letterSpacing: '-0.5px',
            textAlign: 'center', ...FONT_SMOOTH,
          }}>See how it was lit.</p>
          <p style={{
            margin: '0 0 30px', fontWeight: 500, fontSize: 14, lineHeight: '20px',
            color: steel(0.50), letterSpacing: '0.1px',
            textAlign: 'center', ...FONT_SMOOTH,
          }}>Rembrandt · Softbox · 45° left · 4 ft</p>

          {/* Viewfinder — identical material treatment to mobile VF slot */}
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            style={{
              width: _D_VF, height: `calc(${_D_VF} * 0.72)`,
              borderRadius: 0, cursor: 'pointer',
              position: 'relative', overflow: 'hidden',
              // LCD glass panel — opaque dark surface with faint blue-black cast.
              // Real camera LCDs aren't pure black — they have a subtle cool shift
              // from the backlight diffuser layer even when "off".
              background: 'linear-gradient(180deg, #080808 0%, #060606 40%, #050505 100%)',
              // Mobile-identical shadow: inset trough + outer drop + chamfer catch
              boxShadow: isDragOver
                ? `inset 0 0 40px ${_D_AMBER}0.12), ${VIEWFINDER_INNER_SHADOW}`
                : VIEWFINDER_INNER_SHADOW,
              transition: 'box-shadow 0.25s ease',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {/* Surface depth — directional gradient matches 141.71° key light, darkens toward bottom-right */}
            <div style={{
              position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
              background: 'linear-gradient(141.71deg, transparent 0%, rgba(0,0,0,0.05) 55%, rgba(0,0,0,0.10) 100%)',
            }} />
            {/* Chamfer edge catch — top/left bezel highlight at key-light angle */}
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 7,
              background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
              pointerEvents: 'none',
            }} />
            <div style={{
              position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 7,
              background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
              pointerEvents: 'none',
            }} />
            {/* Ghosted portrait — contained inside desktop VF slot */}
            <img src="/ghost-rembrandt.jpg" alt="" style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              objectFit: 'cover', objectPosition: '50% 30%',
              opacity: 0.12, zIndex: 1,
              pointerEvents: 'none',
              filter: 'grayscale(1) brightness(0.6)',
            }} />
            {/* Ellipse depth oval — Leica-style distance indicator */}
            <div style={{ position: 'absolute', left: '2.8%', top: -30, right: '2.8%', bottom: 10, zIndex: 1, opacity: 0.5 }}>
              <img src={ellipseBg} alt="" style={{ width: '100%', height: '100%' }} />
            </div>
            {/* Glass panel overlay — directional key reflection */}
            <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 5 }}>
              <div style={{
                position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0,
                background: GLASS_REFLECTION, opacity: 0.72,
                transform: glassReflectionTransform(tilt), willChange: 'transform',
              }} />
            </div>
            {/* Counter-chamfer — bottom/right edge shadow, opposite the key light */}
            <div style={{
              position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 7,
              background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
              pointerEvents: 'none',
            }} />
            <div style={{
              position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 7,
              background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
              pointerEvents: 'none',
            }} />
            {/* Inner shadow — Figma-exact bevel, always top of stack */}
            <div style={{
              position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 6,
              boxShadow: VIEWFINDER_INNER_SHADOW,
            }} />
            {/* Center: bracket icon + instruction — z-index 3 so it sits
                UNDER the glass overlay (z5) and inner shadow (z6). This makes
                the text look like it's behind the glass, inside the LCD. */}
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 14, zIndex: 3,
              // Subtle text shadow simulates LCD sub-pixel glow
              textShadow: `0 0 6px ${steel(0.12)}`,
            }}>
              <svg width="52" height="52" viewBox="0 0 38 38" fill="none" style={{
                opacity: 0.65,
                animation: 'vfPulseGlow 2.4s ease-in-out infinite',
                filter: `drop-shadow(0 0 8px ${steel(0.20)})`,
              }}>
                <path d="M5 12 V7 Q5 5 7 5 H12" stroke={steel(0.55)} strokeWidth="1.2" strokeLinecap="round" fill="none" />
                <path d="M26 5 H31 Q33 5 33 7 V12" stroke={steel(0.55)} strokeWidth="1.2" strokeLinecap="round" fill="none" />
                <path d="M33 26 V31 Q33 33 31 33 H26" stroke={steel(0.55)} strokeWidth="1.2" strokeLinecap="round" fill="none" />
                <path d="M12 33 H7 Q5 33 5 31 V26" stroke={steel(0.55)} strokeWidth="1.2" strokeLinecap="round" fill="none" />
                <g>
                  <path d="M19 13v8" stroke={steel(0.45)} strokeWidth="1.2" strokeLinecap="round" />
                  <path d="M16 18l3 3 3-3" stroke={steel(0.45)} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </g>
              </svg>
              <p style={{
                margin: 0, fontSize: 13, fontWeight: 700, letterSpacing: '2.8px',
                color: steel(0.42), textTransform: 'uppercase', ...FONT_SMOOTH,
              }}>LOAD PHOTO</p>
            </div>
            {/* Drag-over glow */}
            {isDragOver && (
              <div style={{
                position: 'absolute', inset: 0, zIndex: 3, pointerEvents: 'none',
                background: `radial-gradient(ellipse 80% 65% at center, ${_D_AMBER}0.10) 0%, ${_D_AMBER}0.03) 50%, transparent 75%)`,
                boxShadow: `inset 0 0 40px ${_D_AMBER}0.12)`,
              }} />
            )}
          </div>

          {/* Action row — Studio Matte WELL + DOME buttons */}
          <div style={{ display: 'flex', gap: 16, marginTop: 28, alignItems: 'center' }}>
            {/* Try a Sample — Studio Matte steel CTA with well */}
            <div style={{ position: 'relative' }}>
              <div style={{
                position: 'absolute', inset: -4, borderRadius: 16,
                boxShadow: [
                  'inset 6px 6px 14px rgba(0,0,0,0.88)',
                  'inset 3px 3px 7px rgba(0,0,0,0.70)',
                  'inset 1px 1px 3px rgba(0,0,0,0.50)',
                  'inset -1px -1px 3px rgba(255,255,255,0.012)',
                  '-1px -1px 1px rgba(255,255,255,0.035)',
                  '3px 4px 10px rgba(0,0,0,0.50)',
                ].join(', '),
                pointerEvents: 'none',
              }} />
              <button onClick={loadSample} style={{
                position: 'relative',
                background: CTA_BG, border: 'none',
                cursor: 'pointer', padding: '10px 24px', borderRadius: 12,
                boxShadow: [
                  '10px 10px 28px rgba(0,0,0,0.78)',
                  '5px 5px 12px rgba(0,0,0,0.58)',
                  '2px 2px 5px rgba(0,0,0,0.38)',
                  '-1px -1px 2px rgba(255,255,255,0.06)',
                  `0 0 6px ${steel(0.06)}`,
                  'inset 0 2px 0 rgba(255,255,255,0.14)',
                  'inset 2px 0 0 rgba(255,255,255,0.07)',
                  'inset -1px -1px 0 rgba(0,0,0,0.40)',
                ].join(', '),
                opacity: sampleLoading ? 0.5 : 1,
                WebkitTapHighlightColor: 'transparent',
              }}
              className="sm-btn-lift"
              >
                <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.75), textTransform: 'uppercase', ...FONT_SMOOTH }}>
                  {sampleLoading ? 'Loading...' : 'Try a Sample'}
                </span>
              </button>
            </div>
            {hasLastResult && (
              <div style={{ position: 'relative' }}>
                {/* Well cavity */}
                <div style={{
                  position: 'absolute', inset: -4, borderRadius: 16,
                  background: 'radial-gradient(ellipse at 50% 40%, #040508 0%, #02030500 70%)',
                  boxShadow: [
                    'inset 6px 6px 14px rgba(0,0,0,0.88)',
                    'inset 3px 3px 7px rgba(0,0,0,0.70)',
                    'inset 1px 1px 3px rgba(0,0,0,0.50)',
                    'inset -1px -1px 3px rgba(255,255,255,0.012)',
                    '-1px -1px 1px rgba(255,255,255,0.035)',
                    '3px 4px 10px rgba(0,0,0,0.50)',
                  ].join(', '),
                  pointerEvents: 'none',
                }} />
                <button onClick={onViewLastResult} style={{
                  position: 'relative',
                  background: CTA_BG, border: 'none',
                  cursor: 'pointer', padding: '10px 24px', borderRadius: 12,
                  boxShadow: [
                    '10px 10px 28px rgba(0,0,0,0.78)',
                    '5px 5px 12px rgba(0,0,0,0.58)',
                    '2px 2px 5px rgba(0,0,0,0.38)',
                    '-1px -1px 2px rgba(255,255,255,0.06)',
                    `0 0 6px ${steel(0.06)}`,
                    'inset 0 2px 0 rgba(255,255,255,0.14)',
                    'inset 2px 0 0 rgba(255,255,255,0.07)',
                    'inset -1px -1px 0 rgba(0,0,0,0.40)',
                  ].join(', '),
                  transition: 'transform 0.12s ease',
                  WebkitTapHighlightColor: 'transparent',
                }}
                className="sm-btn-lift"
                >
                  <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.75), textTransform: 'uppercase', ...FONT_SMOOTH }}>Last Result</span>
                </button>
              </div>
            )}
            {onBuildWizard && (
              <div style={{ position: 'relative' }}>
                <div style={{
                  position: 'absolute', inset: -4, borderRadius: 16,
                  boxShadow: [
                    'inset 6px 6px 14px rgba(0,0,0,0.88)',
                    'inset 3px 3px 7px rgba(0,0,0,0.70)',
                    'inset 1px 1px 3px rgba(0,0,0,0.50)',
                    'inset -1px -1px 3px rgba(255,255,255,0.012)',
                    '-1px -1px 1px rgba(255,255,255,0.035)',
                    '3px 4px 10px rgba(0,0,0,0.50)',
                  ].join(', '),
                  pointerEvents: 'none',
                }} />
                <button onClick={() => { tapHaptic(); softClickSound(); trackEvent('HOME_BUILD_ENTRY', { source: 'desktop_idle_panel' }); onBuildWizard(); }} style={{
                  position: 'relative',
                  background: CTA_BG, border: 'none',
                  cursor: 'pointer', padding: '10px 24px', borderRadius: 12,
                  boxShadow: [
                    '10px 10px 28px rgba(0,0,0,0.78)',
                    '5px 5px 12px rgba(0,0,0,0.58)',
                    '2px 2px 5px rgba(0,0,0,0.38)',
                    '-1px -1px 2px rgba(255,255,255,0.06)',
                    `0 0 6px ${steel(0.06)}`,
                    'inset 0 2px 0 rgba(255,255,255,0.14)',
                    'inset 2px 0 0 rgba(255,255,255,0.07)',
                    'inset -1px -1px 0 rgba(0,0,0,0.40)',
                  ].join(', '),
                  transition: 'transform 0.12s ease',
                  WebkitTapHighlightColor: 'transparent',
                }}
                className="sm-btn-lift"
                >
                  <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '1.5px', color: steel(0.75), textTransform: 'uppercase', ...FONT_SMOOTH }}>Build from Intent</span>
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── PHOTO LOADED STATE ── */}
      {hasImage && (<>

        {/* Bottom dock — gradient scrim + EXIF + CTA */}
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 12,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '0 0 40px', pointerEvents: 'auto',
          background: `linear-gradient(to bottom, transparent 0%, ${SCREEN_BG}80 30%, ${SCREEN_BG}d1 70%, ${SCREEN_BG}eb 100%)`,
        }}>
          <ExifStrip exifData={exifData} style={{ marginBottom: 18, opacity: 0.85 }} />
          {/* CTA — well cavity wrapper: recessed socket the button sits in */}
          <div style={{ position: 'relative' }}>
            <div style={{
              position: 'absolute', inset: -4, borderRadius: 17, pointerEvents: 'none',
              boxShadow: [
                'inset 8px 8px 18px rgba(0,0,0,0.90)',
                'inset 4px 4px 9px rgba(0,0,0,0.72)',
                'inset 2px 2px 4px rgba(0,0,0,0.52)',
                'inset -1px -1px 3px rgba(255,255,255,0.012)',
                '-1px -1px 1px rgba(255,255,255,0.035)',
                '4px 5px 14px rgba(0,0,0,0.55)',
              ].join(', '),
            }} />
            <button
              onClick={handleButtonClick}
              onMouseDown={handleButtonPress}
              onMouseUp={handleButtonRelease}
              onMouseEnter={() => setIsHovered(true)}
              onMouseLeave={() => { setIsHovered(false); handleButtonRelease(); }}
              style={{
                position: 'relative',
                padding: '11px 36px',
                border: 'none', borderRadius: 12, cursor: 'pointer',
                overflow: 'hidden',
                background: isPressed
                  ? 'linear-gradient(141.71deg, #020304 0%, #040506 50%, #060708 100%)'
                  : CTA_BG,
                boxShadow: isPressed
                  ? [
                      'inset 0 4px 10px rgba(0,0,0,0.88)',
                      'inset 3px 0 8px rgba(0,0,0,0.58)',
                      'inset -1px -1px 4px rgba(0,0,0,0.42)',
                      `0 0 0 1px rgba(${SC.r},${SC.g},${SC.b},0.18)`,
                      `0 0 8px rgba(${SC.r},${SC.g},${SC.b},0.06)`,
                      '1px 1px 3px rgba(0,0,0,0.30)',
                    ].join(', ')
                  : [
                      '10px 10px 28px rgba(0,0,0,0.78)',
                      '5px 5px 12px rgba(0,0,0,0.58)',
                      '2px 2px 5px rgba(0,0,0,0.38)',
                      '-1px -1px 2px rgba(255,255,255,0.06)',
                      `0 0 0 1px rgba(${SC.r},${SC.g},${SC.b},0.45)`,
                      `0 0 20px rgba(${SC.r},${SC.g},${SC.b},0.16)`,
                      'inset 0 2px 0 rgba(255,255,255,0.20)',
                      'inset 2px 0 0 rgba(255,255,255,0.09)',
                      'inset -1px -1px 0 rgba(0,0,0,0.48)',
                    ].join(', '),
                transition: `all ${isPressed ? '0.06s' : '0.18s'} ease`,
                transform: isPressed ? 'translateY(1px) scale(0.993)' : isHovered ? 'translateY(-1px)' : 'none',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              {/* LED accent line — top chamfer glow */}
              <div style={{
                position: 'absolute', top: 0, left: '8%', right: '8%', height: 1,
                background: `linear-gradient(90deg, transparent 0%, rgba(${SC.r},${SC.g},${SC.b},${isPressed ? 0.05 : 0.65}) 50%, transparent 100%)`,
                transition: 'background 0.15s ease',
              }} />
              <span style={{
                fontSize: 13, fontWeight: 700, letterSpacing: '2.5px', textTransform: 'uppercase',
                color: isPressed ? steel(0.28) : `rgba(${SC.r},${SC.g},${SC.b},0.95)`,
                textShadow: isPressed ? 'none' : `0 -1px 1px rgba(0,0,0,0.75), 0 1px 0 rgba(255,255,255,0.05), 0 0 12px rgba(${SC.r},${SC.g},${SC.b},0.28)`,
                ...FONT_SMOOTH,
              }}>{analyzeLabel}</span>
            </button>
          </div>
        </div>
      </>)}

    </div>
  ) : null;

  return (
    <div ref={rootRef} style={{ position: 'fixed', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: SCREEN_BG, overflow: 'hidden', overscrollBehavior: 'none' }}>
      {/* MatteBackground spans full viewport — visible around the maxWidth-constrained content */}
      <MatteBackground variant="carbon" />
    <div
      onClick={handleBodyTap}
      onTouchStart={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
      onTouchMove={(e) => { if (e.target === e.currentTarget) grainHaptic(); }}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        margin: '0 auto',
        overflow: 'hidden',
        fontFamily: 'Inter, system-ui, sans-serif',
        filter: daylightMode ? 'brightness(1.15)' : undefined,
        transition: 'filter 0.4s ease',
        ...(isDesktop ? {
          display: 'grid',
          gridTemplateColumns: '1fr',
          gridTemplateRows: '1fr',
          maxWidth: 1400,
        } : {}),
      }}
    >
      <input ref={fileRef} type="file" accept="image/*" onChange={handleFileChange} style={{ display: 'none' }} />
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" onChange={handleFileChange} style={{ display: 'none' }} />

      {/* ── Wordmark — mobile only (desktop has it in right panel) ── */}
      {!isDesktop && (
      <div
        role="button"
        aria-label="Menu"
        tabIndex={0}
        onClick={() => { setProfileOpen(v => !v); softClickSound(); tapHaptic(); }}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setProfileOpen(v => !v); softClickSound(); tapHaptic(); } }}
        onTouchStart={startWordmarkPress}
        onTouchEnd={endWordmarkPress}
        onTouchCancel={endWordmarkPress}
        onMouseDown={startWordmarkPress}
        onMouseUp={endWordmarkPress}
        onMouseLeave={endWordmarkPress}
        style={{
          position: 'absolute', top: 24, left: 22, padding: 6,
          cursor: 'pointer', WebkitTapHighlightColor: 'transparent', userSelect: 'none', zIndex: 15,
          opacity: hasImage ? 0.20 : undefined,
          transition: 'opacity 0.6s ease',
        }}
      >
        {/* Brand + one-line story. Strong enough to anchor the top, quiet enough
            to not compete with the VF. Two-line stack: brand name + what it does. */}
        <p style={{
          margin: 0,
          fontWeight: 800, fontSize: 17, lineHeight: '20px',
          color: C.textPrimary, letterSpacing: '-0.3px',
          ...FONT_SMOOTH,
        }}>No Guesswork <span style={{ fontWeight: 600, fontSize: '0.88em', letterSpacing: '0.10em', color: steel(0.50) }}>Lighting</span></p>
        <p style={{
          margin: '3px 0 0',
          fontWeight: 600, fontSize: 13, lineHeight: '16px',
          color: steel(0.42), letterSpacing: '0.3px',
          ...FONT_SMOOTH,
        }}>Reverse-engineer any portrait lighting</p>
      </div>
      )}


{/* ── Profile panel scrim — mobile only ── */}
      {!isDesktop && profileOpen && (
        <div
          onClick={() => { setProfileOpen(false); softClickSound(); }}
          style={{
            position: 'absolute', inset: 0, zIndex: 24,
            backgroundColor: 'rgba(0,0,0,0.25)',
            WebkitTapHighlightColor: 'transparent',
          }}
        />
      )}

      {/* ── Profile Panel — mobile only (desktop has tools in right panel) ── */}
      {!isDesktop && <div style={{
        position: 'absolute', top: 76, left: 20, right: 20,
        borderRadius: 14, backgroundColor: '#0f1013',
        boxShadow: '1px 2px 4px 0px rgba(0,0,0,0.2), 2px 4px 12px 0px rgba(0,0,0,0.4), inset -1px -1px 2px 0px rgba(0,0,0,0.12), inset 1px 1px 0px 0px rgba(255,255,255,0.05)',
        padding: '16px 20px', zIndex: 25,
        opacity: profileOpen ? 1 : 0,
        transform: profileOpen ? 'translateY(0)' : 'translateY(-8px)',
        transition: 'opacity 0.25s ease, transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        pointerEvents: profileOpen ? 'auto' : 'none',
      }}>
        {user ? (
          <>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'rgba(245,247,250,0.88)', WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision' }}>
              {user.username || user.email}
            </p>
            {user.email && user.username && (
              <p style={{ margin: '4px 0 0', fontSize: 13, fontWeight: 500, color: steel(0.55), WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision' }}>
                {user.email}
              </p>
            )}
            <div style={{ height: 1, backgroundColor: 'rgba(255,255,255,0.04)', margin: '12px 0' }} />
            {/* ── Studio tools ── */}
            {[
              { label: 'Lighting Recipes', action: onRecipes },
              { label: 'Saved Setups',     action: onSavedSetups },
              { label: 'Build from Scratch', action: onBuildWizard },
              { label: 'My Kit',           action: onMyKit },
              { label: 'Lighting Journal', action: onSessionLog },
              { label: 'Look Library', action: onLookLibrary },
              { label: 'Client Brief', action: onClientBrief },
              { label: 'From Video', action: onVideoCapture },
            ].map(item => (
              <button key={item.label} onClick={() => { item.action?.(); setProfileOpen(false); softClickSound(); tapHaptic(); }}
                style={{
                  backgroundColor: 'transparent', border: 'none', cursor: 'pointer', padding: '6px 0',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
                  WebkitTapHighlightColor: 'transparent', minHeight: 36,
                }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: C.textPrimary, letterSpacing: '0.2px', ...FONT_SMOOTH }}>{item.label}</span>
                <span style={{ fontSize: 13, color: steel(0.4), lineHeight: 1, ...FONT_SMOOTH }}>›</span>
              </button>
            ))}
            <div style={{ height: 1, backgroundColor: 'rgba(255,255,255,0.04)', margin: '10px 0 8px' }} />
            {/* ── Account ── */}
            <button onClick={() => { onSettings?.(); setProfileOpen(false); softClickSound(); tapHaptic(); }}
              style={{
                backgroundColor: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 0',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
                WebkitTapHighlightColor: 'transparent',
              }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'rgba(184,191,199,0.75)', letterSpacing: '0.3px', WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision' }}>Settings</span>
              <span style={{ fontSize: 13, color: steel(0.58), lineHeight: 1 }}>›</span>
            </button>
            <div style={{ height: 1, backgroundColor: 'rgba(255,255,255,0.04)', margin: '8px 0' }} />
            <button onClick={() => { onLogout?.(); setProfileOpen(false); softClickSound(); tapHaptic(); }}
              style={{
                backgroundColor: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
                fontSize: 13, fontWeight: 600, color: 'rgba(180,60,60,0.75)', letterSpacing: '0.5px',
                WebkitTapHighlightColor: 'transparent',
                WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision',
              }}>
              Sign Out
            </button>
          </>
        ) : (
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: steel(0.62), WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision' }}>
            Not signed in
          </p>
        )}
        {/* Build version stamp — quiet bottom-right, like firmware version on pro gear */}
        <p style={{
          margin: '10px 0 0', textAlign: 'right',
          fontSize: 9, fontWeight: 500, letterSpacing: '0.5px',
          color: steel(0.18),
          WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale',
        }}>v1.4.0</p>
      </div>}


      {/* Illumination Well removed — one button, one mental model.
          Recall (view last result) is now a long-press on the main analyze button.
          Mute toggle moved into the Settings panel (HAPTIC row). */}

      {/* ── Photo Slot (Viewfinder) — tap to select, drag to drop, long-press to clear ── */}
      <div
        onClick={() => { if (urlLoadError) setUrlLoadError(null); fileRef.current?.click(); }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onTouchStart={() => { handleViewfinderTouch(); startViewfinderPress(); }}
        onTouchEnd={endViewfinderPress}
        onTouchCancel={endViewfinderPress}
        onContextMenu={(e) => { if (hasImage) { e.preventDefault(); clearImage(); } }}
        role="button"
        aria-label={hasImage ? 'Photo loaded — tap to swap, long-press to clear' : 'Tap to load a photo'}
        style={{
          // Desktop loaded: 720px bounded panel matching Processing.
          // Desktop empty: full-bleed. Mobile: absolute fill.
          position: isDesktop ? 'relative' : 'absolute',
          ...(isDesktop ? {
            height: '100%',
            gridColumn: '1 / -1', gridRow: '1 / -1',
            ...(hasImage ? { width: 'fit-content', justifySelf: 'center', height: 'calc(100% - 40px)', alignSelf: 'center' } : {}),
          } : {
            top: 0, left: 0, right: 0, bottom: 0,
          }),
          borderRadius: 0,
          // Edge-to-edge viewfinder — no rounded corners, flush with screen edges.
          // Drag-over: faint steel tint to signal accept state.
          border: isDragOver ? `1.5px solid rgba(132, 158, 184,0.40)` : 'none',
          overflow: 'hidden',
          cursor: 'pointer',
          // VF surface — dark LCD panel when housing a photo on desktop,
          // transparent on mobile so it inherits the Carbon Black body
          // through the MatteBackground.
          // LCD panel — matches Home empty VF slot exactly
          backgroundColor: (isDesktop && hasImage) ? undefined : 'transparent',
          background: (isDesktop && hasImage)
            ? 'linear-gradient(180deg, #0d0d0d 0%, #080808 40%, #060606 100%)'
            : 'transparent',
          borderRadius: 0,
          boxShadow: isDragOver
            ? 'inset 0 0 40px rgba(132, 158, 184,0.15)'
            : (isDesktop && hasImage) ? VIEWFINDER_INNER_SHADOW
            : (hasImage || isDesktop) ? 'none' : [
                // Deep bezel channel — panel is recessed into the body
                'inset 0 3px 8px rgba(0,0,0,0.85)',
                'inset 2px 0 6px rgba(0,0,0,0.55)',
                'inset 0 1px 1px rgba(0,0,0,0.70)',
                // Bottom edge bounce — faint light catch on the lower bezel lip
                'inset 0 -1px 0 rgba(255,255,255,0.035)',
                // Right edge bounce
                'inset -1px 0 0 rgba(255,255,255,0.02)',
                // Outer lip highlight — the body surface around the bezel catches key light
                '0 -1px 0 rgba(255,255,255,0.04)',
              ].join(', '),
          WebkitTapHighlightColor: 'transparent',
          transition: 'box-shadow 0.2s ease, transform 0.08s ease',
          transform: viewfinderShake ? 'translateX(4px)' : 'translateX(0)',
          animation: viewfinderShake ? 'vfShake 0.4s ease' : 'none',
        }}
      >
        {/* 0 — LCD panel backlight — suppressed on desktop so MatteBackground shows through letterbox areas. */}
        <div style={{
          position: 'absolute', inset: 0,
          opacity: (isDesktop && hasImage) ? 0 : 1,
          background: 'transparent',
          pointerEvents: 'none', zIndex: 0,
        }} />

        {/* 0a — Ghosted sample portrait — faint hint of a face in the empty VF.
             Shows "a portrait goes here" and hints at the analysis subject.
             Sits behind brackets/text (z1) but above LCD backlight (z0).
             Fades out when a real photo loads. The image is already prefetched
             at mount (line ~89) so this renders instantly from cache. */}
        {!hasImage && !isDesktop && (
          <img src="/ghost-rembrandt.jpg" alt="" style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%',
            objectFit: 'cover', objectPosition: '50% 30%',
            opacity: 0.15, zIndex: 1,
            pointerEvents: 'none',
            filter: 'grayscale(1) brightness(0.7)',
          }} />
        )}

        {/* 0b — LCD sub-pixel texture — faint horizontal scan lines that make the
             surface read as a real display panel, not a flat div. Subtle enough to
             disappear when a photo loads but visible on the dark empty state. */}
        {!hasImage && !isDesktop && (
          <div style={{
            position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
            backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.008) 2px, rgba(255,255,255,0.008) 3px)',
            backgroundSize: '100% 3px',
            mixBlendMode: 'overlay',
            opacity: 0.6,
          }} />
        )}

        {/* 0c — Glass surface reflection — the powered-off LCD still has a glass surface
             that catches ambient light. Diagonal wipe matching 141.71° key direction. */}
        {!hasImage && !isDesktop && (
          <div style={{
            position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1,
            background: 'linear-gradient(141.71deg, rgba(255,255,255,0.025) 0%, rgba(255,255,255,0.008) 25%, transparent 50%, transparent 80%, rgba(255,255,255,0.005) 100%)',
          }} />
        )}

        {/* 1 — Ellipse depth oval — desktop hides when no photo */}
        {!isDesktop && (
        <div style={{ position: 'absolute', left: '2.8%', top: -30, right: '2.8%', bottom: 10, zIndex: 1 }}>
          <img src={ellipseBg} alt="" style={{ width: '100%', height: '100%' }} />
        </div>
        )}

        {/* Grid + reticle — only show when a real photo is loaded.
            Fades to near-invisible after initial flash so the photo owns
            the viewport. The camera-instrument metaphor served its purpose;
            now the image IS the content. */}
        {hasImage && (<div style={{
          position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none',
          animation: 'hudFadeDown 0.8s ease 0.2s forwards',
        }}>
        <ViewfinderHUD />
        </div>)}

        {/* 5b — EXIF readout strip — real camera metadata from the loaded photo.
             Shows model, f-stop, shutter, ISO, focal length in a quiet bottom bar.
             Only renders when EXIF was successfully extracted — no fake data. */}
        {hasImage && (
          <ExifStrip exifData={exifData} style={{
            animation: 'ghostFadeIn 0.6s ease 0.3s both',
          }} />
        )}

        {/* 5c — Load confirmation flash — brief viewfinder edge flare when photo is accepted.
             Unmistakable "got it" feedback — the glass border pulses once, bright blue-white. */}
        {loadFlash && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 12,
            pointerEvents: 'none',
            boxShadow: 'inset 0 0 30px rgba(132,158,184,0.25), inset 0 0 60px rgba(132,158,184,0.10)',
            animation: 'loadAcceptFlash 0.6s ease-out forwards',
          }} />
        )}

        {/* Invisible settings hit target removed — Apple principle "reduce, don't hide".
            Settings is already reachable via wordmark tap → profile panel → Settings row. */}

        {/* 7b — Tap prompt / URL fetching / URL error indicator (mobile only on desktop — overlay handles it) */}
        {!hasImage && !isDesktop && (
          urlLoadError ? (
            <p style={{
              position: 'absolute', top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              margin: 0, width: '75%', textAlign: 'center',
              fontSize: 13, fontWeight: 600, letterSpacing: '0.2px', lineHeight: '15px',
              color: 'rgba(237,154,56,0.85)',
              pointerEvents: 'none', zIndex: 7,
              WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale',
            }}>{urlLoadError}</p>
          ) : (
            <div style={{
              // VF center — prominent import affordance. Replaces the tiny
              // corner glyph with a clear, centred tap target that reads as
              // "load your photo here" without competing with the analyze CTA.
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              gap: 6,
              // Nudge cluster slightly above geometric center — closer to
              // the golden mean and away from the dome zone below.
              paddingBottom: Math.round(stableVH * 0.12),
              opacity: (showPrompt || isUrlFetching) ? 1 : 0,
              transition: 'opacity 1.2s ease',
              pointerEvents: 'none', zIndex: 7,
            }}>
              {!isUrlFetching && (<>
                {/* Tight content cluster: brackets + instruction + hint arrow.
                    Grouped close together so the VF center has one cohesive element
                    instead of scattered parts floating in empty space. */}
                <svg width="88" height="88" viewBox="0 0 38 38" fill="none" style={{
                  animation: 'vfPulseGlow 2.4s ease-in-out infinite',
                  filter: `drop-shadow(0 0 12px ${steel(0.25)})`,
                }}>
                  <path d="M5 12 V7 Q5 5 7 5 H12" stroke={steel(0.45)} strokeWidth="0.9" strokeLinecap="round" fill="none" />
                  <path d="M26 5 H31 Q33 5 33 7 V12" stroke={steel(0.45)} strokeWidth="0.9" strokeLinecap="round" fill="none" />
                  <path d="M33 26 V31 Q33 33 31 33 H26" stroke={steel(0.45)} strokeWidth="0.9" strokeLinecap="round" fill="none" />
                  <path d="M12 33 H7 Q5 33 5 31 V26" stroke={steel(0.45)} strokeWidth="0.9" strokeLinecap="round" fill="none" />
                  <circle cx="19" cy="19" r="1.5" fill={steel(0.35)} />
                </svg>
                {/* VF copy — instruction + deliverables + ghosted proof.
                    Two-state design: this IS the payoff preview for the empty state.
                    It communicates what the user gets, not just what to do. */}
                <p style={{
                  margin: '6px 0 0', fontSize: 17, fontWeight: 700, letterSpacing: '-0.2px',
                  color: steel(0.62),
                  textShadow: '0 -1px 1px rgba(0,0,0,0.6), 0 1px 0 rgba(255,255,255,0.04)',
                  textAlign: 'center', lineHeight: '22px',
                  ...FONT_SMOOTH,
                }}>See how it was lit</p>
                {/* Proof line — matches desktop hero */}
                <p style={{
                  margin: '6px 0 0', fontSize: 12, fontWeight: 600, letterSpacing: '0.5px',
                  color: steel(0.42),
                  textShadow: '0 -1px 1px rgba(0,0,0,0.5)',
                  textAlign: 'center', lineHeight: '16px',
                  fontStyle: 'italic',
                  ...FONT_SMOOTH,
                }}>Rembrandt · Softbox · 45° left · 4 ft</p>
              </>)}
              {isUrlFetching && (
                <p style={{
                  margin: 0, fontSize: 12, fontWeight: 700, letterSpacing: '2px',
                  color: steel(0.70),
                  WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale', textRendering: 'geometricPrecision',
                }}>LOADING…</p>
              )}
            </div>
          )
        )}

        {/* 7c — Drag-over state overlay — stronger glow for clear drop-zone feedback */}
        {isDragOver && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 7,
            background: 'radial-gradient(ellipse 80% 65% at center, rgba(132, 158, 184,0.12) 0%, rgba(132, 158, 184,0.04) 50%, transparent 75%)',
            pointerEvents: 'none',
          }} />
        )}

        {/* 8 — Image preview (when selected) — sits under glass overlay */}
        {imagePreview && (
          <img key={imagePreview} src={imagePreview} alt="Selected"
            onLoad={(e) => {
              const { naturalWidth: w, naturalHeight: h } = e.target;
              setIsLandscape(w > 0 && h > 0 && w / h > 1.15);
            }}
            style={{
              ...(isDesktop ? {
                display: 'block', height: '100%', width: 'auto',
              } : {
                position: 'absolute', inset: 0, width: '100%', height: '100%',
                objectFit: 'cover',
              }),
              objectPosition: isDesktop ? '50% 50%' : '50% 25%',
              opacity: isDesktop ? 0.95 : 0.85, zIndex: 8,
              animation: 'heroZoomIn 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards',
              transformOrigin: 'center 25%',
            }} />
        )}

        {/* 8a — Landscape crop indicator — subtle letterbox lines when a landscape
             image is displayed in the portrait VF. Tells the photographer their
             image extends beyond what's visible, like a camera LCD crop overlay. */}
        {hasImage && isLandscape && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 9, pointerEvents: 'none',
            display: 'flex', flexDirection: 'column', justifyContent: 'center',
          }}>
            <div style={{
              position: 'absolute', top: '18%', left: 8, right: 8, height: 1,
              background: `linear-gradient(to right, transparent 0%, ${steel(0.25)} 15%, ${steel(0.25)} 85%, transparent 100%)`,
            }} />
            <div style={{
              position: 'absolute', bottom: '18%', left: 8, right: 8, height: 1,
              background: `linear-gradient(to right, transparent 0%, ${steel(0.25)} 15%, ${steel(0.25)} 85%, transparent 100%)`,
            }} />
            <p style={{
              position: 'absolute', top: 'calc(18% - 14px)', right: 12,
              margin: 0, fontSize: 8, fontWeight: 600, letterSpacing: '1px',
              color: steel(0.30),
              WebkitFontSmoothing: 'antialiased',
            }}>CROP</p>
          </div>
        )}

        {/* 8b — LCD backlight wash — mobile only. Desktop photo sits on clean matte. */}
        {lcdOn && !isDesktop && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 8,
            background: [
              'radial-gradient(ellipse 130% 110% at 30% 36%, rgba(255,220,170,0.20) 0%, rgba(255,205,140,0.13) 32%, rgba(255,185,110,0.06) 65%, transparent 100%)',
            ].join(', '),
            transition: 'opacity 1.2s ease',
            pointerEvents: 'none',
          }} />
        )}

        {/* 9 — Glass panel overlay — shows inside recessed panel on both mobile and desktop loaded.
               Mobile empty: reduced opacity. Desktop empty: handled by VF slot above. */}
        {!isDesktop && (
        <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 0, zIndex: 9, pointerEvents: 'none' }}>
          <div style={{ position: 'absolute', inset: 0, background: LENS_VIGNETTE, opacity: hasImage ? 1 : 0.6 }} />
          <div style={DITHER_STYLE} />
          <div style={{ position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0, background: GLASS_REFLECTION, borderRadius: 0, opacity: hasImage ? 0.62 : 0.30, transform: glassReflectionTransform(tilt), willChange: 'transform' }} />
        </div>
        )}

        {/* 10 — Inner shadow — mobile only (desktop loaded gets it from panel boxShadow). */}
        {!isDesktop && (
        <div style={{
          position: 'absolute', inset: 0, borderRadius: 0,
          pointerEvents: 'none', boxShadow: VIEWFINDER_INNER_SHADOW, zIndex: 10,
          opacity: hasImage ? 1 : 0.65,
        }} />
        )}

        {/* 9b — Glass overlay — desktop loaded. Lens vignette + key light reflection over photo. */}
        {isDesktop && hasImage && (
        <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 9, pointerEvents: 'none' }}>
          <div style={{ position: 'absolute', inset: 0, background: LENS_VIGNETTE }} />
          <div style={DITHER_STYLE} />
          <div style={{
            position: 'absolute', top: 0, left: 0, right: '5%', bottom: 0,
            background: GLASS_REFLECTION, opacity: 0.72,
            transform: glassReflectionTransform(tilt), willChange: 'transform',
          }} />
        </div>
        )}

        {/* 10b — Bezel depth shadow — desktop loaded only. Body overhangs the recessed LCD. */}
        {isDesktop && hasImage && (
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 11,
          background: [
            'linear-gradient(to bottom, rgba(0,0,0,0.80) 0%, rgba(0,0,0,0.45) 7%, rgba(0,0,0,0.14) 18%, transparent 30%)',
            'linear-gradient(to top,   rgba(0,0,0,0.60) 0%, rgba(0,0,0,0.28) 7%, rgba(0,0,0,0.08) 16%, transparent 28%)',
            'linear-gradient(to right, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0.30) 7%, rgba(0,0,0,0.08) 16%, transparent 26%)',
            'linear-gradient(to left,  rgba(0,0,0,0.45) 0%, rgba(0,0,0,0.18) 7%, transparent 20%)',
          ].join(', '),
        }} />
        )}
        {/* 10c — Chamfer highlights — desktop loaded only. Key-light catch on top-left bezel edge.
            Must sit above 10b (bezel depth shadow) so the highlights aren't swallowed by the dark edge gradient. */}
        {isDesktop && hasImage && (<>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, zIndex: 12, pointerEvents: 'none',
            background: 'linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.04) 35%, rgba(255,255,255,0.01) 100%)',
          }} />
          <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 1, zIndex: 12, pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.03) 35%, transparent 65%)',
          }} />
          <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 1, zIndex: 12, pointerEvents: 'none',
            background: 'linear-gradient(90deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.18) 50%, transparent 100%)',
          }} />
          <div style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 1, zIndex: 12, pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 50%, transparent 100%)',
          }} />
        </>)}

        {/* 11 — Teach glow — first-session pulsing edge glow to draw the eye to the VF.
             Gentle steel-blue inner border that breathes, says "this is where your photo goes"
             without words. Fades in after 1s, loops until a photo is loaded. */}
        {showTeach && !hasImage && !urlLoadError && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 11,
            pointerEvents: 'none',
            boxShadow: [
              'inset 0 0 20px rgba(132,158,184,0.12)',
              'inset 0 0 40px rgba(132,158,184,0.06)',
            ].join(', '),
            animation: 'teachGlow 2.8s ease-in-out infinite',
            opacity: 0,
          }} />
        )}
      </div>

      {/* Sound / haptic / daylight toggles moved to Settings screen */}

      {/* ── Mobile-only: button trough, well, analyze button, sample CTA, teach ──
           On desktop these controls live in the right panel. */}
      {!isDesktop && <>
      {/* ── LCD spill — warm light leaking from upper-left from under viewfinder glass ── */}
      <div style={{
        position: 'absolute', top: VF_TOP + 20, left: 10, right: 10, height: VF_HEIGHT - 30,
        pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 95% 75% at 35% 40%, rgba(255,210,150,0.050) 0%, rgba(255,195,120,0.025) 40%, transparent 80%)',
        opacity: lcdOn ? 1 : 0,
        transition: 'opacity 1.4s ease',
      }} />

      {/* ── Vertical rhythm line — connects VF center to dome.
           Faint descending gradient that ties the composition together.
           Only visible on empty state — photo replaces it. */}
      {!hasImage && (
        <div style={{
          position: 'absolute',
          left: '50%', width: 1,
          top: Math.round(stableVH * 0.52),
          bottom: stableVH - BTN_TOP + 20,
          transform: 'translateX(-0.5px)',
          background: `linear-gradient(180deg, ${steel(0.08)} 0%, ${steel(0.14)} 50%, transparent 100%)`,
          pointerEvents: 'none', zIndex: 2,
          animation: 'ghostFadeIn 1.5s ease 0.8s both',
        }} />
      )}

      {/* ── Analyze Track ── */}
      <div
        role="button"
        aria-label={hasImage ? 'Analyze' : hasLastResult ? 'Select image — long-press to view last result' : 'Select image'}
        onClick={handleButtonClick}
        onMouseDown={handleButtonPress}
        onMouseUp={handleButtonRelease}
        onMouseLeave={handleButtonRelease}
        onTouchStart={handleButtonPress}
        onTouchEnd={handleButtonRelease}
        onTouchCancel={handleButtonRelease}
        onContextMenu={(e) => e.preventDefault()}
        style={{
          position: 'absolute', left: '50%', top: TRK_TOP, width: TRK_D, height: TRK_D, transform: 'translateX(-50%)',
          cursor: 'pointer', WebkitTapHighlightColor: 'transparent', userSelect: 'none',
        }}
      >
        {/* Ring track — when alive, the whole ring pulses via filter: brightness().
            This is the cleanest coordination: the actual LED ring SVG dims and
            flares, no overlays needed. */}
        <img
          src={trackSrc}
          alt=""
          style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%',
            animation: (hasImage && !isPressed
              && effectiveUiState !== 'loading'
              && effectiveUiState !== 'error'
              && effectiveUiState !== 'idle')
              ? effectiveUiState === 'hasResult'
                ? 'ringAliveGreenPulse 2.4s linear infinite'
                : 'ringAlivePulse 2.4s linear infinite'
              : 'none',
          }}
        />
        {/* Upper-left light catch — matches viewfinder 141.71° direction */}
        <div style={{
          position: 'absolute', inset: 0, borderRadius: '50%', pointerEvents: 'none',
          background: 'linear-gradient(141.71deg, rgba(255,255,255,0.10) 0%, transparent 35%, transparent 65%, rgba(0,0,0,0.15) 100%)',
        }} />
      </div>

      {/* Trough + Well removed — full-bleed layout means the dome floats
           directly on the photo/VF with just the gradient scrim for grounding.
           The machined cavity was designed for the old contained-slot layout. */}

      {/* ── Bottom scrim — grounds the dome on full-bleed photo.
           Faint gradient fade so the button never floats on raw highlights. */}
      <div style={{
        position: 'absolute',
        left: 0, right: 0,
        bottom: 0,
        height: Math.round(stableVH * 0.32),
        background: 'linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.35) 60%, rgba(0,0,0,0.55) 100%)',
        pointerEvents: 'none', zIndex: 3,
        opacity: hasImage ? 1 : 0,
        transition: 'opacity 0.6s ease',
      }} />

      {/* ── Analyze Button — Figma spec (rgba(31,34,42) face; drop+inner shadow; sunk on press) ── */}
      <div
        role="button"
        onClick={handleButtonClick}
        onMouseDown={handleButtonPress}
        onMouseUp={handleButtonRelease}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => { setIsHovered(false); handleButtonRelease(); }}
        onTouchStart={handleButtonPress}
        onTouchEnd={handleButtonRelease}
        onTouchCancel={handleButtonRelease}
        onContextMenu={(e) => e.preventDefault()}
        style={{
          position: 'absolute', left: '50%', top: BTN_TOP, width: BTN_D, height: BTN_D,
          transform: btnTransform,
          cursor: 'pointer', WebkitTapHighlightColor: 'transparent', userSelect: 'none',
          borderRadius: '50%', willChange: 'transform',
          // Face surface states — ring/track never move, only the face interior responds
          // idle:    full outer drop stack + directional gradient; face floats above well floor
          // alive:   same but top-left specular slightly brighter — image is loaded, ready to fire
          // hover:   outer drop collapses, inset deepens — face skin compresses under cursor
          // pressed: maximum inset + deepest gradient; mechanism has fired
          background: buttonState === 'pressed'
            ? 'linear-gradient(141.71deg, #020304 0%, #040506 50%, #060708 100%)'
            : isHovered
              ? 'linear-gradient(141.71deg, #010102 0%, #020304 50%, #030405 100%)'
              : buttonState === 'alive'
                ? 'linear-gradient(141.71deg, #343d52 0%, #1c2438 50%, #080a10 100%)'
                : 'linear-gradient(141.71deg, #242a34 0%, #131720 50%, #06080c 100%)',
          boxShadow: buttonState === 'pressed'
            ? [
                // Outer near-zero — button is seated; floor contact only
                '2px 2px 6px rgba(0,0,0,0.70)',
                // Well rim fully eclipses button edge — perimeter shadows, small blur, not blurry center
                'inset 0 3px 8px rgba(0,0,0,0.92)',   // top-left key fully blocked
                'inset 3px 0 7px rgba(0,0,0,0.70)',   // left key blocked
                'inset -2px -2px 6px rgba(0,0,0,0.55)', // bottom-right in deep shadow
                'inset 0 1px 2px rgba(0,0,0,0.80)',   // crisp top-edge dark — no specular
              ].join(', ')
            : isHovered
              ? [
                  // Outer drop collapses — button deep in well
                  '3px 3px 8px rgba(0,0,0,0.80)',
                  '1px 1px 3px rgba(0,0,0,0.60)',
                  // Well rim heavily eclipses all edges — deep perimeter shadows
                  'inset 0 5px 12px rgba(0,0,0,0.96)',   // top rim kills key light
                  'inset 5px 0 10px rgba(0,0,0,0.78)',   // left rim kills key light
                  'inset -3px -3px 8px rgba(0,0,0,0.70)', // bottom-right fully shadowed
                  'inset 0 2px 4px rgba(0,0,0,0.88)',    // hard top-edge contact shadow
                  // No chamfer highlight — well rim has fully blocked the key
                  'inset 0 1px 0 rgba(0,0,0,0.60)',
                ].join(', ')
              : buttonState === 'alive'
                ? [
                    // Alive — button raised 3px above well floor; deeper drops cast further
                    '14px 14px 36px rgba(0,0,0,0.98)',
                    '7px 7px 18px rgba(0,0,0,0.86)',
                    '3px 3px 7px rgba(0,0,0,0.65)',
                    // Stronger top-left edge catch — elevated surface intercepts key light
                    '-2px -2px 4px rgba(255,255,255,0.11)',
                    // Brighter inner chamfer — top face is angled toward the key
                    'inset 0 2px 0 rgba(255,255,255,0.22)',
                    'inset 2px 0 0 rgba(255,255,255,0.13)',
                    'inset -1px -1px 0 rgba(0,0,0,0.55)',
                  ].join(', ')
                : [
                    // Idle — X:Y matched to 141.71° diagonal
                    '12px 12px 32px rgba(0,0,0,0.96)',
                    '6px 6px 14px rgba(0,0,0,0.82)',
                    '2px 2px 6px rgba(0,0,0,0.60)',
                    // Outer side-wall catch — visible edge highlight
                    '-1px -1px 3px rgba(255,255,255,0.08)',
                    // Inner chamfer — polished machined edge catches key light
                    'inset 0 2px 0 rgba(255,255,255,0.18)',
                    'inset 2px 0 0 rgba(255,255,255,0.10)',
                    // Bottom-right chamfer — in shadow
                    'inset -1px -1px 0 rgba(0,0,0,0.65)',
                  ].join(', '),
          animation: buttonState === 'pressed' || isHovered ? 'none' : 'btnBreath 5.2s cubic-bezier(0.42,0.00,0.20,1.00) infinite',
          transition: btnTransition,
        }}
      >
      </div>

      {/* ── LED ring — directional arc lit top-left; colour tracks uiState ── */}
      <div style={{
        position: 'absolute', left: '50%', top: BTN_TOP, width: BTN_D, height: BTN_D,
        transform: btnTransform, borderRadius: '50%', pointerEvents: 'none',
        willChange: 'transform',
        boxShadow: ringBoxShadow,
        animation: ringAnimation,
        transition: `${btnTransition}, box-shadow 0.35s ease`,
      }} />

      {/* Activity Indicator dot removed — too many lights */}

      {/* ── Analyze label — engraved instrument lettering.
           All-caps, wide tracking, medium weight — reads like a precision
           control label, not a software button. */}
      <p style={{
        position: 'absolute',
        top: LBL_TOP, left: '50%', width: BTN_D,
        transform: lblTransform,
        margin: 0, fontWeight: 700, fontSize: isDesktop ? 14 : 13, lineHeight: '16px',
        color: analyzeText, letterSpacing: isDesktop ? '3px' : '2.5px', textShadow: analyzeGlow,
        textTransform: 'uppercase',
        textAlign: 'center', whiteSpace: 'nowrap', pointerEvents: 'none',
        transition: `color 0.18s ease, transform ${buttonState === 'pressed' ? '0.06s cubic-bezier(0.25,0.46,0.45,0.94)' : '0.22s cubic-bezier(0.34,1.56,0.64,1)'}`,
        WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale',
      }}>{analyzeLabel}</p>

      {/* ── Phase-2 teach tooltip — appears briefly after first photo load ──
           Tells the user what the big button does now that they've loaded a photo.
           Auto-fades after 4s. Positioned above the button for clear association. */}
      {showBtnTeach && (
        <div style={{
          position: 'absolute',
          top: WELL_TOP - 36,
          left: 0, right: 0,
          display: 'flex', justifyContent: 'center',
          pointerEvents: 'none', zIndex: 30,
          animation: 'teachTooltipIn 0.5s ease both, teachTooltipOut 0.6s ease 3.4s forwards',
        }}>
          <div style={{
            padding: '6px 16px',
            borderRadius: 12,
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.12)',
            boxShadow: '0 2px 12px rgba(0,0,0,0.5)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
          }}>
            <p style={{
              margin: 0,
              fontSize: 12, fontWeight: 600, letterSpacing: '0.2px',
              color: 'rgba(245,247,250,0.90)',
              textShadow: '0 1px 2px rgba(0,0,0,0.7)',
              WebkitFontSmoothing: 'antialiased', MozOsxFontSmoothing: 'grayscale',
              textRendering: 'geometricPrecision',
              whiteSpace: 'nowrap',
            }}>Tap to see how it was lit</p>
          </div>
          {/* Small caret pointing down to the button */}
          <div style={{
            position: 'absolute', bottom: -5, left: '50%', transform: 'translateX(-50%)',
            width: 0, height: 0,
            borderLeft: '5px solid transparent',
            borderRight: '5px solid transparent',
            borderTop: '5px solid rgba(255,255,255,0.10)',
          }} />
        </div>
      )}

      {/* ── Below-dome CTA zone — two lanes: Build (bordered pill) + Sample (text link) ──
           Build pill is a proper button with border/background — secondary to dome but
           clearly more discoverable than a text link. Sample link remains available as
           a soft secondary. Both hidden once a photo is loaded. */}
      {!hasImage && !profileOpen && (
        <div
          style={{
            position: 'absolute',
            top: BTN_TOP + BTN_D + 10,
            left: 0, right: 0,
            display: 'flex', justifyContent: 'center', alignItems: 'center',
            gap: 14,
            zIndex: 8,
            animation: showTeach ? 'ghostFadeIn 0.8s ease 1.2s both' : 'none',
          }}
        >
          {/* Build pill — bordered button, secondary weight but clear affordance */}
          {!isDesktop && onBuildWizard && (
            <div
              onClick={() => {
                tapHaptic();
                softClickSound();
                trackEvent('HOME_BUILD_ENTRY', { source: 'secondary_cta' });
                onBuildWizard();
              }}
              style={{
                display: 'flex', alignItems: 'center',
                padding: '7px 18px',
                borderRadius: 20,
                border: `1px solid ${steel(0.22)}`,
                background: 'rgba(167,173,183,0.04)',
                cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
                flexShrink: 0,
              }}
            >
              <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.6px', color: steel(0.54), ...FONT_SMOOTH }}>
                Build from Intent ›
              </span>
            </div>
          )}
          {/* Vertical rule separator — only when both entries visible */}
          {!isDesktop && onBuildWizard && (
            <span style={{ width: 1, height: 12, background: steel(0.15), display: 'block', flexShrink: 0 }} />
          )}
          {/* Sample link — soft secondary, existing behavior unchanged */}
          <p
            onClick={loadSample}
            style={{
              margin: 0,
              fontSize: 13, fontWeight: 600, letterSpacing: '0.4px',
              color: sampleLoading ? steel(0.30) : steel(0.40),
              cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
              opacity: sampleLoading ? 0.5 : 1,
              transition: 'opacity 0.25s ease',
              ...FONT_SMOOTH,
            }}
          >
            {sampleLoading ? 'Loading…' : 'Try a sample →'}
          </p>
          {/* Gate Zero G0.3 — the accuracy claim must be auditable before
              signup. Leads to every scored reference read, misses included. */}
          {onAccuracy && (
            <>
              <span style={{ width: 1, height: 12, background: steel(0.15), display: 'block', flexShrink: 0 }} />
              <p
                onClick={() => { softClickSound(); tapHaptic(); onAccuracy(); }}
                style={{
                  margin: 0,
                  fontSize: 13, fontWeight: 600, letterSpacing: '0.4px',
                  color: steel(0.40),
                  cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
                  ...FONT_SMOOTH,
                }}
              >How accurate? →</p>
            </>
          )}
        </div>
      )}

      {/* ── Last result indicator — subtle chip when a prior result exists ── */}
      {!isDesktop && hasLastResult && !hasImage && (
        <div
          onClick={() => { if (onViewLastResult) { softClickSound(); tapHaptic(); onViewLastResult(); } }}
          style={{
            position: 'absolute',
            top: BTN_TOP - 36,
            left: '50%', transform: 'translateX(-50%)',
            padding: '5px 14px', borderRadius: 20,
            background: 'rgba(72,186,136,0.12)',
            border: '1px solid rgba(72,186,136,0.25)',
            cursor: 'pointer',
            zIndex: 8,
            display: 'flex', alignItems: 'center', gap: 6,
            WebkitTapHighlightColor: 'transparent',
            animation: 'ghostFadeIn 0.6s ease 0.5s both',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: 'rgba(72,186,136,0.75)' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'rgba(72,186,136,0.80)', letterSpacing: '0.3px', ...FONT_SMOOTH }}>
            Last read
          </span>
        </div>
      )}

      {/* ── Spotlight coach-marks — first-time user walkthrough ──────────────
           Semi-transparent scrim with spotlight cutout over the active UI element.
           Tooltip floats near the spotlight target. Tap anywhere to advance.
           Step 0: Viewfinder — "Tap here to load your photo"
           Step 1: Analyze button — "Then tap to analyze the lighting"
           Step 2: Sample CTA — "Or try a sample to see it in action" */}
      {teachVisible && (() => {
        // Spotlight geometry — position the cutout over the target element
        // Column may be narrower than 430px on small viewports
        const COL_W = Math.min(430, window.innerWidth);
        const COL_CX = Math.round(COL_W / 2);
        // Full-bleed viewport: VF fills 0→stableVH. Spotlight targets
        // are absolute pixel positions. Cards sit near VF center (~35%).
        const vhCenter = Math.round(stableVH * 0.35);
        const spotlights = [
          { // Step 0: IMPORT icon — center of viewport
            x: COL_CX - 60, y: Math.round(stableVH * 0.28), w: 120, h: 100, r: 18,
            title: 'Recreate any light you see',
            desc: 'Drop in a portrait you want to reverse-engineer.',
            tipY: Math.round(stableVH * 0.28) + 120,
            arrow: 'up',
          },
          { // Step 1: Analyze button — dome at bottom
            x: COL_CX - BTN_D / 2 - 10, y: BTN_TOP - 10, w: BTN_D + 20, h: BTN_D + 20, r: BTN_D,
            title: 'Get the exact setup',
            desc: 'Pattern, modifier, distance, height — decoded.',
            tipY: vhCenter,
            arrow: 'down',
          },
          { // Step 2: Sample CTA — below dome
            x: COL_CX - 155, y: BTN_TOP + BTN_D + 2, w: 310, h: 48, r: 24,
            title: 'See it in action',
            desc: 'We\'ll analyze a Rembrandt portrait for you.',
            tipY: vhCenter,
            arrow: 'down',
          },
        ];
        const s = spotlights[teachStep] || spotlights[0];
        // Clamp tooltip to viewport — prevent clipping on short screens
        const CARD_H = 170;
        const maxTipY = stableVH - safeBottom - CARD_H - 8;
        const minTipY = safeBottom + 8;
        s.tipY = Math.max(minTipY, Math.min(maxTipY, s.tipY));
        s.y = Math.max(0, Math.min(stableVH - safeBottom - s.h, s.y));

        // Spotlight center for radial clip
        const cx = s.x + s.w / 2;
        const cy = s.y + s.h / 2;
        const rx = s.w / 2 + 14; // padding around spotlight
        const ry = s.h / 2 + 14;
        // Step-specific accent color: steel → indigo-blue → green
        const stepColors = ['rgba(132,158,184,1)', 'rgba(107,148,245,1)', 'rgba(72,186,136,1)'];
        const sc = stepColors[teachStep] || stepColors[0];

        // Arrow geometry — computed once, used by SVG
        // Steps 1 & 2: card shifted left so arrow arcs naturally to centered spotlight
        const cardLeft = s.arrow === 'down' ? 16 : 24;
        const cardRight = s.arrow === 'down' ? 16 : 24;
        const cardW = COL_W - cardLeft - cardRight;
        const cardCX = cardLeft + cardW / 2;
        const cardEdgeY = s.arrow === 'up' ? s.tipY : s.tipY + 72;
        // Arrow tip lands at spotlight edge (bottom edge for up-arrows, top edge for down)
        const tipYA = s.arrow === 'up' ? (s.y + s.h) : s.y;
        const svgTop = Math.min(tipYA, cardEdgeY) - 10;
        const svgBot = Math.max(tipYA, cardEdgeY) + 10;
        const svgH = svgBot - svgTop;
        const startLY = cardEdgeY - svgTop;
        const endLY = tipYA - svgTop;
        // Natural arc: card is left-offset, spotlight centered — modest rightward curve
        const cpOffset = s.arrow === 'up' ? 30 : 20;
        const cpX = (cardCX + cx) / 2 + cpOffset;
        const cpY1 = startLY + (endLY - startLY) * 0.3;
        const cpY2 = startLY + (endLY - startLY) * 0.7;
        const curvePath = `M${cardCX} ${startLY} C${cpX} ${cpY1}, ${cpX} ${cpY2}, ${cx} ${endLY}`;
        const aSize = 8;
        const aDir = s.arrow === 'up' ? -1 : 1;
        // Arrowhead chevron at the curve endpoint (spotlight edge)
        // Chevron centered on endpoint: tip extends past, arms behind
        const aHalf = aSize / 2;
        const aPath = `M${cx - aSize} ${endLY - aHalf * aDir} L${cx} ${endLY + aHalf * aDir} L${cx + aSize} ${endLY - aHalf * aDir}`;
        // Approximate curve length for stroke-dasharray draw-on animation
        const curveLen = Math.hypot(cx - cardCX, endLY - startLY) * 1.4;

        return (
          <div
            onClick={advanceTeach}
            style={{
              position: 'absolute', inset: 0, zIndex: 50,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              animation: teachStep >= 3 ? 'teachOverlayOut 0.5s ease forwards' : 'teachOverlayIn 0.6s ease both',
            }}
          >
            {/* Scrim — crisp spotlight cutout, deep surrounding dim */}
            <div style={{
              position: 'absolute', inset: 0,
              background: `radial-gradient(ellipse ${rx * 2}px ${ry * 2}px at ${cx}px ${cy}px, transparent 0%, transparent 38%, rgba(0,0,0,0.42) 50%, rgba(0,0,0,0.62) 66%, rgba(0,0,0,0.72) 100%)`,
              transition: 'background 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />

            {/* Volumetric light bloom — soft radial glow behind the spotlight (studio light metaphor) */}
            <div style={{
              position: 'absolute',
              left: cx - 100, top: cy - 100,
              width: 200, height: 200,
              borderRadius: '50%',
              background: `radial-gradient(circle, ${sc.replace(/[\d.]+\)$/, '0.06)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.02)')} 40%, transparent 70%)`,
              pointerEvents: 'none',
              animation: 'teachBloom 3s ease-in-out infinite',
              transition: 'left 0.55s cubic-bezier(0.4,0,0.2,1), top 0.55s cubic-bezier(0.4,0,0.2,1)',
            }} />

            {/* Outer glow ring — soft halo, step-colored */}
            <div style={{
              position: 'absolute',
              left: s.x - 14, top: s.y - 14,
              width: s.w + 28, height: s.h + 28,
              borderRadius: s.r ? s.r + 14 : 14,
              border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.12)')}`,
              boxShadow: `0 0 44px ${sc.replace(/[\d.]+\)$/, '0.12)')}, 0 0 18px ${sc.replace(/[\d.]+\)$/, '0.06)')}, inset 0 0 20px ${sc.replace(/[\d.]+\)$/, '0.05)')}`,
              pointerEvents: 'none',
              // Starts still, then pulses after arrow draw-on (0.9s delay)
              animation: 'teachSpotlightPulse 2s ease-in-out 0.9s infinite',
              transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />

            {/* Inner spotlight ring — crisp border, pulses after arrow arrives */}
            <div style={{
              position: 'absolute',
              left: s.x - 3, top: s.y - 3,
              width: s.w + 6, height: s.h + 6,
              borderRadius: s.r ? s.r + 3 : 3,
              border: `1.5px solid ${sc.replace(/[\d.]+\)$/, '0.50)')}`,
              boxShadow: `0 0 20px ${sc.replace(/[\d.]+\)$/, '0.22)')}, 0 0 6px ${sc.replace(/[\d.]+\)$/, '0.12)')}, inset 0 0 10px ${sc.replace(/[\d.]+\)$/, '0.08)')}`,
              pointerEvents: 'none',
              animation: 'teachSpotlightPulse 2s ease-in-out 1.1s infinite',
              transition: 'all 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
            }} />

            {/* ── Compact tooltip chip — glass card with animated border ── */}
            <div key={teachStep} style={{
              position: 'absolute',
              top: s.tipY,
              left: cardLeft, right: cardRight,
              animation: 'teachCardSpring 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) both',
            }}>
              {/* Animated border glow — conic-gradient sweep */}
              <div style={{
                position: 'absolute', inset: -1,
                borderRadius: 15,
                background: `conic-gradient(from var(--teach-border-angle, 0deg), ${sc.replace(/[\d.]+\)$/, '0.00)')}, ${sc.replace(/[\d.]+\)$/, '0.18)')}, ${sc.replace(/[\d.]+\)$/, '0.00)')}, ${sc.replace(/[\d.]+\)$/, '0.10)')}, ${sc.replace(/[\d.]+\)$/, '0.00)')})`,
                animation: 'teachBorderSweep 4s linear infinite',
                opacity: 0.7,
                pointerEvents: 'none',
              }} />
              <div style={{
                position: 'relative',
                padding: '24px 28px 20px',
                borderRadius: 18,
                backgroundColor: 'rgba(10,11,14,0.92)',
                border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.08)')}`,
                boxShadow: [
                  '0 8px 32px rgba(0,0,0,0.55)',
                  '0 2px 8px rgba(0,0,0,0.35)',
                  `0 0 0 0.5px ${sc.replace(/[\d.]+\)$/, '0.06)')}`,
                  'inset 0 1px 0 rgba(255,255,255,0.07)',
                  'inset 0 -1px 0 rgba(0,0,0,0.2)',
                ].join(', '),
                backdropFilter: 'blur(20px) saturate(1.3)',
                WebkitBackdropFilter: 'blur(20px) saturate(1.3)',
              }}>
                {/* Two-row layout: large text block on top, icon + action on bottom */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {/* Top: large headline + description */}
                  <div>
                    <p style={{
                      margin: 0, fontSize: 22, fontWeight: 800, lineHeight: '26px',
                      color: 'rgba(245,247,250,0.96)',
                      letterSpacing: '-0.4px',
                      ...FONT_SMOOTH,
                    }}>{s.title}</p>
                    <p style={{
                      margin: '6px 0 0', fontSize: 16, fontWeight: 500, lineHeight: '22px',
                      color: 'rgba(184,191,199,0.72)',
                      ...FONT_SMOOTH,
                    }}>{s.desc}</p>
                  </div>
                  {/* Bottom row: animated icon + action pill */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Icon badge — 52px, animated with glow */}
                  <div style={{
                    width: 52, height: 52, flexShrink: 0,
                    borderRadius: 14,
                    background: `linear-gradient(145deg, ${sc.replace(/[\d.]+\)$/, '0.14)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.03)')} 100%)`,
                    border: `1px solid ${sc.replace(/[\d.]+\)$/, '0.16)')}`,
                    boxShadow: `inset 0 1px 0 ${sc.replace(/[\d.]+\)$/, '0.08)')}, 0 2px 6px rgba(0,0,0,0.25)`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    animation: 'teachIconFloat 3s ease-in-out infinite',
                  }}>
                    {teachStep === 0 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'teachIconGlow 2s ease-in-out infinite' }}>
                        <path d="M5 11V7a2 2 0 012-2h4" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="2" strokeLinecap="round" />
                        <path d="M21 5h4a2 2 0 012 2v4" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="2" strokeLinecap="round" />
                        <path d="M27 21v4a2 2 0 01-2 2h-4" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="2" strokeLinecap="round" />
                        <path d="M11 27H7a2 2 0 01-2-2v-4" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="2" strokeLinecap="round" />
                        <g style={{ animation: 'teachArrowBounce 1.8s ease-in-out infinite' }}>
                          <path d="M16 10v8" stroke={sc.replace(/[\d.]+\)$/, '0.55)')} strokeWidth="1.5" strokeLinecap="round" />
                          <path d="M13 15l3 3 3-3" stroke={sc.replace(/[\d.]+\)$/, '0.55)')} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </g>
                      </svg>
                    )}
                    {teachStep === 1 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'teachIconGlow 2s ease-in-out infinite' }}>
                        <path d="M16 8C10 8 5.2 11.5 3 16c2.2 4.5 7 8 13 8s10.8-3.5 13-8c-2.2-4.5-7-8-13-8z" stroke={sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" fill="none" />
                        <circle cx="16" cy="16" r="4" stroke={sc.replace(/[\d.]+\)$/, '0.65)')} strokeWidth="1.8" fill="none" />
                        <circle cx="16" cy="16" r="1.5" fill={sc.replace(/[\d.]+\)$/, '0.50)')} />
                      </svg>
                    )}
                    {teachStep === 2 && (
                      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" style={{ animation: 'teachIconGlow 2s ease-in-out infinite' }}>
                        <circle cx="16" cy="16" r="12" stroke={sc.replace(/[\d.]+\)$/, '0.30)')} strokeWidth="1.6" fill="none" />
                        <path d="M17 6L9 18h6l-1 8 8-12h-6l1-8z" stroke={sc.replace(/[\d.]+\)$/, '0.70)')} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill={sc.replace(/[\d.]+\)$/, '0.08)')} />
                      </svg>
                    )}
                  </div>

                  <div style={{ flex: 1 }} />
                  {/* Action pill — elevated */}
                  <div
                    onClick={(e) => { e.stopPropagation(); advanceTeach(); }}
                    style={{
                      flexShrink: 0,
                      padding: '8px 18px',
                      borderRadius: 10,
                      background: `linear-gradient(135deg, ${sc.replace(/[\d.]+\)$/, '0.16)')} 0%, ${sc.replace(/[\d.]+\)$/, '0.06)')} 100%)`,
                      border: `1px solid ${sc.replace(/[\d.]+\)$/, teachStep < 2 ? '0.18)' : '0.26)')}`,
                      boxShadow: `0 2px 8px rgba(0,0,0,0.3), inset 0 1px 0 ${sc.replace(/[\d.]+\)$/, '0.06)')}`,
                      cursor: 'pointer',
                      transition: 'transform 0.15s ease, box-shadow 0.15s ease',
                    }}
                  >
                    <p style={{
                      margin: 0, fontSize: 16, fontWeight: 700, letterSpacing: '0.4px',
                      color: sc.replace(/[\d.]+\)$/, teachStep < 2 ? '0.90)' : '0.95)'),
                      ...FONT_SMOOTH,
                      whiteSpace: 'nowrap',
                    }}>{teachStep < 2 ? 'Next →' : 'Try it →'}</p>
                  </div>
                  </div>{/* close bottom row */}
                </div>{/* close two-row layout */}

                {/* Progress track + skip */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  marginTop: 8,
                }}>
                  {/* Animated progress track */}
                  <div style={{
                    flex: 1, maxWidth: 80, height: 3, borderRadius: 2,
                    backgroundColor: 'rgba(255,255,255,0.05)',
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${((teachStep + 1) / 3) * 100}%`,
                      height: '100%', borderRadius: 2,
                      background: `linear-gradient(90deg, ${sc.replace(/[\d.]+\)$/, '0.35)')}, ${sc.replace(/[\d.]+\)$/, '0.60)')})`,
                      transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1), background 0.5s ease',
                      boxShadow: `0 0 6px ${sc.replace(/[\d.]+\)$/, '0.20)')}`,
                    }} />
                  </div>
                  {/* Step count */}
                  <span style={{
                    fontSize: 9, fontWeight: 600, letterSpacing: '0.5px',
                    color: sc.replace(/[\d.]+\)$/, '0.35)'),
                    marginLeft: 8,
                    ...FONT_SMOOTH,
                  }}>{teachStep + 1}/3</span>
                  <div style={{ flex: 1 }} />
                  {teachStep < 2 && (
                    <button
                      onClick={(e) => { e.stopPropagation(); skipTeach(); }}
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0',
                        fontSize: 10, fontWeight: 600,
                        color: steel(0.24),
                        WebkitTapHighlightColor: 'transparent',
                        ...FONT_SMOOTH,
                      }}
                    >Skip</button>
                  )}
                </div>
              </div>
            </div>

            {/* "Tap anywhere" hint — delayed entry */}
            <p style={{
              position: 'absolute', bottom: 14, left: 0, right: 0,
              textAlign: 'center', margin: 0,
              fontSize: 10, fontWeight: 500, letterSpacing: '0.5px',
              color: steel(0.22),
              ...FONT_SMOOTH,
              animation: 'teachStepFade 0.6s ease 1s both',
              pointerEvents: 'none',
            }}>Tap anywhere to continue</p>

            {/* Dynamic arrow — draws itself from card → spotlight with animated stroke */}
            <svg key={`arrow-${teachStep}`} style={{
              position: 'absolute', left: 0, top: svgTop,
              width: COL_W, height: svgH,
              pointerEvents: 'none', overflow: 'visible',
              filter: `drop-shadow(0 0 10px ${sc.replace(/[\d.]+\)$/, '0.35)')})`,
            }}>
              {/* Glow trail — wide soft stroke */}
              <path d={curvePath} stroke={sc.replace(/[\d.]+\)$/, '0.12)')}
                strokeWidth="8" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen}
                strokeDashoffset={curveLen}
                style={{ animation: `teachDrawOn 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.2s forwards` }} />
              {/* Main stroke — medium, colored */}
              <path d={curvePath} stroke={sc.replace(/[\d.]+\)$/, '0.75)')}
                strokeWidth="2.5" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen}
                strokeDashoffset={curveLen}
                style={{ animation: `teachDrawOn 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.25s forwards` }} />
              {/* Highlight edge — thin white */}
              <path d={curvePath} stroke="rgba(255,255,255,0.12)"
                strokeWidth="1" strokeLinecap="round" fill="none"
                strokeDasharray={curveLen}
                strokeDashoffset={curveLen}
                style={{ animation: `teachDrawOn 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.3s forwards` }} />
              {/* Arrowhead — slides from card base along curve to endpoint */}
              <style>{`
                @keyframes teachArrowSlide${teachStep} {
                  0%   { opacity: 0.4; transform: translate(${cardCX - cx}px, ${startLY - endLY}px) scale(0.7); }
                  40%  { opacity: 1; }
                  100% { opacity: 1; transform: translate(0, 0) scale(1); }
                }
              `}</style>
              <g style={{
                opacity: 0,
                animation: `teachArrowSlide${teachStep} 0.7s cubic-bezier(0.4, 0, 0.2, 1) 0.2s forwards`,
              }}>
                <g style={{ animation: 'teachArrowBounce 1.4s ease-in-out 1.1s infinite' }}>
                  {/* Glow halo behind arrowhead */}
                  <circle cx={cx} cy={endLY} r="12" fill={sc.replace(/[\d.]+\)$/, '0.08)')} />
                  <path d={aPath} stroke={sc.replace(/[\d.]+\)$/, '0.95)')}
                    strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  <path d={aPath} stroke="rgba(255,255,255,0.22)"
                    strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                </g>
              </g>
            </svg>
          </div>
        );
      })()}
      </>}
      {/* end !isDesktop mobile-only block */}

      {/* ── Desktop right panel ── */}
      {desktopRightPanel}

      {/* ── Desktop dock — ghost text links (token: NAV_GHOST) ── */}
      {!hasImage && isDesktop && (
        <div style={{
          position: 'absolute', bottom: 32, left: '50%', transform: 'translateX(-50%)',
          display: 'flex', alignItems: 'center',
          gap: 6, pointerEvents: 'auto', zIndex: 9,
        }}>
          {[
            { label: 'Recipes', action: onRecipes },
            { label: 'Saved Setups', action: onSavedSetups },
            { label: 'Build a Setup', action: () => { trackEvent('HOME_BUILD_ENTRY', { source: 'desktop_action_row' }); onBuildWizard(); } },
            { label: 'My Kit', action: onMyKit },
            { label: 'Journal', action: onSessionLog },
            { label: 'Look Library', action: onLookLibrary },
            { label: 'From Video', action: onVideoCapture },
          ].map((item, i) => (
            <Fragment key={item.label}>
              {i > 0 && (
                <span style={{ color: NAV_DOT.color, fontSize: NAV_DOT.fontSize, userSelect: 'none' }}>·</span>
              )}
              <button onClick={() => { item.action?.(); softClickSound(); tapHaptic(); }}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  padding: '6px 10px',
                  fontSize: NAV_GHOST.fontSize, fontWeight: NAV_GHOST.fontWeight,
                  letterSpacing: NAV_GHOST.letterSpacing,
                  color: NAV_GHOST.color,
                  transition: 'color 0.2s ease',
                  WebkitTapHighlightColor: 'transparent',
                  ...FONT_SMOOTH,
                }}
                onMouseEnter={e => { e.currentTarget.style.color = NAV_GHOST.hoverColor; }}
                onMouseLeave={e => { e.currentTarget.style.color = NAV_GHOST.color; }}
              >
                {item.label}
              </button>
            </Fragment>
          ))}
        </div>
      )}

      {/* ── State animation keyframes ── */}
      <style>{`
        /* Desktop button hover — physical lift with spring easing.
           The button face rises out of its well on hover (shadow deepens),
           sinks on press (shadow collapses, inset appears). */
        .sm-btn-lift {
          transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1),
                      box-shadow 0.22s ease,
                      filter 0.18s ease;
        }
        .sm-btn-lift:hover {
          transform: translateY(-2px);
          filter: brightness(1.08);
        }
        .sm-btn-lift:active {
          transform: translateY(1px);
          filter: brightness(0.92);
          transition: transform 0.06s ease, filter 0.06s ease;
        }
        @keyframes ghostFadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        /* wordmarkFade removed — wordmark stays visible in empty state */
        @keyframes hudFadeDown {
          from { opacity: 1; }
          to   { opacity: 0.15; }
        }
        /* ── Onboarding overlay transitions ── */
        @keyframes teachOverlayIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes teachOverlayOut {
          from { opacity: 1; }
          to   { opacity: 0; pointer-events: none; }
        }
        @keyframes teachStepFade {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        /* ── Coach icon badge pulse — gentle glow breathe ── */
        @keyframes teachIconPulse {
          0%   { transform: scale(1); opacity: 0.85; }
          50%  { transform: scale(1.06); opacity: 1; }
          100% { transform: scale(1); opacity: 0.85; }
        }


        /* ── Teach glow — first-session VF edge pulse (2.8s, infinite) ──
           Gentle steel-blue inner glow that breathes in and out. Delayed 1s
           so the page settles before the hint appears. */
        @keyframes teachGlow {
          0%   { opacity: 0; }
          15%  { opacity: 1; }
          50%  { opacity: 0.4; }
          85%  { opacity: 1; }
          100% { opacity: 0; }
        }

        /* ── Teach tooltip — slides up + fades in ── */
        @keyframes teachTooltipIn {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes teachTooltipOut {
          from { opacity: 1; transform: translateY(0); }
          to   { opacity: 0; transform: translateY(-4px); }
        }

        /* ── Coach icon float — gentle up/down hover ── */
        @keyframes teachIconFloat {
          0%   { transform: translateY(0) scale(1); filter: brightness(1); }
          50%  { transform: translateY(-5px) scale(1.12); filter: brightness(1.4); }
          100% { transform: translateY(0) scale(1); filter: brightness(1); }
        }
        @keyframes teachIconGlow {
          0%   { filter: drop-shadow(0 0 2px currentColor) brightness(1); }
          50%  { filter: drop-shadow(0 0 8px currentColor) brightness(1.3); }
          100% { filter: drop-shadow(0 0 2px currentColor) brightness(1); }
        }
        @keyframes teachSpotlightPulse {
          0%   { transform: scale(1); opacity: 0.5; }
          50%  { transform: scale(1.06); opacity: 0.9; }
          100% { transform: scale(1); opacity: 0.5; }
        }

        /* ── Coach arrow bounce — arrowhead pulses toward target ── */
        @keyframes teachArrowBounce {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(3px); }
        }

        /* ── Card spring entrance — overshoot + settle ── */
        @keyframes teachCardSpring {
          0%   { opacity: 0; transform: translateY(16px) scale(0.96); }
          60%  { opacity: 1; transform: translateY(-3px) scale(1.01); }
          80%  { transform: translateY(1px) scale(1.0); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }

        /* ── Arrow draw-on — stroke-dashoffset animates to 0 ── */
        @keyframes teachDrawOn {
          to { stroke-dashoffset: 0; }
        }

        /* teachArrowSlideN keyframes are generated inline per step */

        /* ── Volumetric light bloom breathe ── */
        @keyframes teachBloom {
          0%   { transform: scale(1); opacity: 0.7; }
          50%  { transform: scale(1.15); opacity: 1; }
          100% { transform: scale(1); opacity: 0.7; }
        }

        /* ── Animated conic border sweep ── */
        @property --teach-border-angle {
          syntax: '<angle>';
          initial-value: 0deg;
          inherits: false;
        }
        @keyframes teachBorderSweep {
          to { --teach-border-angle: 360deg; }
        }

        @keyframes vfShake {
          0%,100% { transform: translateX(0); }
          15% { transform: translateX(4px); }
          30% { transform: translateX(-4px); }
          45% { transform: translateX(3px); }
          60% { transform: translateX(-2px); }
          75% { transform: translateX(1px); }
        }
        @keyframes vfPulseGlow {
          0%   { opacity: 0.45; filter: drop-shadow(0 0 4px rgba(132,158,184,0.12)); transform: scale(1); }
          50%  { opacity: 1.00; filter: drop-shadow(0 0 16px rgba(132,158,184,0.45)); transform: scale(1.10); }
          100% { opacity: 0.45; filter: drop-shadow(0 0 4px rgba(132,158,184,0.12)); transform: scale(1); }
        }
        @keyframes btnBreath {
          /* Shadow-only breath — diameter never changes, ring always fits flush.
             Drop shadow deepens/lifts to simulate the face rising and falling
             under ambient light. Top-left specular inset pulses with the breath
             to maintain the 141.71° directional read throughout the cycle. */
          0%   { box-shadow: 10px 10px 28px rgba(0,0,0,0.94), 5px 5px 12px rgba(0,0,0,0.78), 2px 2px 5px rgba(0,0,0,0.55), -1px -1px 2px rgba(255,255,255,0.05), inset 0 1.5px 0 rgba(255,255,255,0.13), inset 1.5px 0 0 rgba(255,255,255,0.07), inset -1px -1px 0 rgba(0,0,0,0.60); }
          25%  { box-shadow: 11px 11px 32px rgba(0,0,0,0.96), 6px 6px 16px rgba(0,0,0,0.82), 3px 3px 6px rgba(0,0,0,0.58), -1px -1px 2px rgba(255,255,255,0.07), inset 0 1.5px 0 rgba(255,255,255,0.16), inset 1.5px 0 0 rgba(255,255,255,0.09), inset -1px -1px 0 rgba(0,0,0,0.62); }
          50%  { box-shadow: 12px 12px 36px rgba(0,0,0,0.97), 7px 7px 18px rgba(0,0,0,0.85), 3px 3px 7px rgba(0,0,0,0.62), -1px -1px 3px rgba(255,255,255,0.09), inset 0 1.5px 0 rgba(255,255,255,0.18), inset 1.5px 0 0 rgba(255,255,255,0.10), inset -1px -1px 0 rgba(0,0,0,0.64); }
          75%  { box-shadow: 11px 11px 32px rgba(0,0,0,0.96), 6px 6px 16px rgba(0,0,0,0.82), 3px 3px 6px rgba(0,0,0,0.58), -1px -1px 2px rgba(255,255,255,0.07), inset 0 1.5px 0 rgba(255,255,255,0.16), inset 1.5px 0 0 rgba(255,255,255,0.09), inset -1px -1px 0 rgba(0,0,0,0.62); }
          100% { box-shadow: 10px 10px 28px rgba(0,0,0,0.94), 5px 5px 12px rgba(0,0,0,0.78), 2px 2px 5px rgba(0,0,0,0.55), -1px -1px 2px rgba(255,255,255,0.05), inset 0 1.5px 0 rgba(255,255,255,0.13), inset 1.5px 0 0 rgba(255,255,255,0.07), inset -1px -1px 0 rgba(0,0,0,0.60); }
        }

        /* ── Ring alive pulse — heartbeat rhythm (lub-dub) ──
           First beat: sharp hard peak. Brief dip. Second beat: softer echo.
           Long rest before repeating. 2.4s total = ~25 bpm, calm resting heart. */
        @keyframes ringAlivePulse {
          0%   { filter: brightness(0.28); }
          7%   { filter: brightness(2.8) drop-shadow(0 0 5px rgba(130,180,255,1.0)) drop-shadow(0 0 10px rgba(100,155,255,0.78)); }
          14%  { filter: brightness(0.45); }
          21%  { filter: brightness(2.1) drop-shadow(0 0 4px rgba(130,180,255,0.82)) drop-shadow(0 0 8px rgba(100,155,255,0.55)); }
          30%  { filter: brightness(0.28); }
          100% { filter: brightness(0.28); }
        }

        /* ── Ring alive green pulse — hasResult heartbeat (Re-analyze ready) ──
           Same timing as ringAlivePulse; green (72,186,136) drop-shadow
           to match the green ring color in hasResult state. */
        @keyframes ringAliveGreenPulse {
          0%   { filter: brightness(0.28); }
          7%   { filter: brightness(2.8) drop-shadow(0 0 5px rgba(140,230,190,1.0)) drop-shadow(0 0 10px rgba(72,186,136,0.78)); }
          14%  { filter: brightness(0.45); }
          21%  { filter: brightness(2.1) drop-shadow(0 0 4px rgba(140,230,190,0.82)) drop-shadow(0 0 8px rgba(72,186,136,0.55)); }
          30%  { filter: brightness(0.28); }
          100% { filter: brightness(0.28); }
        }

        /* ── Ring load accept — single bright flare when photo is accepted ──
           Blue-white flash matching the viewfinder chrome. One-shot, 0.6s. */
        @keyframes ringLoadAccept {
          0%   { box-shadow: 0 0 0 1.5px rgba(132,158,184,0.95), 0 0 12px rgba(132,158,184,0.70), 0 0 24px rgba(132,158,184,0.35), 0 0 40px rgba(132,158,184,0.15); }
          100% { box-shadow: 0 0 0 1px rgba(107,148,245,0.38), -1px -1px 0 0 rgba(107,148,245,0.60), 1px 1px 0 0 rgba(0,0,0,0.28); }
        }

        /* ── Green ring heartbeat — loading/analyzing (2.0s lub-dub, slightly faster = working) ── */
        @keyframes ringPulse {
          0%   { box-shadow: 0 0 0 1px rgba(72,186,136,0.18), -1px -1px 0 0 rgba(72,186,136,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(72,186,136,0.10); }
          7%   { box-shadow: 0 0 0 1px rgba(72,186,136,0.96), -1px -1px 0 0 rgba(140,230,190,1.00), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 8px rgba(72,186,136,0.72), 0 0 18px rgba(72,186,136,0.44), 0 0 32px rgba(72,186,136,0.20); }
          14%  { box-shadow: 0 0 0 1px rgba(72,186,136,0.22), -1px -1px 0 0 rgba(72,186,136,0.26), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(72,186,136,0.12); }
          21%  { box-shadow: 0 0 0 1px rgba(72,186,136,0.78), -1px -1px 0 0 rgba(140,230,190,0.90), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 6px rgba(72,186,136,0.55), 0 0 14px rgba(72,186,136,0.30), 0 0 24px rgba(72,186,136,0.14); }
          30%  { box-shadow: 0 0 0 1px rgba(72,186,136,0.18), -1px -1px 0 0 rgba(72,186,136,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(72,186,136,0.10); }
          100% { box-shadow: 0 0 0 1px rgba(72,186,136,0.18), -1px -1px 0 0 rgba(72,186,136,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(72,186,136,0.10); }
        }

        /* ── Red ring heartbeat — error (1.1s lub-dub, fast = urgent/alarming) ── */
        @keyframes ringFlash {
          0%   { box-shadow: 0 0 0 1px rgba(215,55,55,0.18), -1px -1px 0 0 rgba(215,55,55,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(215,55,55,0.10); }
          7%   { box-shadow: 0 0 0 1px rgba(215,55,55,0.96), -1px -1px 0 0 rgba(255,100,100,1.00), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 8px rgba(215,55,55,0.72), 0 0 18px rgba(215,55,55,0.44), 0 0 32px rgba(215,55,55,0.20); }
          14%  { box-shadow: 0 0 0 1px rgba(215,55,55,0.22), -1px -1px 0 0 rgba(215,55,55,0.26), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(215,55,55,0.12); }
          21%  { box-shadow: 0 0 0 1px rgba(215,55,55,0.78), -1px -1px 0 0 rgba(255,100,100,0.90), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 6px rgba(215,55,55,0.55), 0 0 14px rgba(215,55,55,0.30), 0 0 24px rgba(215,55,55,0.14); }
          30%  { box-shadow: 0 0 0 1px rgba(215,55,55,0.18), -1px -1px 0 0 rgba(215,55,55,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(215,55,55,0.10); }
          100% { box-shadow: 0 0 0 1px rgba(215,55,55,0.18), -1px -1px 0 0 rgba(215,55,55,0.22), 1px 1px 0 0 rgba(0,0,0,0.28), 0 0 2px rgba(215,55,55,0.10); }
        }

        /* ── Well LED green heartbeat — loading state (2.0s lub-dub) ── */
        @keyframes dotPulse {
          0%   { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.18); }
          7%   { opacity: 1.00; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 5px rgba(140,230,190,0.95), 0 0 10px rgba(72,186,136,0.60), 0 0 18px rgba(72,186,136,0.28); }
          14%  { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.18); }
          21%  { opacity: 0.95; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 4px rgba(140,230,190,0.78), 0 0 8px rgba(72,186,136,0.44), 0 0 14px rgba(72,186,136,0.20); }
          30%  { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.18); }
          100% { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.18); }
        }

        /* ── Well LED red heartbeat — error state (1.1s lub-dub, urgent) ── */
        @keyframes dotFlash {
          0%   { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(215,55,55,0.18); }
          7%   { opacity: 1.00; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 5px rgba(255,100,100,0.95), 0 0 10px rgba(215,55,55,0.60), 0 0 18px rgba(215,55,55,0.28); }
          14%  { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(215,55,55,0.18); }
          21%  { opacity: 0.95; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 4px rgba(255,100,100,0.78), 0 0 8px rgba(215,55,55,0.44), 0 0 14px rgba(215,55,55,0.20); }
          30%  { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(215,55,55,0.18); }
          100% { opacity: 0.55; box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(215,55,55,0.18); }
        }

        /* ── Well LED alive pulse — heartbeat mirror of ringAlivePulse (2.4s) ──
           Glow flares on the same lub-dub beats so well and ring breathe together. */
        @keyframes wellAlivePulse {
          0%   { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(107,148,245,0.15); }
          7%   { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 5px rgba(107,148,245,0.92), 0 0 10px rgba(107,148,245,0.46); }
          14%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(107,148,245,0.15); }
          21%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 4px rgba(107,148,245,0.72), 0 0 8px rgba(107,148,245,0.34); }
          30%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(107,148,245,0.15); }
          100% { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(107,148,245,0.15); }
        }

        /* ── Well LED green pulse — hasResult heartbeat (Re-analyze ready) ──
           Same 2.4s lub-dub timing as wellAlivePulse; green (72,186,136) to match
           the green ring and green ring-alive pulse on the analyze button. */
        @keyframes wellGreenPulse {
          0%   { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.15); }
          7%   { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 5px rgba(140,230,190,0.95), 0 0 10px rgba(72,186,136,0.60), 0 0 18px rgba(72,186,136,0.28); }
          14%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.15); }
          21%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 4px rgba(140,230,190,0.78), 0 0 8px rgba(72,186,136,0.44), 0 0 14px rgba(72,186,136,0.20); }
          30%  { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.15); }
          100% { box-shadow: inset 0 1px 1.5px rgba(0,0,0,0.9), inset 1px 0 1px rgba(0,0,0,0.55), inset -0.5px -0.5px 0.6px rgba(255,255,255,0.10), 0 0 1.5px rgba(72,186,136,0.15); }
        }

        /* ── Load accept flash — viewfinder edge flare on photo acceptance ──
           Single 0.6s pulse: inset glow peaks at 15% then fades to nothing.
           Steel-blue tint matches the viewfinder chrome — reads as "the glass
           acknowledging the photo" not as a generic UI highlight. */
        @keyframes loadAcceptFlash {
          0%   { opacity: 1; }
          15%  { opacity: 1; }
          100% { opacity: 0; }
        }
        /* prefers-reduced-motion: teach overlays exempt — they're essential
           for first-time onboarding. The reduce-motion setting in app preferences
           handles this via data-reduce-motion attribute instead. */
      `}</style>
    </div>
    </div>
  );
}
