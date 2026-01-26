"""Billing API endpoints for subscription management via Stripe."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.config.plans import PLANS, get_plan
from app.domain.organization_operations import organization_ops
from app.domain.subscription_operations import subscription_ops
from app.models.billing import BillingEvent, BillingEventType
from app.models.subscription import PlanTier, SubscriptionStatus
from app.services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class PlanInfo(BaseModel):
    """Public plan information."""

    tier: str
    display_name: str
    price_monthly: int  # cents
    base_repo_limit: int
    overage_price: int  # cents per repo
    features: dict[str, bool]


class SubscriptionInfo(BaseModel):
    """Subscription information for the current organization."""

    plan_tier: str
    display_name: str
    status: str
    base_repo_limit: int
    current_period_end: str | None
    cancel_at_period_end: bool
    is_manually_assigned: bool
    is_trialing: bool


class CheckoutRequest(BaseModel):
    """Request to create a checkout session."""

    plan_tier: str
    organization_id: UUID
    source: str = "billing"  # "billing", "select-plan", or "onboarding" — determines redirect URLs


class CheckoutResponse(BaseModel):
    """Response with checkout URL."""

    checkout_url: str


class PortalRequest(BaseModel):
    """Request to create a portal session."""

    organization_id: UUID


class PortalResponse(BaseModel):
    """Response with portal URL."""

    portal_url: str


# ─────────────────────────────────────────────────────────────────────────────
# Public Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/plans", response_model=list[PlanInfo])
async def list_plans() -> list[PlanInfo]:
    """
    List all available plans (public endpoint).

    Returns plan details including pricing and feature flags.
    No authentication required.
    """
    return [
        PlanInfo(
            tier=plan.tier,
            display_name=plan.display_name,
            price_monthly=plan.price_monthly,
            base_repo_limit=plan.base_repo_limit,
            overage_price=plan.overage_repo_price,
            features=plan.features,
        )
        for plan in PLANS.values()
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Authenticated Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/subscription/{organization_id}", response_model=SubscriptionInfo)
async def get_subscription(
    organization_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> SubscriptionInfo:
    """
    Get subscription details for an organization.

    User must be a member of the organization.
    """
    # Verify user has access to this org
    role = await organization_ops.get_member_role(db, organization_id, current_user.id)
    if not role:
        raise HTTPException(403, "Not a member of this organization")

    subscription = await subscription_ops.get_by_org(db, organization_id)
    if not subscription:
        raise HTTPException(404, "Subscription not found")

    plan = get_plan(subscription.plan_tier)

    return SubscriptionInfo(
        plan_tier=subscription.plan_tier,
        display_name=plan.display_name,
        status=subscription.status,
        base_repo_limit=subscription.base_repo_limit,
        current_period_end=(
            subscription.current_period_end.isoformat() if subscription.current_period_end else None
        ),
        cancel_at_period_end=subscription.cancel_at_period_end,
        is_manually_assigned=subscription.is_manually_assigned,
        is_trialing=subscription.status == SubscriptionStatus.TRIALING.value,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: CheckoutRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for plan subscription.

    User must be owner or admin of the organization.
    Returns a URL to redirect the user to Stripe Checkout.
    Includes a 14-day free trial.
    """
    if not settings.stripe_enabled:
        raise HTTPException(400, "Payments not configured")

    # Verify user is owner/admin
    role = await organization_ops.get_member_role(db, request.organization_id, current_user.id)
    if not role or role not in ("owner", "admin"):
        raise HTTPException(403, "Only owners and admins can manage billing")

    # Validate plan tier
    valid_tiers = [PlanTier.INDIE.value, PlanTier.PRO.value, PlanTier.SCALE.value]
    if request.plan_tier not in valid_tiers:
        raise HTTPException(400, f"Invalid plan tier. Must be one of: {valid_tiers}")

    # Get subscription
    subscription = await subscription_ops.get_by_org(db, request.organization_id)
    if not subscription:
        raise HTTPException(404, "Subscription not found")

    # Check if manually assigned (can't use Stripe checkout)
    if subscription.is_manually_assigned:
        raise HTTPException(400, "Subscription is manually managed — contact support to change")

    # Get or create Stripe customer
    org = await organization_ops.get(db, request.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    if not subscription.stripe_customer_id:
        customer_id = stripe_service.create_customer(org, current_user)
        await subscription_ops.update(db, subscription, {"stripe_customer_id": customer_id})
        await db.commit()
    else:
        customer_id = subscription.stripe_customer_id

    # Determine redirect URLs based on source
    if request.source == "onboarding":
        # User selecting plan during onboarding wizard — return to onboarding flow
        success_url = f"{settings.frontend_url}/onboarding?checkout=success&step=invite"
        cancel_url = f"{settings.frontend_url}/onboarding?checkout=canceled&step=plan"
    elif request.source == "select-plan":
        # New user selecting a plan (standalone page) — redirect to dashboard on success
        success_url = f"{settings.frontend_url}/dashboard?checkout=success"
        cancel_url = f"{settings.frontend_url}/select-plan?checkout=canceled"
    else:
        # Existing user upgrading from billing settings
        success_url = f"{settings.frontend_url}/settings/billing?success=true"
        cancel_url = f"{settings.frontend_url}/settings/billing?canceled=true"

    checkout_url = stripe_service.create_checkout_session(
        customer_id=customer_id,
        plan_tier=request.plan_tier,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/portal", response_model=PortalResponse)
async def create_portal(
    request: PortalRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> PortalResponse:
    """
    Create a Stripe Customer Portal session for self-service billing.

    User must be owner or admin of the organization.
    Returns a URL to redirect the user to Stripe Portal.
    """
    if not settings.stripe_enabled:
        raise HTTPException(400, "Payments not configured")

    # Verify user is owner/admin
    role = await organization_ops.get_member_role(db, request.organization_id, current_user.id)
    if not role or role not in ("owner", "admin"):
        raise HTTPException(403, "Only owners and admins can manage billing")

    # Get subscription
    subscription = await subscription_ops.get_by_org(db, request.organization_id)
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(400, "No Stripe customer — subscribe first")

    # Create portal session
    return_url = f"{settings.frontend_url}/settings/billing"
    portal_url = stripe_service.create_portal_session(
        customer_id=subscription.stripe_customer_id,
        return_url=return_url,
    )

    return PortalResponse(portal_url=portal_url)


# ─────────────────────────────────────────────────────────────────────────────
# Webhook Handler
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/webhooks/stripe")
async def handle_stripe_webhook(
    request: Request,
    db: DbSession,
) -> dict[str, str]:
    """
    Handle Stripe webhook events.

    This endpoint is called by Stripe when subscription events occur.
    Verifies the webhook signature before processing.
    No authentication required (verified by Stripe signature).
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify signature
    try:
        event = stripe_service.construct_webhook_event(payload, sig_header)
    except ValueError:
        raise HTTPException(400, "Invalid webhook signature") from None

    event_type = str(event.get("type", ""))
    event_id = str(event.get("id", ""))
    data = event.get("data", {})
    obj = data.get("object", {}) if isinstance(data, dict) else {}

    logger.info(f"Received Stripe webhook: {event_type} ({event_id})")

    # Check for duplicate (idempotency)
    existing = await db.execute(
        select(BillingEvent).where(BillingEvent.stripe_event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info(f"Skipping duplicate webhook: {event_id}")
        return {"status": "already_processed"}

    # Route to handler
    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(db, obj, event_id)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(db, obj, event_id)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, obj, event_id)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(db, obj, event_id)
    elif event_type == "customer.subscription.trial_will_end":
        await _handle_trial_ending(db, obj, event_id)
    else:
        logger.debug(f"Unhandled webhook event type: {event_type}")

    await db.commit()
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Webhook Handlers
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_checkout_completed(
    db: DbSession,
    session: dict[str, Any],
    event_id: str,
) -> None:
    """Handle successful checkout — activate subscription."""
    customer_id = session.get("customer", "")
    stripe_subscription_id = session.get("subscription", "")

    # Get plan tier from metadata
    metadata = session.get("metadata", {})
    plan_tier = metadata.get("plan_tier", "indie") if isinstance(metadata, dict) else "indie"

    subscription = await subscription_ops.get_by_stripe_customer(db, customer_id)
    if not subscription:
        logger.error(f"No subscription found for customer {customer_id}")
        return

    plan = get_plan(plan_tier)
    previous_tier = subscription.plan_tier

    # Determine status (trialing if subscription has trial)
    stripe_sub = stripe_service.get_subscription(stripe_subscription_id)
    status = SubscriptionStatus.ACTIVE.value
    if stripe_sub and stripe_sub.get("status") == "trialing":
        status = SubscriptionStatus.TRIALING.value

    # Update subscription
    await subscription_ops.update(
        db,
        subscription,
        {
            "plan_tier": plan_tier,
            "status": status,
            "base_repo_limit": plan.base_repo_limit,
            "stripe_subscription_id": stripe_subscription_id,
        },
    )

    # Log billing event
    await subscription_ops.log_event(
        db,
        organization_id=subscription.organization_id,
        event_type=BillingEventType.PLAN_CHANGED,
        previous_value={"plan_tier": previous_tier},
        new_value={"plan_tier": plan_tier, "status": status},
        stripe_event_id=event_id,
        description=f"Subscribed to {plan.display_name} via Stripe Checkout",
    )

    logger.info(f"Activated {plan_tier} subscription for org {subscription.organization_id}")


async def _handle_subscription_updated(
    db: DbSession,
    stripe_sub: dict[str, Any],
    event_id: str,
) -> None:
    """Handle subscription updates (status changes, period changes)."""
    customer_id = stripe_sub.get("customer", "")
    subscription = await subscription_ops.get_by_stripe_customer(db, customer_id)
    if not subscription:
        logger.warning(f"No subscription found for customer {customer_id}")
        return

    # Update period dates
    updates: dict[str, Any] = {
        "cancel_at_period_end": stripe_sub.get("cancel_at_period_end", False),
    }

    # Parse period timestamps
    period_start = stripe_sub.get("current_period_start")
    period_end = stripe_sub.get("current_period_end")
    if period_start:
        updates["current_period_start"] = datetime.fromtimestamp(period_start, tz=UTC)
    if period_end:
        updates["current_period_end"] = datetime.fromtimestamp(period_end, tz=UTC)

    # Update status
    status_map = {
        "active": SubscriptionStatus.ACTIVE.value,
        "trialing": SubscriptionStatus.TRIALING.value,
        "past_due": SubscriptionStatus.PAST_DUE.value,
        "canceled": SubscriptionStatus.CANCELED.value,
        "unpaid": SubscriptionStatus.UNPAID.value,
    }
    stripe_status = stripe_sub.get("status", "")
    if stripe_status in status_map:
        updates["status"] = status_map[stripe_status]

    await subscription_ops.update(db, subscription, updates)

    # Log event
    await subscription_ops.log_event(
        db,
        organization_id=subscription.organization_id,
        event_type=BillingEventType.SUBSCRIPTION_UPDATED,
        new_value={
            "status": updates.get("status"),
            "cancel_at_period_end": updates["cancel_at_period_end"],
        },
        stripe_event_id=event_id,
    )


async def _handle_subscription_deleted(
    db: DbSession,
    stripe_sub: dict[str, Any],
    event_id: str,
) -> None:
    """Handle subscription cancellation — revert to lowest tier."""
    customer_id = stripe_sub.get("customer", "")
    subscription = await subscription_ops.get_by_stripe_customer(db, customer_id)
    if not subscription:
        return

    previous_tier = subscription.plan_tier
    # Revert to indie (lowest paid tier) but mark as canceled
    indie_plan = get_plan("indie")

    await subscription_ops.update(
        db,
        subscription,
        {
            "plan_tier": PlanTier.INDIE.value,
            "status": SubscriptionStatus.CANCELED.value,
            "base_repo_limit": indie_plan.base_repo_limit,
            "canceled_at": datetime.now(UTC),
            "stripe_subscription_id": None,
        },
    )

    await subscription_ops.log_event(
        db,
        organization_id=subscription.organization_id,
        event_type=BillingEventType.SUBSCRIPTION_CANCELED,
        previous_value={"plan_tier": previous_tier},
        new_value={"plan_tier": "indie", "status": "canceled"},
        stripe_event_id=event_id,
        description="Subscription canceled",
    )

    logger.info(f"Canceled subscription for org {subscription.organization_id}")


async def _handle_payment_failed(
    db: DbSession,
    invoice: dict[str, Any],
    event_id: str,
) -> None:
    """Handle failed payment — mark as past due."""
    customer_id = invoice.get("customer", "")
    subscription = await subscription_ops.get_by_stripe_customer(db, customer_id)
    if not subscription:
        return

    await subscription_ops.update(
        db,
        subscription,
        {"status": SubscriptionStatus.PAST_DUE.value},
    )

    await subscription_ops.log_event(
        db,
        organization_id=subscription.organization_id,
        event_type=BillingEventType.PAYMENT_FAILED,
        new_value={"status": "past_due", "invoice_id": invoice.get("id")},
        stripe_event_id=event_id,
        description="Payment failed",
    )

    logger.warning(f"Payment failed for org {subscription.organization_id}")


async def _handle_trial_ending(
    db: DbSession,
    stripe_sub: dict[str, Any],
    event_id: str,
) -> None:
    """Handle trial ending notification (3 days before trial ends)."""
    customer_id = stripe_sub.get("customer", "")
    subscription = await subscription_ops.get_by_stripe_customer(db, customer_id)
    if not subscription:
        return

    # Log event for potential follow-up (email notifications, etc.)
    await subscription_ops.log_event(
        db,
        organization_id=subscription.organization_id,
        event_type=BillingEventType.SUBSCRIPTION_UPDATED,
        new_value={"trial_ending": True, "trial_end": stripe_sub.get("trial_end")},
        stripe_event_id=event_id,
        description="Trial ending in 3 days",
    )

    logger.info(f"Trial ending soon for org {subscription.organization_id}")
