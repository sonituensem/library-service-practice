"""CRUD endpoints for the library's book inventory."""

from rest_framework import viewsets

from books.models import Book
from books.serializers import BookSerializer


class BookViewSet(viewsets.ModelViewSet):
    """List, create, retrieve, update, and delete books."""

    queryset = Book.objects.all()
    serializer_class = BookSerializer

# Create your views here.
