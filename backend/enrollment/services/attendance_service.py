"""
AttendanceService — creates attendance sessions and bulk-records student statuses.

No score or result tables are touched.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import IntegrityError
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import SchoolClass, Term
from enrollment.models import AttendanceRecord, AttendanceSession, Student

import datetime


def start_attendance_session(
    school_class: SchoolClass,
    date: datetime.date,
    user,
) -> AttendanceSession:
    """
    Open an attendance session for *school_class* on *date*.

    Raises:
        rest_framework.exceptions.ValidationError — if a session already
        exists for this class on this date.

    Returns:
        The newly created AttendanceSession.
    """
    try:
        session = AttendanceSession.objects.create(
            school=school_class.school,
            school_class=school_class,
            date=date,
            marked_by=user,
        )
    except IntegrityError:
        raise ValidationError(
            f"An attendance session for '{school_class.name}' on {date} already exists."
        )

    return session


def mark_attendance(
    session: AttendanceSession,
    records: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Bulk-create (or update) attendance records for a session.

    Args:
        session: the open AttendanceSession to record against.
        records: list of dicts with keys ``student_id`` (UUID) and ``status``
                 (one of present / absent / late).

    Behaviour:
        - Uses bulk_create with update_conflicts so the endpoint is idempotent:
          re-submitting the same session overwrites existing statuses rather
          than raising an error.
        - Students not enrolled in session.school are silently ignored —
          tenant isolation is preserved because the school filter is applied
          when resolving student IDs.

    Returns:
        {"records_saved": int}
    """
    school = session.school

    # Resolve student UUIDs that belong to this school (tenant-safe).
    student_id_set = {r["student_id"] for r in records}
    valid_students = {
        s.id: s
        for s in Student.objects.filter(school=school, id__in=student_id_set)
    }

    now = timezone.now()
    objects = [
        AttendanceRecord(
            id=uuid.uuid4(),
            school=school,
            session=session,
            student=valid_students[r["student_id"]],
            status=r["status"],
            created_at=now,
            updated_at=now,
        )
        for r in records
        if r["student_id"] in valid_students
    ]

    AttendanceRecord.objects.bulk_create(
        objects,
        update_conflicts=True,
        update_fields=["status", "updated_at"],
        unique_fields=["session_id", "student_id"],
    )

    return {"records_saved": len(objects)}


def get_student_attendance_summary(
    student: Student,
    term: Term,
) -> dict:
    """
    Return attendance statistics for *student* within *term*.

    Counts are derived in a single aggregated query — no N+1 queries.

    Args:
        student: the student to summarise.
        term:    the term whose date range bounds the lookup.

    Returns::

        {
            "days_present":          int,
            "days_absent":           int,
            "days_late":             int,
            "total_days":            int,
            "attendance_percentage": float,   # based on present + late
        }

    Notes:
        - attendance_percentage counts "late" as attended so that a student
          who arrives late is not penalised as fully absent.
        - Returns all-zero dict when no records exist for the period.
    """
    agg = (
        AttendanceRecord.objects
        .filter(
            school_id=student.school_id,  # tenant-safe via cached FK, no extra query
            student=student,
            session__date__gte=term.start_date,
            session__date__lte=term.end_date,
        )
        .aggregate(
            days_present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
            days_absent=Count("id",  filter=Q(status=AttendanceRecord.Status.ABSENT)),
            days_late=Count("id",    filter=Q(status=AttendanceRecord.Status.LATE)),
        )
    )

    present = agg["days_present"]
    absent  = agg["days_absent"]
    late    = agg["days_late"]
    total   = present + absent + late

    attendance_percentage = round((present + late) / total * 100, 2) if total else 0.0

    return {
        "days_present": present,
        "days_absent":  absent,
        "days_late":    late,
        "total_days":   total,
        "attendance_percentage": attendance_percentage,
    }
