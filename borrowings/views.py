"""Read-only endpoints for customer borrowing records."""

from rest_framework import permissions, viewsets
from rest_framework_simplejwt.authentication import JWTAuthentication

from borrowings.models import Borrowing
from borrowings.serializers import BorrowingReadSerializer


class BorrowingViewSet(viewsets.ReadOnlyModelViewSet):
    """List visible borrowings or retrieve one borrowing by id."""

    queryset = Borrowing.objects.select_related("book", "user")
    serializer_class = BorrowingReadSerializer
    authentication_classes = (JWTAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_staff", False):
            return queryset
        if not getattr(user, "is_authenticated", False):
            return queryset.none()
        return queryset.filter(user=user)
