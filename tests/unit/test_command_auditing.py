import os

from django.core.management.base import BaseCommand
from django.db import connection
from django.test import TestCase, TransactionTestCase

from awesome_audit_log.context import get_request_ctx
from tests.fixtures.testapp.models import Widget


class TestCommandContext(TestCase):
    """Test that command execution context is properly set and cleared."""

    def test_context_set_during_execution(self):
        """Test that context is set during command execution and cleared after."""
        context_during_execution = None

        class TestCommand(BaseCommand):
            def handle(self, *args, **options):
                nonlocal context_during_execution
                context_during_execution = get_request_ctx()

        cmd = TestCommand()
        cmd.execute()

        self.assertIsNotNone(context_during_execution)
        self.assertEqual(context_during_execution.entry_point, "management_command")

        self.assertIsNone(get_request_ctx())

    def test_context_cleared_on_exception(self):
        """Test that context is cleared even when command raises an exception."""

        class TestCommand(BaseCommand):
            def handle(self, *args, **options):
                raise ValueError("Test error")

        cmd = TestCommand()

        with self.assertRaises(ValueError):
            cmd.execute()

        self.assertIsNone(get_request_ctx())

    def test_context_includes_command_name(self):
        """Test that context includes command name, route, and method."""
        context_during_execution = None

        class TestCommand(BaseCommand):
            def handle(self, *args, **options):
                nonlocal context_during_execution
                context_during_execution = get_request_ctx()

        cmd = TestCommand()
        cmd.execute()

        self.assertIsNotNone(context_during_execution.path)
        self.assertIsNotNone(context_during_execution.route)
        self.assertEqual(context_during_execution.method, "execute")

    def test_context_includes_command_args(self):
        """Test that context includes command arguments while filtering system options."""
        context_during_execution = None

        class TestCommand(BaseCommand):
            def add_arguments(self, parser):
                parser.add_argument("--my-option", type=str)
                parser.add_argument("--flag", action="store_true")

            def handle(self, *args, **options):
                nonlocal context_during_execution
                context_during_execution = get_request_ctx()

        cmd = TestCommand()
        cmd.execute(my_option="test_value", flag=True, verbosity=1)

        self.assertIsNotNone(context_during_execution.user_agent)
        self.assertIn("my_option=test_value", context_during_execution.user_agent)
        self.assertIn("flag=True", context_during_execution.user_agent)
        self.assertNotIn("verbosity", context_during_execution.user_agent)

    def test_context_includes_system_user(self):
        """Test that context includes system user from environment variables."""
        context_during_execution = None

        class TestCommand(BaseCommand):
            def handle(self, *args, **options):
                nonlocal context_during_execution
                context_during_execution = get_request_ctx()

        cmd = TestCommand()
        cmd.execute()

        self.assertIsNotNone(context_during_execution)
        self.assertTrue(hasattr(context_during_execution, "user_name"))

        # Verify user_name is populated if environment variables are available
        if os.getenv("USER") or os.getenv("USERNAME"):
            self.assertIsNotNone(context_during_execution.user_name)


class TestCommandAuditing(TransactionTestCase):
    """Test that database changes from commands are automatically audited."""

    def setUp(self):
        """Clean up audit log tables before each test."""
        super().setUp()
        from tests.config.conftest import LOG_TABLE_REGEX

        with connection.cursor() as c:
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in c.fetchall()]
            for table in tables:
                if LOG_TABLE_REGEX.fullmatch(table):
                    c.execute(f"DROP TABLE IF EXISTS {table}")

    def _get_audit_log(self, object_pk, action=None):
        """Helper method to retrieve audit log entries."""
        query = "SELECT entry_point, action FROM widget_log WHERE object_pk = ?"
        params = [str(object_pk)]

        if action:
            query += " AND action = ?"
            params.append(action)

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def test_command_db_changes_are_audited(self):
        """Test that INSERT operations from commands are audited with full context."""

        class CreateWidgetCommand(BaseCommand):
            help = "Create a test widget"

            def add_arguments(self, parser):
                parser.add_argument("--name", type=str, default="test")

            def handle(self, *args, **options):
                Widget.objects.create(name=options["name"])

        cmd = CreateWidgetCommand()
        cmd.execute(name="command_widget")

        widget = Widget.objects.get(name="command_widget")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT entry_point, path, route, user_agent, action "
                "FROM widget_log WHERE object_pk = ?",
                [str(widget.pk)],
            )
            result = cursor.fetchone()

        self.assertIsNotNone(result)
        entry_point, path, route, user_agent, action = result

        self.assertEqual(entry_point, "management_command")
        self.assertIsNotNone(path)
        self.assertIsNotNone(route)
        self.assertIn("name=command_widget", user_agent or "")
        self.assertEqual(action, "insert")

    def test_command_update_is_audited(self):
        """Test that UPDATE operations from commands are audited with context."""
        widget = Widget.objects.create(name="original")

        class UpdateWidgetCommand(BaseCommand):
            def handle(self, *args, **options):
                w = Widget.objects.get(name="original")
                w.name = "updated_by_command"
                w.save()

        UpdateWidgetCommand().execute()

        result = self._get_audit_log(widget.pk, "update")
        self.assertIsNotNone(result)

        entry_point, action = result
        self.assertEqual(entry_point, "management_command")
        self.assertEqual(action, "update")

    def test_command_delete_is_audited(self):
        """Test that DELETE operations from commands are audited with context."""
        widget = Widget.objects.create(name="to_delete")
        widget_pk = widget.pk

        class DeleteWidgetCommand(BaseCommand):
            def handle(self, *args, **options):
                Widget.objects.get(name="to_delete").delete()

        DeleteWidgetCommand().execute()

        result = self._get_audit_log(widget_pk, "delete")
        self.assertIsNotNone(result)

        entry_point, action = result
        self.assertEqual(entry_point, "management_command")
        self.assertEqual(action, "delete")
