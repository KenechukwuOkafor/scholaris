"""
Teacher Dashboard Service.

Returns per-teacher metrics scoped to the teacher's assigned classes and subjects.
Reads from analytics tables + live ResultStatistics for subject breakdowns.
Cached in Redis for 300 seconds.

Cache key: analytics:teacher_dashboard:{school_id}:{teacher_id}
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def get_teacher_dashboard(school, teacher) -> dict:
    """
    Return a metrics dict for the given teacher.

    Args:
        school:  a School instance.
        teacher: an accounts.Teacher instance.

    Returns:
        JSON-serialisable dict.
    """
    cache_key = f"analytics:teacher_dashboard:{school.pk}:{teacher.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _build_teacher_dashboard(school, teacher)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def _build_teacher_dashboard(school, teacher) -> dict:
    from academics.models import ResultStatistics, TeachingAssignment
    from analytics.models import AttendanceAnalytics, ClassAnalytics
    from core.models import Term

    today = timezone.localdate()

    # Active term
    try:
        active_term = Term.objects.for_school(school).get(is_active=True)
    except Term.DoesNotExist:
        active_term = None

    # Teacher's assignments in the active term's school classes.
    assignments = (
        TeachingAssignment.objects
        .for_school(school)
        .filter(teacher=teacher)
        .select_related("school_class", "subject")
        .order_by("school_class__name", "subject__name")
    )

    assigned_class_ids = list(assignments.values_list("school_class_id", flat=True).distinct())
    assigned_subject_ids = list(assignments.values_list("subject_id", flat=True).distinct())

    # Class analytics for teacher's classes (active term).
    class_summaries = []
    if active_term and assigned_class_ids:
        for ca in (
            ClassAnalytics.objects
            .for_school(school)
            .filter(term=active_term, school_class_id__in=assigned_class_ids)
            .select_related("school_class")
        ):
            class_summaries.append({
                "class":           ca.school_class.name,
                "total_students":  ca.total_students,
                "average_score":   str(ca.average_score),
                "pass_rate":       str(ca.pass_rate),
            })

    # Subject statistics (ResultStatistics) for teacher's subjects+classes.
    subject_stats = []
    if active_term:
        for rs in (
            ResultStatistics.objects
            .for_school(school)
            .filter(
                term=active_term,
                subject_id__in=assigned_subject_ids,
                school_class_id__in=assigned_class_ids,
            )
            .select_related("subject", "school_class")
        ):
            subject_stats.append({
                "subject":       rs.subject.name,
                "class":         rs.school_class.name,
                "class_average": str(rs.class_average),
                "highest_score": str(rs.highest_score),
                "lowest_score":  str(rs.lowest_score),
            })

    # Attendance rates for teacher's classes (active term).
    attendance_rows = []
    if active_term and assigned_class_ids:
        for aa in (
            AttendanceAnalytics.objects
            .for_school(school)
            .filter(term=active_term, school_class_id__in=assigned_class_ids)
            .select_related("school_class")
        ):
            attendance_rows.append({
                "class":              aa.school_class.name,
                "total_sessions":     aa.total_sessions,
                "attendance_rate":    str(aa.average_attendance_rate),
                "present_count":      aa.present_count,
                "absent_count":       aa.absent_count,
            })

    # Assignment list.
    assignment_list = [
        {"class": a.school_class.name, "subject": a.subject.name}
        for a in assignments
    ]

    return {
        "teacher":      f"{teacher.first_name} {teacher.last_name}",
        "school":       school.name,
        "as_of":        str(today),
        "active_term":  str(active_term) if active_term else None,
        "assignments":  assignment_list,
        "classes":      class_summaries,
        "subjects":     subject_stats,
        "attendance":   attendance_rows,
    }


def invalidate_teacher_dashboard_cache(school, teacher) -> None:
    cache.delete(f"analytics:teacher_dashboard:{school.pk}:{teacher.pk}")
