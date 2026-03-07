"""
NotificationService — create and manage in-app notifications.
"""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError

from enrollment.models import Parent
from notifications.models import Notification


def create_notification(
    school,
    title: str,
    message: str,
    type: str = Notification.Type.SYSTEM,
    recipient_user=None,
    recipient_parent: Parent | None = None,
) -> Notification:
    """
    Create and persist a Notification scoped to *school*.

    Exactly one of recipient_user or recipient_parent must be provided.

    Args:
        school:           School instance the notification belongs to.
        title:            Short heading (max 255 chars).
        message:          Full notification body.
        type:             One of Notification.Type choices (default: system).
        recipient_user:   A User instance — staff, teacher, or admin.
        recipient_parent: A Parent instance.

    Returns:
        The saved Notification.

    Raises:
        rest_framework.exceptions.ValidationError — if neither recipient
        is supplied.
    """
    if recipient_user is None and recipient_parent is None:
        raise ValidationError(
            "A notification must have at least one recipient "
            "(recipient_user or recipient_parent)."
        )

    return Notification.objects.create(
        school=school,
        recipient_user=recipient_user,
        recipient_parent=recipient_parent,
        title=title,
        message=message,
        type=type,
    )


def mark_notification_read(notification: Notification) -> Notification:
    """
    Mark *notification* as read.

    Uses update_fields for a targeted single-column write.  Idempotent —
    no DB write is issued when the notification is already read.

    Args:
        notification: the Notification to mark read.

    Returns:
        The updated Notification instance (is_read=True).
    """
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
    return notification


def get_user_notifications(user, *, unread_only: bool = False) -> QuerySet:
    """
    Return Notification rows addressed to *user*, scoped to their school.

    Uses the school FK stored on the notification (set at creation time by
    create_notification) — no extra profile lookup needed.

    Args:
        user:        The User whose notifications are fetched.
        unread_only: When True, only unread notifications are returned.

    Returns:
        A lazy QuerySet ordered newest-first; caller may slice or paginate.
    """
    qs = Notification.objects.filter(recipient_user=user)
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs.select_related("school")


def get_parent_notifications(parent: Parent, *, unread_only: bool = False) -> QuerySet:
    """
    Return Notification rows addressed to *parent*, tenant-safe via for_school().

    Args:
        parent:      The Parent whose notifications are fetched.
        unread_only: When True, only unread notifications are returned.

    Returns:
        A lazy QuerySet ordered newest-first.
    """
    qs = Notification.objects.for_school(parent.school).filter(
        recipient_parent=parent
    )
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs
