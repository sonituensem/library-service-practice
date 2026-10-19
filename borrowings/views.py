"""Endpoints for customer borrowing records."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from books.models import Book
from borrowings.models import Borrowing
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingReadSerializer,
)


class BorrowingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create borrowing records and read records visible to the current user."""

    queryset = Borrowing.objects.select_related("book", "user")
    serializer_class = BorrowingReadSerializer
    authentication_classes = (JWTAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get_serializer_class(self):
        if self.action == "create":
            return BorrowingCreateSerializer
        return BorrowingReadSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_staff", False):
            return queryset
        if not getattr(user, "is_authenticated", False):
            return queryset.none()
        return queryset.filter(user=user)

    @extend_schema(
        request=None,
        responses={
            status.HTTP_200_OK: BorrowingReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="This borrowing has already been returned."
            ),
        },
    )
    @action(detail=True, methods=("post",), url_path="return")
    def return_book(self, request, *args, **kwargs):
        """Mark a borrowing returned once and restore one available copy."""
        with transaction.atomic():
            borrowing = self.get_object()
            returned = Borrowing.objects.filter(
                pk=borrowing.pk,
                actual_return_date__isnull=True,
            ).update(actual_return_date=timezone.localdate())
            if not returned:
                raise ValidationError(
                    {
                        "actual_return_date": (
                            "This borrowing has already been returned."
                        )
                    }
                )

            Book.objects.filter(pk=borrowing.book_id).update(
                inventory=F("inventory") + 1
            )
            borrowing.refresh_from_db()

        serializer = BorrowingReadSerializer(
            borrowing,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
