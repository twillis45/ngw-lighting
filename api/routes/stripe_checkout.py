"""
Stripe Checkout integration.

Endpoints:
  POST /api/stripe/create-checkout-session
      Creates a Stripe Checkout Session and returns the hosted URL.
      The frontend redirects the user there to complete payment.

  POST /api/stripe/webhook
      Receives Stripe webhook events (checkout.session.completed, etc.)
      and records payment in the DB.

Required env vars:
  STRIPE_SECRET_KEY                sk_test_... / sk_live_...
  STRIPE_PRICE_ID_MONTHLY          price_... (Pro monthly)
  STRIPE_PRICE_ID_YEARLY           price_... (Pro yearly)
  STRIPE_PRICE_ID_STUDIO_MONTHLY   price_... (Studio monthly)
  STRIPE_PRICE_ID_STUDIO_YEARLY    price_... (Studio yearly)
  STRIPE_WEBHOOK_SECRET            whsec_... (webhook signature verification)
"""

from __future__ import annotations

import os
import logging
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel

from auth.security import get_optional_user
from db.database import create_subscription, cancel_subscription_by_stripe_id, get_subscription_by_stripe_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Stripe client — initialised lazily so missing key only errors at call time,
# not at import time (keeps dev server bootable without Stripe creds).
# ---------------------------------------------------------------------------

def _get_stripe():
    key = os.getenv('STRIPE_SECRET_KEY')
    if not key:
        raise HTTPException(
            status_code=503,
            detail='Stripe is not configured. Set STRIPE_SECRET_KEY in the environment.',
        )
    stripe.api_key = key
    return stripe


PRICE_IDS: dict[str, dict[str, Optional[str]]] = {
    'pro': {
        'monthly': os.getenv('STRIPE_PRICE_ID_MONTHLY'),
        'yearly':  os.getenv('STRIPE_PRICE_ID_YEARLY'),
    },
    'studio': {
        'monthly': os.getenv('STRIPE_PRICE_ID_STUDIO_MONTHLY'),
        'yearly':  os.getenv('STRIPE_PRICE_ID_STUDIO_YEARLY'),
    },
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CheckoutSessionRequest(BaseModel):
    billing_period: str = 'monthly'   # 'monthly' | 'yearly'
    plan: str = 'pro'
    # The price the user was SHOWN, from /api/paywall/adaptive-pricing. Sent so
    # the server can refuse to charge a different amount -- see _resolve_price_id.
    price_point: Optional[int] = None
    success_url: str                   # must contain ?checkout_success=1
    cancel_url:  str
    # Paywall attribution — passed through to Stripe session metadata
    ngw_session_id:  Optional[str] = None
    trigger_type:    Optional[str] = None   # e.g. nailed_it | exit_intent | shoot_mode
    surface:         Optional[str] = None   # e.g. blueprint_card | gear_recommendation
    paywall_type:    Optional[str] = None   # pricing | shoot
    source_screen:   Optional[str] = None   # ResultsScreenV2 | RecipeScreen
    copy_variant:    Optional[str] = None
    pricing_variant: Optional[str] = None


class CheckoutSessionResponse(BaseModel):
    url: str
    session_id: str


# ---------------------------------------------------------------------------
# POST /api/stripe/create-checkout-session
# ---------------------------------------------------------------------------

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('ALLOWED_ORIGINS', '').split(',') if o.strip()]


@router.post('/stripe/create-checkout-session', response_model=CheckoutSessionResponse)
async def create_checkout_session(
    body: CheckoutSessionRequest,
    user=Depends(get_optional_user),
):
    """Create a Stripe Checkout Session and return the hosted checkout URL.

    Requires a valid JWT — only registered users can initiate checkout.
    This prevents anonymous actors from creating Stripe sessions on behalf
    of the app, which could be used for phishing/misuse of the Stripe account.
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to start checkout. Please log in first.",
        )

    if body.plan not in ('pro', 'studio'):
        raise HTTPException(400, f'Unsupported plan: {body.plan}')

    # Validate success_url and cancel_url origins to prevent open-redirect abuse.
    if _ALLOWED_ORIGINS:
        for url in (body.success_url, body.cancel_url):
            if not any(url.startswith(o) for o in _ALLOWED_ORIGINS):
                raise HTTPException(400, 'Invalid redirect URL origin.')

    plan_prices = PRICE_IDS.get(body.plan, {})
    price_id = plan_prices.get(body.billing_period)

    # ── Charge what was shown, or refuse ──────────────────────────────────────
    # Added 2026-09-03. This route used to ignore the displayed price entirely:
    # the adaptive ladder showed 39/49/59/79 and line_items always carried the
    # one fixed Price ID. Production was returning "Unlock Pro -- $59/mo" while
    # this would have charged the monthly base. In test mode that was invisible;
    # live it is billing someone an amount they never agreed to.
    #
    # A tiered Price ID is opened by setting STRIPE_PRICE_ID_<PLAN>_<PERIOD>_<PT>.
    # If a caller reports a price point we cannot charge exactly, we FAIL rather
    # than fall back -- a silent fallback is the bug this replaces.
    #
    # AMENDED 2026-09-03 after the stage-8 board probed five checkout paths and
    # found three ways past this guard:
    #   B  client OMITS price_point (the field is Optional) -> guard skipped,
    #      base charged. Six of the seven startStripeCheckout() call sites in
    #      the shipped UI pass no arguments at all, so this was the MAJORITY
    #      path, not an edge case.
    #   C  client sends a LOWER price_point than it displayed -> base charged.
    #   E  plan='studio' -> the guard did not run at all.
    # The divergence undercharges rather than overcharges, so no buyer was at
    # risk -- but "agree by construction" was false, and it failed in exactly
    # the way f9b9893 was written to stop: enforced only against a client that
    # cooperates.
    from engine.paywall.adaptive_pricing import sellable_points as _sellable
    _rungs = _sellable(body.billing_period)
    if body.price_point is None and len(_rungs) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                'price_point is required: more than one price rung is '
                f'configured for {body.billing_period} ({_rungs}), so the server '
                'cannot know which price was displayed. Refusing to guess.'
            ),
        )
    if body.price_point is not None:
        _tier_env = f'STRIPE_PRICE_ID_{body.billing_period.upper()}_{body.price_point}'
        _tier_id = os.getenv(_tier_env)
        if _tier_id:
            price_id = _tier_id
        else:
            from engine.paywall.adaptive_pricing import PRICE_LADDER
            # The base differs by period: the yearly figure is the monthly
            # ladder base x10 (see get_adaptive_pricing's price_yearly). Compare
            # against the right one, or every yearly checkout 409s -- which is
            # exactly what this guard did on its first draft.
            _base = PRICE_LADDER[0] * (10 if body.billing_period == 'yearly' else 1)
            if body.price_point != _base:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f'Cannot charge ${body.price_point}: no Stripe price is configured '
                        f'for it ({_tier_env} is unset). Refusing to charge a different '
                        f'amount than was displayed.'
                    ),
                )
    if not price_id:
        raise HTTPException(
            400,
            f'No Stripe Price ID configured for plan="{body.plan}" billing_period="{body.billing_period}". '
            f'Set the corresponding STRIPE_PRICE_ID_* env var.',
        )

    _stripe = _get_stripe()

    try:
        session_params = dict(
            mode='subscription',
            line_items=[{'price': price_id, 'quantity': 1}],
            # Stripe appends session_id automatically when the placeholder is present
            success_url=body.success_url + '&session_id={CHECKOUT_SESSION_ID}',
            cancel_url=body.cancel_url,
            allow_promotion_codes=True,
            metadata={k: v for k, v in {
                'plan':            body.plan,
                'billing_period':  body.billing_period,
                'ngw_session_id':  body.ngw_session_id,
                'trigger_type':    body.trigger_type,
                'surface':         body.surface,
                'paywall_type':    body.paywall_type,
                'source_screen':   body.source_screen,
                'copy_variant':    body.copy_variant,
                'pricing_variant': body.pricing_variant,
            }.items() if v is not None},
        )
        # Pre-fill email so the Stripe checkout form is ready to go
        if user and user.get('email'):
            session_params['customer_email'] = user['email']
        session = _stripe.checkout.Session.create(**session_params)
    except _stripe.error.StripeError as exc:
        logger.error('Stripe error creating session: %s', exc)
        raise HTTPException(502, f'Stripe error: {exc.user_message or str(exc)}')

    return CheckoutSessionResponse(url=session.url, session_id=session.id)


# ---------------------------------------------------------------------------
# POST /api/stripe/webhook
# ---------------------------------------------------------------------------

@router.post('/stripe/webhook')
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias='stripe-signature'),
):
    """
    Receive and verify Stripe webhook events.
    Handles checkout.session.completed to confirm payment server-side.
    """
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    payload = await request.body()

    if webhook_secret and stripe_signature:
        _stripe = _get_stripe()
        try:
            event = _stripe.Webhook.construct_event(
                payload, stripe_signature, webhook_secret
            )
        except _stripe.error.SignatureVerificationError:
            logger.warning('Stripe webhook signature verification failed')
            raise HTTPException(400, 'Invalid signature')
    else:
        # No secret configured — reject rather than accept unverified events.
        # Set STRIPE_WEBHOOK_SECRET in the environment to enable webhooks.
        logger.error('Stripe webhook received but STRIPE_WEBHOOK_SECRET is not configured — rejecting')
        raise HTTPException(400, 'Webhook secret not configured — cannot verify event')

    event_type = event.get('type') if isinstance(event, dict) else event.type

    if event_type == 'checkout.session.completed':
        session = event['data']['object'] if isinstance(event, dict) else event.data.object
        customer_email = (
            session.get('customer_details', {}).get('email')
            if isinstance(session, dict)
            else getattr(getattr(session, 'customer_details', None), 'email', None)
        )
        session_id = session.get('id') if isinstance(session, dict) else session.id
        stripe_customer_id = (
            session.get('customer') if isinstance(session, dict)
            else getattr(session, 'customer', None)
        )
        stripe_subscription_id = (
            session.get('subscription') if isinstance(session, dict)
            else getattr(session, 'subscription', None)
        )
        # Derive billing_period from metadata or default to monthly
        metadata = (
            session.get('metadata', {}) if isinstance(session, dict)
            else getattr(session, 'metadata', {}) or {}
        )
        billing_period = metadata.get('billing_period', 'monthly')
        plan = metadata.get('plan', 'pro')
        if plan not in ('pro', 'studio'):
            plan = 'pro'  # fallback for legacy sessions without plan metadata

        logger.info('Checkout completed: session=%s email=%s plan=%s', session_id, customer_email, plan)

        if session_id and customer_email:
            existing = get_subscription_by_stripe_session(session_id)
            if existing:
                logger.info(
                    'Duplicate webhook — subscription already exists for session=%s, skipping',
                    session_id,
                )
                return {'received': True, 'status': 'already_processed'}

            try:
                create_subscription(
                    stripe_session_id=session_id,
                    customer_email=customer_email,
                    plan=plan,
                    billing_period=billing_period,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=stripe_subscription_id,
                )
                logger.info('Subscription created for session=%s email=%s', session_id, customer_email)
            except Exception as exc:
                logger.error('Failed to persist subscription for session=%s: %s', session_id, exc)
                # Return 500 so Stripe retries the webhook on transient DB failures.
                # Without this, a failed write silently succeeds from Stripe's perspective.
                raise HTTPException(500, 'Failed to persist subscription — will retry')

    elif event_type == 'customer.subscription.deleted':
        # Stripe fires this when a subscription is cancelled (immediately or at period end).
        # Mark the local subscription record as cancelled so access is revoked promptly.
        sub_obj = event['data']['object'] if isinstance(event, dict) else event.data.object
        stripe_sub_id = (
            sub_obj.get('id') if isinstance(sub_obj, dict) else getattr(sub_obj, 'id', None)
        )
        logger.info('Subscription cancelled: stripe_subscription_id=%s', stripe_sub_id)
        if stripe_sub_id:
            try:
                updated = cancel_subscription_by_stripe_id(stripe_sub_id)
                if updated:
                    logger.info('Subscription marked cancelled: stripe_subscription_id=%s', stripe_sub_id)
                else:
                    logger.warning(
                        'No active subscription found to cancel for stripe_subscription_id=%s', stripe_sub_id
                    )
            except Exception as exc:
                logger.error(
                    'Failed to cancel subscription for stripe_subscription_id=%s: %s', stripe_sub_id, exc
                )

    return {'received': True}
