"""
URL patterns for the /api/attendance/ prefix.

All four endpoints are served from views defined in enrollment.views —
the models live in enrollment, so no separate app is needed.
"""

from django.urls import path

from .views import (
    ClassAttendanceView,
    MarkAttendanceView,
    StartAttendanceSessionView,
    StudentAttendanceView,
)

app_name = "attendance"

urlpatterns = [
    path("start-session/", StartAttendanceSessionView.as_view(), name="start-session"),
    path("mark/", MarkAttendanceView.as_view(), name="mark"),
    path("class/", ClassAttendanceView.as_view(), name="class"),
    path("student/", StudentAttendanceView.as_view(), name="student"),
]
