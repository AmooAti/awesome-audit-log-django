from django.test import TestCase, override_settings

from awesome_audit_log.db import AuditDBIsNotAvailable
from tests.testapp.models import Widget
from pytest import raises

@override_settings(
    AWESOME_AUDIT_LOG={'RAISE_ERROR_IF_DB_UNAVAILABLE': True, 'DATABASE_ALIAS': 'wrong'}
)
class TestSettings(TestCase):
    def test_raise_exception_when_default_is_wrong(self):
        with raises(AuditDBIsNotAvailable):
            w = Widget.objects.create(name="Z", qty=9)

