"""
ResultProcessor — computes and persists end-of-term results for a class.

Responsibilities:
  1. Aggregate Score rows into per-student per-subject totals.
  2. Compute per-student total_score and average_score across all subjects.
  3. Compute subject rankings (position per subject within the class).
  4. Compute class rankings (position in class by total score).
  5. Bulk-upsert StudentSubjectResult (one row per student per subject).
  6. Bulk-upsert ResultSummary (one row per student).
  7. Bulk-upsert ResultStatistics (one row per subject).

All writes happen inside a single atomic transaction supplied by the caller.
Score rows are never modified.

Ranking uses competition (standard) ranking:
  Scores  [90, 90, 80, 70] → positions [1, 1, 3, 4]
  Scores  [95, 85, 85, 80] → positions [1, 2, 2, 4]

Example validation (3 students, 2 subjects):
  Student A: Maths=80, English=70  → total=150, avg=75.00
  Student B: Maths=90, English=90  → total=180, avg=90.00
  Student C: Maths=90, English=70  → total=160, avg=80.00

  Class ranking (by total):  B→1, C→2, A→3
  Maths subject ranking:     B/C tied→1, A→3
  English subject ranking:   B→1, A/C tied→2 (both scored 70)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.utils import timezone
from rest_framework.exceptions import NotFound

from academics.models import (
    ResultStatistics,
    ResultSummary,
    Score,
    StudentSubjectResult,
)
from core.models import SchoolClass, Term
from enrollment.models import Student


_TWO_PLACES = Decimal("0.01")


class ResultProcessor:

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def process_results(
        self,
        *,
        school_class: SchoolClass,
        term: Term,
    ) -> dict[str, Any]:
        """
        Compute and persist all results for a class in a term.

        Must be called inside a transaction.atomic() block.

        Returns:
            {
                "students_processed": int,
                "subjects_processed": int,
                "statistics_generated": bool,
            }
        """
        school = school_class.school

        students = self._fetch_students(school_class=school_class, school=school)
        if not students:
            return {
                "students_processed": 0,
                "subjects_processed": 0,
                "statistics_generated": False,
            }

        student_ids = [s.id for s in students]
        student_map = {s.id: s for s in students}

        # Single query — all score rows for this class/term.
        raw_scores = list(
            Score.objects.filter(
                school=school,
                term=term,
                student_id__in=student_ids,
            ).values("student_id", "subject_id", "score")
        )

        if not raw_scores:
            return {
                "students_processed": 0,
                "subjects_processed": 0,
                "statistics_generated": False,
            }

        # --- Computation pipeline (pure Python, no further DB reads) --------

        # subject_totals[student_id][subject_id] = Decimal total
        subject_totals = self.compute_subject_totals(raw_scores)

        # student_results[student_id] = {total_score, average_score, position}
        student_results = self.compute_student_totals(subject_totals)

        if school.enable_class_ranking:
            self.compute_class_rankings(student_results)

        # subject_rankings[subject_id][student_id] = position
        subject_rankings = self._compute_subject_rankings(
            subject_totals=subject_totals,
            enabled=school.enable_class_ranking,
        )

        # --- Persistence (three bulk upserts) --------------------------------

        self._upsert_subject_results(
            subject_totals=subject_totals,
            subject_rankings=subject_rankings,
            student_map=student_map,
            school=school,
            school_class=school_class,
            term=term,
        )

        self._upsert_summaries(
            student_results=student_results,
            student_map=student_map,
            school=school,
            school_class=school_class,
            term=term,
        )

        self._upsert_statistics(
            subject_totals=subject_totals,
            school=school,
            school_class=school_class,
            term=term,
        )

        return {
            "students_processed": len(student_results),
            "subjects_processed": len(subject_rankings),
            "statistics_generated": True,
        }

    def calculate_class_results(
        self,
        *,
        class_id: uuid.UUID,
        term_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Backward-compatible entry point that resolves objects from IDs
        and delegates to process_results().

        Must be called inside a transaction.atomic() block.
        """
        school_class, term, _school = self._resolve_inputs(
            class_id=class_id, term_id=term_id
        )
        return self.process_results(school_class=school_class, term=term)

    # ------------------------------------------------------------------
    # Named computation methods (pure functions — no DB access)
    # ------------------------------------------------------------------

    def compute_subject_totals(
        self,
        raw_scores: list[dict],
    ) -> dict[uuid.UUID, dict[uuid.UUID, Decimal]]:
        """
        Aggregate raw Score rows into per-student per-subject totals.

        Args:
            raw_scores: list of dicts with keys student_id, subject_id, score.

        Returns:
            subject_totals[student_id][subject_id] = Decimal total

        Example:
            Student A has CA1=20, CA2=15, Exam=60 in Maths
            → subject_totals[A][maths_id] = Decimal("95")
        """
        totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = defaultdict(
            lambda: defaultdict(Decimal)
        )
        for row in raw_scores:
            totals[row["student_id"]][row["subject_id"]] += Decimal(str(row["score"]))
        return totals

    def compute_student_totals(
        self,
        subject_totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """
        Derive per-student total_score and average_score from subject totals.

        Args:
            subject_totals: output of compute_subject_totals().

        Returns:
            student_results[student_id] = {
                "total_score":   Decimal,
                "average_score": Decimal,
                "position":      None,   # populated later by compute_class_rankings
            }

        Example (2 subjects):
            subject_totals[A] = {maths: 95, english: 75}
            → total=170.00, average=85.00
        """
        results: dict[uuid.UUID, dict[str, Any]] = {}
        for student_id, subjects in subject_totals.items():
            total = sum(subjects.values())
            n = len(subjects)
            average = (total / n).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            results[student_id] = {
                "total_score": total.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
                "average_score": average,
                "position": None,
            }
        return results

    def compute_class_rankings(
        self,
        student_results: dict[uuid.UUID, dict[str, Any]],
    ) -> None:
        """
        Assign class positions in-place using competition ranking by total_score.

        Ties share the lowest position in their group; the next rank skips
        the appropriate number of places.

        Example:
            totals [180, 160, 160, 150] → positions [1, 2, 2, 4]

        Args:
            student_results: dict mutated in place — "position" key is set.
        """
        ranked = sorted(
            student_results.items(),
            key=lambda item: item[1]["total_score"],
            reverse=True,
        )
        position = 1
        for i, (_student_id, data) in enumerate(ranked):
            if i > 0 and data["total_score"] < ranked[i - 1][1]["total_score"]:
                position = i + 1
            data["position"] = position

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_subject_rankings(
        self,
        subject_totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]],
        *,
        enabled: bool,
    ) -> dict[uuid.UUID, dict[uuid.UUID, int | None]]:
        """
        Compute per-subject competition rankings within the class.

        Args:
            subject_totals: output of compute_subject_totals().
            enabled:        mirrors school.enable_class_ranking.

        Returns:
            subject_rankings[subject_id][student_id] = position (or None)

        Example (3 students, Maths scores: B=90, C=90, A=80):
            → subject_rankings[maths_id] = {B: 1, C: 1, A: 3}
        """
        # Invert: per_subject[subject_id] = [(student_id, total), ...]
        per_subject: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = defaultdict(list)
        for student_id, subjects in subject_totals.items():
            for subject_id, total in subjects.items():
                per_subject[subject_id].append((student_id, total))

        rankings: dict[uuid.UUID, dict[uuid.UUID, int | None]] = {}

        for subject_id, entries in per_subject.items():
            if not enabled:
                rankings[subject_id] = {sid: None for sid, _ in entries}
                continue

            sorted_entries = sorted(entries, key=lambda x: x[1], reverse=True)
            subject_map: dict[uuid.UUID, int] = {}
            position = 1
            for i, (student_id, total) in enumerate(sorted_entries):
                if i > 0 and total < sorted_entries[i - 1][1]:
                    position = i + 1
                subject_map[student_id] = position
            rankings[subject_id] = subject_map

        return rankings

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
            raise NotFound(f"Term {term_id} not found for school '{school.name}'.")

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

    def _upsert_subject_results(
        self,
        *,
        subject_totals: dict[uuid.UUID, dict[uuid.UUID, Decimal]],
        subject_rankings: dict[uuid.UUID, dict[uuid.UUID, int | None]],
        student_map: dict[uuid.UUID, Student],
        school,
        school_class: SchoolClass,
        term: Term,
    ) -> None:
        """Bulk upsert StudentSubjectResult — one row per student per subject."""
        now = timezone.now()
        objects = []

        for student_id, subjects in subject_totals.items():
            for subject_id, total in subjects.items():
                position = subject_rankings.get(subject_id, {}).get(student_id)
                objects.append(
                    StudentSubjectResult(
                        id=uuid.uuid4(),
                        school=school,
                        student=student_map[student_id],
                        school_class=school_class,
                        subject_id=subject_id,
                        term=term,
                        total_score=total.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
                        subject_position=position,
                        created_at=now,
                        updated_at=now,
                    )
                )

        StudentSubjectResult.objects.bulk_create(
            objects,
            update_conflicts=True,
            update_fields=["total_score", "subject_position", "updated_at"],
            unique_fields=["school_id", "student_id", "subject_id", "term_id"],
        )

    def _upsert_summaries(
        self,
        *,
        student_results: dict[uuid.UUID, dict[str, Any]],
        student_map: dict[uuid.UUID, Student],
        school,
        school_class: SchoolClass,
        term: Term,
    ) -> None:
        """Bulk upsert ResultSummary — one row per student."""
        now = timezone.now()

        objects = [
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
            objects,
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
        """Bulk upsert ResultStatistics — one row per subject (class-level stats)."""
        # Invert: subject_scores[subject_id] = [all student totals]
        subject_scores: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
        for subjects in subject_totals.values():
            for subject_id, total in subjects.items():
                subject_scores[subject_id].append(total)

        now = timezone.now()
        objects = []

        for subject_id, scores in subject_scores.items():
            n = len(scores)
            highest = max(scores).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            lowest = min(scores).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            class_avg = (sum(scores) / n).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

            objects.append(
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
            objects,
            update_conflicts=True,
            update_fields=["highest_score", "lowest_score", "class_average", "updated_at"],
            unique_fields=["school_id", "school_class_id", "subject_id", "term_id"],
        )
