"""API tests for payment visibility and read-only endpoints."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book
from borrowings.models import Borrowing
from payments.models import Payment


User = get_user_model()


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
