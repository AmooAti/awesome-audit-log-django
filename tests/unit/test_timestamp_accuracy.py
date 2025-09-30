from datetime import datetime, timezone
from unittest.mock import patch
from django.test import TestCase, override_settings

from tests.fixtures.testapp.models import Widget
from tests.config.settings import AWESOME_AUDIT_LOG


class TimestampAccuracyTestCase(TestCase):
    def test_timestamp_is_included_in_payload(self):
        with patch(
            "awesome_audit_log.signals.insert_audit_log_sync"
        ) as mock_insert_sync:
            Widget.objects.create(name="Test Widget", qty=10)

            mock_insert_sync.assert_called_once()
            call_args = mock_insert_sync.call_args

            payload = call_args[0][1]

            self.assertIn("created_at", payload)

            try:
                timestamp = datetime.fromisoformat(payload["created_at"])
                now = datetime.now(timezone.utc)
                time_diff = abs((now - timestamp).total_seconds())
                self.assertLess(
                    time_diff,
                    5,
                    "Timestamp should be within 5 seconds of current time",
                )
            except ValueError:
                self.fail(
                    f"created_at is not a valid ISO timestamp: {payload['created_at']}"
                )

    def test_timestamp_captured_at_event_time_not_later(self):
        from unittest.mock import MagicMock

        before_event = datetime.now(timezone.utc)

        with patch(
            "awesome_audit_log.signals.insert_audit_log_async"
        ) as mock_insert_async:
            mock_insert_async.delay = MagicMock()

            with patch("awesome_audit_log.signals.CELERY_AVAILABLE", True):
                with override_settings(
                    AWESOME_AUDIT_LOG={**AWESOME_AUDIT_LOG, "ASYNC": True}
                ):
                    Widget.objects.create(name="Async Widget", qty=5)

                    call_args = mock_insert_async.delay.call_args
                    payload = call_args[0][1]

                    self.assertIn("created_at", payload)
                    event_timestamp = datetime.fromisoformat(payload["created_at"])

                    after_event = datetime.now(timezone.utc)

                    self.assertGreaterEqual(event_timestamp, before_event)
                    self.assertLessEqual(event_timestamp, after_event)

                    time_diff = (after_event - event_timestamp).total_seconds()
                    self.assertLess(
                        time_diff,
                        1,
                        "Timestamp should be captured immediately at event time",
                    )

    def test_all_actions_include_timestamp(self):
        with patch(
            "awesome_audit_log.signals.insert_audit_log_sync"
        ) as mock_insert_sync:
            widget = Widget.objects.create(name="Widget", qty=1)
            insert_payload = mock_insert_sync.call_args[0][1]
            self.assertIn("created_at", insert_payload)
            self.assertEqual(insert_payload["action"], "insert")

            widget.qty = 2
            widget.save()
            update_payload = mock_insert_sync.call_args[0][1]
            self.assertIn("created_at", update_payload)
            self.assertEqual(update_payload["action"], "update")

            widget.delete()
            delete_payload = mock_insert_sync.call_args[0][1]
            self.assertIn("created_at", delete_payload)
            self.assertEqual(delete_payload["action"], "delete")

            self.assertEqual(mock_insert_sync.call_count, 3)
