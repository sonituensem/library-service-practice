"""CRUD endpoints for the library's book inventory."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework_simplejwt.authentication import JWTAuthentication

from books.models import Book
from books.permissions import IsAdminOrReadOnly
from books.serializers import BookSerializer


@extend_schema_view(
    list=extend_schema(auth=[]),
    retrieve=extend_schema(auth=[]),
)
class BookViewSet(viewsets.ModelViewSet):
    """List, create, retrieve, update, and delete books."""

    queryset = Book.objects.all()
    serializer_class = BookSerializer
    authentication_classes = (JWTAuthentication,)
    permission_classes = (IsAdminOrReadOnly,)
