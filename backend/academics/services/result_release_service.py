"""
ResultReleaseService — publish and unpublish computed results per class+term.
"""

from __future__ import annotations

from django.utils import timezone

from academics.models import ResultRelease
from core.models import SchoolClass, Term
from core.services.audit_service import (
    ACTION_RESULT_PUBLISH,
    ACTION_RESULT_UNPUBLISH,
    log_action,
)


def publish_results(
    school_class: SchoolClass,
    term: Term,
    actor=None,
) -> ResultRelease:
    """
    Mark results for *school_class* in *term* as published.

    Creates the ResultRelease row if it does not yet exist.

    Args:
        school_class: the class whose results should be published.
        term:         the term to publish results for.
        actor:        the User performing the action (for audit logging).

    Returns:
        The updated ResultRelease instance.
    """
    release, _ = ResultRelease.objects.get_or_create(
        school_class=school_class,
        term=term,
        defaults={"school": school_class.school},
    )
    if not release.is_published:
        release.is_published = True
        release.published_at = timezone.now()
        release.save(update_fields=["is_published", "published_at", "updated_at"])

    log_action(
        actor=actor,
        action=ACTION_RESULT_PUBLISH,
        target_model="ResultRelease",
        target_id=release.id,
        metadata={
            "class": school_class.name,
            "term": term.name,
            "school": school_class.school.name,
        },
        school=school_class.school,
    )
    return release


def unpublish_results(
    school_class: SchoolClass,
    term: Term,
    actor=None,
) -> ResultRelease:
    """
    Mark results for *school_class* in *term* as unpublished.

    Creates the ResultRelease row if it does not yet exist (already unpublished
    by default, so this is a no-op in that case).

    Args:
        school_class: the class whose results should be hidden.
        term:         the term to unpublish.
        actor:        the User performing the action (for audit logging).

    Returns:
        The updated ResultRelease instance.
    """
    release, _ = ResultRelease.objects.get_or_create(
        school_class=school_class,
        term=term,
        defaults={"school": school_class.school},
    )
    if release.is_published:
        release.is_published = False
        release.save(update_fields=["is_published", "updated_at"])

    log_action(
        actor=actor,
        action=ACTION_RESULT_UNPUBLISH,
        target_model="ResultRelease",
        target_id=release.id,
        metadata={
            "class": school_class.name,
            "term": term.name,
            "school": school_class.school.name,
        },
        school=school_class.school,
    )
    return release


def is_results_published(school_class: SchoolClass, term: Term) -> bool:
    """
    Return True if results for *school_class* in *term* are published.

    Returns False when no ResultRelease row exists (default state is
    unpublished).

    Args:
        school_class: the class to check.
        term:         the term to check.

    Returns:
        bool
    """
    try:
        release = ResultRelease.objects.get(school_class=school_class, term=term)
        return release.is_published
    except ResultRelease.DoesNotExist:
        return False
