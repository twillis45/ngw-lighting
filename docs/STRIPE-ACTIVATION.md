# Stripe activation checklist — NGW Lighting

**Status:** blocked on account activation. Measured August 26, 2026.

```
acct_1JglkMAfg2Db6k6m
  name:     "Toddwillisphoto"
  livemode: false
```

NGW Lighting can serve, analyze, and gate. It **cannot take a payment**, and
that is the only thing standing between Line 1 and revenue.

---

## Decision first — which account?

Do not skip this. The connected account is named **Toddwillisphoto**, which
reads as the photography business — **Line 4, Stewart Visuals** — not
No Guesswork Systems LLC, which owns Line 1.

Renaming it is the wrong fix if the tax ID and bank account behind it belong to
the photography sole-prop. That puts the LLC's label on another entity's
account: worse than leaving it wrong, because it then *looks* correct.

Check **Settings → Business** at https://dashboard.stripe.com/settings/account

| If the entity behind it is… | Then |
|---|---|
| No Guesswork Systems LLC | Rename the account, activate it, reuse the keys |
| The photography business | **Create a new account** for the LLC. Line 1 revenue belongs in the LLC's Mercury account under the LLC's EIN |

---

## Todd only — I cannot do these

These need financial credentials and identity documents. Do not paste any of
them into a chat.

- [ ] **EIN** — recorded in `ngw-os/docs/COMPANY-REGISTER.md` as *"not recorded
      — supply."* Stripe activation will ask for it, so this gap blocks the step.
- [ ] Legal business name, address, and industry
- [ ] Bank account for payouts — the LLC's Mercury account
- [ ] Identity verification for the responsible party
- [ ] Statement descriptor — what appears on a customer's card statement.
      Choose deliberately: it should read as the brand the customer bought from.

---

## Products and prices to create

Two plans × two billing periods = **four Price objects**. The code reads all
four independently; a missing one returns a 400 naming the exact env var.

| Plan | Period | Price | Effective /mo | Env var |
|---|---|---|---|---|
| Pro | monthly | **$39** | $39.00 | `STRIPE_PRICE_ID_MONTHLY` |
| Pro | **quarterly** | **$105** | $35.00 | `STRIPE_PRICE_ID_QUARTERLY` ⚠️ needs a code line |
| Pro | yearly | **$390** | $32.50 | `STRIPE_PRICE_ID_YEARLY` |
| Studio | — | unpriced | — | defer until a buyer exists |

The term ladder is monotonic on purpose: **$39 → $35 → $32.50**. Quarterly at $99 would
be 15.4% off, close enough to annual's 16.7% that the annual rung stops making sense.
$105 protects it.

Quarterly is also the seasonal accommodation — a wedding photographer buys Q2 into Q3
and lapses over winter without cancelling. Most of the value of a pause feature, at the
cost of one Price object.

Pro amounts come from `ui/src/data/pricingStore.js` (`price_monthly: 39`,
`price_yearly: 390`, a 17% yearly discount). **Studio tier pricing is not set
anywhere in the codebase** — decide it before creating those two prices.

All four must be **recurring** prices, not one-time.

---

## Webhook

Endpoint: `https://app.noguessworksystems.com/api/stripe/webhook`

The handler acts on exactly two events — subscribe to these and no more:

- `checkout.session.completed`
- `customer.subscription.deleted`

Copy the signing secret (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`.

The handler **fails closed**: with that variable unset it logs
`"Stripe webhook received but STRIPE_WEBHOOK_SECRET is not configured —
rejecting"` and rejects. A silently-unconfigured webhook cannot leak; it just
never grants a plan. Symptom: payment succeeds, customer stays on free.

---

## Render environment — six variables

Service `ngw-api` → Environment:

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRICE_ID_MONTHLY=price_...
STRIPE_PRICE_ID_QUARTERLY=price_...
STRIPE_PRICE_ID_YEARLY=price_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Studio's two price vars stay unset. The code 400s with a message naming the missing
variable, which is the correct behaviour for a tier with no price yet.

`STRIPE_SECRET_KEY` is read at call time (`_get_stripe()`), but **`PRICE_IDS`
is built at module import**, so the price variables need a service restart —
the same trap as `plan_guard`. Restart after saving.

Also confirm **`ALLOWED_ORIGINS`** includes `https://app.noguessworksystems.com`.
`create-checkout-session` validates `success_url` and `cancel_url` against it to
prevent open-redirect abuse, and rejects with 400 if they don't match.

---

## What I can verify once you've done the above

- [ ] All six variables present and non-empty in the running service
- [ ] `POST /api/stripe/create-checkout-session` returns 401 anonymously
      (it requires a JWT by design — anonymous callers must not be able to
      create sessions against your Stripe account)
- [ ] All three Pro terms return a checkout URL; Studio still 400s by design
- [ ] Webhook endpoint reachable and rejecting unsigned POSTs
- [ ] A real end-to-end checkout grants the plan — the only proof that counts
- [ ] `claim-verification` run over any pricing copy before it faces a buyer

---

## Not blocking, worth knowing

`/api/paywall/impression/{id}/converted` and `/dismissed` accept anonymous
writes keyed on a caller-supplied id with no ownership check. Analytics
integrity only — no disclosure, no payment impact. Recorded as REVIEW in
`tests/test_protected_routes_sweep.py`.
