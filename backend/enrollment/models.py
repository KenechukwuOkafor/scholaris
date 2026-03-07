import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import SchoolClass, SchoolScopedModel, Session, Term

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


class AttendanceSession(SchoolScopedModel):
    """
    Represents a single class attendance-taking event on a given date.

    One row per (school, school_class, date) — a class can only have one
    attendance session opened per day.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    date = models.DateField(db_index=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_sessions",
    )

    class Meta:
        db_table = "enrollment_attendancesession"
        ordering = ["-date", "school_class__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_class", "date"],
                name="uniq_attendance_session_per_class_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "date"],
                name="idx_attsession_school_date",
            ),
            models.Index(
                fields=["school", "school_class", "date"],
                name="idx_attsession_cls_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} — {self.date}"


class AttendanceRecord(SchoolScopedModel):
    """
    Records the attendance status of one student for an AttendanceSession.

    One row per (session, student) — a student can only have one record
    per attendance session.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT  = "absent",  "Absent"
        LATE    = "late",    "Late"

    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PRESENT,
        db_index=True,
    )

    class Meta:
        db_table = "enrollment_attendancerecord"
        ordering = ["session", "student__last_name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="uniq_attendance_record_per_session_student",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student"],
                name="idx_attrec_school_student",
            ),
            models.Index(
                fields=["session", "status"],
                name="idx_attrec_session_status",
            ),
            # Compound index for the parent portal attendance query:
            #   .filter(school=school, student=student, session__date__range=...)
            # "date" lives on AttendanceSession; indexing session here lets the
            # planner use a nested-loop join against AttendanceSession's date index
            # instead of a full scan after filtering by school+student.
            models.Index(
                fields=["school", "student", "session"],
                name="idx_attrec_student_session",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.session.date}: {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Parent / Guardian
# ---------------------------------------------------------------------------


class Parent(SchoolScopedModel):
    """
    A parent or guardian associated with a school.

    One Parent record can be linked to multiple students via StudentParent.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)

    class Meta:
        db_table = "enrollment_parent"
        ordering = ["school", "name"]
        indexes = [
            models.Index(fields=["school", "name"], name="idx_parent_school_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone})"


class StudentParent(SchoolScopedModel):
    """
    Links a Student to a Parent with a stated relationship.

    One row per (student, parent) — the same parent cannot be linked to
    the same student twice.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_parents",
    )
    parent = models.ForeignKey(
        Parent,
        on_delete=models.CASCADE,
        related_name="student_parents",
    )
    relationship = models.CharField(
        max_length=100,
        help_text='e.g. "Mother", "Father", "Guardian".',
    )

    class Meta:
        db_table = "enrollment_studentparent"
        ordering = ["student__last_name", "parent__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "parent"],
                name="uniq_student_parent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student"],
                name="idx_stpar_school_student",
            ),
            models.Index(
                fields=["school", "parent"],
                name="idx_stpar_school_parent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent.name} → {self.student} ({self.relationship})"


# ---------------------------------------------------------------------------
# Student Enrollment / Promotion
# ---------------------------------------------------------------------------


class StudentEnrollment(SchoolScopedModel):
    """
    Records a student's placement in a class for a given academic session.

    One row per (student, session) — a student can only be enrolled in
    one class per session.  The most recent enrollment has is_current=True;
    all older enrollments for the same student have is_current=False.

    Promotion (moving to a higher class for a new session) is handled by
    promotion_service.promote_student(), which creates the new row and
    atomically deactivates the previous one.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    session = models.ForeignKey(
        Session,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    is_current = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "enrollment_studentenrollment"
        ordering = ["-session__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "session"],
                name="uniq_enrollment_student_session",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "school_class", "session"],
                name="idx_enroll_cls_session",
            ),
            models.Index(
                fields=["school", "student"],
                name="idx_enroll_school_student",
            ),
            models.Index(
                fields=["school", "is_current"],
                name="idx_enroll_school_current",
            ),
        ]

    def __str__(self) -> str:
        status = "current" if self.is_current else "past"
        return (
            f"{self.student} → {self.school_class.name} "
            f"({self.session.name}) [{status}]"
        )
