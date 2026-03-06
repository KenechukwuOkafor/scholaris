from django.core.exceptions import ValidationError
from django.db import models

from core.models import SchoolScopedModel


class Teacher(SchoolScopedModel):
    """
    A teacher employed at a school.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        db_table = "accounts_teacher"
        ordering = ["last_name", "first_name"]
        constraints = [
            # Email must be unique within a school; two different schools
            # may legitimately share the same email address in multi-tenant SaaS.
            models.UniqueConstraint(
                fields=["school", "email"],
                name="uniq_teacher_email_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "last_name", "first_name"],
                name="idx_teacher_school_name",
            ),
            models.Index(fields=["school", "status"], name="idx_teacher_school_status"),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def clean(self) -> None:
        if self.email:
            self.email = self.email.lower()

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
