"""Borrowing record administration."""

from django.contrib import admin

from borrowings.models import Borrowing


@admin.register(Borrowing)
class BorrowingAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "user",
        "borrow_date",
        "expected_return_date",
        "actual_return_date",
    )
    list_filter = ("borrow_date", "expected_return_date", "actual_return_date")
    search_fields = ("book__title", "user__email")

# Register your models here.
