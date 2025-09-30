"""
Test the migrate_audit_timestamps management command.
"""

from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.test import TestCase, override_settings

from tests.config.settings import AWESOME_AUDIT_LOG


class MigrationCommandTestCase(TestCase):
    """Test the migrate_audit_timestamps management command."""

    def test_command_help(self):
        """Test that the command help is displayed correctly."""
        from awesome_audit_log.management.commands.migrate_audit_timestamps import (
            Command,
        )

        self.assertEqual(
            Command.help,
            "Migrate audit log tables to fix timestamp accuracy for async logging",
        )

        command = Command()
        parser = command.create_parser("test", "migrate_audit_timestamps")

        actions = [action.dest for action in parser._actions]
        self.assertIn("dry_run", actions)
        self.assertIn("force", actions)
        self.assertIn("database", actions)

    @override_settings(
        AWESOME_AUDIT_LOG={**AWESOME_AUDIT_LOG, "DATABASE_ALIAS": "default"}
    )
    @patch("awesome_audit_log.management.commands.migrate_audit_timestamps.connections")
    def test_dry_run_mode(self, mock_connections):
        """Test dry run mode of the migration command."""
        mock_connection = MagicMock()
        mock_connection.vendor = "sqlite"
        mock_connection.settings_dict = {"NAME": "test_db"}
        mock_connections.__getitem__.return_value = mock_connection

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("test_model_log",)]
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        out = StringIO()
        call_command("migrate_audit_timestamps", "--dry-run", stdout=out)
        output = out.getvalue()

        self.assertIn("DRY RUN MODE - No changes will be made", output)
        self.assertIn("Found 1 audit log tables", output)
        self.assertIn("test_model_log", output)
        self.assertIn("DRY RUN: Would migrate 1 tables", output)

    @override_settings(
        AWESOME_AUDIT_LOG={**AWESOME_AUDIT_LOG, "DATABASE_ALIAS": "default"}
    )
    @patch("awesome_audit_log.management.commands.migrate_audit_timestamps.connections")
    def test_no_audit_tables_found(self, mock_connections):
        """Test when no audit tables are found."""
        mock_connection = MagicMock()
        mock_connection.vendor = "sqlite"
        mock_connection.settings_dict = {"NAME": "test_db"}
        mock_connections.__getitem__.return_value = mock_connection

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []  # No tables found
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        out = StringIO()
        call_command("migrate_audit_timestamps", "--dry-run", stdout=out)
        output = out.getvalue()

        self.assertIn("No audit log tables found to migrate", output)

    @override_settings(
        AWESOME_AUDIT_LOG={
            **AWESOME_AUDIT_LOG,
            "DATABASE_ALIAS": "nonexistent",
            "FALLBACK_TO_DEFAULT": True,
        }
    )
    @patch("awesome_audit_log.management.commands.migrate_audit_timestamps.connections")
    def test_database_not_found_with_fallback(self, mock_connections):
        """Test fallback to default database when specified database not found."""
        from django.db.utils import ConnectionDoesNotExist

        def mock_getitem(key):
            if key == "nonexistent":
                raise ConnectionDoesNotExist("Database 'nonexistent' not found")
            elif key == "default":
                mock_connection = MagicMock()
                mock_connection.vendor = "sqlite"
                mock_connection.settings_dict = {"NAME": "test_db"}
                mock_cursor = MagicMock()
                mock_cursor.fetchall.return_value = []
                mock_connection.cursor.return_value.__enter__.return_value = mock_cursor
                return mock_connection
            else:
                raise ConnectionDoesNotExist(f"Database '{key}' not found")

        mock_connections.__getitem__.side_effect = mock_getitem

        out = StringIO()
        call_command("migrate_audit_timestamps", "--dry-run", stdout=out)
        output = out.getvalue()

        self.assertIn(
            "Database 'nonexistent' not found, falling back to 'default'", output
        )

    @override_settings(
        AWESOME_AUDIT_LOG={
            **AWESOME_AUDIT_LOG,
            "DATABASE_ALIAS": "nonexistent",
            "FALLBACK_TO_DEFAULT": False,
        }
    )
    @patch("awesome_audit_log.management.commands.migrate_audit_timestamps.connections")
    def test_database_not_found_without_fallback(self, mock_connections):
        """Test error when database not found and no fallback configured."""
        from django.db.utils import ConnectionDoesNotExist
        from django.core.management.base import CommandError

        mock_connections.__getitem__.side_effect = ConnectionDoesNotExist(
            "Database 'nonexistent' not found"
        )

        with self.assertRaises(CommandError):
            call_command("migrate_audit_timestamps", "--dry-run")
