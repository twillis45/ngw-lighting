# Deferred at promotion — NGW Lighting

Each line names the item, a date or an explicit "no date," and **what risk is
being accepted**. A deferral without a named risk is an omission with better
paperwork.

## 2026-08-29 — Sign in with Apple

- [ ] **Sign in with Apple** — deferred, **due at iOS App Store submission**
      (trigger, not a date).

  **What was removed.** A "Continue with Apple" button on the signed-out Studio
  login screen. It had no route, no config and no code anywhere in the repo: the
  handler fired a *positive* haptic and returned. Found by the stage-4 Nielsen
  heuristics gate on 2026-08-28, ruled by the owner on 2026-08-29.

  **Why removed rather than disabled.** Two greyed-out sign-in buttons on the
  front door is a worse first impression than none, and a control that renders
  while claiming a capability the product does not have is the exact §DT failure
  the gate exists to catch.

  **Risk accepted.** Photographers who prefer Apple sign-in must use email and
  password. That path works today, and password reset was wired the same day, so
  no user is left without a recovery route.

  **What makes it come due.** Apple requires Sign in with Apple of App Store apps
  that offer any other third-party sign-in. The moment Google sign-in ships AND
  an iOS build is submitted, this stops being optional. It needs a paid Apple
  Developer Program membership ($99/yr), a Services ID, a Sign in with Apple
  key, and a backend route that does not yet exist.

  **Reversal cost.** Larger than Google's: none of the backend exists.

## Related

- Google sign-in is NOT deferred — the backend is implemented and the frontend
  is wired. It is gated on `GOOGLE_CLIENT_ID`, and the button does not render
  until the server reports the credential is present, so an unconfigured
  deployment shows no button rather than a broken one.
