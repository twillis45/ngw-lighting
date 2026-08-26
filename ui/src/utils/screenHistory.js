/**
 * screenHistory — the Studio shell's navigation trail.
 *
 * Extracted as pure functions so the push/pop rules can be tested without a
 * DOM. Before this existed, every `onBack` in Day1DemoApp hardcoded a
 * destination and 8 of 11 chose 'home', so any second hop lost the user's
 * place. Legacy's AppContext has carried a history array all along; this is
 * the same idea, kept pure.
 */

/** Cap the trail so a long session cannot grow it without bound. */
export const HISTORY_MAX = 50;

/**
 * Record `prev` before moving to `next`. Mutates and returns `stack`.
 * A no-op when the screen is unchanged — re-navigating to the current
 * screen must not stack duplicates.
 */
export function pushScreen(stack, prev, next) {
  if (prev === next) return stack;
  stack.push(prev);
  while (stack.length > HISTORY_MAX) stack.shift();
  return stack;
}

/**
 * Pop the most recent screen that isn't the one being left. Returns
 * `fallback` when the trail is empty — a user who deep-links straight into
 * a screen still gets a working back button.
 */
export function popScreen(stack, current, fallback = 'home') {
  while (stack.length) {
    const candidate = stack.pop();
    if (candidate !== current) return candidate;
  }
  return fallback;
}
