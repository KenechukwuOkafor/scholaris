"""
URL routes for the Parent Portal.

All paths are prefixed with /api/parent/ in the root URLconf.
"""

from django.urls import path

from .views_parent_portal import (
    ParentAttendanceView,
    ParentFeesView,
    ParentLoginView,
    ParentNotificationsView,
    ParentProfileView,
    ParentReportCardsView,
    ParentStudentsView,
)

app_name = "parent_portal"

urlpatterns = [
    # Authentication
    path("login/",         ParentLoginView.as_view(),         name="login"),

    # Portal
    path("profile/",       ParentProfileView.as_view(),       name="profile"),
    path("students/",      ParentStudentsView.as_view(),       name="students"),
    path("reportcards/",   ParentReportCardsView.as_view(),   name="reportcards"),
    path("attendance/",    ParentAttendanceView.as_view(),     name="attendance"),
    path("fees/",          ParentFeesView.as_view(),           name="fees"),
    path("notifications/", ParentNotificationsView.as_view(), name="notifications"),
]
