"""API tests for payment visibility and read-only endpoints."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book
from borrowings.models import Borrowing
from payments.models import Payment
from payments.services import (
    StripeCheckoutError,
    calculate_borrowing_total,
    retrieve_checkout_session,
)


User = get_user_model()


class StripeSessionRetrievalTests(SimpleTestCase):
    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.services.stripe.checkout.Session.retrieve")
    def test_retrieves_checkout_session_with_test_key(self, mock_retrieve):
        expected_session = SimpleNamespace(id="cs_test_verified")
        mock_retrieve.return_value = expected_session

        session = retrieve_checkout_session("cs_test_verified")

        self.assertIs(session, expected_session)
        mock_retrieve.assert_called_once_with("cs_test_verified")

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.services.stripe.checkout.Session.retrieve")
    def test_stripe_error_is_sanitized(self, mock_retrieve):
        mock_retrieve.side_effect = stripe.APIConnectionError(
            "secret request details"
        )

        with self.assertRaises(StripeCheckoutError) as error:
            retrieve_checkout_session("cs_test_verified")

        self.assertNotIn("secret request details", str(error.exception))

    @override_settings(STRIPE_SECRET_KEY="sk_live_must_not_be_used")
    @patch("payments.services.stripe.checkout.Session.retrieve")
    def test_retrieval_rejects_live_key(self, mock_retrieve):
        with self.assertRaises(StripeCheckoutError):
            retrieve_checkout_session("cs_live_not_allowed")

        mock_retrieve.assert_not_called()


class PaymentAPITests(APITestCase):
    list_url = "/api/payments/"

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
        self.payment = Payment.objects.create(
            status=Payment.Status.PENDING,
            type=Payment.Type.PAYMENT,
            borrowing=self.borrowing,
            session_url="https://checkout.stripe.com/session/test",
            session_id="cs_test_reader",
            money_to_pay=Decimal("8.75"),
        )
        self.other_payment = Payment.objects.create(
            status=Payment.Status.PAID,
            type=Payment.Type.FINE,
            borrowing=self.other_borrowing,
            session_url="https://checkout.stripe.com/session/other",
            session_id="cs_test_other",
            money_to_pay=Decimal("2.50"),
        )

    def create_borrowing(self, user):
        return Borrowing.objects.create(
            borrow_date=date(2026, 1, 1),
            expected_return_date=date(2026, 1, 8),
            book=self.book,
            user=user,
        )

    def authenticate_as(self, user):
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access_token}")

    def test_payment_list_requires_authentication(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_lists_only_payments_for_their_borrowings(self):
        self.authenticate_as(self.reader)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [self.payment.id],
        )

    def test_staff_can_list_all_payments(self):
        self.authenticate_as(self.librarian)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data},
            {self.payment.id, self.other_payment.id},
        )

    def test_payment_detail_exposes_contract_fields(self):
        self.authenticate_as(self.reader)

        response = self.client.get(f"{self.list_url}{self.payment.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "id": self.payment.id,
                "status": Payment.Status.PENDING,
                "type": Payment.Type.PAYMENT,
                "borrowing": self.borrowing.id,
                "session_url": self.payment.session_url,
                "session_id": self.payment.session_id,
                "money_to_pay": "8.75",
            },
        )

    def test_borrowing_total_is_zero_for_same_day_dates(self):
        self.borrowing.expected_return_date = self.borrowing.borrow_date

        total = calculate_borrowing_total(self.borrowing)

        self.assertEqual(total, Decimal("0.00"))

    def test_customer_cannot_retrieve_another_users_payment(self):
        self.authenticate_as(self.reader)

        response = self.client.get(
            f"{self.list_url}{self.other_payment.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_payment_api_does_not_allow_customer_to_create_or_update(self):
        self.authenticate_as(self.reader)

        create_response = self.client.post(
            self.list_url,
            {
                "status": Payment.Status.PAID,
                "type": Payment.Type.PAYMENT,
                "borrowing": self.borrowing.id,
                "money_to_pay": "0.01",
            },
            format="json",
        )
        update_response = self.client.patch(
            f"{self.list_url}{self.payment.id}/",
            {"status": Payment.Status.PAID},
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            update_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)


class PaymentCallbackAPITests(APITestCase):
    success_url = "/api/payments/success/"
    cancel_url = "/api/payments/cancel/"

    def setUp(self):
        user = User.objects.create_user(
            "reader@example.com", "StrongPass9#", first_name="Alex"
        )
        book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="HARD",
            inventory=0,
            daily_fee=Decimal("1.25"),
        )
        borrowing = Borrowing.objects.create(
            borrow_date=date(2026, 1, 1),
            expected_return_date=date(2026, 1, 8),
            book=book,
            user=user,
        )
        self.payment = Payment.objects.create(
            status=Payment.Status.PENDING,
            type=Payment.Type.PAYMENT,
            borrowing=borrowing,
            session_url="https://checkout.stripe.com/session/test",
            session_id="cs_test_callback",
            money_to_pay=Decimal("8.75"),
        )

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.views.send_successful_payment_notification.delay")
    @patch("payments.views.retrieve_checkout_session")
    def test_success_confirms_payment_and_queues_one_notification(
        self, mock_retrieve, mock_notify
    ):
        mock_retrieve.return_value = SimpleNamespace(
            id=self.payment.session_id,
            status="complete",
            payment_status="paid",
        )
        callback_url = (
            f"{self.success_url}?session_id={self.payment.session_id}"
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(callback_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], Payment.Status.PAID)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        mock_notify.assert_called_once_with(self.payment.id)

        with self.captureOnCommitCallbacks(execute=True):
            duplicate_response = self.client.get(callback_url)

        self.assertEqual(duplicate_response.status_code, status.HTTP_200_OK)
        mock_notify.assert_called_once_with(self.payment.id)

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.views.send_successful_payment_notification.delay")
    @patch("payments.views.retrieve_checkout_session")
    def test_unpaid_session_does_not_mark_payment_paid(
        self, mock_retrieve, mock_notify
    ):
        mock_retrieve.return_value = SimpleNamespace(
            id=self.payment.session_id,
            status="open",
            payment_status="unpaid",
        )

        response = self.client.get(
            self.success_url,
            {"session_id": self.payment.session_id},
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        mock_notify.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY="sk_test_for_tests_only")
    @patch("payments.views.retrieve_checkout_session")
    def test_success_requires_known_session_and_rejects_invalid_id(
        self, mock_retrieve
    ):
        missing_id_response = self.client.get(self.success_url)
        unknown_id_response = self.client.get(
            self.success_url,
            {"session_id": "cs_test_unknown"},
        )
        mock_retrieve.return_value = SimpleNamespace(
            id="cs_test_different",
            status="complete",
            payment_status="paid",
        )
        mismatched_id_response = self.client.get(
            self.success_url,
            {"session_id": self.payment.session_id},
        )

        self.assertEqual(
            missing_id_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            unknown_id_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            mismatched_id_response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        mock_retrieve.assert_called_once_with(self.payment.session_id)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    @override_settings(STRIPE_SECRET_KEY="")
    @patch("payments.views.retrieve_checkout_session")
    def test_success_returns_service_unavailable_without_test_key(
        self, mock_retrieve
    ):
        response = self.client.get(
            self.success_url,
            {"session_id": self.payment.session_id},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        mock_retrieve.assert_called_once_with(self.payment.session_id)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_cancel_explains_session_window_without_changing_payment(self):
        response = self.client.get(self.cancel_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("24 hours", response.data["message"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
