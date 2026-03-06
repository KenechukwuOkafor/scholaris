from django.urls import path

from .views import BroadsheetSubmitView

app_name = "academics"

urlpatterns = [
    path(
        "broadsheet/submit/",
        BroadsheetSubmitView.as_view(),
        name="broadsheet-submit",
    ),
]
