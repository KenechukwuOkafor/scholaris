"""
Student Promotion Engine.

promote_student  — move one student into a new class for a new session.
promote_class    — promote every active student in a class in one call.

Both functions are idempotent: re-running with the same arguments
is safe and returns the existing enrollment without creating duplicates.

Promotion atomically:
  1. Creates a new StudentEnrollment(school_class=next_class, session=session).
  2. Sets all previous is_current=True enrollments for the student to False.
  3. Updates Student.student_class to reflect the new placement.

Steps 1-3 run inside a database transaction so a partial failure leaves
the data in a consistent state.
"""

from __future__ import annotations

import logging

from django.db import transaction

from core.models import SchoolClass, Session
from core.services.audit_service import ACTION_PROMOTION_PROMOTE_CLASS, log_action
from enrollment.models import Student, StudentEnrollment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# promote_student
# ---------------------------------------------------------------------------


def promote_student(
    student: Student,
    next_class: SchoolClass,
    session: Session,
) -> tuple[StudentEnrollment, bool]:
    """
    Enroll *student* in *next_class* for *session*.

    If the student already has an enrollment for *session*, returns
    (existing_enrollment, False) without modifying anything.

    Otherwise:
      - Deactivates all previous is_current=True enrollments for the student.
      - Creates a new StudentEnrollment(is_current=True).
      - Updates Student.student_class to next_class.

    Args:
        student:    the student to promote.
        next_class: the SchoolClass the student is moving into.
        session:    the academic Session for the new enrollment.

    Returns:
        (StudentEnrollment, created: bool)

    Raises:
        ValueError — if next_class and student do not belong to the same school.
    """
    if next_class.school_id != student.school_id:
        raise ValueError(
            f"next_class '{next_class.name}' belongs to a different school "
            f"than student '{student}'."
        )

    with transaction.atomic():
        enrollment, created = StudentEnrollment.objects.get_or_create(
            student=student,
            session=session,
            defaults={
                "school": student.school,
                "school_class": next_class,
                "is_current": True,
            },
        )

        if not created:
            logger.debug(
                "promote_student: student=%s already enrolled for session=%s — skipped",
                student,
                session,
            )
            return enrollment, False

        # Deactivate all other current enrollments for this student.
        StudentEnrollment.objects.filter(
            student=student,
            is_current=True,
        ).exclude(pk=enrollment.pk).update(is_current=False)

        # Keep Student.student_class in sync with the new placement.
        Student.objects.filter(pk=student.pk).update(student_class=next_class)

    logger.info(
        "promote_student: student=%s → class=%s session=%s",
        student,
        next_class,
        session,
    )
    return enrollment, True


# ---------------------------------------------------------------------------
# promote_class
# ---------------------------------------------------------------------------


def promote_class(
    current_class: SchoolClass,
    next_class: SchoolClass,
    session: Session,
    actor=None,
) -> dict[str, int]:
    """
    Promote every active student in *current_class* to *next_class* for
    *session*.

    Only students with status=ACTIVE are promoted; graduated, withdrawn,
    and suspended students are excluded.

    The entire batch runs inside one database transaction — if any student's
    promotion fails, the whole operation is rolled back.

    Args:
        current_class: the class being promoted out of.
        next_class:    the class students are moving into.
        session:       the new academic session for the promotions.

    Returns:
        {
            "promoted": int,   # new enrollments created
            "skipped":  int,   # students already enrolled for this session
        }

    Raises:
        ValueError — if current_class and next_class belong to different schools,
                     or if session belongs to a different school.
    """
    school = current_class.school

    if next_class.school_id != school.pk:
        raise ValueError(
            "current_class and next_class must belong to the same school."
        )
    if session.school_id != school.pk:
        raise ValueError(
            "session must belong to the same school as the classes."
        )

    students = list(
        Student.objects.for_school(school).filter(
            student_class=current_class,
            status=Student.Status.ACTIVE,
        )
    )

    promoted = 0
    skipped = 0

    with transaction.atomic():
        for student in students:
            _, created = promote_student(student, next_class, session)
            if created:
                promoted += 1
            else:
                skipped += 1

    logger.info(
        "promote_class: %s → %s | session=%s | promoted=%d skipped=%d",
        current_class.name,
        next_class.name,
        session.name,
        promoted,
        skipped,
    )

    log_action(
        actor=actor,
        action=ACTION_PROMOTION_PROMOTE_CLASS,
        target_model="SchoolClass",
        target_id=current_class.id,
        metadata={
            "from_class": current_class.name,
            "to_class": next_class.name,
            "session": session.name,
            "promoted": promoted,
            "skipped": skipped,
        },
        school=school,
    )

    return {"promoted": promoted, "skipped": skipped}
