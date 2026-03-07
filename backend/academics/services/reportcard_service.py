"""
ReportCardService — assembles a student's end-of-term report card.

Reads exclusively from precomputed result tables — no scores are recomputed here:
  • StudentSubjectResult  — per-subject totals and subject rankings
  • ResultSummary         — student-level totals, average, and class position
  • ResultStatistics      — class-level stats per subject (highest, lowest, average)
  • Score                 — raw per-assessment-type scores for assessment breakdown
  • StudentTraitRating    — behavioural/psychomotor trait ratings grouped by category

Total DB queries: 5 (including one correlated subquery for students_in_class).
"""

from __future__ import annotations

import base64
import mimetypes
import os
from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Count, OuterRef, Subquery
from rest_framework.exceptions import NotFound, PermissionDenied

from academics.models import (
    ResultRelease,
    ResultStatistics,
    ResultSummary,
    Score,
    StudentSubjectResult,
    StudentTraitRating,
)
from core.models import Term
from enrollment.models import Student

_NOT_FOUND_MSG = "No computed results found. Run result processing first."


# ---------------------------------------------------------------------------
# Image helper
# ---------------------------------------------------------------------------


def _image_to_data_uri(image_field) -> str | None:
    """
    Convert a Django ImageField value to a base64-encoded data URI.

    Returns None when the field is empty or the file does not exist on disk.
    Data URIs are necessary for WeasyPrint when rendering from an HTML string
    (no base URL available to resolve relative or media paths).
    """
    if not image_field or not image_field.name:
        return None
    try:
        path = image_field.path
        if not os.path.isfile(path):
            return None
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/png"
        with open(path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Grade helper
# ---------------------------------------------------------------------------


def _compute_grade(total_score: Decimal) -> str:
    """Map a subject total score (0–100) to a letter grade."""
    if total_score >= 70:
        return "A"
    if total_score >= 60:
        return "B"
    if total_score >= 50:
        return "C"
    if total_score >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Remark generator
# ---------------------------------------------------------------------------


def generate_student_remark(summary: dict) -> str:
    """
    Generate an automatic teacher's remark from a student's term summary.

    Rules applied in two layers:

    Layer 1 — base remark from average_score:
        ≥ 80  → "Excellent performance. Keep it up."
        ≥ 70  → "Very good performance."
        ≥ 60  → "Good result."
        ≥ 50  → "Fair result, improvement needed."
        < 50  → "Poor performance, immediate improvement required."

    Layer 2 — position enhancement (overrides or appends):
        position == 1          → "Outstanding performance. You came first in your class."
        position ≤ 3           → "Excellent performance. You are among the top students."
        position > class_size/2 → base remark + " You can do much better with more effort."

    Args:
        summary: the summary dict from generate_report_card(), containing
                 average_score, class_position, and students_in_class.

    Returns:
        A single remark string.
    """
    average  = summary["average_score"]
    position = summary["class_position"]
    class_size = summary["students_in_class"]

    # Layer 1: base remark from average
    if average >= 80:
        base = "Excellent performance. Keep it up."
    elif average >= 70:
        base = "Very good performance."
    elif average >= 60:
        base = "Good result."
    elif average >= 50:
        base = "Fair result, improvement needed."
    else:
        base = "Poor performance, immediate improvement required."

    # Layer 2: position enhancement
    if position is None:
        return base

    if position == 1:
        return "Outstanding performance. You came first in your class."

    if position <= 3:
        return "Excellent performance. You are among the top students."

    if class_size and position > class_size / 2:
        return f"{base} You can do much better with more effort."

    return base


# ---------------------------------------------------------------------------
# Trait ratings helper
# ---------------------------------------------------------------------------


def _get_trait_ratings(student: Student, term: Term) -> dict[str, list[dict[str, str]]]:
    """
    Fetch and group all trait ratings for *student* in *term*.

    Returns::

        {
            "Affective Traits": [
                {"trait": "Punctuality",      "rating": "Excellent"},
                {"trait": "Behaviour",         "rating": "Very Good"},
            ],
            "Psychomotor Skills": [
                {"trait": "Handwriting",       "rating": "Good"},
            ],
        }

    Query count: 1.
    """
    rows = (
        StudentTraitRating.objects
        .for_school(student.school)
        .filter(student=student, term=term)
        .select_related("trait", "trait__category", "scale")
        .order_by(
            "trait__category__display_order",
            "trait__category__name",
            "trait__display_order",
            "trait__name",
        )
    )

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.trait.category.name].append({
            "trait": row.trait.name,
            "rating": row.scale.label,
        })

    return dict(grouped)


# ---------------------------------------------------------------------------
# Report card generator
# ---------------------------------------------------------------------------


def generate_report_card(
    student: Student,
    term: Term,
) -> dict[str, Any]:
    """
    Build a fully structured report card for *student* in *term*.

    The school is derived from ``student.school`` and applied to every query
    via ``.for_school()`` for strict tenant isolation.

    Raises:
        rest_framework.exceptions.NotFound — when no computed results exist
        for this student/term (neither ResultSummary nor StudentSubjectResult).

    Returns::

        {
            "student_info": {
                "student_id": str,
                "name":       str,
                "class":      str,
                "term":       str,
                "session":    str,
            },
            "summary": {
                "total_score":      Decimal,
                "average_score":    Decimal,
                "class_position":   int | None,
                "students_in_class": int,
            },
            "subjects": [
                {
                    "subject_id":    str,
                    "subject":       str,
                    "assessments":   {"CA1": Decimal, "Exam": Decimal, ...},
                    "total_score":   Decimal,
                    "grade":         str,
                    "position":      int | None,
                    "class_average": Decimal | None,
                    "highest":       Decimal | None,
                    "lowest":        Decimal | None,
                },
                ...  # ordered by subject name
            ],
            "traits": {
                "Affective Traits":   [{"trait": str, "rating": str}, ...],
                "Psychomotor Skills": [{"trait": str, "rating": str}, ...],
            },
        }
    """
    school = student.school

    # ── Query 1: Overall summary + class size + publish status ────────────
    #
    # Three values resolved in a single SQL query via correlated subqueries:
    #   • students_in_class — count of ResultSummary rows for the same class/term
    #   • results_published — is_published from ResultRelease (None → unpublished)
    #
    # The publish gate fires immediately after this query so no result data
    # is returned to the caller when results are not yet published.
    _class_size_sq = (
        ResultSummary.objects
        .filter(
            school_id=OuterRef("school_id"),
            school_class_id=OuterRef("school_class_id"),
            term_id=OuterRef("term_id"),
        )
        .values("school_class_id")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )

    _published_sq = (
        ResultRelease.objects
        .filter(
            school_class_id=OuterRef("school_class_id"),
            term_id=OuterRef("term_id"),
        )
        .values("is_published")[:1]
    )

    try:
        summary = (
            ResultSummary.objects
            .for_school(school)
            .select_related("school_class", "term__session")
            .annotate(
                students_in_class=Subquery(_class_size_sq),
                results_published=Subquery(_published_sq),
            )
            .get(student=student, term=term)
        )
    except ResultSummary.DoesNotExist:
        raise NotFound(_NOT_FOUND_MSG)

    school_class = summary.school_class

    # ── Publish gate ──────────────────────────────────────────────────────
    # results_published is None when no ResultRelease row exists (default
    # unpublished state) or False when explicitly unpublished.
    if not summary.results_published:
        raise PermissionDenied(
            "Results for this class have not been published."
        )

    # ── Query 2: Per-subject results ──────────────────────────────────────
    subject_results = list(
        StudentSubjectResult.objects
        .for_school(school)
        .filter(student=student, term=term)
        .select_related("subject")
        .order_by("subject__name")
    )

    if not subject_results:
        raise NotFound(_NOT_FOUND_MSG)

    # ── Query 3: Class-level statistics keyed by subject_id ───────────────
    stats_by_subject: dict[Any, ResultStatistics] = {
        rs.subject_id: rs
        for rs in ResultStatistics.objects
        .for_school(school)
        .filter(school_class=school_class, term=term)
    }

    # ── Query 4: Raw scores → {subject_id: {assessment_name: score}} ──────
    assessments: dict[Any, dict[str, Decimal]] = defaultdict(dict)
    for row in (
        Score.objects
        .for_school(school)
        .filter(student=student, term=term)
        .select_related("assessment_type", "subject")
        .order_by("subject_id", "assessment_type__order", "assessment_type__name")
    ):
        assessments[row.subject_id][row.assessment_type.name] = row.score

    # ── Query 5: Trait ratings (inside _get_trait_ratings) ────────────────
    traits = _get_trait_ratings(student, term)

    # ── Assemble ──────────────────────────────────────────────────────────
    subjects = []
    for sr in subject_results:
        stats = stats_by_subject.get(sr.subject_id)
        subjects.append({
            "subject_id": str(sr.subject_id),
            "subject": sr.subject.name,
            "assessments": dict(assessments.get(sr.subject_id, {})),
            "total_score": sr.total_score,
            "grade": _compute_grade(sr.total_score),
            "position": sr.subject_position,
            "class_average": stats.class_average if stats else None,
            "highest": stats.highest_score if stats else None,
            "lowest": stats.lowest_score if stats else None,
        })

    next_term_begins = term.next_term_begins
    return {
        "school": {
            "name": school.name,
            "address": school.address,
            "phone": school.phone,
            "email": school.email,
            "logo": _image_to_data_uri(school.logo),
            "principal_signature": _image_to_data_uri(school.principal_signature),
            "school_stamp": _image_to_data_uri(school.school_stamp),
        },
        "student_info": {
            "student_id": str(student.id),
            "name": f"{student.first_name} {student.last_name}",
            "class": school_class.name,
            "term": summary.term.name,
            "session": summary.term.session.name,
            "next_term_begins": (
                next_term_begins.strftime("%d %B, %Y") if next_term_begins else None
            ),
        },
        "summary": {
            "total_score": summary.total_score,
            "average_score": summary.average_score,
            "class_position": summary.position,
            "students_in_class": summary.students_in_class,
        },
        "subjects": subjects,
        "traits": traits,
        "remarks": generate_student_remark({
            "average_score": summary.average_score,
            "class_position": summary.position,
            "students_in_class": summary.students_in_class,
        }),
    }
