"""
BroadsheetService — bulk score upsert for a class.

Responsible for:
  1. Resolving and validating the teacher against their TeachingAssignment.
  2. Verifying all submitted students are enrolled in the target class.
  3. Enforcing score ceilings from AssessmentType.max_score.
  4. Performing a single-query bulk upsert using bulk_create(update_conflicts=True).

All operations are wrapped in a database transaction by the caller (the view).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import models as django_models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from academics.models import AssessmentType, Score, TeachingAssignment
from accounts.models import Teacher
from core.models import SchoolClass, Subject, Term
from enrollment.models import Student


class BroadsheetService:

    def submit_scores(
        self,
        *,
        user,
        school,
        class_id: uuid.UUID,
        subject_id: uuid.UUID,
        term_id: uuid.UUID,
        assessment_type_id: uuid.UUID,
        score_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Validate and bulk-upsert scores for an entire class.

        Returns a summary dict: {"students_updated": int}.
        """
        teacher = self._resolve_teacher(user=user, school=school)
        school_class = self._get_school_class(class_id=class_id, school=school)
        subject = self._get_subject(subject_id=subject_id, school=school)
        term = self._get_term(term_id=term_id, school=school)
        assessment_type = self._get_assessment_type(
            assessment_type_id=assessment_type_id, school=school
        )

        self._check_teaching_assignment(
            teacher=teacher,
            school=school,
            school_class=school_class,
            subject=subject,
        )

        submitted_student_ids = {e["student_id"] for e in score_entries}
        student_map = self._validate_students(
            student_ids=submitted_student_ids,
            school_class=school_class,
            school=school,
        )

        self._validate_score_values(
            score_entries=score_entries,
            assessment_type=assessment_type,
        )

        count = self._bulk_upsert(
            score_entries=score_entries,
            student_map=student_map,
            school=school,
            subject=subject,
            term=term,
            assessment_type=assessment_type,
        )

        return {"students_updated": count}

    def save_broadsheet_scores(
        self,
        *,
        school,
        school_class: SchoolClass,
        subject: Subject,
        term: Term,
        assessment_type: AssessmentType,
        scores: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Save scores for an entire class with explicit create/update tracking,
        then trigger result computation.

        Each entry in ``scores`` must be::

            {"student_id": <uuid>, "score": <Decimal>}

        All writes and the result computation run inside a single atomic
        transaction so the database is never left in a partially-updated state.

        Returns::

            {"created": <int>, "updated": <int>}
        """
        # Guard: catch programmer errors where mismatched objects are passed in.
        assert school_class.school_id == school.id, (
            f"school_class {school_class.id} belongs to school {school_class.school_id}, "
            f"not {school.id}"
        )
        assert subject.school_id == school.id, (
            f"subject {subject.id} belongs to school {subject.school_id}, "
            f"not {school.id}"
        )
        assert assessment_type.school_id == school.id, (
            f"assessment_type {assessment_type.id} belongs to school "
            f"{assessment_type.school_id}, not {school.id}"
        )

        # Normalise: accept both "student_id" and "student" as the key.
        normalised = [
            {
                "student_id": e.get("student_id") or e["student"],
                "score": Decimal(str(e["score"])),
            }
            for e in scores
        ]

        submitted: dict[uuid.UUID, Decimal] = {
            e["student_id"]: e["score"] for e in normalised
        }
        student_ids = set(submitted)

        # --- Validation (no DB writes yet) ---------------------------------
        student_map = self._validate_students(
            student_ids=student_ids,
            school_class=school_class,
            school=school,
        )
        self._validate_score_values(
            score_entries=normalised,
            assessment_type=assessment_type,
        )

        # --- Persist + compute inside one transaction ----------------------
        with transaction.atomic():
            existing_map = self._fetch_existing_scores(
                school=school,
                student_ids=student_ids,
                subject=subject,
                term=term,
                assessment_type=assessment_type,
            )

            scores_to_create, scores_to_update = self._split_create_update(
                submitted=submitted,
                existing_map=existing_map,
                student_map=student_map,
                school=school,
                subject=subject,
                term=term,
                assessment_type=assessment_type,
            )

            if scores_to_create:
                Score.objects.bulk_create(scores_to_create)

            if scores_to_update:
                Score.objects.bulk_update(
                    scores_to_update,
                    fields=["score", "updated_at"],
                )

            # Trigger result computation after scores are persisted.
            from academics.services.result_processor import ResultProcessor
            ResultProcessor().process_results(
                school_class=school_class,
                term=term,
            )

        return {
            "created": len(scores_to_create),
            "updated": len(scores_to_update),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_teacher(self, *, user, school) -> Teacher:
        """
        Resolve the Teacher record for the authenticated user.

        NOTE: This uses email matching as a provisional approach because
        the custom User model with a direct Teacher FK has not yet been
        built.  Once accounts.User is implemented, replace this lookup
        with:  Teacher.objects.get(user=user, school=school)
        """
        try:
            return Teacher.objects.get(
                email=user.email.lower(),
                school=school,
                status=Teacher.Status.ACTIVE,
            )
        except Teacher.DoesNotExist:
            raise PermissionDenied(
                "No active teacher profile found for this account at this school."
            )

    def _get_school_class(self, *, class_id: uuid.UUID, school) -> SchoolClass:
        try:
            return SchoolClass.objects.get(id=class_id, school=school)
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {class_id} not found for this school.")

    def _get_subject(self, *, subject_id: uuid.UUID, school) -> Subject:
        try:
            return Subject.objects.get(id=subject_id, school=school)
        except Subject.DoesNotExist:
            raise NotFound(f"Subject {subject_id} not found for this school.")

    def _get_term(self, *, term_id: uuid.UUID, school) -> Term:
        try:
            return Term.objects.get(id=term_id, school=school)
        except Term.DoesNotExist:
            raise NotFound(f"Term {term_id} not found for this school.")

    def _get_assessment_type(
        self, *, assessment_type_id: uuid.UUID, school
    ) -> AssessmentType:
        try:
            return AssessmentType.objects.get(id=assessment_type_id, school=school)
        except AssessmentType.DoesNotExist:
            raise NotFound(
                f"AssessmentType {assessment_type_id} not found for this school."
            )

    def _check_teaching_assignment(
        self,
        *,
        teacher: Teacher,
        school,
        school_class: SchoolClass,
        subject: Subject,
    ) -> None:
        has_assignment = TeachingAssignment.objects.filter(
            school=school,
            teacher=teacher,
            school_class=school_class,
            subject=subject,
        ).exists()

        if not has_assignment:
            raise PermissionDenied(
                "You do not have a teaching assignment for this class and subject."
            )

    def _validate_students(
        self,
        *,
        student_ids: set[uuid.UUID],
        school_class: SchoolClass,
        school,
    ) -> dict[uuid.UUID, Student]:
        """
        Verify all submitted student IDs belong to the specified class
        at this school. Returns a {student_id: Student} map.
        """
        students = Student.objects.filter(
            id__in=student_ids,
            school=school,
            student_class=school_class,
            status=Student.Status.ACTIVE,
        )
        student_map = {s.id: s for s in students}

        missing = student_ids - set(student_map.keys())
        if missing:
            raise ValidationError(
                {
                    "scores": (
                        f"{len(missing)} student(s) not found in this class or not active: "
                        f"{', '.join(str(i) for i in missing)}"
                    )
                }
            )

        return student_map

    def _validate_score_values(
        self,
        *,
        score_entries: list[dict[str, Any]],
        assessment_type: AssessmentType,
    ) -> None:
        errors = []
        max_score = Decimal(str(assessment_type.max_score))

        for entry in score_entries:
            value = entry["score"]
            if value > max_score:
                errors.append(
                    f"Student {entry['student_id']}: score {value} exceeds "
                    f"max allowed {max_score} for {assessment_type.name}."
                )

        if errors:
            raise ValidationError({"scores": errors})

    def _bulk_upsert(
        self,
        *,
        score_entries: list[dict[str, Any]],
        student_map: dict[uuid.UUID, Student],
        school,
        subject: Subject,
        term: Term,
        assessment_type: AssessmentType,
    ) -> int:
        """
        Insert or update all score rows in a single query using
        bulk_create(update_conflicts=True) — available in Django 4.1+.
        """
        now = timezone.now()

        score_objects = [
            Score(
                id=uuid.uuid4(),
                school=school,
                student=student_map[entry["student_id"]],
                subject=subject,
                term=term,
                assessment_type=assessment_type,
                score=entry["score"],
                created_at=now,
                updated_at=now,
            )
            for entry in score_entries
        ]

        Score.objects.bulk_create(
            score_objects,
            update_conflicts=True,
            update_fields=["score", "updated_at"],
            unique_fields=[
                "school_id",
                "student_id",
                "subject_id",
                "term_id",
                "assessment_type_id",
            ],
        )

        return len(score_objects)

    def _fetch_existing_scores(
        self,
        *,
        school,
        student_ids: set[uuid.UUID],
        subject: Subject,
        term: Term,
        assessment_type: AssessmentType,
    ) -> dict[uuid.UUID, Score]:
        """
        Return a {student_id: Score} map for rows that already exist.

        Uses SELECT FOR UPDATE so concurrent requests cannot interleave
        their reads and writes on the same rows.

        Single query — no N+1.
        """
        return {
            row.student_id: row
            for row in Score.objects.select_for_update().filter(
                school=school,
                student_id__in=student_ids,
                subject=subject,
                term=term,
                assessment_type=assessment_type,
            )
        }

    def _split_create_update(
        self,
        *,
        submitted: dict[uuid.UUID, Decimal],
        existing_map: dict[uuid.UUID, Score],
        student_map: dict[uuid.UUID, Student],
        school,
        subject: Subject,
        term: Term,
        assessment_type: AssessmentType,
    ) -> tuple[list[Score], list[Score]]:
        """
        Partition submitted scores into two lists:

        - ``scores_to_create``: student has no existing row → new Score objects.
        - ``scores_to_update``: student already has a row → mutate in place.

        Returns (scores_to_create, scores_to_update).
        """
        now = timezone.now()
        scores_to_create: list[Score] = []
        scores_to_update: list[Score] = []

        for student_id, score_value in submitted.items():
            if student_id in existing_map:
                obj = existing_map[student_id]
                if obj.score != score_value:
                    obj.score = score_value
                    obj.updated_at = now
                    scores_to_update.append(obj)
            else:
                scores_to_create.append(
                    Score(
                        id=uuid.uuid4(),
                        school=school,
                        student=student_map[student_id],
                        subject=subject,
                        term=term,
                        assessment_type=assessment_type,
                        score=score_value,
                        created_at=now,
                        updated_at=now,
                    )
                )

        return scores_to_create, scores_to_update
