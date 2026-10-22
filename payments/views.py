"""Read endpoints for customer and staff payment records."""

from django.db import transaction
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.views import APIView

from notifications.tasks import send_successful_payment_notification
from payments.models import Payment
from payments.serializers import PaymentSerializer
from payments.services import retrieve_checkout_session


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


class PaymentSuccessView(APIView):
    """Confirm a completed Stripe Checkout Session."""

    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="session_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
            )
        ],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                description="Stripe confirmed the payment."
            ),
            status.HTTP_202_ACCEPTED: OpenApiResponse(
                description="The Checkout Session is not paid yet."
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="The session_id query parameter is required."
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="No local payment matches this session."
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
                description="Stripe could not verify the session."
            ),
        },
    )
    def get(self, request):
        """Retrieve payment state from Stripe before changing local status."""
        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response(
                {"detail": "The session_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment = Payment.objects.filter(session_id=session_id).first()
        if payment is None:
            return Response(
                {"detail": "No payment matches this Checkout Session."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = retrieve_checkout_session(session_id)
        if getattr(session, "id", None) != session_id:
            return Response(
                {"detail": "Stripe returned a different Checkout Session."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        session_is_paid = (
            session.status == "complete"
            and session.payment_status in {"paid", "no_payment_required"}
        )
        if not session_is_paid:
            return Response(
                {
                    "message": "Stripe has not confirmed this payment yet.",
                    "status": payment.status,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        with transaction.atomic():
            updated = Payment.objects.filter(
                pk=payment.pk,
                status=Payment.Status.PENDING,
            ).update(status=Payment.Status.PAID)
            if updated:
                transaction.on_commit(
                    lambda: send_successful_payment_notification.delay(
                        payment.pk
                    ),
                    robust=True,
                )

        return Response(
            {"message": "Payment confirmed by Stripe.", "status": "PAID"},
            status=status.HTTP_200_OK,
        )


class PaymentCancelView(APIView):
    """Tell a customer that a canceled Checkout Session can be resumed."""

    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    @extend_schema(
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                description=(
                    "Payment remains pending and its Checkout Session is "
                    "available for 24 hours."
                )
            )
        }
    )
    def get(self, request):
        """Return a friendly message without changing payment status."""
        return Response(
            {
                "message": (
                    "Payment was not completed. You can pay later using the "
                    "same Checkout link; the session is available "
                    "for 24 hours."
                )
            },
            status=status.HTTP_200_OK,
        )
