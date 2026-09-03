from django.urls import path

from . import views

app_name = "portfolio"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("retro/", views.retro_list, name="retro_list"),
    path("retro/<str:week>/", views.retro_detail, name="retro_detail"),
    path("projects/", views.projects, name="projects"),
]
