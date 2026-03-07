from django.urls import path

from .views import SchoolDashboardView

app_name = "analytics"

urlpatterns = [
    path("dashboard/", SchoolDashboardView.as_view(), name="dashboard"),
]
