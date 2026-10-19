"""Book inventory for the library service."""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Book(models.Model):
    """A book title and the number of copies currently available."""

    class Cover(models.TextChoices):
        HARD = "HARD", "Hard"
        SOFT = "SOFT", "Soft"

    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    cover = models.CharField(max_length=4, choices=Cover.choices)
    inventory = models.PositiveIntegerField()
    daily_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return f"{self.title} by {self.author}"

# Create your models here.
