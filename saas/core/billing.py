"""Stripe 결제: Checkout 세션, Customer Portal, price→tier 매핑."""
import stripe

from core import config, db

stripe.api_key = config.STRIPE_SECRET_KEY


def tier_from_price(price_id: str) -> str:
    return config.PRICE_TO_TIER.get(price_id, "free")


def _ensure_customer(sb, user_id: str, email: str) -> str:
    profile = db.get_profile(sb, user_id)
    if profile and profile.get("stripe_customer_id"):
        return profile["stripe_customer_id"]
    customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
    db.set_stripe_customer(sb, user_id, customer.id)
    return customer.id


def create_checkout_url(sb, user_id: str, email: str, tier: str) -> str:
    price_id = config.STRIPE_PRICE_PRO if tier == "pro" else config.STRIPE_PRICE_BUSINESS
    customer_id = _ensure_customer(sb, user_id, email)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{config.APP_BASE_URL}?checkout=success",
        cancel_url=f"{config.APP_BASE_URL}?checkout=cancel",
        metadata={"user_id": user_id},
    )
    return session.url


def create_portal_url(sb, user_id: str) -> str | None:
    profile = db.get_profile(sb, user_id)
    if not profile or not profile.get("stripe_customer_id"):
        return None
    session = stripe.billing_portal.Session.create(
        customer=profile["stripe_customer_id"],
        return_url=config.APP_BASE_URL,
    )
    return session.url
