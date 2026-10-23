"""Endpoints for customer borrowing records."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
)
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
from payments.services import create_fine_payment_for_return


class BorrowingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create borrowings and read records visible to the current user."""

    queryset = (
        Borrowing.objects.select_related(
            "book",
            "user",
        )
        .prefetch_related("payments")
    )
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
            if self.action == "list":
                user_id = self.request.query_params.get("user_id")
                if user_id:
                    try:
                        user_id = int(user_id)
                    except ValueError as exc:
                        raise ValidationError(
                            {"user_id": "Must be a positive integer."}
                        ) from exc
                    if user_id <= 0:
                        raise ValidationError(
                            {"user_id": "Must be a positive integer."}
                        )
                    queryset = queryset.filter(user_id=user_id)
        elif not getattr(user, "is_authenticated", False):
            return queryset.none()
        else:
            queryset = queryset.filter(user=user)

        if self.action == "list":
            is_active = self.request.query_params.get("is_active")
            if is_active is not None:
                is_active = is_active.lower()
                if is_active not in {"true", "false"}:
                    raise ValidationError(
                        {"is_active": "Use 'true' or 'false'."}
                    )
                queryset = queryset.filter(
                    actual_return_date__isnull=(is_active == "true")
                )

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="is_active",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by return status: true for not-yet-returned "
                    "borrowings, false for returned borrowings."
                ),
            ),
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description=(
                    "Staff only: restrict results to this user. Ignored "
                    "for non-staff users."
                ),
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List visible borrowings with optional query filters."""
        return super().list(request, *args, **kwargs)

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
            actual_return_date = timezone.localdate()
            returned = Borrowing.objects.filter(
                pk=borrowing.pk,
                actual_return_date__isnull=True,
            ).update(actual_return_date=actual_return_date)
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
            create_fine_payment_for_return(
                borrowing,
                actual_return_date,
            )

        serializer = BorrowingReadSerializer(
            borrowing,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
