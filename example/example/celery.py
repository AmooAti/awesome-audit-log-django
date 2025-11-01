import os
from datetime import timedelta

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

app = Celery("example")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.beat_schedule = {
    "periodic-example-task": {
        "task": "example.tasks.example_periodic_task",
        "schedule": timedelta(seconds=30),
    },
}

app.conf.timezone = "UTC"
