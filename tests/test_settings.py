from django.test import TestCase, override_settings

from awesome_audit_log.db import (
    AuditDBIsNotAvailable,
    AuditDatabaseManager,
    SQLiteDatabaseVendor,
)
from tests.testapp.models import Widget
from pytest import raises

from conftest import fetch_logs_for


class TestSettings(TestCase):
    @override_settings(
        AWESOME_AUDIT_LOG={
            "RAISE_ERROR_IF_DB_UNAVAILABLE": True,
            "DATABASE_ALIAS": "wrong",
        }
    )
    def test_raise_exception_when_db_alias_is_wrong(self):
        with raises(AuditDBIsNotAvailable):
            Widget.objects.create(name="Z", qty=9)

    @override_settings(
        AWESOME_AUDIT_LOG={"FALLBACK_TO_DEFAULT": True, "DATABASE_ALIAS": "wrong"}
    )
    def test_switch_to_when_default_is_wrong(self):
        _audit_database_manager = AuditDatabaseManager()
        _audit_database_manager._get_connection()
        self.assertIsNotNone(_audit_database_manager._connection)
        self.assertIsInstance(_audit_database_manager._vendor, SQLiteDatabaseVendor)

    @override_settings(
        AWESOME_AUDIT_LOG={
            "ENABLED": False,
        }
    )
    def test_not_logging_when_audit_log_disabled(self):
        widget = Widget.objects.create(name="C", qty=2)
        widget_logs = fetch_logs_for("widget")
        widget_logs = [
            r
            for r in widget_logs
            if r["action"] == "insert" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(widget_logs), 0)
