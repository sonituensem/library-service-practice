"""Serializers for creating and reading borrowing records."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from books.models import Book
from books.serializers import BookSerializer
from borrowings.models import Borrowing
from notifications.tasks import send_new_borrowing_notification


class BorrowingReadSerializer(serializers.ModelSerializer):
    """Return a borrowing with detailed book information."""

    book = BookSerializer(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Borrowing
        fields = (
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book",
            "user",
        )
        read_only_fields = fields


class BorrowingCreateSerializer(serializers.ModelSerializer):
    """Create a borrowing for the authenticated user and reserve a copy."""

    book_id = serializers.PrimaryKeyRelatedField(
        source="book",
        queryset=Book.objects.all(),
        write_only=True,
    )
    book = BookSerializer(read_only=True)
    borrow_date = serializers.DateField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Borrowing
        fields = (
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book",
            "book_id",
            "user",
        )
        read_only_fields = ("id", "actual_return_date", "book", "user")

    def validate(self, attrs):
        borrow_date = timezone.localdate()
        expected_return_date = attrs.get("expected_return_date")
        if expected_return_date and expected_return_date < borrow_date:
            raise serializers.ValidationError(
                {
                    "expected_return_date": (
                        "The expected return date cannot precede "
                        "the borrow date."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        book = validated_data.pop("book")

        with transaction.atomic():
            updated = Book.objects.filter(
                pk=book.pk,
                inventory__gt=0,
            ).update(inventory=F("inventory") - 1)
            if not updated:
                raise serializers.ValidationError(
                    {"book_id": "This book is not currently available."}
                )

            book.refresh_from_db(fields=("inventory",))
            borrowing = Borrowing.objects.create(
                book=book,
                user=self.context["request"].user,
                borrow_date=timezone.localdate(),
                **validated_data,
            )
            transaction.on_commit(
                lambda: send_new_borrowing_notification.delay(borrowing.pk),
                robust=True,
            )
            return borrowing
