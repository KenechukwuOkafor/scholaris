# Make the Celery app available when Django starts so that shared_task
# decorators and periodic tasks are registered correctly.
from .celery import app as celery_app

__all__ = ("celery_app",)
