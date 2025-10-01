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
                if k not in ignored_keys and v is not None and v and v != ""
            }

            if not relevant_options:
                return None

            args_list = [f"{k}={v}" for k, v in relevant_options.items()]
            return " ".join(args_list)

        BaseCommand.execute = execute_with_audit


class ImproperlyConfiguredAuditDB(Exception):
    pass
