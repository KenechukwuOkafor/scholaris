from django.conf import settings
from django.db import models

from core.models import SchoolScopedModel, Term
from enrollment.models import Parent, Student


class Notification(SchoolScopedModel):
    """
    An in-app notification delivered to either a platform user (staff /
    teacher) or a parent/guardian.

    Exactly one of recipient_user / recipient_parent must be set — the model
    does not enforce this at the DB level, but create_notification() does.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class Type(models.TextChoices):
        RESULT_RELEASE   = "result_release",   "Result Release"
        ATTENDANCE_ALERT = "attendance_alert", "Attendance Alert"
        FEE_REMINDER     = "fee_reminder",     "Fee Reminder"
        SYSTEM           = "system",           "System"

    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    recipient_parent = models.ForeignKey(
        Parent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(
        max_length=50,
        choices=Type.choices,
        default=Type.SYSTEM,
        db_index=True,
    )
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["school", "recipient_user", "is_read"],
                name="idx_notif_user_read",
            ),
            models.Index(
                fields=["school", "recipient_parent", "is_read"],
                name="idx_notif_parent_read",
            ),
            models.Index(
                fields=["school", "type"],
                name="idx_notif_school_type",
            ),
        ]

    def __str__(self) -> str:
        recipient = self.recipient_user or self.recipient_parent or "—"
        status = "read" if self.is_read else "unread"
        return f"[{self.get_type_display()}] {self.title} → {recipient} ({status})"


class WhatsAppMessage(SchoolScopedModel):
    """
    Tracks a single WhatsApp broadcast message sent (or queued to be sent)
    to a parent about their child's results.

    One row is created per (parent, student, term) combination when
    queue_result_broadcast() is called.  The Celery task updates status
    to 'sent' or 'failed' after delivery is attempted.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT    = "sent",    "Sent"
        FAILED  = "failed",  "Failed"

    parent = models.ForeignKey(
        Parent,
        on_delete=models.CASCADE,
        related_name="whatsapp_messages",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="whatsapp_messages",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="whatsapp_messages",
    )
    phone = models.CharField(
        max_length=20,
        help_text="Recipient phone number in E.164 format, e.g. +2348012345678.",
    )
    message = models.TextField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_whatsappmessage"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["school", "status"],
                name="idx_wa_school_status",
            ),
            models.Index(
                fields=["school", "term", "status"],
                name="idx_wa_school_term_status",
            ),
            models.Index(
                fields=["school", "parent"],
                name="idx_wa_school_parent",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"WhatsApp [{self.get_status_display()}] "
            f"→ {self.phone} ({self.student} / {self.term})"
        )
