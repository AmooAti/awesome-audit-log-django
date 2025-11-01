from django.apps import AppConfig

from awesome_audit_log.conf import get_setting


class AwesomeAuditLogConfig(AppConfig):
    name = "awesome_audit_log"
    label = "awesome_audit_log"
    verbose_name = "Awesome Audit Log"

    def ready(self):
        if get_setting("ENABLED"):
            from . import signals  # noqa: F401

            if get_setting("CAPTURE_COMMANDS"):
                self._setup_command_auditing()

            if get_setting("CAPTURE_CELERY"):
                self._setup_celery_auditing()

    def _setup_command_auditing(self):
        """
        Wrap Django's BaseCommand.execute() to capture context.
        """
        from django.core.management.base import BaseCommand
        from awesome_audit_log.context import (
            RequestContext,
            clear_request_ctx,
            set_request_ctx,
        )
        import os

        original_execute = BaseCommand.execute

        def execute_with_audit(self, *args, **options):
            try:
                default_options = {
                    "verbosity": 1,
                    "settings": None,
                    "pythonpath": None,
                    "traceback": False,
                    "no_color": False,
                    "force_color": False,
                    "skip_checks": False,
                }
                merged_options = {**default_options, **options}

                command_name = self.__class__.__module__.split(".")[-1]
                if command_name == "commands":
                    command_name = self.__class__.__name__.lower().replace(
                        "command", ""
                    )

                command_args = _format_command_args(merged_options)

                set_request_ctx(
                    RequestContext(
                        entry_point="management_command",
                        path=command_name,
                        route=f"{self.__class__.__module__}.{self.__class__.__name__}",
                        method="execute",
                        ip=None,
                        user_id=None,
                        user_name=os.getenv("USER") or os.getenv("USERNAME"),
                        user_agent=command_args,
                    )
                )

                return original_execute(self, *args, **merged_options)
            finally:
                clear_request_ctx()

        def _format_command_args(options):
            """Format command arguments for logging."""
            ignored_keys = {
                "settings",
                "pythonpath",
                "traceback",
                "no_color",
                "force_color",
                "skip_checks",
                "verbosity",
            }

            relevant_options = {
                k: v
                for k, v in options.items()
                if k not in ignored_keys and v is not None
            }

            if not relevant_options:
                return None

            args_list = [f"{k}={v}" for k, v in relevant_options.items()]
            return " ".join(args_list)

        BaseCommand.execute = execute_with_audit

    def _setup_celery_auditing(self):
        """
        Wrap Celery's task execution to capture context using signals.
        Signals are only fired in worker processes, not when calling task.run() directly.
        """
        try:
            from celery import signals
        except ImportError:
            return

        from awesome_audit_log.context import (
            RequestContext,
            clear_request_ctx,
            set_request_ctx,
        )
        import os

        def get_task_context(task):
            task_name = getattr(task, "name", None) or getattr(task, "__name__", None)
            task_module = getattr(task, "__module__", None)

            task_info = f"task={task_name}"
            if task_module:
                task_info = f"{task_info} module={task_module}"

            return RequestContext(
                entry_point="celery_task",
                path=task_name.split(".")[-1] if task_name else None,
                route=task_name,
                method="run",
                ip=None,
                user_id=None,
                user_name=os.getenv("USER") or os.getenv("USERNAME"),
                user_agent=task_info,
            )

        @signals.task_prerun.connect
        def task_prerun_handler(
            sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds
        ):
            if (
                hasattr(task, "name")
                and task.name
                and "insert_audit_log_async" in task.name
            ):
                return
            set_request_ctx(get_task_context(task))

        @signals.task_postrun.connect
        def task_postrun_handler(
            sender=None,
            task_id=None,
            task=None,
            args=None,
            kwargs=None,
            retval=None,
            state=None,
            **kwds,
        ):
            clear_request_ctx()

        self._celery_handlers = (task_prerun_handler, task_postrun_handler)


class ImproperlyConfiguredAuditDB(Exception):
    pass
