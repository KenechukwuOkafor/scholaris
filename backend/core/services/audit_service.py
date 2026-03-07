"""
Audit service — write AuditLog rows for significant system events.

Usage:
    from core.services.audit_service import log_action

    log_action(
        actor=request.user,          # Django User or None for system actions
        action="result.publish",     # dot-namespaced identifier
        target_model="ResultRelease",
        target_id=release.id,
        metadata={
            "class": school_class.name,
            "term": term.name,
        },
    )

Design notes:
    - log_action never raises. Failures are swallowed and logged at WARNING
      level so a broken audit write never interrupts business logic.
    - The call is synchronous and happens inside whatever transaction the
      caller is running. If the caller's transaction is rolled back, the
      audit row is also rolled back — which is the correct behaviour
      (no phantom audit entry for an operation that never committed).

Action name conventions:
    result.publish          ResultRelease published
    result.unpublish        ResultRelease hidden
    payment.record          PaymentTransaction created
    promotion.promote_class All students in a class promoted
    broadsheet.submit       Scores bulk-submitted for a class
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Canonical action name constants — import these instead of bare strings.
ACTION_RESULT_PUBLISH         = "result.publish"
ACTION_RESULT_UNPUBLISH       = "result.unpublish"
ACTION_PAYMENT_RECORD         = "payment.record"
ACTION_PROMOTION_PROMOTE_CLASS = "promotion.promote_class"
ACTION_BROADSHEET_SUBMIT      = "broadsheet.submit"


def log_action(
    *,
    actor,
    action: str,
    target_model: str,
    target_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
    school=None,
) -> None:
    """
    Write a single AuditLog row.

    Args:
        actor:        Django User instance, or None for system-initiated events.
        action:       Dot-namespaced action string (use ACTION_* constants).
        target_model: Model class name string, e.g. "ResultRelease".
        target_id:    UUID of the affected instance (optional).
        metadata:     Arbitrary dict of contextual data (optional).
        school:       School instance.  Inferred from actor.profile.school
                      when omitted — pass explicitly for system actions or
                      when the actor has no profile.

    Returns:
        None.  Never raises.
    """
    try:
        from audit.models import AuditLog

        # Resolve school: explicit > actor profile > None.
        resolved_school = school
        if resolved_school is None and actor is not None:
            try:
                resolved_school = actor.profile.school
            except Exception:
                pass

        if resolved_school is None:
            logger.warning(
                "log_action: could not resolve school for action=%s target=%s(%s) — skipping",
                action,
                target_model,
                target_id,
            )
            return

        AuditLog.objects.create(
            school=resolved_school,
            actor=actor,
            action=action,
            target_model=target_model,
            target_id=target_id,
            metadata=metadata,
        )

    except Exception as exc:
        logger.warning(
            "log_action: failed to write audit log for action=%s target=%s(%s): %s",
            action,
            target_model,
            target_id,
            exc,
        )
