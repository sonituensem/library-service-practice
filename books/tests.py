"""API tests for the Books Service inventory endpoints."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from books.models import Book


User = get_user_model()


class BookAPITests(APITestCase):
    list_url = "/api/books/"

    def setUp(self):
        self.user = User.objects.create_user(
            "librarian@example.com", "StrongPass9#", is_staff=True
        )
        self.reader = User.objects.create_user(
            "reader@example.com", "StrongPass9#", is_staff=False
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="HARD",
            inventory=3,
            daily_fee=Decimal("1.25"),
        )
        self.detail_url = f"{self.list_url}{self.book.pk}/"

    def authenticate_as(self, user):
        access_token = RefreshToken.for_user(user).access_token
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access_token}")

    def test_guest_can_list_books(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.book.pk)
        self.assertEqual(response.data[0]["title"], "The Hobbit")

    def test_guest_can_retrieve_book_details(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["author"], "J. R. R. Tolkien")
        self.assertEqual(response.data["cover"], "HARD")
        self.assertEqual(response.data["inventory"], 3)
        self.assertEqual(
            Decimal(str(response.data["daily_fee"])), Decimal("1.25")
        )

    def test_openapi_marks_public_book_reads_without_authentication(self):
        response = self.client.get("/api/schema/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        books = response.data["paths"]
        self.assertNotIn("security", books["/api/books/"]["get"])
        self.assertNotIn("security", books["/api/books/{id}/"]["get"])
        self.assertEqual(
            books["/api/books/"]["post"]["security"], [{"jwtAuth": []}]
        )

    def test_regular_user_can_read_books(self):
        self.authenticate_as(self.reader)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_authenticated_user_can_create_book(self):
        self.authenticate_as(self.user)

        response = self.client.post(
            self.list_url,
            {
                "title": "Dune",
                "author": "Frank Herbert",
                "cover": "SOFT",
                "inventory": 5,
                "daily_fee": "2.50",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Book.objects.count(), 2)
        created = Book.objects.get(pk=response.data["id"])
        self.assertEqual(created.title, "Dune")
        self.assertEqual(created.cover, "SOFT")
        self.assertEqual(created.inventory, 5)
        self.assertEqual(created.daily_fee, Decimal("2.50"))

    def test_authenticated_user_can_replace_book(self):
        self.authenticate_as(self.user)

        response = self.client.put(
            self.detail_url,
            {
                "title": "The Lord of the Rings",
                "author": "J. R. R. Tolkien",
                "cover": "SOFT",
                "inventory": 2,
                "daily_fee": "3.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "The Lord of the Rings")
        self.assertEqual(self.book.cover, "SOFT")
        self.assertEqual(self.book.inventory, 2)
        self.assertEqual(self.book.daily_fee, Decimal("3.00"))

    def test_authenticated_user_can_patch_inventory_to_zero(self):
        self.authenticate_as(self.user)

        response = self.client.patch(
            self.detail_url, {"inventory": 0}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 0)
        self.assertEqual(self.book.title, "The Hobbit")

    def test_authenticated_user_can_delete_book(self):
        self.authenticate_as(self.user)

        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Book.objects.filter(pk=self.book.pk).exists())

    def test_rejects_negative_inventory(self):
        self.authenticate_as(self.user)

        response = self.client.patch(
            self.detail_url, {"inventory": -1}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inventory", response.data)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)

    def test_rejects_invalid_cover(self):
        self.authenticate_as(self.user)

        response = self.client.patch(
            self.detail_url, {"cover": "PAPER"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cover", response.data)
        self.book.refresh_from_db()
        self.assertEqual(self.book.cover, "HARD")

    def test_rejects_negative_daily_fee(self):
        self.authenticate_as(self.user)

        response = self.client.patch(
            self.detail_url, {"daily_fee": "-0.01"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("daily_fee", response.data)
        self.book.refresh_from_db()
        self.assertEqual(self.book.daily_fee, Decimal("1.25"))

    def test_anonymous_user_cannot_create_book(self):
        response = self.client.post(
            self.list_url,
            {
                "title": "Dune",
                "author": "Frank Herbert",
                "cover": "SOFT",
                "inventory": 5,
                "daily_fee": "2.50",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Book.objects.count(), 1)

    def test_non_staff_user_cannot_change_inventory(self):
        self.authenticate_as(self.reader)

        response = self.client.patch(
            self.detail_url, {"inventory": 0}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)

    def test_non_staff_user_cannot_delete_book(self):
        self.authenticate_as(self.reader)

        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())
