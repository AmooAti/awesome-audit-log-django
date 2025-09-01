import json

from conftest import fetch_logs_for
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase

User = get_user_model()

class TestHttpContext(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="u1", password="x")

    def test_http_context_captured_on_create(self):
        self.client.login(username="u1", password="x")
        resp = self.client.post(
            "/api/widgets/create/",
            data=json.dumps({"name": "C", "qty": 7}),
            content_type="application/json",
            HTTP_USER_AGENT="pytest-agent",
        )
        self.assertEqual(resp.status_code, 200)

        logs = fetch_logs_for("widget")
        self.assertTrue(logs)
        row = logs[0]
        self.assertEqual(row["action"], "insert")
        self.assertEqual(row["path"], "/api/widgets/create/")
        self.assertEqual(row["method"], "POST")
        self.assertEqual(row["route"], "api_widgets_create")
        self.assertEqual(row["user_name"], "u1")
        self.assertIsNotNone(row["user_id"])
        self.assertEqual(row["user_agent"], "pytest-agent")
        self.assertEqual(row["entry_point"], "http")
