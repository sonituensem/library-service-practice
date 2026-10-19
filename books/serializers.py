"""API representation and validation for library books."""

from rest_framework import serializers

from books.models import Book


class BookSerializer(serializers.ModelSerializer):
    """Expose the book inventory fields through the REST API."""

    class Meta:
        model = Book
        fields = ("id", "title", "author", "cover", "inventory", "daily_fee")
        read_only_fields = ("id",)
