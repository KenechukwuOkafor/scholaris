"""
ResultProcessor — computes and persists end-of-term results for a class.

Responsibilities:
  1. Aggregate Score rows into per-student subject totals.
  2. Compute student-level total_score and average_score.
  3. Optionally rank students using competition ranking (1, 2, 2, 4 …).
  4. Bulk-upsert ResultSummary (one row per student).
  5. Bulk-upsert ResultStatistics (one row per subject).

All writes happen inside a single atomic transaction supplied by the caller.
The Score model is never modified.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.db import models as django_models
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from academics.models import ResultStatistics, ResultSummary, Score
from core.models import SchoolClass, Term
from enrollment.models import Student


_TWO_PLACES = Decimal("0.01")


class ResultProcessor:

    def calculate_class_results(
        self,
        *,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Compute and persist results for every student in a class.

        This method must be called inside a transaction.atomic() block.

        Returns:
            {"students_processed": int, "statistics_generated": bool}
        """
        school_class, term, school = self._resolve_inputs(
            class_id=class_id, term_id=term_id
        )

        students = self._fetch_students(school_class=school_class, school=school)
        if not students:
            return {"students_processed": 0, "statistics_generated": False}

        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}

        # ------------------------------------------------------------------
        # 1. Pull all raw score rows in a single query.
        # ------------------------------------------------------------------
        raw_scores = list(
            Score.objects.filter(
                school=school,
                term=term,
                student_id__in=student_ids,
            ).values("student_id", "subject_id", "score")
        )

        if not raw_scores:
            return {"students_processed": 0, "statistics_generated": False}

        # ------------------------------------------------------------------
        # 2. Aggregate: subject_totals[student_id][subject_id] = Decimal
        # ------------------------------------------------------------------
        subject_totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )
        for row in raw_scores:
            subject_totals[row["student_id"]][row["subject_id"]] += Decimal(
                str(row["score"])
            )

        # ------------------------------------------------------------------
        # 3. Compute per-student total and average.
        # ------------------------------------------------------------------
        student_results: dict[uuid.UUID, dict[str, Any]] = {}
        for student_id, subjects in subject_totals.items():
            total = sum(subjects.values())
            n_subjects = len(subjects)
            average = (total / n_subjects).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            student_results[student_id] = {
                "total_score": total.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
                "average_score": average,
                "position": None,
            }

        # ------------------------------------------------------------------
        # 4. Rank students if the school has ranking enabled.
        # ------------------------------------------------------------------
        if school.enable_class_ranking:
            self._assign_positions(student_results)

        # ------------------------------------------------------------------
        # 5. Bulk upsert ResultSummary.
        # ------------------------------------------------------------------
        self._upsert_summaries(
            student_results=student_results,
            student_map=student_map,
            school=school,
            school_class=school_class,
            term=term,
        )

        # ------------------------------------------------------------------
        # 6. Compute and upsert per-subject ResultStatistics.
        # ------------------------------------------------------------------
        self._upsert_statistics(
            subject_totals=subject_totals,
            school=school,
            school_class=school_class,
            term=term,
        )

        return {
            "students_processed": len(student_results),
            "statistics_generated": True,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_inputs(
        self,
        *,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> tuple[SchoolClass, Term, Any]:
        try:
            school_class = SchoolClass.objects.select_related("school").get(id=class_id)
        except SchoolClass.DoesNotExist:
            raise NotFound(f"SchoolClass {class_id} not found.")

        school = school_class.school

        try:
            term = Term.objects.get(id=term_id, school=school)
        except Term.DoesNotExist:
            raise NotFound(
                f"Term {term_id} not found for school '{school.name}'."
            )

        return school_class, term, school

    def _fetch_students(
        self,
        *,
        school_class: SchoolClass,
        school,
    ) -> list[Student]:
        return list(
            Student.objects.filter(
                school=school,
                student_class=school_class,
                status=Student.Status.ACTIVE,
            )
        )

    def _assign_positions(
        self,
        student_results: dict[uuid.UUID, dict[str, Any]],
    ) -> None:
        """
        Competition ranking: students with equal averages share the same rank.
        Example: scores [90, 85, 85, 80] → positions [1, 2, 2, 4].
        """
        ranked = sorted(
            student_results.items(),
            key=lambda item: item[1]["average_score"],
            reverse=True,
        )

        position = 1
        for i, (student_id, data) in enumerate(ranked):
            if i > 0:
                prev_avg = ranked[i - 1][1]["average_score"]
                if data["average_score"] < prev_avg:
                    position = i + 1  # gap for tied students above
            data["position"] = position

    def _upsert_summaries(
        self,
        *,
        student_results: dict[uuid.UUID, dict[str, Any]],
        student_map: dict[uuid.UUID, Student],
        school,
        school_class: SchoolClass,
        term: Term,
    ) -> None:
        now = timezone.now()

        summary_objects = [
            ResultSummary(
                id=uuid.uuid4(),
                school=school,
                student=student_map[student_id],
                school_class=school_class,
                term=term,
                total_score=data["total_score"],
                average_score=data["average_score"],
                position=data["position"],
                created_at=now,
                updated_at=now,
            )
            for student_id, data in student_results.items()
        ]

        ResultSummary.objects.bulk_create(
            summary_objects,
            update_conflicts=True,
            update_fields=["total_score", "average_score", "position", "updated_at"],
            unique_fields=["school_id", "student_id", "term_id"],
        )

    def _upsert_statistics(
        self,
        *,
        subject_totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]],
        school,
        school_class: SchoolClass,
        term: Term,
    ) -> None:
        """
        For each subject with scores, compute class-level statistics
        (highest, lowest, average) and upsert ResultStatistics.
        """
        # Invert subject_totals: subject_scores[subject_id] = [student totals]
        subject_scores: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
        for subjects in subject_totals.values():
            for subject_id, total in subjects.items():
                subject_scores[subject_id].append(total)

        now = timezone.now()
        stats_objects = []

        for subject_id, scores in subject_scores.items():
            n = len(scores)
            highest = max(scores).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            lowest = min(scores).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            class_avg = (sum(scores) / n).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

            stats_objects.append(
                ResultStatistics(
                    id=uuid.uuid4(),
                    school=school,
                    school_class=school_class,
                    subject_id=subject_id,
                    term=term,
                    highest_score=highest,
                    lowest_score=lowest,
                    class_average=class_avg,
                    created_at=now,
                    updated_at=now,
                )
            )

        ResultStatistics.objects.bulk_create(
            stats_objects,
            update_conflicts=True,
            update_fields=[
                "highest_score",
                "lowest_score",
                "class_average",
                "updated_at",
            ],
            unique_fields=["school_id", "school_class_id", "subject_id", "term_id"],
        )
