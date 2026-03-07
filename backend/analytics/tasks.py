"""
Celery tasks for the analytics engine.

Each task:
- Accepts a school_id (UUID str) to scope its work to a single tenant.
- Runs inside an atomic transaction.
- Uses bulk queries only — no N+1 loops.
- Calls update_or_create so it is idempotent (safe to re-run).

Scheduling (example beat config, add to settings):
    CELERY_BEAT_SCHEDULE = {
        "daily-school-metrics": {
            "task": "analytics.tasks.update_school_daily_metrics",
            "schedule": crontab(hour=1, minute=0),  # 01:00 WAT
        },
        ...
    }
"""

from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.db.models import Avg, Case, Count, DecimalField, Max, Min, Q, Sum, When
from django.utils import timezone

from core.models import School, SchoolClass, Subject, Term

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_school(school_id: str) -> School:
    return School.objects.get(pk=school_id)


def _pct(numerator, denominator) -> Decimal:
    """Safe percentage: returns 0 when denominator is 0 or None."""
    try:
        n = Decimal(str(numerator or 0))
        d = Decimal(str(denominator or 0))
        return round(n / d * 100, 2) if d else Decimal("0.00")
    except Exception:
        return Decimal("0.00")


# ---------------------------------------------------------------------------
# Task 1 — SchoolDailyMetrics + EnrollmentAnalytics
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="analytics.tasks.update_school_daily_metrics")
def update_school_daily_metrics(self, school_id: str) -> dict:
    """
    Recompute SchoolDailyMetrics for today and EnrollmentAnalytics for
    the active session, scoped to the given school.

    Queries issued (all school-scoped):
      Q1 — Student aggregation (total / active / gender)
      Q2 — Teacher aggregation (total / active)
      Q3 — AttendanceRecord aggregation for today
      Q4 — StudentEnrollment aggregation for active session
      Q5 — update_or_create SchoolDailyMetrics
      Q6 — update_or_create EnrollmentAnalytics (if active session exists)
    """
    from accounts.models import Teacher
    from enrollment.models import AttendanceRecord, Student, StudentEnrollment
    from core.models import Session

    from .models import EnrollmentAnalytics, SchoolDailyMetrics

    school = _get_school(school_id)
    today = timezone.localdate()

    with transaction.atomic():
        # Q1 — student counts
        student_agg = (
            Student.objects.for_school(school)
            .aggregate(
                total=Count("id"),
                active=Count("id", filter=Q(status=Student.Status.ACTIVE)),
                male=Count("id", filter=Q(gender=Student.Gender.MALE)),
                female=Count("id", filter=Q(gender=Student.Gender.FEMALE)),
            )
        )

        # Q2 — teacher counts
        teacher_agg = (
            Teacher.objects.for_school(school)
            .aggregate(
                total=Count("id"),
                active=Count("id", filter=Q(status=Teacher.Status.ACTIVE)),
            )
        )

        # Q3 — today's attendance
        att_agg = (
            AttendanceRecord.objects
            .filter(school=school, session__date=today)
            .aggregate(
                total=Count("id"),
                attended=Count(
                    "id",
                    filter=Q(status__in=[
                        AttendanceRecord.Status.PRESENT,
                        AttendanceRecord.Status.LATE,
                    ]),
                ),
            )
        )
        total_att = att_agg["total"] or 0
        present = att_agg["attended"] or 0

        SchoolDailyMetrics.objects.update_or_create(
            school=school,
            date=today,
            defaults={
                "total_students":          student_agg["total"] or 0,
                "active_students":         student_agg["active"] or 0,
                "total_teachers":          teacher_agg["total"] or 0,
                "active_teachers":         teacher_agg["active"] or 0,
                "total_attendance_records": total_att,
                "present_count":           present,
                "attendance_rate":         _pct(present, total_att),
            },
        )

        # Q4 — enrollment per active session
        try:
            active_session = (
                Session.objects.for_school(school)
                .get(is_active=True)
            )
        except Session.DoesNotExist:
            active_session = None

        if active_session:
            enroll_agg = (
                StudentEnrollment.objects
                .filter(school=school, session=active_session)
                .aggregate(
                    total=Count("id"),
                    male=Count("id", filter=Q(student__gender=Student.Gender.MALE)),
                    female=Count("id", filter=Q(student__gender=Student.Gender.FEMALE)),
                    class_count=Count("school_class", distinct=True),
                )
            )
            EnrollmentAnalytics.objects.update_or_create(
                school=school,
                session=active_session,
                defaults={
                    "total_enrolled": enroll_agg["total"] or 0,
                    "male_count":     enroll_agg["male"] or 0,
                    "female_count":   enroll_agg["female"] or 0,
                    "class_count":    enroll_agg["class_count"] or 0,
                },
            )

    logger.info("update_school_daily_metrics completed for school=%s date=%s", school_id, today)
    return {"school_id": school_id, "date": str(today)}


# ---------------------------------------------------------------------------
# Task 2 — FinancialAnalytics
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="analytics.tasks.update_financial_metrics")
def update_financial_metrics(self, school_id: str, term_id: str | None = None) -> dict:
    """
    Recompute FinancialAnalytics for every term in the school (or a single term
    if term_id is supplied).

    Queries:
      Q1 — fetch target terms (1 query)
      Q2 — per-term StudentInvoice aggregation (1 query via values())
      Q3 — bulk update_or_create rows
    """
    from finance.models import StudentInvoice

    from .models import FinancialAnalytics

    school = _get_school(school_id)

    with transaction.atomic():
        term_qs = Term.objects.for_school(school).select_related("session")
        if term_id:
            term_qs = term_qs.filter(pk=term_id)
        terms = list(term_qs)

        # One aggregation query per term (still O(terms), not O(students)).
        for term in terms:
            agg = (
                StudentInvoice.objects
                .for_school(school)
                .filter(term=term)
                .aggregate(
                    total_invoiced=Sum("amount_due"),
                    total_collected=Sum("amount_paid"),
                    total_outstanding=Sum(
                        "balance",
                        filter=Q(status__in=[
                            StudentInvoice.Status.UNPAID,
                            StudentInvoice.Status.PARTIALLY_PAID,
                        ]),
                    ),
                    paid_count=Count("id", filter=Q(status=StudentInvoice.Status.PAID)),
                    partial_count=Count(
                        "id", filter=Q(status=StudentInvoice.Status.PARTIALLY_PAID)
                    ),
                    unpaid_count=Count(
                        "id", filter=Q(status=StudentInvoice.Status.UNPAID)
                    ),
                )
            )

            invoiced  = agg["total_invoiced"]  or Decimal("0.00")
            collected = agg["total_collected"] or Decimal("0.00")

            FinancialAnalytics.objects.update_or_create(
                school=school,
                term=term,
                defaults={
                    "total_invoiced":      invoiced,
                    "total_collected":     collected,
                    "total_outstanding":   agg["total_outstanding"] or Decimal("0.00"),
                    "collection_rate":     _pct(collected, invoiced),
                    "fully_paid_count":    agg["paid_count"] or 0,
                    "partially_paid_count": agg["partial_count"] or 0,
                    "unpaid_count":        agg["unpaid_count"] or 0,
                },
            )

    logger.info("update_financial_metrics completed for school=%s", school_id)
    return {"school_id": school_id, "terms_processed": len(terms)}


# ---------------------------------------------------------------------------
# Task 3 — ClassAnalytics
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="analytics.tasks.update_class_analytics")
def update_class_analytics(self, school_id: str, term_id: str | None = None) -> dict:
    """
    Recompute ClassAnalytics for every (class, term) combination in the school.

    Queries:
      Q1 — fetch terms
      Q2 — fetch classes
      Q3 — ResultSummary aggregation grouped by school_class+term (1 query)
      Q4 — distinct subject count per class+term from StudentSubjectResult (1 query)
      Q5 — bulk update_or_create rows
    """
    from academics.models import ResultSummary, StudentSubjectResult

    from .models import ClassAnalytics

    school = _get_school(school_id)

    with transaction.atomic():
        term_qs = Term.objects.for_school(school)
        if term_id:
            term_qs = term_qs.filter(pk=term_id)

        # Single aggregation across all class+term combos.
        # Use avg_score_agg (not average_score) to avoid shadowing the model
        # field name, which would make Max/Min unresolvable in the same query.
        summary_agg = (
            ResultSummary.objects.for_school(school)
            .filter(term__in=term_qs)
            .values("school_class_id", "term_id")
            .annotate(
                total_students=Count("id"),
                avg_score_agg=Avg("average_score"),
                highest_average=Max("average_score"),
                lowest_average=Min("average_score"),
                pass_count=Count(
                    "id", filter=Q(average_score__gte=50)
                ),
            )
        )

        # Subject count per class+term from StudentSubjectResult.
        subject_counts = {
            (row["school_class_id"], row["term_id"]): row["subject_count"]
            for row in (
                StudentSubjectResult.objects.for_school(school)
                .filter(term__in=term_qs)
                .values("school_class_id", "term_id")
                .annotate(subject_count=Count("subject_id", distinct=True))
            )
        }

        # Build a term map for quick lookup.
        term_map = {t.pk: t for t in term_qs}

        # Fetch all classes once.
        class_map = {
            c.pk: c for c in SchoolClass.objects.for_school(school)
        }

        rows_processed = 0
        for row in summary_agg:
            cls_id  = row["school_class_id"]
            term_id_ = row["term_id"]
            total   = row["total_students"] or 0
            pass_c  = row["pass_count"] or 0
            sc = class_map.get(cls_id)
            t  = term_map.get(term_id_)
            if not sc or not t:
                continue

            ClassAnalytics.objects.update_or_create(
                school=school,
                school_class=sc,
                term=t,
                defaults={
                    "total_students":  total,
                    "average_score":   row["avg_score_agg"] or Decimal("0.00"),
                    "highest_average": row["highest_average"] or Decimal("0.00"),
                    "lowest_average":  row["lowest_average"] or Decimal("0.00"),
                    "pass_rate":       _pct(pass_c, total),
                    "subjects_offered": subject_counts.get((cls_id, term_id_), 0),
                },
            )
            rows_processed += 1

    logger.info("update_class_analytics completed for school=%s rows=%d", school_id, rows_processed)
    return {"school_id": school_id, "rows_processed": rows_processed}


# ---------------------------------------------------------------------------
# Task 4 — SubjectAnalytics
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="analytics.tasks.update_subject_analytics")
def update_subject_analytics(self, school_id: str, term_id: str | None = None) -> dict:
    """
    Recompute SubjectAnalytics for every (subject, class, term) combination.

    Queries:
      Q1 — terms
      Q2 — StudentSubjectResult aggregation grouped by subject+class+term (1 query)
      Q3 — bulk update_or_create
    """
    from academics.models import StudentSubjectResult

    from .models import SubjectAnalytics

    school = _get_school(school_id)

    with transaction.atomic():
        term_qs = Term.objects.for_school(school)
        if term_id:
            term_qs = term_qs.filter(pk=term_id)

        # One aggregation query for all subject+class+term combos.
        agg = (
            StudentSubjectResult.objects.for_school(school)
            .filter(term__in=term_qs)
            .values("subject_id", "school_class_id", "term_id")
            .annotate(
                total_students=Count("id"),
                average_score=Avg("total_score"),
                highest_score=Max("total_score"),
                lowest_score=Min("total_score"),
                pass_count=Count("id", filter=Q(total_score__gte=50)),
            )
        )

        term_map = {t.pk: t for t in term_qs}
        class_map = {c.pk: c for c in SchoolClass.objects.for_school(school)}
        subject_map = {s.pk: s for s in Subject.objects.for_school(school)}

        rows_processed = 0
        for row in agg:
            subj = subject_map.get(row["subject_id"])
            cls  = class_map.get(row["school_class_id"])
            term = term_map.get(row["term_id"])
            if not (subj and cls and term):
                continue
            total  = row["total_students"] or 0
            pass_c = row["pass_count"] or 0

            SubjectAnalytics.objects.update_or_create(
                school=school,
                subject=subj,
                school_class=cls,
                term=term,
                defaults={
                    "total_students": total,
                    "average_score":  row["average_score"] or Decimal("0.00"),
                    "highest_score":  row["highest_score"] or Decimal("0.00"),
                    "lowest_score":   row["lowest_score"] or Decimal("0.00"),
                    "pass_rate":      _pct(pass_c, total),
                },
            )
            rows_processed += 1

    logger.info("update_subject_analytics completed for school=%s rows=%d", school_id, rows_processed)
    return {"school_id": school_id, "rows_processed": rows_processed}


# ---------------------------------------------------------------------------
# Task 5 — AttendanceAnalytics
# ---------------------------------------------------------------------------

@shared_task(bind=True, name="analytics.tasks.update_attendance_analytics")
def update_attendance_analytics(self, school_id: str, term_id: str | None = None) -> dict:
    """
    Recompute AttendanceAnalytics for every (class, term) in the school.

    Attendance records are linked to AttendanceSessions which have a date.
    We join via AttendanceRecord → AttendanceSession to group by class+term.

    Queries:
      Q1 — terms
      Q2 — AttendanceSession aggregation (session count per class + date range)
      Q3 — AttendanceRecord aggregation grouped by school_class+term (1 query)
      Q4 — bulk update_or_create
    """
    from enrollment.models import AttendanceRecord, AttendanceSession

    from .models import AttendanceAnalytics

    school = _get_school(school_id)

    with transaction.atomic():
        term_qs = Term.objects.for_school(school).select_related("session")
        if term_id:
            term_qs = term_qs.filter(pk=term_id)
        terms = list(term_qs)

        class_map = {c.pk: c for c in SchoolClass.objects.for_school(school)}

        rows_processed = 0
        for term in terms:
            # Find attendance sessions whose date falls within the term's date range.
            sessions_in_term = AttendanceSession.objects.filter(
                school=school,
                date__gte=term.start_date,
                date__lte=term.end_date,
            )

            # Group session counts by class.
            session_counts = {
                row["school_class_id"]: row["cnt"]
                for row in sessions_in_term.values("school_class_id").annotate(cnt=Count("id"))
            }

            # Aggregate records by class (joining through session).
            record_agg = (
                AttendanceRecord.objects
                .filter(school=school, session__in=sessions_in_term)
                .values("session__school_class_id")
                .annotate(
                    total=Count("id"),
                    present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
                    absent=Count("id", filter=Q(status=AttendanceRecord.Status.ABSENT)),
                    late=Count("id", filter=Q(status=AttendanceRecord.Status.LATE)),
                )
            )

            for row in record_agg:
                cls_id = row["session__school_class_id"]
                cls    = class_map.get(cls_id)
                if not cls:
                    continue

                total   = row["total"] or 0
                present = row["present"] or 0
                late    = row["late"] or 0

                AttendanceAnalytics.objects.update_or_create(
                    school=school,
                    school_class=cls,
                    term=term,
                    defaults={
                        "total_sessions":          session_counts.get(cls_id, 0),
                        "total_records":           total,
                        "present_count":           present,
                        "absent_count":            row["absent"] or 0,
                        "late_count":              late,
                        "average_attendance_rate": _pct(present + late, total),
                    },
                )
                rows_processed += 1

    logger.info("update_attendance_analytics completed for school=%s rows=%d", school_id, rows_processed)
    return {"school_id": school_id, "rows_processed": rows_processed}
