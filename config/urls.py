"""Root URL configuration.

`INSTALLED_APPS` says the app is part of the project; this file says where it answers.
Two different registrations, two different files.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("portfolio.urls")),
]
