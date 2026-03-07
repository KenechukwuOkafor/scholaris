"""
WhatsAppService — queue and deliver WhatsApp broadcast messages.

Provider: Meta WhatsApp Cloud API
  POST https://graph.facebook.com/{version}/{phone_number_id}/messages

Configuration (settings):
    WHATSAPP_PHONE_NUMBER_ID  — Meta dashboard phone number ID
    WHATSAPP_ACCESS_TOKEN     — system user access token
    WHATSAPP_API_URL          — fully resolved endpoint (built in base.py)

Phone numbers must be in E.164 format: +2348012345678
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from core.models import SchoolClass, Term
from enrollment.models import Student, StudentParent
from notifications.models import WhatsAppMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message composer
# ---------------------------------------------------------------------------


def _compose_message(student: Student, term: Term) -> str:
    """
    Build the WhatsApp message body for a result broadcast.

    The text is intentionally concise — WhatsApp messages should be short
    and actionable.
    """
    return (
        f"Dear Parent,\n\n"
        f"The {term.name} results for *{student.first_name} {student.last_name}* "
        f"({student.registration_number}) have been published.\n\n"
        f"Please log in to the school portal to view the full report card.\n\n"
        f"— {student.school.name}"
    )


# ---------------------------------------------------------------------------
# queue_result_broadcast
# ---------------------------------------------------------------------------


def queue_result_broadcast(school_class: SchoolClass, term: Term) -> dict[str, int]:
    """
    Create WhatsAppMessage rows for every parent of every student in
    *school_class* for *term*, then queue a Celery delivery task per message.

    Steps:
        1. Fetch all active students in the class.
        2. For each student, fetch their linked parents (via StudentParent).
        3. Skip parents with no phone number.
        4. Create (or skip existing) WhatsAppMessage rows — idempotent:
           re-broadcasting the same class/term will not duplicate rows.
        5. Enqueue send_whatsapp_message_task for each newly created row.

    Args:
        school_class: the class whose results are being broadcast.
        term:         the term whose results are being broadcast.

    Returns:
        {
            "queued":   int,   # new messages enqueued
            "skipped":  int,   # existing messages or no-phone parents
        }
    """
    from notifications.tasks import send_whatsapp_message_task

    school = school_class.school
    students = Student.objects.for_school(school).filter(
        student_class=school_class,
        status=Student.Status.ACTIVE,
    ).prefetch_related("student_parents__parent")

    queued = 0
    skipped = 0

    for student in students:
        for sp in student.student_parents.select_related("parent"):
            parent = sp.parent

            phone = (parent.phone or "").strip()
            if not phone:
                skipped += 1
                continue

            message_text = _compose_message(student, term)

            # Idempotent: skip if a message for this (parent, student, term) exists.
            wa_msg, created = WhatsAppMessage.objects.get_or_create(
                school=school,
                parent=parent,
                student=student,
                term=term,
                defaults={
                    "phone": phone,
                    "message": message_text,
                    "status": WhatsAppMessage.Status.PENDING,
                },
            )

            if not created:
                skipped += 1
                continue

            # Enqueue the Celery delivery task.
            send_whatsapp_message_task.delay(str(wa_msg.id))
            queued += 1

    logger.info(
        "queue_result_broadcast: class=%s term=%s queued=%d skipped=%d",
        school_class,
        term,
        queued,
        skipped,
    )

    return {"queued": queued, "skipped": skipped}


# ---------------------------------------------------------------------------
# send_whatsapp_message
# ---------------------------------------------------------------------------


def send_whatsapp_message(message_id: str) -> dict[str, Any]:
    """
    Deliver a single WhatsAppMessage via the Meta WhatsApp Cloud API.

    Fetches the WhatsAppMessage row by *message_id*, POSTs the message to
    the API, then updates status to "sent" or "failed".

    Args:
        message_id: UUID string of a WhatsAppMessage.

    Returns:
        {"status": "sent"|"failed", "message_id": str}
    """
    try:
        wa_msg = WhatsAppMessage.objects.select_related(
            "school", "student", "parent", "term"
        ).get(id=message_id)
    except WhatsAppMessage.DoesNotExist:
        logger.error("send_whatsapp_message: message %s not found", message_id)
        return {"status": "failed", "message_id": message_id}

    payload = _build_api_payload(wa_msg.phone, wa_msg.message)
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            settings.WHATSAPP_API_URL,
            json=payload,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()

        wa_msg.status = WhatsAppMessage.Status.SENT
        wa_msg.sent_at = timezone.now()
        wa_msg.save(update_fields=["status", "sent_at", "updated_at"])

        logger.info(
            "send_whatsapp_message: sent id=%s phone=%s",
            message_id,
            wa_msg.phone,
        )
        return {"status": "sent", "message_id": message_id}

    except requests.RequestException as exc:
        wa_msg.status = WhatsAppMessage.Status.FAILED
        wa_msg.save(update_fields=["status", "updated_at"])

        logger.error(
            "send_whatsapp_message: failed id=%s phone=%s error=%s",
            message_id,
            wa_msg.phone,
            exc,
        )
        return {"status": "failed", "message_id": message_id}


# ---------------------------------------------------------------------------
# API payload builder
# ---------------------------------------------------------------------------


def _build_api_payload(phone: str, message_text: str) -> dict[str, Any]:
    """
    Build the JSON payload for the Meta WhatsApp Cloud API.

    Uses the "text" message type (free-form text).  For template-based
    messages (required outside the 24-hour service window), replace the
    "type" key with "template" and add the appropriate template fields.

    Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/text-messages
    """
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_text,
        },
    }
