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


def get_class_attendance(
    school_class: SchoolClass,
    date: datetime.date,
) -> dict:
    """
    Return the attendance session and all records for *school_class* on *date*.

    Args:
        school_class: the class whose attendance to retrieve.
        date:         the day of interest.

    Returns::

        {
            "session":  AttendanceSession | None,
            "records":  list[AttendanceRecord],
            "summary":  {
                "present": int,
                "absent":  int,
                "late":    int,
                "excused": int,
                "total":   int,
            },
        }

    Returns an empty result dict when no session exists for the given day.
    """
    try:
        session = (
            AttendanceSession.objects
            .select_related("school_class", "marked_by")
            .get(school=school_class.school, school_class=school_class, date=date)
        )
    except AttendanceSession.DoesNotExist:
        return {"session": None, "records": [], "summary": {}}

    records_qs = (
        AttendanceRecord.objects
        .filter(session=session)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    )
    records = list(records_qs)

    agg = records_qs.aggregate(
        present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent=Count("id",  filter=Q(status=AttendanceRecord.Status.ABSENT)),
        late=Count("id",    filter=Q(status=AttendanceRecord.Status.LATE)),
        excused=Count("id", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
    )
    agg["total"] = agg["present"] + agg["absent"] + agg["late"] + agg["excused"]

    return {"session": session, "records": records, "summary": agg}


def get_student_attendance(
    student: Student,
    term: Term,
) -> dict:
    """
    Return all attendance records for *student* within *term*, plus a summary.

    Args:
        student: the student to look up.
        term:    the term whose date range bounds the lookup.

    Returns::

        {
            "records": list[AttendanceRecord],   # ordered by date
            "summary": {
                "days_present":          int,
                "days_absent":           int,
                "days_late":             int,
                "days_excused":          int,
                "total_days":            int,
                "attendance_percentage": float,
            },
        }

    Notes:
        - attendance_percentage counts "late" as attended; "excused" is excluded
          from both numerator and denominator so it does not penalise the student.
        - Returns empty records and all-zero summary when no records exist.
    """
    records_qs = (
        AttendanceRecord.objects
        .filter(
            school_id=student.school_id,
            student=student,
            session__date__gte=term.start_date,
            session__date__lte=term.end_date,
        )
        .select_related("session__school_class")
        .order_by("session__date")
    )
    records = list(records_qs)

    agg = records_qs.aggregate(
        days_present=Count("id", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        days_absent=Count("id",  filter=Q(status=AttendanceRecord.Status.ABSENT)),
        days_late=Count("id",    filter=Q(status=AttendanceRecord.Status.LATE)),
        days_excused=Count("id", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
    )

    present = agg["days_present"]
    absent  = agg["days_absent"]
    late    = agg["days_late"]
    excused = agg["days_excused"]
    # Excused days do not count as absent or present — exclude from denominator.
    countable = present + absent + late

    agg["total_days"] = present + absent + late + excused
    agg["attendance_percentage"] = (
        round((present + late) / countable * 100, 2) if countable else 0.0
    )

    return {"records": records, "summary": agg}


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
            "days_excused":          int,
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
            days_excused=Count("id", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
        )
    )

    present = agg["days_present"]
    absent  = agg["days_absent"]
    late    = agg["days_late"]
    excused = agg["days_excused"]
    countable = present + absent + late
    total   = countable + excused

    attendance_percentage = round((present + late) / countable * 100, 2) if countable else 0.0

    return {
        "days_present":  present,
        "days_absent":   absent,
        "days_late":     late,
        "days_excused":  excused,
        "total_days":    total,
        "attendance_percentage": attendance_percentage,
    }
