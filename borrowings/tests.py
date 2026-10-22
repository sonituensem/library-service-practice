"""API and model tests for the Borrowings Service."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book
from borrowings.models import Borrowing
from payments.models import Payment


User = get_user_model()


class BorrowingReadAPITests(APITestCase):
    list_url = "/api/borrowings/"

    def setUp(self):
        self.reader = User.objects.create_user(
            "reader@example.com", "StrongPass9#"
        )
        self.other_reader = User.objects.create_user(
            "other@example.com", "StrongPass9#"
        )
        self.librarian = User.objects.create_user(
            "librarian@example.com", "StrongPass9#", is_staff=True
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="HARD",
            inventory=2,
            daily_fee=Decimal("1.25"),
        )
        self.borrowing = self.create_borrowing(self.reader)
        self.other_borrowing = self.create_borrowing(self.other_reader)

    def create_borrowing(self, user, **date_overrides):
        dates = {
            "borrow_date": date(2026, 1, 1),
            "expected_return_date": date(2026, 1, 8),
            "actual_return_date": None,
        }
        dates.update(date_overrides)
        return Borrowing.objects.create(book=self.book, user=user, **dates)

    def authenticate_as(self, user):
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access_token}")

    def test_borrowing_list_requires_authentication(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_list_contains_only_their_borrowings(self):
        self.authenticate_as(self.reader)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [self.borrowing.id],
        )

    def test_detail_returns_nested_book_and_borrower_id(self):
        self.authenticate_as(self.reader)

        response = self.client.get(f"{self.list_url}{self.borrowing.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"], self.reader.id)
        self.assertEqual(response.data["borrow_date"], "2026-01-01")
        self.assertEqual(response.data["expected_return_date"], "2026-01-08")
        self.assertIsNone(response.data["actual_return_date"])
        self.assertEqual(response.data["book"]["id"], self.book.id)
        self.assertEqual(response.data["book"]["title"], "The Hobbit")
        self.assertEqual(response.data["book"]["author"], "J. R. R. Tolkien")

    def test_user_cannot_retrieve_another_users_borrowing(self):
        self.authenticate_as(self.reader)

        response = self.client.get(
            f"{self.list_url}{self.other_borrowing.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_list_all_borrowings(self):
        self.authenticate_as(self.librarian)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    @patch("borrowings.serializers.create_payment_for_borrowing")
    def test_authenticated_user_can_create_borrowing_and_reserve_copy(
        self, mock_create_payment
    ):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
                "user": self.other_reader.id,
                "borrow_date": "2026-01-01",
                "actual_return_date": "2026-02-01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"], self.reader.id)
        self.assertEqual(
            response.data["borrow_date"],
            timezone.localdate().isoformat(),
        )
        self.assertEqual(response.data["book"]["id"], self.book.id)
        self.assertIsNone(response.data["actual_return_date"])
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 1)
        mock_create_payment.assert_called_once()

    @patch("borrowings.serializers.send_new_borrowing_notification.delay")
    @patch("borrowings.serializers.create_payment_for_borrowing")
    def test_borrowing_creation_queues_notification_after_commit(
        self, mock_create_payment, mock_delay
    ):
        self.authenticate_as(self.reader)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.list_url,
                {
                    "book_id": self.book.id,
                    "expected_return_date": (
                        timezone.localdate() + timedelta(days=7)
                    ).isoformat(),
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_delay.assert_called_once_with(response.data["id"])
        mock_create_payment.assert_called_once()

    @override_settings(STRIPE_SECRET_KEY="")
    def test_checkout_configuration_error_rolls_back_borrowing(self):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.assertEqual(Borrowing.objects.count(), 2)
        self.assertFalse(Payment.objects.exists())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.services.stripe.checkout.Session.create")
    def test_stripe_api_error_rolls_back_borrowing_without_leaking_key(
        self, mock_create_session
    ):
        mock_create_session.side_effect = stripe.APIConnectionError(
            "Stripe connection failed"
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.assertNotIn("sk_test", str(response.data))
        self.assertEqual(Borrowing.objects.count(), 2)
        self.assertFalse(Payment.objects.exists())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)

    @override_settings(STRIPE_SECRET_KEY="sk_live_must_not_be_used")
    @patch("payments.services.stripe.checkout.Session.create")
    def test_live_stripe_key_is_rejected_without_creating_checkout(
        self, mock_create_session
    ):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        mock_create_session.assert_not_called()
        self.assertEqual(Borrowing.objects.count(), 2)
        self.assertFalse(Payment.objects.exists())

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.services.stripe.checkout.Session.create")
    def test_checkout_session_and_payment_are_returned_with_borrowing(
        self, mock_create_session
    ):
        session_url = "https://checkout.stripe.com/c/pay/" + "a" * 300
        mock_create_session.return_value = SimpleNamespace(
            id="cs_test_checkout",
            url=session_url,
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["payments"]), 1)
        payment_data = response.data["payments"][0]
        payment = Payment.objects.get(pk=payment_data["id"])
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.type, Payment.Type.PAYMENT)
        self.assertEqual(payment.money_to_pay, Decimal("8.75"))
        self.assertEqual(payment.session_id, "cs_test_checkout")
        self.assertEqual(payment.session_url, session_url)
        self.assertEqual(payment_data["borrowing"], response.data["id"])
        self.assertEqual(payment_data["money_to_pay"], "8.75")
        self.assertEqual(mock_create_session.call_count, 1)
        checkout_params = mock_create_session.call_args.kwargs
        self.assertEqual(checkout_params["mode"], "payment")
        self.assertEqual(checkout_params["line_items"][0]["quantity"], 1)
        self.assertEqual(
            checkout_params["line_items"][0]["price_data"]["currency"],
            "usd",
        )
        self.assertEqual(
            checkout_params["line_items"][0]["price_data"]["unit_amount"],
            875,
        )
        self.assertEqual(
            checkout_params["success_url"],
            "http://testserver/api/payments/success/"
            "?session_id={CHECKOUT_SESSION_ID}",
        )
        self.assertEqual(
            checkout_params["cancel_url"],
            "http://testserver/api/payments/cancel/",
        )

    def test_anonymous_user_cannot_create_borrowing(self):
        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)

    def test_cannot_borrow_book_with_zero_inventory(self):
        self.book.inventory = 0
        self.book.save(update_fields=("inventory",))
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("book_id", response.data)
        self.assertEqual(Borrowing.objects.count(), 2)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 0)

    def test_expected_return_date_before_borrow_date_is_rejected(self):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (
                    timezone.localdate() - timedelta(days=1)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expected_return_date", response.data)
        self.assertEqual(Borrowing.objects.count(), 2)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)

    def test_user_can_return_borrowing_and_restore_inventory(self):
        self.authenticate_as(self.reader)
        self.borrowing.expected_return_date = timezone.localdate()
        self.borrowing.save(update_fields=("expected_return_date",))
        inventory_before = self.book.inventory

        response = self.client.post(
            f"{self.list_url}{self.borrowing.id}/return/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["actual_return_date"],
            timezone.localdate().isoformat(),
        )
        self.assertEqual(response.data["book"]["id"], self.book.id)
        self.assertEqual(response.data["payments"], [])
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, inventory_before + 1)

    @override_settings(FINE_MULTIPLIER=Decimal("2"))
    @patch("borrowings.views.timezone.localdate")
    def test_late_return_creates_pending_fine(self, mock_localdate):
        return_date = date(2026, 10, 22)
        mock_localdate.return_value = return_date
        self.borrowing.borrow_date = return_date - timedelta(days=10)
        self.borrowing.expected_return_date = return_date - timedelta(days=3)
        self.borrowing.save(
            update_fields=("borrow_date", "expected_return_date")
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            f"{self.list_url}{self.borrowing.id}/return/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        fine = Payment.objects.get(borrowing=self.borrowing)
        self.assertEqual(fine.type, Payment.Type.FINE)
        self.assertEqual(fine.status, Payment.Status.PENDING)
        self.assertEqual(fine.money_to_pay, Decimal("7.50"))
        self.assertEqual(response.data["payments"][0]["id"], fine.id)

    @patch("borrowings.views.timezone.localdate")
    def test_late_return_creates_only_one_fine(self, mock_localdate):
        return_date = date(2026, 10, 22)
        mock_localdate.return_value = return_date
        self.borrowing.borrow_date = return_date - timedelta(days=10)
        self.borrowing.expected_return_date = return_date - timedelta(days=1)
        self.borrowing.save(
            update_fields=("borrow_date", "expected_return_date")
        )
        self.authenticate_as(self.reader)
        return_url = f"{self.list_url}{self.borrowing.id}/return/"

        first_response = self.client.post(return_url, format="json")
        second_response = self.client.post(return_url, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            Payment.objects.filter(
                borrowing=self.borrowing,
                type=Payment.Type.FINE,
            ).count(),
            1,
        )

    @override_settings(FINE_MULTIPLIER=Decimal("0.5"))
    @patch("borrowings.views.timezone.localdate")
    def test_fine_rounds_half_cent_up(self, mock_localdate):
        return_date = date(2026, 10, 22)
        mock_localdate.return_value = return_date
        self.book.daily_fee = Decimal("0.01")
        self.book.save(update_fields=("daily_fee",))
        self.borrowing.borrow_date = return_date - timedelta(days=2)
        self.borrowing.expected_return_date = return_date - timedelta(days=1)
        self.borrowing.save(
            update_fields=("borrow_date", "expected_return_date")
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            f"{self.list_url}{self.borrowing.id}/return/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        fine = Payment.objects.get(borrowing=self.borrowing)
        self.assertEqual(fine.money_to_pay, Decimal("0.01"))

    def test_borrowing_cannot_be_returned_twice(self):
        self.authenticate_as(self.reader)
        self.borrowing.expected_return_date = timezone.localdate()
        self.borrowing.save(update_fields=("expected_return_date",))
        inventory_before = self.book.inventory
        return_url = f"{self.list_url}{self.borrowing.id}/return/"

        first_response = self.client.post(return_url, format="json")
        second_response = self.client.post(return_url, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("actual_return_date", second_response.data)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, inventory_before + 1)

    def test_user_cannot_return_another_users_borrowing(self):
        self.authenticate_as(self.reader)

        response = self.client.post(
            f"{self.list_url}{self.other_borrowing.id}/return/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.other_borrowing.refresh_from_db()
        self.assertIsNone(self.other_borrowing.actual_return_date)

    def test_anonymous_user_cannot_return_borrowing(self):
        response = self.client.post(
            f"{self.list_url}{self.borrowing.id}/return/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class BorrowingDateConstraintTests(APITestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            "reader@example.com", "StrongPass9#"
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="HARD",
            inventory=1,
            daily_fee=Decimal("1.25"),
        )

    def test_expected_return_date_cannot_precede_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    book=self.book,
                    user=self.reader,
                    borrow_date=date(2026, 1, 8),
                    expected_return_date=date(2026, 1, 7),
                )

    def test_actual_return_date_cannot_precede_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    book=self.book,
                    user=self.reader,
                    borrow_date=date(2026, 1, 8),
                    expected_return_date=date(2026, 1, 15),
                    actual_return_date=date(2026, 1, 7),
                )
