"""Read-only endpoints for customer borrowing records."""

from rest_framework import mixins, permissions, viewsets
from rest_framework_simplejwt.authentication import JWTAuthentication

from borrowings.models import Borrowing
from borrowings.serializers import BorrowingCreateSerializer, BorrowingReadSerializer


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
