"""Asynchronous Telegram notifications."""

from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist

from borrowings.models import Borrowing
from notifications.services import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    send_telegram_message,
)


def format_new_borrowing_message(borrowing):
    """Build an administrator-facing message for a new borrowing."""
    customer = " ".join(
        value
        for value in (borrowing.user.first_name, borrowing.user.last_name)
        if value
    ) or borrowing.user.email
    return (
        f"New borrowing #{borrowing.id}\n"
        f"Customer: {customer}\n"
        f"Book: {borrowing.book.title} (ID: {borrowing.book_id})\n"
        f"Borrowed: {borrowing.borrow_date.isoformat()}\n"
        f"Expected return: {borrowing.expected_return_date.isoformat()}"
    )


@shared_task(
    bind=True,
    autoretry_for=(TelegramDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    ignore_result=True,
)
def send_new_borrowing_notification(self, borrowing_id):
    """Notify library administrators after a borrowing is committed."""
    try:
        borrowing = Borrowing.objects.select_related("user", "book").get(
            pk=borrowing_id
        )
    except ObjectDoesNotExist:
        return

    try:
        message = format_new_borrowing_message(borrowing)
        send_telegram_message(message)
    except TelegramConfigurationError:
        # Missing credentials are a deployment configuration issue, not transient.
        raise

