"""Routes for borrowing list and detail endpoints."""

from rest_framework.routers import DefaultRouter

from borrowings.views import BorrowingViewSet

router = DefaultRouter()
router.register("borrowings", BorrowingViewSet, basename="borrowing")

urlpatterns = router.urls
