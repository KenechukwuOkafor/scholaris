"""
Admin Dashboard Service.

Returns a school-wide overview dashboard for school administrators.
Data is read from pre-aggregated analytics tables and cached in Redis
for 300 seconds.

Cache key: analytics:admin_dashboard:{school_id}
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # seconds


def get_admin_dashboard(school) -> dict:
    """
    Return a comprehensive school-wide metrics dict for the admin dashboard.

    Reads from:
    - SchoolDailyMetrics   (today's snapshot)
    - ClassAnalytics       (active term, all classes)
    - FinancialAnalytics   (active term)
    - AttendanceAnalytics  (active term, all classes)
    - EnrollmentAnalytics  (active session)

    Args:
        school: a School instance.

    Returns:
        JSON-serialisable dict.
    """
    cache_key = f"analytics:admin_dashboard:{school.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _build_admin_dashboard(school)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def _build_admin_dashboard(school) -> dict:
    from analytics.models import (
        AttendanceAnalytics,
        ClassAnalytics,
        EnrollmentAnalytics,
        FinancialAnalytics,
        SchoolDailyMetrics,
    )
    from core.models import Session, Term

    today = timezone.localdate()

    # --- Today's daily metrics -------------------------------------------
    try:
        daily = SchoolDailyMetrics.objects.for_school(school).get(date=today)
        daily_data = {
            "active_students":     daily.active_students,
            "total_students":      daily.total_students,
            "active_teachers":     daily.active_teachers,
            "attendance_rate":     str(daily.attendance_rate),
            "present_count":       daily.present_count,
            "total_att_records":   daily.total_attendance_records,
        }
    except SchoolDailyMetrics.DoesNotExist:
        daily_data = {
            "active_students":   0,
            "total_students":    0,
            "active_teachers":   0,
            "attendance_rate":   "0.00",
            "present_count":     0,
            "total_att_records": 0,
        }

    # --- Active term ---------------------------------------------------------
    try:
        active_term = Term.objects.for_school(school).get(is_active=True)
    except Term.DoesNotExist:
        active_term = None

    # --- Active session -------------------------------------------------------
    try:
        active_session = Session.objects.for_school(school).get(is_active=True)
    except Session.DoesNotExist:
        active_session = None

    # --- Financial (active term) ----------------------------------------------
    if active_term:
        try:
            fin = FinancialAnalytics.objects.for_school(school).get(term=active_term)
            financial_data = {
                "term":                str(active_term),
                "total_invoiced":      str(fin.total_invoiced),
                "total_collected":     str(fin.total_collected),
                "total_outstanding":   str(fin.total_outstanding),
                "collection_rate":     str(fin.collection_rate),
                "fully_paid_count":    fin.fully_paid_count,
                "partially_paid_count": fin.partially_paid_count,
                "unpaid_count":        fin.unpaid_count,
            }
        except FinancialAnalytics.DoesNotExist:
            financial_data = {"term": str(active_term) if active_term else None}
    else:
        financial_data = {}

    # --- Class performance (active term) -------------------------------------
    class_rows = []
    if active_term:
        for ca in (
            ClassAnalytics.objects
            .for_school(school)
            .filter(term=active_term)
            .select_related("school_class")
            .order_by("school_class__order", "school_class__name")
        ):
            class_rows.append({
                "class":            ca.school_class.name,
                "total_students":   ca.total_students,
                "average_score":    str(ca.average_score),
                "pass_rate":        str(ca.pass_rate),
                "highest_average":  str(ca.highest_average),
                "lowest_average":   str(ca.lowest_average),
                "subjects_offered": ca.subjects_offered,
            })

    # --- Attendance summary (active term) ------------------------------------
    att_rows = []
    if active_term:
        for aa in (
            AttendanceAnalytics.objects
            .for_school(school)
            .filter(term=active_term)
            .select_related("school_class")
            .order_by("school_class__order", "school_class__name")
        ):
            att_rows.append({
                "class":                aa.school_class.name,
                "total_sessions":       aa.total_sessions,
                "average_attendance_rate": str(aa.average_attendance_rate),
                "present_count":        aa.present_count,
                "absent_count":         aa.absent_count,
                "late_count":           aa.late_count,
            })

    # --- Enrollment (active session) -----------------------------------------
    enrollment_data = {}
    if active_session:
        try:
            ea = EnrollmentAnalytics.objects.for_school(school).get(session=active_session)
            enrollment_data = {
                "session":        str(active_session),
                "total_enrolled": ea.total_enrolled,
                "male_count":     ea.male_count,
                "female_count":   ea.female_count,
                "class_count":    ea.class_count,
            }
        except EnrollmentAnalytics.DoesNotExist:
            enrollment_data = {"session": str(active_session)}

    return {
        "school":      school.name,
        "as_of":       str(today),
        "daily":       daily_data,
        "financial":   financial_data,
        "classes":     class_rows,
        "attendance":  att_rows,
        "enrollment":  enrollment_data,
    }


def invalidate_admin_dashboard_cache(school) -> None:
    """Call this after analytics rows are updated to clear stale data."""
    cache.delete(f"analytics:admin_dashboard:{school.pk}")
