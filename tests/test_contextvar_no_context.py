from django.test import TransactionTestCase
from tests.testapp.models import Widget
from awesome_audit_log.context import get_request_ctx

class TestContextVarWithoutRequest(TransactionTestCase):
    reset_sequences = True

    def test_no_lookuperror_when_no_request(self):
        # Ensure accessing context outside HTTP does not raise
        self.assertIsNone(get_request_ctx())
        w = Widget.objects.create(name="Z", qty=9)
        self.assertIsNotNone(w.pk)
        # No assertion needed: if it crashes, test fails
