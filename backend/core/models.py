import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """
    Abstract base that stamps every row with created_at and updated_at.
    All Scholaris models inherit from SchoolScopedModel (which extends this),
    or from this directly when school-scoping is not applicable (e.g. School itself).
    """

    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class School(TimestampedModel):
    """
    The top-level tenant entity. Every piece of data in the system belongs
    to exactly one School.  No cross-school data access is permitted.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"

    class SchoolType(models.TextChoices):
        PRIMARY = "primary", "Primary"
        SECONDARY = "secondary", "Secondary"
        COMBINED = "combined", "Combined"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    school_type = models.CharField(max_length=20, choices=SchoolType.choices)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to="schools/logos/", null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    # ISO 4217 currency code – defaults to NGN for the target market.
    currency = models.CharField(max_length=3, default="NGN")
    enable_class_ranking = models.BooleanField(
        default=True,
        help_text="When enabled, students are ranked by average score on their result sheets.",
    )

    class Meta:
        db_table = "core_school"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"], name="idx_school_slug"),
            models.Index(fields=["status"], name="idx_school_status"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.slug:
            self.slug = self.slug.lower()


class SchoolScopedModel(TimestampedModel):
    """
    Abstract base model for every model that belongs to a tenant (School).

    All concrete subclasses automatically carry:
    - A UUID primary key
    - A non-nullable FK to School
    - created_at / updated_at timestamps (via TimestampedModel)

    Subclasses MUST NOT redefine `id` or `school` unless there is an explicit
    architectural reason to do so.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Academic Calendar
# ---------------------------------------------------------------------------


class Session(SchoolScopedModel):
    """
    An academic year / session for a school, e.g. "2024/2025".

    Invariants enforced at the model level:
    - Only one session per school may be active at a time.
    - start_date must be before end_date.
    - Dates must not overlap with an existing session for the same school.
    """

    name = models.CharField(max_length=100, help_text='e.g. "2024/2025"')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "core_session"
        ordering = ["-start_date"]
        constraints = [
            # Only one active session per school at the DB level.
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(is_active=True),
                name="uniq_active_session_per_school",
            ),
            # Session name must be unique within a school.
            models.UniqueConstraint(
                fields=["school", "name"],
                name="uniq_session_name_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "is_active"], name="idx_session_school_active"),
            models.Index(fields=["school", "start_date"], name="idx_session_school_start"),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} — {self.name}"

    def clean(self) -> None:
        self._validate_dates()
        self._validate_no_overlap()

    def _validate_dates(self) -> None:
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError(
                {"end_date": "Session end date must be after its start date."}
            )

    def _validate_no_overlap(self) -> None:
        if not (self.start_date and self.end_date and self.school_id):
            return

        qs = Session.objects.filter(
            school_id=self.school_id,
            start_date__lt=self.end_date,
            end_date__gt=self.start_date,
        ).exclude(pk=self.pk)

        if qs.exists():
            raise ValidationError(
                "This session's dates overlap with an existing session for this school."
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class Term(SchoolScopedModel):
    """
    A term (or semester) within an academic Session.

    Invariants enforced at the model level:
    - Only one term per session may be active at a time.
    - Term dates must fall within the parent session's date range.
    - start_date must be before end_date.
    - Term dates must not overlap with sibling terms in the same session.
    """

    class TermNumber(models.IntegerChoices):
        FIRST = 1, "First Term"
        SECOND = 2, "Second Term"
        THIRD = 3, "Third Term"

    session = models.ForeignKey(
        Session,
        on_delete=models.PROTECT,
        related_name="terms",
    )
    term_number = models.IntegerField(choices=TermNumber.choices)
    name = models.CharField(
        max_length=100,
        blank=True,
        help_text='Auto-populated from term_number if left blank, e.g. "First Term".',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "core_term"
        ordering = ["session__start_date", "term_number"]
        constraints = [
            # Only one active term per session at the DB level.
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(is_active=True),
                name="uniq_active_term_per_session",
            ),
            # Each term number is unique within a session.
            models.UniqueConstraint(
                fields=["session", "term_number"],
                name="uniq_term_number_per_session",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "is_active"], name="idx_term_school_active"),
            models.Index(fields=["session", "is_active"], name="idx_term_session_active"),
            models.Index(fields=["session", "start_date"], name="idx_term_session_start"),
        ]

    def __str__(self) -> str:
        return f"{self.session.name} — {self.get_term_number_display()}"

    def clean(self) -> None:
        self._populate_name()
        self._validate_school_matches_session()
        self._validate_dates()
        self._validate_within_session()
        self._validate_no_overlap()

    def _validate_school_matches_session(self) -> None:
        """Confirm the school FK matches the session's school (set in save())."""
        if self.session_id and self.school_id:
            try:
                if self.school_id != self.session.school_id:
                    raise ValidationError(
                        {"school": "Term's school must match its session's school."}
                    )
            except Session.DoesNotExist:
                pass

    def _populate_name(self) -> None:
        if not self.name and self.term_number:
            self.name = self.get_term_number_display()

    def _validate_dates(self) -> None:
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError(
                {"end_date": "Term end date must be after its start date."}
            )

    def _validate_within_session(self) -> None:
        if not (self.start_date and self.end_date and self.session_id):
            return
        try:
            session = self.session
        except Session.DoesNotExist:
            return

        errors: dict[str, str] = {}
        if self.start_date < session.start_date:
            errors["start_date"] = (
                f"Term start date ({self.start_date}) cannot be before "
                f"session start date ({session.start_date})."
            )
        if self.end_date > session.end_date:
            errors["end_date"] = (
                f"Term end date ({self.end_date}) cannot be after "
                f"session end date ({session.end_date})."
            )
        if errors:
            raise ValidationError(errors)

    def _validate_no_overlap(self) -> None:
        if not (self.start_date and self.end_date and self.session_id):
            return

        qs = Term.objects.filter(
            session_id=self.session_id,
            start_date__lt=self.end_date,
            end_date__gt=self.start_date,
        ).exclude(pk=self.pk)

        if qs.exists():
            raise ValidationError(
                "This term's dates overlap with an existing term in the same session."
            )

    def save(self, *args, **kwargs) -> None:
        # Sync school from session before full_clean() so clean_fields()
        # never sees a null school when a valid session is provided.
        if self.session_id and not self.school_id:
            try:
                self.school_id = self.session.school_id
            except Session.DoesNotExist:
                pass
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# School Structure
# ---------------------------------------------------------------------------


class SchoolClass(SchoolScopedModel):
    """
    A class/grade level within a school, e.g. "JSS 1", "Primary 3".
    Class names are unique per school.
    """

    name = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display order — lower numbers appear first.",
    )

    class Meta:
        db_table = "core_schoolclass"
        ordering = ["school", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="uniq_schoolclass_name_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "order"], name="idx_schoolclass_school_order"),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} — {self.name}"


class Subject(SchoolScopedModel):
    """
    A subject taught at a school, e.g. "Mathematics", "English Language".
    Subject names are unique per school.
    """

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20,
        blank=True,
        help_text="Short subject code, e.g. MTH, ENG. Optional but unique per school when set.",
    )

    class Meta:
        db_table = "core_subject"
        ordering = ["school", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="uniq_subject_name_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "code"],
                condition=models.Q(code__gt=""),
                name="uniq_subject_code_per_school",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "name"], name="idx_subject_school_name"),
        ]

    def __str__(self) -> str:
        return f"{self.school.name} — {self.name}"
