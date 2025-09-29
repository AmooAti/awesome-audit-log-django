"""
Celery tasks for async audit logging.
"""

import logging
from typing import Any, Dict

from django.apps import apps
from django.db import models

logger = logging.getLogger(__name__)

try:
    from celery import shared_task  # type: ignore

    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

    # Create a dummy decorator for when Celery is not available
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func

        return decorator


@shared_task(bind=True, max_retries=3)
def insert_audit_log_async(self, model_path: str, payload: Dict[str, Any]) -> None:
    """
    Async task to insert audit log entry.

    Args:
        model_path: Full model path (e.g., 'app_label.ModelName')
        payload: Audit log data dictionary
    """
    try:
        # Get the model class from the path
        app_label, model_name = model_path.split(".")
        model_class = apps.get_model(app_label, model_name)

        # Import here to avoid circular imports
        from awesome_audit_log.db import AuditDatabaseManager

        audit_manager = AuditDatabaseManager()
        audit_manager.insert_log_row(model_class, payload)

        logger.debug(f"Successfully inserted audit log for {model_path}")

    except Exception as exc:
        logger.error(f"Failed to insert audit log for {model_path}: {exc}")
        # Retry the task with exponential backoff
        raise self.retry(countdown=60 * (2**self.request.retries), exc=exc)


def insert_audit_log_sync(model: models.Model, payload: Dict[str, Any]) -> None:
    """
    Synchronous audit log insertion (fallback when Celery is not available).

    Args:
        model: Django model instance
        payload: Audit log data dictionary
    """
    from awesome_audit_log.db import AuditDatabaseManager

    audit_manager = AuditDatabaseManager()
    audit_manager.insert_log_row(model, payload)
