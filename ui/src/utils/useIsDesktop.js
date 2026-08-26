/**
 * useIsDesktop — viewport width breakpoint hook for Studio Matte screens.
 *
 * Returns true when viewport width is >= 1024px. This threshold controls
 * BOTH the internal two-column layout switch AND the FitToViewport
 * designWidth branching in Day1DemoApp.  They must match — a mismatch
 * creates a conflict zone where screens render desktop layouts inside
 * mobile-scaled FitToViewport frames.
 *
 * For tablet portrait (768–1023px), screens that need a wider layout
 * (e.g. the cockpit) should use a LOCAL viewport-width check rather
 * than lowering this global threshold.
 */
import { useEffect, useState } from 'react';

export const LAYOUT_DESKTOP_MIN = 1024;
// Tablet portrait threshold — screens that need a wider layout (ResultScreen,
// SetupScreen) bypass FitToViewport and activate two-column layout at this
// breakpoint without lowering the global desktop threshold.
export const TABLET_MIN_WIDTH = 768;

/**
 * useMinWidth — reactive `(min-width: Npx)` match.
 *
 * The generic form of useIsDesktop. Exists because Day1DemoApp branched on
 * a raw `window.innerWidth` read fourteen times: those are evaluated once
 * per render and never re-run, so a rotation or a resize left the shell in
 * the wrong layout regime until something else happened to re-render it.
 */
export function useMinWidth(px) {
  const query = `(min-width: ${px}px)`;
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const handler = (e) => setMatches(e.matches);
    // Safari < 14 uses addListener/removeListener
    if (mq.addEventListener) mq.addEventListener('change', handler);
    else mq.addListener(handler);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', handler);
      else mq.removeListener(handler);
    };
  }, [query]);

  return matches;
}

export function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(`(min-width: ${LAYOUT_DESKTOP_MIN}px)`).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(`(min-width: ${LAYOUT_DESKTOP_MIN}px)`);
    const handler = (e) => setIsDesktop(e.matches);
    // Safari < 14 uses addListener/removeListener
    if (mq.addEventListener) mq.addEventListener('change', handler);
    else mq.addListener(handler);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', handler);
      else mq.removeListener(handler);
    };
  }, []);

  return isDesktop;
}

/**
 * useViewportWidth — live viewport width in px. Used for fluid sizing on
 * wide screens (e.g. scaling the Result hero column above 1180px). Returns 0
 * during SSR.
 */
export function useViewportWidth() {
  const [w, setW] = useState(() => (typeof window === 'undefined' ? 0 : window.innerWidth));
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handler = () => setW(window.innerWidth);
    window.addEventListener('resize', handler);
    // Orientation change fires on device rotation — delayed to let viewport settle.
    const orientHandler = () => setTimeout(handler, 150);
    window.addEventListener('orientationchange', orientHandler);
    const soApi = window.screen?.orientation;
    if (soApi) soApi.addEventListener('change', handler);
    return () => {
      window.removeEventListener('resize', handler);
      window.removeEventListener('orientationchange', orientHandler);
      if (soApi) soApi.removeEventListener('change', handler);
    };
  }, []);
  return w;
}
