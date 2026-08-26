/**
 * Tests for the Studio navigation trail.
 *
 * Run: node ui/src/utils/screenHistory.test.mjs
 *
 * The failure these guard is concrete: before the trail existed,
 * Home -> My Kit -> Recipes -> Back landed on Home instead of My Kit,
 * because every onBack hardcoded its destination.
 */
import assert from 'node:assert/strict';
import { pushScreen, popScreen, HISTORY_MAX } from './screenHistory.js';

let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log(`  ok  ${name}`); };

test('back returns to where you came from, not home', () => {
  const s = [];
  pushScreen(s, 'home', 'mykit');
  pushScreen(s, 'mykit', 'recipes');
  assert.equal(popScreen(s, 'recipes'), 'mykit');
});

test('a second back continues up the trail', () => {
  const s = [];
  pushScreen(s, 'home', 'mykit');
  pushScreen(s, 'mykit', 'recipes');
  assert.equal(popScreen(s, 'recipes'), 'mykit');
  assert.equal(popScreen(s, 'mykit'), 'home');
});

test('empty trail falls back to home', () => {
  assert.equal(popScreen([], 'recipes'), 'home');
});

test('empty trail honours an explicit fallback', () => {
  assert.equal(popScreen([], 'roomplanner', 'setup'), 'setup');
});

test('navigating to the current screen does not stack a duplicate', () => {
  const s = [];
  pushScreen(s, 'home', 'mykit');
  pushScreen(s, 'mykit', 'mykit');
  assert.deepEqual(s, ['home']);
});

test('back never returns the screen being left', () => {
  const s = ['recipes', 'recipes'];
  assert.equal(popScreen(s, 'recipes'), 'home');
});

test('trail is capped and keeps the most recent entries', () => {
  const s = [];
  for (let i = 0; i < HISTORY_MAX + 20; i++) pushScreen(s, `s${i}`, `s${i + 1}`);
  assert.equal(s.length, HISTORY_MAX);
  assert.equal(s.at(-1), `s${HISTORY_MAX + 19}`);
});

console.log(`\n${passed} passed`);
