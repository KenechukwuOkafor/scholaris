from django.urls import path

from .views import (
    MarkNotificationReadView,
    NotificationListView,
    UnreadNotificationListView,
)

app_name = "notifications"

urlpatterns = [
    path(
        "",
        NotificationListView.as_view(),
        name="notification-list",
    ),
    path(
        "unread/",
        UnreadNotificationListView.as_view(),
        name="notification-unread",
    ),
    path(
        "mark-read/",
        MarkNotificationReadView.as_view(),
        name="notification-mark-read",
    ),
]
