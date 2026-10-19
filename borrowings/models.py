"""Borrowing records and their date invariants."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from books.models import Book


class Borrowing(models.Model):
    """A book loan and its planned and actual return dates."""

    borrow_date = models.DateField()
    expected_return_date = models.DateField()
    actual_return_date = models.DateField(blank=True, null=True)
    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="borrowings",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="borrowings",
    )

    class Meta:
        ordering = ("-borrow_date", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(expected_return_date__gte=F("borrow_date")),
                name="borrowing_expected_date_after_borrow",
            ),
            models.CheckConstraint(
                condition=Q(actual_return_date__isnull=True)
                | Q(actual_return_date__gte=F("borrow_date")),
                name="borrowing_actual_date_after_borrow",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-borrow_date"),
                name="borrow_user_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.book} borrowed by {self.user} on {self.borrow_date}"
