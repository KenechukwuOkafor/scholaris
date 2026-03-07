"""
Proprietor Dashboard Service.

Returns a high-level executive view across academic, financial, attendance,
and enrollment dimensions — suitable for school owners/proprietors.
Reads exclusively from analytics tables (no live queries).
Cached in Redis for 300 seconds.

Cache key: analytics:proprietor_dashboard:{school_id}
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Avg, Max, Min
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def get_proprietor_dashboard(school) -> dict:
    """
    Return an executive-level metrics dict for the proprietor.

    Args:
        school: a School instance.

    Returns:
        JSON-serialisable dict.
    """
    cache_key = f"analytics:proprietor_dashboard:{school.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _build_proprietor_dashboard(school)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def _build_proprietor_dashboard(school) -> dict:
    from analytics.models import (
        AttendanceAnalytics,
        ClassAnalytics,
        EnrollmentAnalytics,
        FinancialAnalytics,
        SchoolDailyMetrics,
    )
    from core.models import Session, Term

    today = timezone.localdate()

    # Active term / session
    try:
        active_term = Term.objects.for_school(school).get(is_active=True)
    except Term.DoesNotExist:
        active_term = None

    try:
        active_session = Session.objects.for_school(school).get(is_active=True)
    except Session.DoesNotExist:
        active_session = None

    # --- Enrollment KPIs (active session) ------------------------------------
    enrollment_kpis = {}
    if active_session:
        try:
            ea = EnrollmentAnalytics.objects.for_school(school).get(session=active_session)
            enrollment_kpis = {
                "session":        active_session.name,
                "total_enrolled": ea.total_enrolled,
                "male_count":     ea.male_count,
                "female_count":   ea.female_count,
                "class_count":    ea.class_count,
            }
        except EnrollmentAnalytics.DoesNotExist:
            enrollment_kpis = {"session": active_session.name}

    # --- Academic KPIs (active term) -----------------------------------------
    academic_kpis = {}
    if active_term:
        ca_agg = (
            ClassAnalytics.objects
            .for_school(school)
            .filter(term=active_term)
            .aggregate(
                school_avg=Avg("average_score"),
                best_class_avg=Max("average_score"),
                worst_class_avg=Min("average_score"),
                overall_pass_rate=Avg("pass_rate"),
            )
        )
        academic_kpis = {
            "term":              str(active_term),
            "school_average":    str(round(ca_agg["school_avg"] or Decimal("0"), 2)),
            "best_class_avg":    str(round(ca_agg["best_class_avg"] or Decimal("0"), 2)),
            "worst_class_avg":   str(round(ca_agg["worst_class_avg"] or Decimal("0"), 2)),
            "overall_pass_rate": str(round(ca_agg["overall_pass_rate"] or Decimal("0"), 2)),
        }

    # --- Financial KPIs (active term) ----------------------------------------
    financial_kpis = {}
    if active_term:
        try:
            fa = FinancialAnalytics.objects.for_school(school).get(term=active_term)
            financial_kpis = {
                "term":              str(active_term),
                "total_invoiced":    str(fa.total_invoiced),
                "total_collected":   str(fa.total_collected),
                "total_outstanding": str(fa.total_outstanding),
                "collection_rate":   str(fa.collection_rate),
            }
        except FinancialAnalytics.DoesNotExist:
            financial_kpis = {"term": str(active_term)}

    # --- Attendance KPIs (active term) ----------------------------------------
    attendance_kpis = {}
    if active_term:
        att_agg = (
            AttendanceAnalytics.objects
            .for_school(school)
            .filter(term=active_term)
            .aggregate(
                school_att_rate=Avg("average_attendance_rate"),
                best_att=Max("average_attendance_rate"),
                worst_att=Min("average_attendance_rate"),
            )
        )
        attendance_kpis = {
            "term":                str(active_term),
            "school_att_rate":     str(round(att_agg["school_att_rate"] or Decimal("0"), 2)),
            "best_class_att":      str(round(att_agg["best_att"] or Decimal("0"), 2)),
            "worst_class_att":     str(round(att_agg["worst_att"] or Decimal("0"), 2)),
        }

    # --- Today's live snapshot -----------------------------------------------
    try:
        daily = SchoolDailyMetrics.objects.for_school(school).get(date=today)
        today_snapshot = {
            "active_students":   daily.active_students,
            "active_teachers":   daily.active_teachers,
            "attendance_rate":   str(daily.attendance_rate),
        }
    except SchoolDailyMetrics.DoesNotExist:
        today_snapshot = {}

    # --- Historical term trends ----------------------------------------------
    term_trend = []
    for fa in (
        FinancialAnalytics.objects
        .for_school(school)
        .select_related("term", "term__session")
        .order_by("term__start_date")
    ):
        ca_avg = (
            ClassAnalytics.objects
            .for_school(school)
            .filter(term=fa.term)
            .aggregate(s=Avg("average_score"))["s"]
        ) or Decimal("0")
        aa_avg = (
            AttendanceAnalytics.objects
            .for_school(school)
            .filter(term=fa.term)
            .aggregate(s=Avg("average_attendance_rate"))["s"]
        ) or Decimal("0")
        term_trend.append({
            "term":             str(fa.term),
            "session":          fa.term.session.name,
            "collection_rate":  str(fa.collection_rate),
            "academic_avg":     str(round(ca_avg, 2)),
            "attendance_rate":  str(round(aa_avg, 2)),
        })

    return {
        "school":       school.name,
        "school_type":  school.school_type,
        "currency":     school.currency,
        "as_of":        str(today),
        "today":        today_snapshot,
        "enrollment":   enrollment_kpis,
        "academic":     academic_kpis,
        "financial":    financial_kpis,
        "attendance":   attendance_kpis,
        "term_trends":  term_trend,
    }


def invalidate_proprietor_dashboard_cache(school) -> None:
    cache.delete(f"analytics:proprietor_dashboard:{school.pk}")
