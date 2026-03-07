"""
Celery tasks for the notifications app.
"""

from celery import shared_task


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,          # 60 s between retries
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,           # cap at 10 minutes
    name="notifications.send_whatsapp_message",
)
def send_whatsapp_message_task(self, message_id: str) -> dict:
    """
    Celery task: deliver a single WhatsAppMessage via the provider API.

    Args:
        message_id: UUID string of the WhatsAppMessage row to deliver.

    Returns:
        {"status": "sent"|"failed", "message_id": str}
    """
    from notifications.services.whatsapp_service import send_whatsapp_message

    result = send_whatsapp_message(message_id)
    return result
