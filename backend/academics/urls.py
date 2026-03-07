from django.urls import path

from .views import (
    BroadsheetSubmitView,
    ClassReportCardPDFView,
    PublishResultsView,
    ReportCardDownloadView,
    UnpublishResultsView,
)

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
    path(
        "results/publish/",
        PublishResultsView.as_view(),
        name="results-publish",
    ),
    path(
        "results/unpublish/",
        UnpublishResultsView.as_view(),
        name="results-unpublish",
    ),
    path(
        "reportcard/download/",
        ReportCardDownloadView.as_view(),
        name="reportcard-download",
    ),
]
