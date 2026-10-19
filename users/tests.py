"""API tests for registration, JWT authentication, and user profiles."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase


User = get_user_model()


class UserRegistrationTests(APITestCase):
    registration_url = "/api/users/"

    def test_registers_user_and_never_returns_password(self):
        response = self.client.post(
            self.registration_url,
            {
                "email": "reader@example.com",
                "password": "StrongPass9#",
                "first_name": "Alex",
                "last_name": "Reader",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "reader@example.com")
        self.assertNotIn("password", response.data)
        user = User.objects.get(email="reader@example.com")
        self.assertTrue(user.check_password("StrongPass9#"))

    def test_rejects_duplicate_email(self):
        User.objects.create_user("reader@example.com", "StrongPass9#")

        response = self.client.post(
            self.registration_url,
            {"email": "reader@EXAMPLE.COM", "password": "AnotherPass9#"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_rejects_weak_password(self):
        response = self.client.post(
            self.registration_url,
            {"email": "reader@example.com", "password": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)


class UserAuthenticationAndProfileTests(APITestCase):
    token_url = "/api/users/token/"
    refresh_url = "/api/users/token/refresh/"
    profile_url = "/api/users/me/"

    def setUp(self):
        self.password = "StrongPass9#"
        self.user = User.objects.create_user(
            "reader@example.com",
            self.password,
            first_name="Alex",
            last_name="Reader",
        )

    def get_access_token(self):
        response = self.client.post(
            self.token_url,
            {"email": self.user.email, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        return response.data["access"], response.data["refresh"]

    def test_obtains_and_refreshes_jwt_tokens(self):
        _, refresh = self.get_access_token()

        response = self.client.post(
            self.refresh_url,
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_profile_requires_authentication(self):
        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authorize_header_authenticates_profile_requests(self):
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user.email)
        self.assertEqual(response.data["first_name"], "Alex")
        self.assertNotIn("password", response.data)

    def test_profile_update_changes_only_allowed_fields(self):
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.patch(
            self.profile_url,
            {"first_name": "Sam", "is_staff": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Sam")
        self.assertFalse(self.user.is_staff)

    def test_profile_update_changes_email_and_hashes_new_password(self):
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.patch(
            self.profile_url,
            {"email": "new@EXAMPLE.COM", "password": "AnotherStrong9#"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertTrue(self.user.check_password("AnotherStrong9#"))
        self.assertFalse(self.user.check_password(self.password))

        self.client.credentials()
        login_response = self.client.post(
            self.token_url,
            {"email": "new@example.com", "password": "AnotherStrong9#"},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)

    def test_profile_update_rejects_duplicate_email(self):
        User.objects.create_user("other@example.com", "AnotherStrong9#")
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.patch(
            self.profile_url,
            {"email": "other@EXAMPLE.COM"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "reader@example.com")

    def test_profile_update_rejects_weak_password(self):
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.patch(
            self.profile_url,
            {"password": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_profile_put_updates_the_authenticated_user(self):
        access, _ = self.get_access_token()
        self.client.credentials(HTTP_AUTHORIZE=f"Bearer {access}")

        response = self.client.put(
            self.profile_url,
            {"first_name": "Sam", "last_name": "Booklover"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Sam")
        self.assertEqual(self.user.last_name, "Booklover")

    def test_rejects_invalid_credentials(self):
        response = self.client.post(
            self.token_url,
            {"email": self.user.email, "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
