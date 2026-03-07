import uuid

from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Teacher
from core.managers import SchoolManager
from core.models import School, SchoolClass, SchoolScopedModel, Subject, Term, TimestampedModel
from enrollment.models import Student


class AssessmentType(TimestampedModel):
    """
    A grading component for a specific school and term, e.g. CA1, Test, Exam.

    Each AssessmentType carries a weight (percentage contribution out of 100).
    The sum of all weights for a school+term combination must equal exactly 100.

    Examples:
      CA1 = 10, CA2 = 10, Exam = 80  → total 100 ✓
      Test = 20, Assignment = 20, Exam = 60  → total 100 ✓

    max_score mirrors weight because in this grading system the maximum
    marks a student can earn in a component equals that component's
    percentage contribution.  Score.clean() relies on max_score, so both
    fields are kept in sync inside clean().
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="assessment_types",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="assessment_types",
    )
    name = models.CharField(max_length=100)
    weight = models.PositiveSmallIntegerField(
        help_text="Percentage contribution to the total score (all weights in a term must sum to 100).",
    )
    max_score = models.PositiveSmallIntegerField(
        help_text="Maximum marks a student can score. Kept in sync with weight.",
        editable=False,
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display order — lower numbers appear first.",
    )

    objects = SchoolManager()

    class Meta:
        db_table = "academics_assessmenttype"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "term", "name"],
                name="uniq_assessmenttype_name_per_school_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_assessmenttype_school_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.weight}%)"

    def clean(self) -> None:
        self._validate_weight()
        self._validate_term_belongs_to_school()
        self._validate_total_weight()
        # Keep max_score in sync so Score.clean() continues to work correctly.
        self.max_score = self.weight

    def _validate_weight(self) -> None:
        if self.weight is not None and self.weight <= 0:
            raise ValidationError({"weight": "Weight must be a positive number."})
        if self.weight is not None and self.weight > 100:
            raise ValidationError({"weight": "A single assessment type cannot exceed 100%."})

    def _validate_term_belongs_to_school(self) -> None:
        if self.term_id and self.school_id:
            try:
                if self.term.school_id != self.school_id:
                    raise ValidationError(
                        {"term": "The selected term does not belong to this school."}
                    )
            except Term.DoesNotExist:
                pass

    def _validate_total_weight(self) -> None:
        if not (self.weight and self.school_id and self.term_id):
            return

        existing_total = (
            AssessmentType.objects.filter(
                school_id=self.school_id,
                term_id=self.term_id,
            )
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum("weight"))["total"]
            or 0
        )

        if existing_total + self.weight > 100:
            raise ValidationError(
                {
                    "weight": (
                        f"Total assessment weight for this term would be "
                        f"{existing_total + self.weight}%. "
                        f"The maximum allowed is 100%."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class TeachingAssignment(SchoolScopedModel):
    """
    Records which teacher teaches a subject in a specific class.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField

    Invariants enforced at the model level:
    - A teacher, class, and subject combination must be unique per school.
    - The teacher, class, and subject must all belong to the same school.
    """

    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        related_name="teaching_assignments",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="teaching_assignments",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="teaching_assignments",
    )

    class Meta:
        db_table = "academics_teachingassignment"
        ordering = ["school_class__name", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "teacher", "school_class", "subject"],
                name="uniq_teaching_assignment",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "teacher"],
                name="idx_assignment_school_teacher",
            ),
            models.Index(
                fields=["school", "school_class"],
                name="idx_assignment_school_class",
            ),
            models.Index(
                fields=["school", "subject"],
                name="idx_assignment_school_subject",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.teacher} teaches {self.subject} in {self.school_class}"

    def clean(self) -> None:
        self._validate_same_school()

    def _validate_same_school(self) -> None:
        errors: dict[str, str] = {}

        if self.teacher_id and self.school_id:
            try:
                if self.teacher.school_id != self.school_id:
                    errors["teacher"] = "Teacher does not belong to this school."
            except Teacher.DoesNotExist:
                pass

        if self.school_class_id and self.school_id:
            try:
                if self.school_class.school_id != self.school_id:
                    errors["school_class"] = "Class does not belong to this school."
            except SchoolClass.DoesNotExist:
                pass

        if self.subject_id and self.school_id:
            try:
                if self.subject.school_id != self.school_id:
                    errors["subject"] = "Subject does not belong to this school."
            except Subject.DoesNotExist:
                pass

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class Score(SchoolScopedModel):
    """
    Records the score a student receives for one assessment component
    in a subject during a specific term.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField

    Invariants enforced at the model level:
    - A student can have only one score per (subject, term, assessment_type).
    - Score must not exceed the assessment type's max_score.
    - Score must not be negative.
    - Student, subject, and term must all belong to the same school.
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="scores",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="scores",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="scores",
    )
    assessment_type = models.ForeignKey(
        AssessmentType,
        on_delete=models.PROTECT,
        related_name="scores",
    )
    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Must be between 0 and the assessment type's max_score.",
    )

    class Meta:
        db_table = "academics_score"
        ordering = ["student__last_name", "subject__name", "assessment_type__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student", "subject", "term", "assessment_type"],
                name="uniq_score_per_student_subject_term_assessment",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student", "term"],
                name="idx_score_school_student_term",
            ),
            models.Index(
                fields=["school", "subject", "term"],
                name="idx_score_school_subject_term",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.student} — {self.subject} — {self.assessment_type}: {self.score}"
        )

    def clean(self) -> None:
        self._validate_score_range()
        self._validate_same_school()

    def _validate_score_range(self) -> None:
        if self.score is None:
            return
        if self.score < 0:
            raise ValidationError({"score": "Score cannot be negative."})
        if self.assessment_type_id:
            try:
                if self.score > self.assessment_type.max_score:
                    raise ValidationError(
                        {
                            "score": (
                                f"Score {self.score} exceeds the maximum allowed "
                                f"({self.assessment_type.max_score}) for "
                                f"{self.assessment_type.name}."
                            )
                        }
                    )
            except AssessmentType.DoesNotExist:
                pass

    def _validate_same_school(self) -> None:
        errors: dict[str, str] = {}

        if self.student_id and self.school_id:
            try:
                if self.student.school_id != self.school_id:
                    errors["student"] = "Student does not belong to this school."
            except Student.DoesNotExist:
                pass

        if self.subject_id and self.school_id:
            try:
                if self.subject.school_id != self.school_id:
                    errors["subject"] = "Subject does not belong to this school."
            except Subject.DoesNotExist:
                pass

        if self.term_id and self.school_id:
            try:
                if self.term.school_id != self.school_id:
                    errors["term"] = "Term does not belong to this school."
            except Term.DoesNotExist:
                pass

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ResultStatistics(SchoolScopedModel):
    """
    Computed class-level statistics for a subject in a term.

    This model is a denormalised cache — values are derived from Score records
    and should be recomputed whenever scores for the (class, subject, term)
    combination change.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField

    Invariants enforced at the model level:
    - Only one statistics row per (school, school_class, subject, term).
    - highest_score >= class_average >= lowest_score.
    - All values must be >= 0.
    - school_class, subject, and term must all belong to the same school.
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="result_statistics",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="result_statistics",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="result_statistics",
    )
    highest_score = models.DecimalField(max_digits=6, decimal_places=2)
    lowest_score = models.DecimalField(max_digits=6, decimal_places=2)
    class_average = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        db_table = "academics_resultstatistics"
        verbose_name = "Result Statistics"
        verbose_name_plural = "Result Statistics"
        ordering = ["school_class__name", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_class", "subject", "term"],
                name="uniq_result_statistics_per_class_subject_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_resultstat_school_term",
            ),
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_resultstat_cls_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} — {self.subject} stats"

    def clean(self) -> None:
        self._validate_stat_values()
        self._validate_same_school()

    def _validate_stat_values(self) -> None:
        errors: dict[str, str] = {}

        for field in ("highest_score", "lowest_score", "class_average"):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = f"{field.replace('_', ' ').capitalize()} cannot be negative."

        if errors:
            raise ValidationError(errors)

        h, l, a = self.highest_score, self.lowest_score, self.class_average
        if None not in (h, l, a):
            if l > h:
                raise ValidationError(
                    {"lowest_score": "Lowest score cannot be greater than highest score."}
                )
            if not (l <= a <= h):
                raise ValidationError(
                    {"class_average": "Class average must be between lowest and highest score."}
                )

    def _validate_same_school(self) -> None:
        errors: dict[str, str] = {}

        if self.school_class_id and self.school_id:
            try:
                if self.school_class.school_id != self.school_id:
                    errors["school_class"] = "Class does not belong to this school."
            except SchoolClass.DoesNotExist:
                pass

        if self.subject_id and self.school_id:
            try:
                if self.subject.school_id != self.school_id:
                    errors["subject"] = "Subject does not belong to this school."
            except Subject.DoesNotExist:
                pass

        if self.term_id and self.school_id:
            try:
                if self.term.school_id != self.school_id:
                    errors["term"] = "Term does not belong to this school."
            except Term.DoesNotExist:
                pass

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ResultSummary(SchoolScopedModel):
    """
    Stores the computed end-of-term result for a single student in a class.

    One row per (school, student, term).  Values are computed by
    ResultProcessor and should be treated as a read cache — do not
    edit directly.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="result_summaries",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="result_summaries",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="result_summaries",
    )
    total_score = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Sum of all subject totals for this student in this term.",
    )
    average_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Mean subject score (total_score / number_of_subjects).",
    )
    position = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Class rank. NULL when school.enable_class_ranking is False.",
    )

    class Meta:
        db_table = "academics_resultsummary"
        verbose_name = "Result Summary"
        verbose_name_plural = "Result Summaries"
        ordering = ["term", "position", "student__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student", "term"],
                name="uniq_result_summary_student_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_resultsummary_class_term",
            ),
            models.Index(
                fields=["school", "term", "average_score"],
                name="idx_resultsummary_term_avg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.term} (avg: {self.average_score})"


class StudentSubjectResult(SchoolScopedModel):
    """
    Computed per-student per-subject result for a term.

    One row per (school, student, subject, term).  Values are written by
    ResultProcessor and must be treated as a read cache — do not edit directly.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="subject_results",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="subject_results",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="subject_results",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="subject_results",
    )
    total_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Sum of all assessment scores for this student in this subject.",
    )
    subject_position = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Rank within the class for this subject. NULL when ranking is disabled.",
    )

    class Meta:
        db_table = "academics_studentsubjectresult"
        verbose_name = "Student Subject Result"
        verbose_name_plural = "Student Subject Results"
        ordering = ["term", "subject__name", "subject_position"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student", "subject", "term"],
                name="uniq_student_subject_result",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_subjresult_cls_term",
            ),
            models.Index(
                fields=["school", "student", "term"],
                name="idx_subjresult_student_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.subject} (pos: {self.subject_position})"


# ---------------------------------------------------------------------------
# Report Card Template
# ---------------------------------------------------------------------------


class ReportCardTemplate(SchoolScopedModel):
    """
    A school-specific HTML template for report card PDF generation.

    Each school may define multiple named templates but only one may be
    active at a time (enforced by a partial unique constraint).  When an
    active template exists it is used by generate_report_card_pdf() instead
    of the default filesystem template.

    The html_template field is a full Django template string rendered with
    a single ``report`` context variable that matches the structure returned
    by generate_report_card().

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    name = models.CharField(
        max_length=150,
        help_text="Human-readable name for this template, e.g. 'Standard 2025'.",
    )
    html_template = models.TextField(
        help_text=(
            "Full HTML template string rendered with Django's template engine. "
            "Use {{ report }} and its nested keys as context variables."
        ),
    )
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Only one template per school may be active at a time.",
    )

    class Meta:
        db_table = "academics_reportcardtemplate"
        ordering = ["school", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="uniq_reportcardtemplate_name_per_school",
            ),
            # Guarantees at most one active template per school at the DB level.
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(is_active=True),
                name="uniq_active_reportcardtemplate_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="idx_rct_school_active",
            ),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.name} ({status})"

    def save(self, *args, **kwargs) -> None:
        if self.is_active:
            ReportCardTemplate.objects\
                .for_school(self.school)\
                .exclude(pk=self.pk)\
                .update(is_active=False)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Trait Rating System
# ---------------------------------------------------------------------------


class TraitCategory(SchoolScopedModel):
    """
    A grouping of related behavioural/psychomotor traits for a school.

    Examples: "Affective Traits", "Psychomotor Skills"
    """

    name = models.CharField(max_length=100)
    display_order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display order — lower numbers appear first.",
    )

    class Meta:
        db_table = "academics_traitcategory"
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"],
                name="uniq_traitcategory_name_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "display_order"],
                name="idx_traitcategory_school_order",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Trait(SchoolScopedModel):
    """
    A single measurable behaviour or skill within a TraitCategory.

    Examples: "Punctuality", "Mental Alertness", "Handwriting", "Reading"
    """

    category = models.ForeignKey(
        TraitCategory,
        on_delete=models.CASCADE,
        related_name="traits",
    )
    name = models.CharField(max_length=100)
    display_order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display order within its category — lower numbers appear first.",
    )

    class Meta:
        db_table = "academics_trait"
        ordering = ["category__display_order", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "category", "name"],
                name="uniq_trait_name_per_category",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "category"],
                name="idx_trait_school_category",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category.name} — {self.name}"


class TraitScale(SchoolScopedModel):
    """
    A rating level that a school defines for trait evaluations.

    Each school configures its own scale, e.g.:
      Excellent (5), Very Good (4), Good (3), Fair (2), Poor (1)
    """

    label = models.CharField(max_length=50)
    numeric_value = models.PositiveSmallIntegerField(
        help_text="Numeric representation of this rating level.",
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display order — lower numbers appear first.",
    )

    class Meta:
        db_table = "academics_traitscale"
        ordering = ["display_order", "-numeric_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "label"],
                name="uniq_traitscale_label_per_school",
            ),
            models.UniqueConstraint(
                fields=["school", "numeric_value"],
                name="uniq_traitscale_value_per_school",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "display_order"],
                name="idx_traitscale_school_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.numeric_value})"


class StudentTraitRating(SchoolScopedModel):
    """
    Records a teacher's rating for a student on a specific trait in a term.

    One row per (school, student, term, trait).
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="trait_ratings",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="trait_ratings",
    )
    trait = models.ForeignKey(
        Trait,
        on_delete=models.PROTECT,
        related_name="ratings",
    )
    scale = models.ForeignKey(
        TraitScale,
        on_delete=models.PROTECT,
        related_name="ratings",
    )

    class Meta:
        db_table = "academics_studenttraitrating"
        ordering = ["student__last_name", "term", "trait__display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student", "term", "trait"],
                name="uniq_student_trait_rating",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student", "term"],
                name="idx_traitrating_student_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} — {self.trait.name}: {self.scale.label}"
