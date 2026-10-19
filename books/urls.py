"""Routes for the Books Service."""

from rest_framework.routers import DefaultRouter

from books.views import BookViewSet

router = DefaultRouter()
router.register("books", BookViewSet, basename="book")

urlpatterns = router.urls
