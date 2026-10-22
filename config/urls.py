"""URL configuration for the Library Service project."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/", include("books.urls")),
    path("api/", include("borrowings.urls")),
    path("api/", include("payments.urls")),
    path("api/users/", include("users.urls")),
]
