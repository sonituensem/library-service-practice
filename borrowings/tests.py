from django.test import TestCase

"""API and model tests for the Borrowings Service."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book
from borrowings.models import Borrowing


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
        self.assertEqual([item["id"] for item in response.data], [self.borrowing.id])

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

        response = self.client.get(f"{self.list_url}{self.other_borrowing.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_list_all_borrowings(self):
        self.authenticate_as(self.librarian)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_authenticated_user_can_create_borrowing_and_reserve_copy(self):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "user": self.other_reader.id,
                "borrow_date": "2026-01-01",
                "actual_return_date": "2026-02-01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"], self.reader.id)
        self.assertEqual(response.data["borrow_date"], timezone.localdate().isoformat())
        self.assertEqual(response.data["book"]["id"], self.book.id)
        self.assertIsNone(response.data["actual_return_date"])
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 1)

    def test_anonymous_user_cannot_create_borrowing(self):
        response = self.client.post(
            self.list_url,
            {
                "book_id": self.book.id,
                "expected_return_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
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
                "expected_return_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
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
                "expected_return_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expected_return_date", response.data)
        self.assertEqual(Borrowing.objects.count(), 2)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)


class BorrowingDateConstraintTests(APITestCase):
    def setUp(self):
        self.reader = User.objects.create_user("reader@example.com", "StrongPass9#")
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
