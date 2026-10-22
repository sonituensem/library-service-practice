"""Business logic for calculating and starting borrowing payments."""

from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from rest_framework.exceptions import APIException

from payments.models import Payment


class StripeCheckoutError(APIException):
    """A safe API error for an unavailable or misconfigured Stripe service."""

    status_code = 503
    default_detail = "Stripe Checkout is not available right now."
    default_code = "stripe_unavailable"


def calculate_borrowing_total(borrowing):
    """Multiply the daily fee by days between the planned borrowing dates."""
    days = (borrowing.expected_return_date - borrowing.borrow_date).days
    total = borrowing.book.daily_fee * days
    return total.quantize(Decimal("0.01"))


def _configure_stripe():
    secret_key = settings.STRIPE_SECRET_KEY
    if not secret_key.startswith("sk_test_"):
        raise StripeCheckoutError()

    stripe.api_key = secret_key


def _create_checkout_session(payment, request):
    _configure_stripe()
    amount_in_cents = int(payment.money_to_pay * 100)
    borrowing = payment.borrowing
    success_url = request.build_absolute_uri(reverse("payment-success"))
    success_url += "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = request.build_absolute_uri(reverse("payment-cancel"))

    try:
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"Library borrowing #{borrowing.pk}",
                        },
                        "unit_amount": amount_in_cents,
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(payment.pk),
            metadata={
                "payment_id": str(payment.pk),
                "borrowing_id": str(borrowing.pk),
            },
        )
    except stripe.StripeError:
        # SDK errors can carry request data. Keep the API response safe.
        raise StripeCheckoutError() from None


def retrieve_checkout_session(session_id):
    """Fetch a Checkout Session from Stripe using the test-mode key."""
    _configure_stripe()
    try:
        return stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:
        raise StripeCheckoutError() from None


@transaction.atomic
def create_payment_for_borrowing(borrowing, request):
    """Persist a pending payment and its hosted Stripe Checkout session."""
    amount = calculate_borrowing_total(borrowing)
    payment = Payment.objects.create(
        status=Payment.Status.PENDING,
        type=Payment.Type.PAYMENT,
        borrowing=borrowing,
        money_to_pay=amount,
    )
    session = _create_checkout_session(payment, request)
    if not session.id or not session.url:
        raise StripeCheckoutError()

    payment.session_id = session.id
    payment.session_url = session.url
    payment.save(update_fields=("session_id", "session_url"))
    return payment
