import uuid

from django.core.exceptions import ValidationError
from django.db import models

from core.models import SchoolClass, SchoolScopedModel, Session, Term


class Student(SchoolScopedModel):
    """
    A student enrolled at a school.

    Inherits from SchoolScopedModel:
    - id          → UUIDField primary key
    - school      → ForeignKey(School, on_delete=PROTECT)
    - created_at  → DateTimeField
    - updated_at  → DateTimeField
    """

    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        GRADUATED = "graduated", "Graduated"
        WITHDRAWN = "withdrawn", "Withdrawn"
        SUSPENDED = "suspended", "Suspended"

    student_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )
    registration_number = models.CharField(max_length=50)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        db_table = "enrollment_student"
        ordering = ["last_name", "first_name"]
        constraints = [
            # Registration number must be unique within a school.
            models.UniqueConstraint(
                fields=["school", "registration_number"],
                name="uniq_student_reg_number_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "status"], name="idx_student_school_status"),
            models.Index(
                fields=["school", "last_name", "first_name"],
                name="idx_student_school_name",
            ),
            models.Index(
                fields=["school", "registration_number"],
                name="idx_student_school_reg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.registration_number})"

    def clean(self) -> None:
        if self.student_class_id and self.school_id:
            try:
                if self.student_class.school_id != self.school_id:
                    raise ValidationError(
                        {"student_class": "The assigned class does not belong to this school."}
                    )
            except SchoolClass.DoesNotExist:
                pass

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
