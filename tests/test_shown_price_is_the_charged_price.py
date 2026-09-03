"""The displayed price and the charged price must be the same number.

Until 2026-09-03 they were computed by two systems that never spoke:

  engine/paywall/adaptive_pricing.py  chose 39/49/59/79 from behaviour, the UI
    displayed it, db/paywall_analytics recorded it as `price_shown`
  api/routes/stripe_checkout.py       built line_items from ONE fixed
    STRIPE_PRICE_ID_MONTHLY and never looked at the price point

Production on 2026-09-03 returned price_point 59 with the CTA
"Unlock Pro - $59/mo" for a high-intent profile. Checkout would have charged
the monthly base. Only Stripe test mode kept that from being a real mischarge.

These tests fail if the two can ever diverge again.
"""
import os
import pytest

from engine.paywall.adaptive_pricing import (
    PRICE_LADDER,
    get_adaptive_pricing,
    sellable_points,
    _clamp_to_sellable,
)

STATES = ["low_value", "discovery", "success_moment", "high_intent", "failure_tension"]


class TestNeverShowAnUnchargeablePrice:
    @pytest.mark.parametrize("state", STATES)
    @pytest.mark.parametrize("score", [None, 0.5, 0.7, 0.85, 0.99])
    def test_every_surfaced_price_is_sellable(self, state, score):
        """The headline number, whatever the behaviour model wants, must be a
        price we can actually put through Stripe."""
        r = get_adaptive_pricing(state, intelligence_score=score)
        allowed = sellable_points()
        assert r["price_point"] in allowed, (
            f"{state}/score={score} surfaced ${r['price_point']}, "
            f"which cannot be charged (sellable: {allowed})"
        )

    @pytest.mark.parametrize("state", STATES)
    def test_the_cta_string_carries_the_same_number(self, state):
        """A clamp that fixes the integer but leaves the marketing copy saying
        $59 has fixed nothing -- the CTA is what the buyer actually reads."""
        r = get_adaptive_pricing(state, intelligence_score=0.99)
        assert f"${r['price_point']}" in r["messaging"]["cta"], (
            f"CTA {r['messaging']['cta']!r} disagrees with price_point "
            f"{r['price_point']}"
        )

    def test_guardrail_cannot_push_past_what_we_can_charge(self):
        """The anti-discount guardrail raises the price to session_max_price.
        It ran AFTER the ladder and must not reopen the hole."""
        r = get_adaptive_pricing("high_intent", session_max_price=79)
        assert r["price_point"] in sellable_points()

    def test_experiment_variant_cannot_either(self):
        r = get_adaptive_pricing("high_intent", experiment_variant="price_high")
        assert r["price_point"] in sellable_points()

    def test_clamp_snaps_down_never_up(self):
        """Charging more than the model asked for is the worse failure."""
        for want in PRICE_LADDER:
            assert _clamp_to_sellable(want) <= want


class TestSellableSetTracksStripeConfig:
    def test_base_is_always_sellable(self):
        assert PRICE_LADDER[0] in sellable_points()

    def test_a_rung_opens_when_its_price_id_is_configured(self, monkeypatch):
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY_59", "price_fake_59")
        assert 59 in sellable_points()
        r = get_adaptive_pricing("high_intent")
        assert r["price_point"] == 59, "configured rung should now be offerable"

    def test_a_rung_closes_again_when_unset(self, monkeypatch):
        monkeypatch.delenv("STRIPE_PRICE_ID_MONTHLY_59", raising=False)
        assert 59 not in sellable_points()


class TestCheckoutGuardAcceptsTheBaseInBothPeriods:
    """The guard's first draft compared a YEARLY price point (390) against the
    MONTHLY ladder base (39) and would have 409'd every annual checkout --
    turning a mischarge bug into a cannot-charge-at-all bug."""

    @pytest.fixture()
    def client(self, monkeypatch):
        """The route 401s before it ever reaches the price guard, so this
        fixture MUST authenticate. The first version of these tests did not,
        and asserted only `!= 409` -- so a 401 satisfied them and they passed
        while testing nothing at all."""
        from fastapi.testclient import TestClient
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake_for_guard_test")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_fake_monthly")
        monkeypatch.setenv("STRIPE_PRICE_ID_YEARLY", "price_fake_yearly")
        from main import app
        from auth.security import get_optional_user
        # The route also rejects unknown redirect origins with 400, which is
        # another way these assertions could pass without reaching the guard.
        import api.routes.stripe_checkout as sc
        monkeypatch.setattr(sc, "_ALLOWED_ORIGINS", ["https://x.test"], raising=False)
        app.dependency_overrides[get_optional_user] = lambda: {
            "id": "price-guard-test-user", "email": "guard@test.local",
        }
        yield TestClient(app)
        app.dependency_overrides.pop(get_optional_user, None)

    def test_the_fixture_actually_authenticates(self, client):
        """Guards the guard: if auth regresses, every assertion below becomes
        vacuous again rather than failing."""
        r = client.post("/api/stripe/create-checkout-session", json={
            "billing_period": "monthly", "plan": "pro", "price_point": 39,
            "success_url": "https://x.test/?checkout_success=1",
            "cancel_url": "https://x.test/",
        })
        assert r.status_code not in (401, 400), (
            f"fixture never reaches the price guard (got {r.status_code}: "
            f"{r.text[:160]}); tests below would prove nothing"
        )

    @pytest.mark.parametrize("period,point", [("monthly", 39), ("yearly", 390)])
    def test_base_price_is_not_rejected(self, client, period, point):
        r = client.post("/api/stripe/create-checkout-session", json={
            "billing_period": period, "plan": "pro", "price_point": point,
            "success_url": "https://x.test/?checkout_success=1",
            "cancel_url": "https://x.test/",
        })
        # It must not be OUR 409. Stripe itself will fail on the fake key, and
        # that is fine -- we are asserting the guard let it through.
        assert r.status_code != 409, (
            f"{period} base ${point} was rejected by the price guard: {r.text[:200]}"
        )

    def test_an_unconfigured_higher_rung_is_still_refused(self, client):
        r = client.post("/api/stripe/create-checkout-session", json={
            "billing_period": "monthly", "plan": "pro", "price_point": 79,
            "success_url": "https://x.test/?checkout_success=1",
            "cancel_url": "https://x.test/",
        })
        assert r.status_code == 409
        assert "79" in r.text


class TestTheBoardsFiveProbes:
    """The stage-8 review board (2026-09-03) instrumented Session.create and
    drove five checkout paths. Three got past the guard. These encode all five
    so they cannot come back.

      A honest monthly, sends the shown rung      -> charged that rung      OK
      B client OMITS price_point                  -> charged base           WAS BROKEN
      C client sends a LOWER price_point          -> charged base           WAS BROKEN
      D yearly, honest, sends shown yearly figure -> 409, funnel dead       WAS BROKEN
      E plan='studio'                             -> guard never ran        WAS BROKEN

    B mattered most: six of the seven startStripeCheckout() call sites in the
    shipped UI pass no arguments, so omission was the majority path.
    """

    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_base_39")
        monkeypatch.setenv("STRIPE_PRICE_ID_YEARLY", "price_base_390")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY_59", "price_tier_59")
        from main import app
        from auth.security import get_optional_user
        import api.routes.stripe_checkout as sc
        monkeypatch.setattr(sc, "_ALLOWED_ORIGINS", ["https://x.test"], raising=False)
        app.dependency_overrides[get_optional_user] = lambda: {"id": "u", "email": "u@t.local"}
        yield TestClient(app)
        app.dependency_overrides.pop(get_optional_user, None)

    def _post(self, client, **kw):
        body = {"billing_period": "monthly", "plan": "pro",
                "success_url": "https://x.test/?checkout_success=1",
                "cancel_url": "https://x.test/"}
        body.update(kw)
        return client.post("/api/stripe/create-checkout-session", json=body)

    def test_B_omitting_price_point_is_refused_when_rungs_exist(self, client):
        """With a 59 rung configured the server cannot know what was shown."""
        r = self._post(client)
        assert r.status_code == 422, (
            f"omitted price_point was accepted ({r.status_code}); the base would "
            f"be charged against whatever the page displayed"
        )

    def test_C_a_price_point_with_no_rung_is_refused_not_downgraded(self, client):
        r = self._post(client, price_point=79)
        assert r.status_code == 409

    def test_E_studio_is_guarded_too(self, client):
        """The guard used to require plan == 'pro'."""
        r = self._post(client, plan="studio", price_point=79)
        assert r.status_code == 409, (
            "studio bypassed the price guard entirely"
        )

    def test_D_yearly_rung_lookup_uses_the_yearly_variable(self):
        """sellable_points looked only at monthly vars, so configuring a rung
        offered an annual price checkout would then refuse."""
        import importlib, os
        import engine.paywall.adaptive_pricing as m
        os.environ["STRIPE_PRICE_ID_YEARLY_590"] = "price_y_590"
        importlib.reload(m)
        try:
            assert 59 in m.sellable_points("yearly")
        finally:
            del os.environ["STRIPE_PRICE_ID_YEARLY_590"]
            importlib.reload(m)

    def test_sellable_points_actually_reads_the_environment(self, monkeypatch):
        """test_base_is_always_sellable passes even against a function that
        ignores its inputs entirely -- which is how the vacuous conditional
        survived. This one fails unless the env is really consulted."""
        import importlib
        import engine.paywall.adaptive_pricing as m
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY_79", "price_79")
        importlib.reload(m)
        with_rung = m.sellable_points("monthly")
        monkeypatch.delenv("STRIPE_PRICE_ID_MONTHLY_79")
        importlib.reload(m)
        without = m.sellable_points("monthly")
        assert with_rung != without, "sellable_points ignores its configuration"
        assert 79 in with_rung and 79 not in without


class TestTheServersOwnQuoteOutranksTheClient:
    """Board condition C2, case C: a client could send a price_point LOWER than
    it had been shown and be charged that.

    The board proposed reading price_shown back from paywall_impressions. That
    would not have closed it -- ImpressionPayload.price_shown is an int the
    CLIENT posts, so trusting it at checkout launders the same untrusted number
    through a longer path. price_quotes records only what the server computed
    inside /paywall/adaptive-pricing.
    """

    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_base_39")
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY_59", "price_tier_59")
        from main import app
        from auth.security import get_optional_user
        import api.routes.stripe_checkout as sc
        monkeypatch.setattr(sc, "_ALLOWED_ORIGINS", ["https://x.test"], raising=False)
        app.dependency_overrides[get_optional_user] = lambda: {"id": "u", "email": "u@t.local"}
        yield TestClient(app)
        app.dependency_overrides.pop(get_optional_user, None)

    def _quote(self, session_id, price):
        from db.paywall_analytics import init_paywall_analytics_tables, record_price_quote
        init_paywall_analytics_tables()
        record_price_quote(session_id=session_id, price_point=price, value_state="high_intent")

    def _checkout(self, client, session_id, **kw):
        body = {"billing_period": "monthly", "plan": "pro",
                "ngw_session_id": session_id,
                "success_url": "https://x.test/?checkout_success=1",
                "cancel_url": "https://x.test/"}
        body.update(kw)
        return client.post("/api/stripe/create-checkout-session", json=body)

    def test_a_client_claiming_a_lower_price_than_it_was_quoted_is_refused(self, client):
        """THE case C defect. Shown 59, claims 39."""
        sid = "sess-lowball"
        self._quote(sid, 59)
        r = self._checkout(client, sid, price_point=39)
        assert r.status_code == 409, (
            f"client was quoted $59, claimed $39, and got {r.status_code} -- "
            f"it would have been charged the lower price"
        )
        assert "59" in r.text

    def test_omitting_the_price_uses_the_servers_quote_not_the_base(self, client):
        """Six of seven UI call sites send nothing. They must still get the
        price this session was actually quoted."""
        sid = "sess-silent"
        self._quote(sid, 59)
        r = self._checkout(client, sid)
        assert r.status_code != 422, "server had a quote and still demanded one from the client"
        assert r.status_code != 409, f"server refused its own quote: {r.text[:160]}"

    def test_an_honest_client_agreeing_with_the_quote_passes(self, client):
        sid = "sess-honest"
        self._quote(sid, 59)
        r = self._checkout(client, sid, price_point=59)
        assert r.status_code not in (409, 422), r.text[:200]

    def test_quotes_are_per_session_not_global(self, client):
        """A quote for one session must not price another."""
        self._quote("sess-one", 59)
        r = self._checkout(client, "sess-two", price_point=39)
        assert r.status_code != 409, "a different session's quote leaked into this one"
