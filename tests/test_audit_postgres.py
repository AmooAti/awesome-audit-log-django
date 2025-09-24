import pytest
from django.db import connections
from django.test import TransactionTestCase, override_settings

from tests.conftest import fetch_logs_for
from tests.settings import AWESOME_AUDIT_LOG
from tests.testapp.models import Category, Widget


psycopg_installed = True
try:
    import psycopg  # noqa: F401
except Exception:
    try:
        import psycopg2  # noqa: F401
    except Exception:
        psycopg_installed = False


@pytest.mark.skipif(not psycopg_installed, reason="psycopg/psycopg2 not installed")
@pytest.mark.django_db(databases=["postgres", "postgres_with_different_schema"])
@override_settings(
    AWESOME_AUDIT_LOG={**AWESOME_AUDIT_LOG, "DATABASE_ALIAS": "postgres"}
)
class TestAuditPostgreSQL(TransactionTestCase):
    reset_sequences = True
    databases = ["default", "postgres", "postgres_with_different_schema"]

    def test_log_table_created_and_has_insert_row(self):
        conn = connections["postgres"]
        with conn.cursor() as c:
            c.execute("SELECT to_regclass(%s);", ["public.widget_log"])
            self.assertIsNone(
                c.fetchone()[0], "widget_log should NOT exist before creating a Widget"
            )

        w = Widget.objects.create(name="H", qty=1)

        # Now the log table must exist
        with conn.cursor() as c:
            c.execute("SELECT to_regclass(%s);", ["public.widget_log"])
            self.assertIsNotNone(
                c.fetchone()[0], "widget_log should exist after creating a Widget"
            )

            c.execute(
                "SELECT COUNT(*) FROM public.widget_log WHERE action = %s AND object_pk = %s;",
                ["insert", str(w.pk)],
            )
            self.assertEqual(c.fetchone()[0], 1)

        logs = fetch_logs_for("widget")
        self.assertTrue(len(logs) >= 1)
        last = logs[0]
        self.assertEqual(last["action"], "insert")
        self.assertEqual(last["object_pk"], str(w.pk))
        self.assertIn("qty", last["after"])
        self.assertEqual(last["after"]["qty"], 1)

    def test_update_and_delete_logged(self):
        w = Widget.objects.create(name="B", qty=2)
        w.qty = 5
        w.save()
        pk = w.pk
        w.delete()

        logs = fetch_logs_for("widget")
        # Expect at least 3 rows: insert, update, delete
        actions = [r["action"] for r in logs]
        self.assertIn("insert", actions)
        self.assertIn("update", actions)
        self.assertIn("delete", actions)

        # Update
        update_rows = [
            r for r in logs if r["action"] == "update" and r["object_pk"] == str(pk)
        ]
        self.assertTrue(update_rows)
        diff = update_rows[0]["changes"]
        self.assertIn("qty", diff)
        self.assertEqual(diff["qty"]["from"], 2)
        self.assertEqual(diff["qty"]["to"], 5)

        # Delete
        del_rows = [
            r for r in logs if r["action"] == "delete" and r["object_pk"] == str(pk)
        ]
        self.assertTrue(del_rows)
        self.assertIsNone(del_rows[0]["after"])
        self.assertEqual(del_rows[0]["before"]["name"], "B")
        self.assertEqual(del_rows[0]["before"]["qty"], 5)

    def test_only_updated_fields_are_logged(self):
        w = Widget.objects.create(name="F", qty=2)
        w.qty = 5
        w.save()
        pk = w.pk

        logs = fetch_logs_for("widget")
        update_rows = [
            r for r in logs if r["action"] == "update" and r["object_pk"] == str(pk)
        ]
        self.assertIn("qty", update_rows[0]["changes"])
        self.assertNotIn("name", update_rows[0]["changes"])

    @override_settings(
        AWESOME_AUDIT_LOG={
            **AWESOME_AUDIT_LOG,
            "AUDIT_MODELS": ["tests_testapp.category"],
        }
    )
    def test_only_selected_models_are_logged(self):
        widget = Widget.objects.create(name="C", qty=2)
        category = Category.objects.create(name="B")

        widget_logs = fetch_logs_for("widget")
        widget_logs = [
            r
            for r in widget_logs
            if r["action"] == "insert" and r["object_pk"] == str(widget.pk)
        ]

        category_logs = fetch_logs_for(Category._meta.db_table)

        category_logs = [
            r
            for r in category_logs
            if r["action"] == "insert" and r["object_pk"] == str(category.pk)
        ]
        self.assertEqual(len(widget_logs), 0)
        self.assertEqual(len(category_logs), 1)

    @override_settings(
        AWESOME_AUDIT_LOG={
            **AWESOME_AUDIT_LOG,
            "NOT_AUDIT_MODELS": ["tests_testapp.widget"],
        }
    )
    def test_opt_out_models_not_logged(self):
        widget = Widget.objects.create(name="C", qty=2)
        widget_logs = fetch_logs_for("widget")
        widget_logs = [
            r
            for r in widget_logs
            if r["action"] == "insert" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(widget_logs), 0)

    @override_settings(
        AWESOME_AUDIT_LOG={
            **AWESOME_AUDIT_LOG,
            "DATABASE_ALIAS": "postgres_with_different_schema",
            "PG_SCHEMA": "audit_log",
        }
    )
    def test_logs_recorded_on_different_schema(self):
        conn = connections["postgres_with_different_schema"]

        with conn.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS audit_log;")

        # Verify the schema exists and the log table doesn't exist yet
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'audit_log' AND table_name = 'widget_log');"
            )
            self.assertFalse(
                cursor.fetchone()[0],
                "widget_log should NOT exist in audit_log schema before creating a Widget",
            )

        widget = Widget.objects.create(
            name="postgres_with_different_schema_widget", qty=2
        )

        widget_logs = fetch_logs_for("widget")
        widget_logs = [
            w
            for w in widget_logs
            if w["action"] == "insert" and w["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(widget_logs), 1)
        self.assertEqual(
            widget_logs[0]["after"]["name"], "postgres_with_different_schema_widget"
        )
        self.assertEqual(widget_logs[0]["after"]["qty"], 2)
