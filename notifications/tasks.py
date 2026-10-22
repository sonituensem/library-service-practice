"""Asynchronous Telegram notifications."""

from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from borrowings.models import Borrowing
from notifications.services import TelegramDeliveryError, send_telegram_message


def format_new_borrowing_message(borrowing):
    """Build an administrator-facing message for a new borrowing."""
    customer = format_customer_name(borrowing)
    return (
        f"New borrowing #{borrowing.id}\n"
        f"Customer: {customer}\n"
        f"Book: {borrowing.book.title} (ID: {borrowing.book_id})\n"
        f"Borrowed: {borrowing.borrow_date.isoformat()}\n"
        f"Expected return: {borrowing.expected_return_date.isoformat()}"
    )


def format_customer_name(borrowing):
    """Return the customer's name or email for administrator messages."""
    return " ".join(
        value
        for value in (borrowing.user.first_name, borrowing.user.last_name)
        if value
    ) or borrowing.user.email


def format_overdue_borrowing_message(borrowing, today=None):
    """Build a detailed administrator-facing overdue notice."""
    today = today or timezone.localdate()
    days_overdue = (today - borrowing.expected_return_date).days
    return (
        f"Overdue borrowing #{borrowing.id}\n"
        f"Customer: {format_customer_name(borrowing)}\n"
        f"Book: {borrowing.book.title} (ID: {borrowing.book_id})\n"
        f"Borrowed: {borrowing.borrow_date.isoformat()}\n"
        f"Expected return: {borrowing.expected_return_date.isoformat()}\n"
        f"Days overdue: {days_overdue}"
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

    message = format_new_borrowing_message(borrowing)
    send_telegram_message(message)


@shared_task(
    bind=True,
    autoretry_for=(TelegramDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    ignore_result=True,
)
def send_overdue_borrowing_notification(self, borrowing_id):
    """Send an individual notice if the borrowing remains overdue."""
    today = timezone.localdate()
    borrowing = Borrowing.objects.filter(
        pk=borrowing_id,
        expected_return_date__lte=today,
        actual_return_date__isnull=True,
    ).select_related("user", "book").first()
    if borrowing is None:
        return

    message = format_overdue_borrowing_message(borrowing, today=today)
    send_telegram_message(message)


@shared_task(
    autoretry_for=(TelegramDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    ignore_result=True,
)
def send_no_overdue_borrowings_notification():
    """Notify administrators when the daily check finds no overdue loans."""
    send_telegram_message("No borrowings overdue today!")


@shared_task(ignore_result=True)
def check_overdue_borrowings():
    """Queue individual Telegram messages for all currently overdue loans."""
    today = timezone.localdate()
    overdue_ids = list(
        Borrowing.objects.filter(
            expected_return_date__lte=today,
            actual_return_date__isnull=True,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )

    if not overdue_ids:
        send_no_overdue_borrowings_notification.delay()
        return 0

    for borrowing_id in overdue_ids:
        send_overdue_borrowing_notification.delay(borrowing_id)

    return len(overdue_ids)
