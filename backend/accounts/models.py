from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models

from core.models import School, SchoolScopedModel, TimestampedModel

User = get_user_model()


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


class UserProfile(TimestampedModel):
    """
    Links a Django User to exactly one School tenant.

    This is the authoritative source for request.user.school.
    Every user who accesses school data must have a profile; views
    use get_request_school() to enforce this.

    A superuser (is_staff=True) may operate without a profile — views
    fall back to payload-derived school in that case so admin tooling
    continues to work.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="user_profiles",
    )

    class Meta:
        db_table = "accounts_userprofile"
        indexes = [
            models.Index(fields=["school"], name="idx_userprofile_school"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} @ {self.school.name}"
