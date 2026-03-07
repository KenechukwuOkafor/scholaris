"""
Dashboard analytics service.

get_school_overview(school) returns a snapshot of the key school-wide
metrics in exactly 4 database queries — no N+1, no Python-level loops.

Query map
---------
Q1  Student   — COUNT active students
Q2  Teacher   — COUNT active teachers
Q3  AttendanceRecord — two COUNTs (total today, present/late today) in one aggregate
Q4  StudentInvoice   — two SUMs (amount_paid, outstanding balance) in one aggregate
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import Teacher
from enrollment.models import AttendanceRecord, Student
from finance.models import StudentInvoice


def get_school_overview(school) -> dict:
    """
    Return a dashboard snapshot for *school*.

    All five metrics are derived from aggregation queries scoped to the
    given school via `.for_school(school)` or an explicit `school=school`
    filter — no cross-tenant data leaks are possible.

    Args:
        school: a School instance.

    Returns:
        {
            "students":         int,    # active students
            "teachers":         int,    # active teachers
            "attendance_today": float,  # % of today's records that are present/late
            "fees_collected":   Decimal,
            "outstanding_fees": Decimal,
        }

    Query count: 4
        Q1 — Student count
        Q2 — Teacher count
        Q3 — AttendanceRecord aggregation (today)
        Q4 — StudentInvoice aggregation (all time)
    """

    # Q1 — active students ────────────────────────────────────────────────────
    total_students = (
        Student.objects
        .for_school(school)
        .filter(status=Student.Status.ACTIVE)
        .count()
    )

    # Q2 — active teachers ────────────────────────────────────────────────────
    total_teachers = (
        Teacher.objects
        .for_school(school)
        .filter(status=Teacher.Status.ACTIVE)
        .count()
    )

    # Q3 — today's attendance (single aggregation) ────────────────────────────
    today = timezone.localdate()

    att = (
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

    total_att = att["total"] or 0
    attendance_today = (
        round(att["attended"] / total_att * 100, 1) if total_att else 0.0
    )

    # Q4 — fees (single aggregation) ─────────────────────────────────────────
    fees = (
        StudentInvoice.objects
        .for_school(school)
        .aggregate(
            fees_collected=Sum("amount_paid"),
            outstanding_fees=Sum(
                "balance",
                filter=Q(status__in=[
                    StudentInvoice.Status.UNPAID,
                    StudentInvoice.Status.PARTIALLY_PAID,
                ]),
            ),
        )
    )

    return {
        "students":         total_students,
        "teachers":         total_teachers,
        "attendance_today": attendance_today,
        "fees_collected":   fees["fees_collected"] or Decimal("0.00"),
        "outstanding_fees": fees["outstanding_fees"] or Decimal("0.00"),
    }
