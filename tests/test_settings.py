from django.test import TestCase, override_settings

from awesome_audit_log.db import AuditDBIsNotAvailable, AuditDatabaseManager, \
    SQLiteDatabaseVendor
from tests.testapp.models import Widget
from pytest import raises


@override_settings(
    AWESOME_AUDIT_LOG={'RAISE_ERROR_IF_DB_UNAVAILABLE': True, 'DATABASE_ALIAS': 'wrong'}
)
class TestSettings(TestCase):
    def test_raise_exception_when_db_alias_is_wrong(self):
        with raises(AuditDBIsNotAvailable):
            Widget.objects.create(name="Z", qty=9)

    @override_settings(
        AWESOME_AUDIT_LOG={
            'FALLBACK_TO_DEFAULT': True,
            'DATABASE_ALIAS': 'wrong'}
    )
    def test_switch_to_when_default_is_wrong(self):
        _audit_database_manager = AuditDatabaseManager()
        _audit_database_manager._get_connection()
        self.assertIsNotNone(_audit_database_manager._connection)
        self.assertIsInstance(_audit_database_manager._vendor, SQLiteDatabaseVendor)
