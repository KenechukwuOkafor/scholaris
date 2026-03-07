"""
ParentService — create parents and link them to students.
"""

from __future__ import annotations

from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

from enrollment.models import Parent, Student, StudentParent


def create_parent(
    student: Student,
    name: str,
    phone: str,
    relationship: str,
    email: str = "",
) -> tuple[Parent, StudentParent]:
    """
    Create a new Parent scoped to student.school and immediately link them
    to *student* with *relationship*.

    Args:
        student:      the student to associate the new parent with.
        name:         full name of the parent/guardian.
        phone:        contact phone number.
        relationship: e.g. "Mother", "Father", "Guardian".
        email:        optional email address.

    Returns:
        A (Parent, StudentParent) tuple.

    Raises:
        rest_framework.exceptions.ValidationError — if the student already
        has this parent linked (duplicate link).
    """
    parent = Parent.objects.create(
        school=student.school,
        name=name,
        phone=phone,
        email=email,
    )

    try:
        link = StudentParent.objects.create(
            school=student.school,
            student=student,
            parent=parent,
            relationship=relationship,
        )
    except IntegrityError:
        raise ValidationError(
            f"Student '{student}' is already linked to parent '{parent.name}'."
        )

    return parent, link


def link_parent(
    student: Student,
    parent: Parent,
    relationship: str,
) -> StudentParent:
    """
    Link an existing Parent to a Student.

    Tenant-safe: raises ValidationError if student and parent belong to
    different schools.

    Args:
        student:      the student to link.
        parent:       an existing Parent instance.
        relationship: e.g. "Mother", "Father", "Guardian".

    Returns:
        The newly created StudentParent instance.

    Raises:
        rest_framework.exceptions.ValidationError — if schools differ or
        the link already exists.
    """
    if student.school_id != parent.school_id:
        raise ValidationError(
            "Student and parent must belong to the same school."
        )

    try:
        return StudentParent.objects.create(
            school=student.school,
            student=student,
            parent=parent,
            relationship=relationship,
        )
    except IntegrityError:
        raise ValidationError(
            f"Student '{student}' is already linked to parent '{parent.name}'."
        )
