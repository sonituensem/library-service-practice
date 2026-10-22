from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Register the payments application with Django."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
