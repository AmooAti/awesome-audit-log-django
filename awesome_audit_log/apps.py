from django.apps import AppConfig

from awesome_audit_log.conf import get_setting


class AwesomeAuditLogConfig(AppConfig):
    name = "awesome_audit_log"
    label = "awesome_audit_log"
    verbose_name = "Awesome Audit Log"

    def ready(self):
        if get_setting("ENABLED"):
            from . import signals  # noqa: F401

        # Auto-register Celery tasks if async is enabled
        if get_setting("ASYNC"):
            from . import tasks  # noqa: F401


class ImproperlyConfiguredAuditDB(Exception):
    pass
