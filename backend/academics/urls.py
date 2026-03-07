from django.urls import path

from .views import BroadsheetSubmitView, ClassReportCardPDFView

app_name = "academics"

urlpatterns = [
    path(
        "broadsheet/submit/",
        BroadsheetSubmitView.as_view(),
        name="broadsheet-submit",
    ),
    path(
        "report-card/class/<uuid:class_id>/<uuid:term_id>/",
        ClassReportCardPDFView.as_view(),
        name="class-report-card-pdf",
    ),
]
