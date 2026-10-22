"""Tests for Telegram delivery and asynchronous notification tasks."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from books.models import Book
from borrowings.models import Borrowing
from notifications.services import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    send_telegram_message,
)
from notifications.tasks import send_new_borrowing_notification


User = get_user_model()


class TelegramDeliveryTests(TestCase):
    @override_settings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="-100123",
    )
    @patch("notifications.services.urlopen")
    def test_sends_form_encoded_message_and_returns_telegram_message_id(
        self, mock_urlopen
    ):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "result": {"message_id": 42}}
        ).encode("utf-8")
        mock_urlopen.return_value = response

        result = send_telegram_message("A new book was borrowed")

        request = mock_urlopen.call_args.args[0]
        self.assertIn("/bottest-token/sendMessage", request.full_url)
        self.assertEqual(
            request.data,
            b"chat_id=-100123&text=A+new+book+was+borrowed",
        )
        self.assertEqual(result, 42)

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_missing_configuration_is_reported_without_a_request(self):
        with self.assertRaises(TelegramConfigurationError):
            send_telegram_message("A new book was borrowed")

    @override_settings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="-100123",
    )
    @patch("notifications.services.urlopen")
    def test_telegram_api_rejection_is_reported(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": False, "description": "Forbidden"}
        ).encode("utf-8")
        mock_urlopen.return_value = response

        with self.assertRaises(TelegramDeliveryError):
            send_telegram_message("A new book was borrowed")

    @override_settings(
        TELEGRAM_BOT_TOKEN="secret-token",
        TELEGRAM_CHAT_ID="-100123",
    )
    @patch("notifications.services.urlopen")
    def test_http_error_does_not_expose_the_bot_token(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "https://api.telegram.org/botsecret-token/sendMessage",
            403,
            "Forbidden",
            None,
            None,
        )

        with self.assertRaises(TelegramDeliveryError) as error:
            send_telegram_message("A new book was borrowed")

        self.assertNotIn("secret-token", str(error.exception))

    @override_settings(
        TELEGRAM_BOT_TOKEN="secret-token",
        TELEGRAM_CHAT_ID="-100123",
    )
    @patch("notifications.services.urlopen")
    def test_network_error_is_reported_without_request_details(
        self, mock_urlopen
    ):
        mock_urlopen.side_effect = URLError(
            "https://api.telegram.org/botsecret-token/sendMessage"
        )

        with self.assertRaises(TelegramDeliveryError) as error:
            send_telegram_message("A new book was borrowed")

        self.assertNotIn("secret-token", str(error.exception))


class NewBorrowingNotificationTaskTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            "reader@example.com",
            "StrongPass9#",
            first_name="Alex",
            last_name="Reader",
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="HARD",
            inventory=0,
            daily_fee=Decimal("1.25"),
        )
        self.borrowing = Borrowing.objects.create(
            user=self.reader,
            book=self.book,
            borrow_date=date(2026, 10, 20),
            expected_return_date=date(2026, 10, 27),
        )

    @patch("notifications.tasks.send_telegram_message")
    def test_task_sends_borrowing_details_to_telegram_service(self, mock_send):
        send_new_borrowing_notification.run(self.borrowing.id)

        message = mock_send.call_args.args[0]
        self.assertIn(f"New borrowing #{self.borrowing.id}", message)
        self.assertIn("Customer: Alex Reader", message)
        self.assertIn("Book: The Hobbit", message)
        self.assertIn("Borrowed: 2026-10-20", message)
        self.assertIn("Expected return: 2026-10-27", message)

    @patch("notifications.tasks.send_telegram_message")
    def test_task_uses_email_when_customer_name_is_empty(self, mock_send):
        self.reader.first_name = ""
        self.reader.last_name = ""
        self.reader.save(update_fields=("first_name", "last_name"))

        send_new_borrowing_notification.run(self.borrowing.id)

        self.assertIn(
            "Customer: reader@example.com",
            mock_send.call_args.args[0],
        )

    @patch("notifications.tasks.send_telegram_message")
    def test_missing_borrowing_is_ignored(self, mock_send):
        send_new_borrowing_notification.run(self.borrowing.id + 1000)

        mock_send.assert_not_called()
