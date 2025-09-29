"""
Test Celery integration for async audit logging.
"""

import pytest
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from tests.fixtures.testapp.models import Widget
from awesome_audit_log.tasks import (
    CELERY_AVAILABLE,
    insert_audit_log_async,
    insert_audit_log_sync,
)
from awesome_audit_log.signals import _insert_audit_log


class CeleryIntegrationTestCase(TestCase):
    def setUp(self):
        self.model = Widget
        self.payload = {
            "action": "insert",
            "object_pk": "1",
            "before": None,
            "after": '{"id": 1, "name": "test"}',
            "changes": '{"name": {"from": null, "to": "test"}}',
        }

    def test_celery_availability_detection(self):
        """Test that Celery availability is properly detected."""
        # This test just ensures the import doesn't fail
        # The actual availability depends on whether Celery is installed
        self.assertIsInstance(CELERY_AVAILABLE, bool)

    @override_settings(AWESOME_AUDIT_LOG={"ASYNC": True})
    @patch("awesome_audit_log.signals.insert_audit_log_async")
    @patch("awesome_audit_log.signals.insert_audit_log_sync")
    def test_async_logging_when_enabled_and_celery_available(
        self, mock_sync, mock_async
    ):
        """Test that async logging is used when enabled and Celery is available."""
        mock_async.delay = MagicMock()

        with patch("awesome_audit_log.signals.CELERY_AVAILABLE", True):
            _insert_audit_log(self.model, self.payload)
            # Check that async was called and sync was not
            mock_async.delay.assert_called_once_with(
                "tests_testapp.widget", self.payload
            )
            mock_sync.assert_not_called()

    @override_settings(AWESOME_AUDIT_LOG={"ASYNC": False})
    @patch("awesome_audit_log.signals.insert_audit_log_async")
    @patch("awesome_audit_log.signals.insert_audit_log_sync")
    def test_sync_logging_when_async_disabled(self, mock_sync, mock_async):
        """Test that sync logging is used when async is disabled."""
        _insert_audit_log(self.model, self.payload)
        mock_sync.assert_called_once_with(self.model, self.payload)
        mock_async.delay.assert_not_called()

    @override_settings(AWESOME_AUDIT_LOG={"ASYNC": True})
    @patch("awesome_audit_log.signals.insert_audit_log_async")
    @patch("awesome_audit_log.signals.insert_audit_log_sync")
    def test_sync_logging_when_celery_unavailable(self, mock_sync, mock_async):
        """Test that sync logging is used when Celery is not available."""
        with patch("awesome_audit_log.signals.CELERY_AVAILABLE", False):
            _insert_audit_log(self.model, self.payload)
            mock_sync.assert_called_once_with(self.model, self.payload)
            mock_async.delay.assert_not_called()

    @patch("awesome_audit_log.db.AuditDatabaseManager")
    def test_insert_audit_log_sync(self, mock_audit_manager):
        """Test synchronous audit log insertion."""
        mock_instance = MagicMock()
        mock_audit_manager.return_value = mock_instance

        insert_audit_log_sync(self.model, self.payload)

        mock_audit_manager.assert_called_once()
        mock_instance.insert_log_row.assert_called_once_with(self.model, self.payload)

    @patch("awesome_audit_log.tasks.apps.get_model")
    @patch("awesome_audit_log.db.AuditDatabaseManager")
    def test_insert_audit_log_async_success(self, mock_audit_manager, mock_get_model):
        """Test successful asynchronous audit log insertion."""
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_instance = MagicMock()
        mock_audit_manager.return_value = mock_instance

        mock_task = MagicMock()
        mock_task.request.retries = 0

        insert_audit_log_async(mock_task, "tests_testapp.widget", self.payload)

        mock_get_model.assert_called_once_with("tests_testapp", "widget")
        mock_audit_manager.assert_called_once()
        mock_instance.insert_log_row.assert_called_once_with(mock_model, self.payload)

    @patch("awesome_audit_log.tasks.apps.get_model")
    @patch("awesome_audit_log.db.AuditDatabaseManager")
    def test_insert_audit_log_async_retry_on_failure(
        self, mock_audit_manager, mock_get_model
    ):
        """Test that async task retries on failure."""
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_instance = MagicMock()
        mock_audit_manager.return_value = mock_instance

        mock_instance.insert_log_row.side_effect = Exception("Database error")

        mock_task = MagicMock()
        mock_task.request.retries = 0

        with pytest.raises(Exception):
            insert_audit_log_async(mock_task, "tests_testapp.widget", self.payload)

        mock_task.retry.assert_called_once()

    @patch("awesome_audit_log.tasks.apps.get_model")
    def test_insert_audit_log_async_invalid_model_path(self, mock_get_model):
        """Test that async task handles invalid model paths gracefully."""
        mock_get_model.side_effect = Exception("Model not found")

        mock_task = MagicMock()
        mock_task.request.retries = 0

        with pytest.raises(Exception):
            insert_audit_log_async(mock_task, "invalid.Model", self.payload)

        mock_task.retry.assert_called_once()

    @override_settings(AWESOME_AUDIT_LOG={"ASYNC": True})
    @patch("awesome_audit_log.signals.insert_audit_log_async")
    def test_async_logging_with_real_model_operations(self, mock_async):
        """Test async logging with actual model operations."""
        mock_async.delay = MagicMock()

        with patch("awesome_audit_log.signals.CELERY_AVAILABLE", True):
            widget = Widget.objects.create(name="Test Widget", qty=10)

            widget.name = "Updated Widget"
            widget.save()

            widget.delete()

            self.assertEqual(mock_async.delay.call_count, 3)
