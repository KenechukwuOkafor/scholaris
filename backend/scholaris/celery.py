"""
Celery application for Scholaris.

Workers are started with:
    celery -A scholaris worker -l info
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scholaris.settings.dev")

app = Celery("scholaris")

# Read configuration from Django settings using the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all installed INSTALLED_APPS.
app.autodiscover_tasks()
