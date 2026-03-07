"""
Analytics models for Scholaris.

All models inherit SchoolScopedModel (UUID PK + school FK + timestamps).
All querysets must use SchoolManager.for_school() to prevent cross-tenant leakage.
"""

from django.db import models

from core.models import SchoolClass, SchoolScopedModel, Session, Subject, Term


class SchoolDailyMetrics(SchoolScopedModel):
    """
    School-wide snapshot for a single calendar day.
    One row per (school, date).
    Computed by: update_school_daily_metrics Celery task.
    """

    date = models.DateField(db_index=True)
    total_students = models.PositiveIntegerField(default=0)
    active_students = models.PositiveIntegerField(default=0)
    total_teachers = models.PositiveIntegerField(default=0)
    active_teachers = models.PositiveIntegerField(default=0)
    # Percentage of attendance records that are present/late today (0–100).
    attendance_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Attendance rate for the day as a percentage (0–100).",
    )
    total_attendance_records = models.PositiveIntegerField(default=0)
    present_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "analytics_schooldailymetrics"
        verbose_name = "School Daily Metrics"
        verbose_name_plural = "School Daily Metrics"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "date"],
                name="uniq_schooldailymetrics_school_date",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "date"], name="idx_sdm_school_date"),
        ]

    def __str__(self) -> str:
        return f"{self.school} — {self.date} (attendance: {self.attendance_rate}%)"


class ClassAnalytics(SchoolScopedModel):
    """
    Aggregated academic performance metrics for a class in a term.
    One row per (school, school_class, term).
    Computed by: update_class_analytics Celery task.
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="analytics",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="class_analytics",
    )
    total_students = models.PositiveIntegerField(default=0)
    average_score = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Mean of all student average scores in this class+term.",
    )
    highest_average = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Best individual average score in the class.",
    )
    lowest_average = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Worst individual average score in the class.",
    )
    pass_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percentage of students with average score >= 50.",
    )
    subjects_offered = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of distinct subjects scored in this class+term.",
    )

    class Meta:
        db_table = "analytics_classanalytics"
        verbose_name = "Class Analytics"
        verbose_name_plural = "Class Analytics"
        ordering = ["school_class__name", "-term__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_class", "term"],
                name="uniq_classanalytics_cls_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_classanalytics_school_term",
            ),
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_classanalytics_cls_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} — {self.term} (avg: {self.average_score})"


class SubjectAnalytics(SchoolScopedModel):
    """
    Aggregated performance for a subject in a class during a term.
    One row per (school, subject, school_class, term).
    Computed by: update_subject_analytics Celery task.
    """

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="analytics",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="subject_analytics",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="subject_analytics",
    )
    total_students = models.PositiveIntegerField(default=0)
    average_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    highest_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    lowest_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    pass_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percentage of students with total_score >= 50 in this subject.",
    )

    class Meta:
        db_table = "analytics_subjectanalytics"
        verbose_name = "Subject Analytics"
        verbose_name_plural = "Subject Analytics"
        ordering = ["subject__name", "-term__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject", "school_class", "term"],
                name="uniq_subjectanalytics_subj_cls_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_subjanal_school_term",
            ),
            models.Index(
                fields=["school", "subject", "term"],
                name="idx_subjectanalytics_subj_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subject} in {self.school_class} — {self.term}"


class FinancialAnalytics(SchoolScopedModel):
    """
    Fee collection summary for a school in a term.
    One row per (school, term).
    Computed by: update_financial_metrics Celery task.
    """

    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="financial_analytics",
    )
    total_invoiced = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Sum of all amount_due across invoices for this term.",
    )
    total_collected = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Sum of all amount_paid across invoices for this term.",
    )
    total_outstanding = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Sum of balance for unpaid/partially-paid invoices in this term.",
    )
    collection_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="total_collected / total_invoiced * 100 (percentage).",
    )
    fully_paid_count = models.PositiveIntegerField(
        default=0, help_text="Number of invoices with status=PAID.",
    )
    partially_paid_count = models.PositiveIntegerField(default=0)
    unpaid_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "analytics_financialanalytics"
        verbose_name = "Financial Analytics"
        verbose_name_plural = "Financial Analytics"
        ordering = ["-term__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "term"],
                name="uniq_financialanalytics_school_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_finanalytics_school_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school} — {self.term} (collected: {self.total_collected})"


class EnrollmentAnalytics(SchoolScopedModel):
    """
    Enrollment statistics for a school in an academic session.
    One row per (school, session).
    Computed by: update_school_daily_metrics Celery task (enrollment portion).
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="enrollment_analytics",
    )
    total_enrolled = models.PositiveIntegerField(default=0)
    male_count = models.PositiveIntegerField(default=0)
    female_count = models.PositiveIntegerField(default=0)
    class_count = models.PositiveSmallIntegerField(
        default=0, help_text="Number of distinct classes with enrolled students.",
    )

    class Meta:
        db_table = "analytics_enrollmentanalytics"
        verbose_name = "Enrollment Analytics"
        verbose_name_plural = "Enrollment Analytics"
        ordering = ["-session__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "session"],
                name="uniq_enrollmentanalytics_school_session",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "session"],
                name="idx_enrollanal_school_session",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school} — {self.session} (enrolled: {self.total_enrolled})"


class AttendanceAnalytics(SchoolScopedModel):
    """
    Attendance summary for a class in a term.
    One row per (school, school_class, term).
    Computed by: update_attendance_analytics Celery task.
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="attendance_analytics",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="attendance_analytics",
    )
    total_sessions = models.PositiveIntegerField(
        default=0, help_text="Number of attendance sessions taken this term.",
    )
    total_records = models.PositiveIntegerField(
        default=0, help_text="Total attendance records (sessions × students).",
    )
    present_count = models.PositiveIntegerField(default=0)
    absent_count = models.PositiveIntegerField(default=0)
    late_count = models.PositiveIntegerField(default=0)
    average_attendance_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="(present + late) / total_records * 100.",
    )

    class Meta:
        db_table = "analytics_attendanceanalytics"
        verbose_name = "Attendance Analytics"
        verbose_name_plural = "Attendance Analytics"
        ordering = ["school_class__name", "-term__start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_class", "term"],
                name="uniq_attendanceanalytics_cls_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_attanalytics_school_term",
            ),
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_attanalytics_cls_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} — {self.term} (rate: {self.average_attendance_rate}%)"
