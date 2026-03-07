from django.urls import path

from .views import (
    CreateParentView,
    LinkParentView,
    MarkAttendanceView,
    StartAttendanceSessionView,
)

app_name = "enrollment"

urlpatterns = [
    path(
        "attendance/start/",
        StartAttendanceSessionView.as_view(),
        name="attendance-start",
    ),
    path(
        "attendance/mark/",
        MarkAttendanceView.as_view(),
        name="attendance-mark",
    ),
    path(
        "parents/create/",
        CreateParentView.as_view(),
        name="parent-create",
    ),
    path(
        "parents/link/",
        LinkParentView.as_view(),
        name="parent-link",
    ),
]
