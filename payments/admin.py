"""Admin configuration for payment records."""

from django.contrib import admin

from payments.models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Show payment state, amount, and associated borrowing in admin."""

    list_display = ("id", "status", "type", "borrowing", "money_to_pay")
    list_filter = ("status", "type")
    search_fields = (
        "session_id",
        "borrowing__user__email",
        "borrowing__book__title",
    )
