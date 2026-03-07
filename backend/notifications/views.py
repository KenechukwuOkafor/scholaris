from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenant import get_request_school

from .models import Notification
from .serializers import MarkReadSerializer, NotificationSerializer
from .services.notification_service import (
    get_user_notifications,
    mark_notification_read,
)


class NotificationListView(APIView):
    """
    GET /api/notifications/

    Return all notifications for the authenticated user, scoped to their
    school, ordered newest first.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        school = get_request_school(request)
        qs = get_user_notifications(request.user)
        if school is not None:
            qs = qs.filter(school=school)
        return Response(NotificationSerializer(qs, many=True).data)


class UnreadNotificationListView(APIView):
    """
    GET /api/notifications/unread/

    Return only unread notifications for the authenticated user, with a count.
    Scoped to the user's school.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        school = get_request_school(request)
        qs = get_user_notifications(request.user, unread_only=True)
        if school is not None:
            qs = qs.filter(school=school)
        return Response(
            {
                "count": qs.count(),
                "notifications": NotificationSerializer(qs, many=True).data,
            }
        )


class MarkNotificationReadView(APIView):
    """
    POST /api/notifications/mark-read/

    Mark a single notification as read.

    Request body:
        { "notification_id": "<uuid>" }

    Tenant safety: the notification must belong to the authenticated user's
    school and must be addressed to them.  Returns 403 on ownership mismatch.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notification_id = serializer.validated_data["notification_id"]

        school = get_request_school(request)

        # Fetch within school scope when school is known.
        qs = (
            Notification.objects.for_school(school)
            if school is not None
            else Notification.objects
        )

        try:
            notification = qs.get(id=notification_id)
        except Notification.DoesNotExist:
            raise NotFound(f"Notification {notification_id} not found.")

        if notification.recipient_user_id != request.user.pk:
            raise PermissionDenied("You do not own this notification.")

        notification = mark_notification_read(notification)
        return Response(NotificationSerializer(notification).data)
