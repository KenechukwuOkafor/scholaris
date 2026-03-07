from django.conf import settings
from django.db import models

from core.models import SchoolScopedModel


class AuditLog(SchoolScopedModel):
    """
    Immutable record of a significant action performed in the system.

    One row is written per auditable event (result publish, payment, class
    promotion, broadsheet submission, etc.).  Rows are never updated or
    deleted — this table is append-only by convention.

    Fields inherited from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField  (auto-set on insert)
    - updated_at → DateTimeField  (auto-set on insert and update)

    actor is nullable to support system-initiated events (Celery tasks,
    management commands) that have no interactive user.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="The user who triggered the action. Null for system actions.",
    )
    action = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Dot-namespaced action identifier, e.g. "result.publish".',
    )
    target_model = models.CharField(
        max_length=100,
        db_index=True,
        help_text="The Django model class name that was acted upon.",
    )
    target_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Primary key of the affected model instance.",
    )
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Arbitrary contextual data about the action.",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Exact UTC time the action was recorded.",
    )

    class Meta:
        db_table = "audit_auditlog"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(
                fields=["school", "action"],
                name="idx_audit_school_action",
            ),
            models.Index(
                fields=["school", "actor"],
                name="idx_audit_school_actor",
            ),
            models.Index(
                fields=["school", "target_model", "target_id"],
                name="idx_audit_school_target",
            ),
        ]

    def __str__(self) -> str:
        actor = self.actor or "system"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {actor} — {self.action} on {self.target_model}({self.target_id})"
