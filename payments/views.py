"""Read endpoints for customer and staff payment records."""

from rest_framework import mixins, permissions, viewsets
from rest_framework_simplejwt.authentication import JWTAuthentication

from payments.models import Payment
from payments.serializers import PaymentSerializer


class PaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """List and retrieve payments visible to the authenticated user."""

    queryset = Payment.objects.select_related(
        "borrowing__user",
        "borrowing__book",
    )
    serializer_class = PaymentSerializer
    authentication_classes = (JWTAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if getattr(user, "is_staff", False):
            return queryset
        if not getattr(user, "is_authenticated", False):
            return queryset.none()
        return queryset.filter(borrowing__user=user)
