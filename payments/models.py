"""Payment records associated with library borrowings."""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from borrowings.models import Borrowing


class Payment(models.Model):
    """A pending or completed charge for a borrowing or an overdue fine."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"

    class Type(models.TextChoices):
        PAYMENT = "PAYMENT", "Payment"
        FINE = "FINE", "Fine"

    status = models.CharField(
        max_length=7,
        choices=Status.choices,
        default=Status.PENDING,
    )
    type = models.CharField(max_length=7, choices=Type.choices)
    borrowing = models.ForeignKey(
        Borrowing,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    session_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
    )
    session_id = models.CharField(max_length=255, blank=True, default="")
    money_to_pay = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.get_type_display()} for borrowing {self.borrowing_id}"
