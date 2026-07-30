from datetime import datetime, timezone
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from awesome_audit_log import db as audit_db
from awesome_audit_log.db import (
    AuditDatabaseManager,
    AuditDBIsNotAvailable,
    MySQlDatabaseVendor,
    PostgresDatabaseVendor,
    SQLiteDatabaseVendor,
    reset_table_cache,
)
from tests.helpers import fetch_logs_for
from tests.fixtures.testapp.models import Widget


def _drop_widget_log():
    with connection.cursor() as c:
        c.execute("DROP TABLE IF EXISTS widget_log")


def _payload(object_pk="1"):
    return {
        "action": "insert",
        "object_pk": object_pk,
        "before": None,
        "after": "{}",
        "changes": "{}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class AuditTableTestCase(TransactionTestCase):
    databases = ["default"]

    def setUp(self):
        super().setUp()
        reset_table_cache()
        _drop_widget_log()

    def tearDown(self):
        reset_table_cache()
        super().tearDown()


class TestTableCache(AuditTableTestCase):
    def test_write_path_never_probes_for_the_table(self):
        with patch.object(
            AuditDatabaseManager, "_table_exists", autospec=True
        ) as probe:
            Widget.objects.create(name="probe-a", qty=1)
            Widget.objects.create(name="probe-b", qty=2)

        probe.assert_not_called()
        self.assertEqual(len(fetch_logs_for("widget")), 2)

    def test_write_path_never_pings(self):
        with patch.object(AuditDatabaseManager, "_ping", autospec=True) as ping:
            Widget.objects.create(name="ping-a", qty=1)
            Widget.objects.create(name="ping-b", qty=2)

        ping.assert_not_called()
        self.assertEqual(len(fetch_logs_for("widget")), 2)

    def test_probe_runs_once_per_key_across_manager_instances(self):
        with patch.object(
            AuditDatabaseManager, "_table_exists", autospec=True, return_value=False
        ) as probe:
            for _ in range(3):
                AuditDatabaseManager().ensure_log_table_for_model_exist(Widget)

        self.assertEqual(probe.call_count, 1)

    def test_reset_table_cache_forces_a_recheck(self):
        with patch.object(
            AuditDatabaseManager, "_table_exists", autospec=True, return_value=True
        ) as probe:
            AuditDatabaseManager().ensure_log_table_for_model_exist(Widget)
            AuditDatabaseManager().ensure_log_table_for_model_exist(Widget)
            self.assertEqual(probe.call_count, 1)

            reset_table_cache()

            AuditDatabaseManager().ensure_log_table_for_model_exist(Widget)
            self.assertEqual(probe.call_count, 2)

    def test_reset_table_cache_clears_the_vendor_cache(self):
        AuditDatabaseManager()._get_connection()
        self.assertIn("default", audit_db._VENDOR_CACHE)

        reset_table_cache()

        self.assertEqual(audit_db._VENDOR_CACHE, {})

    def test_dropped_table_is_recovered_mid_process(self):
        Widget.objects.create(name="before-drop", qty=1)
        self.assertEqual(len(fetch_logs_for("widget")), 1)

        # Out of band and deliberately without touching the cache, exactly as a
        # DBA or a stray test fixture would do it.
        _drop_widget_log()

        widget = Widget.objects.create(name="after-drop", qty=2)

        logs = fetch_logs_for("widget")
        self.assertEqual([r["object_pk"] for r in logs], [str(widget.pk)])

    def test_batched_insert_is_replayed_whole_after_a_create(self):
        payloads = [_payload(str(i)) for i in range(3)]

        with patch.object(
            AuditDatabaseManager, "_insert_batch_size", staticmethod(lambda *a: 1)
        ):
            AuditDatabaseManager().insert_log_rows(Widget, payloads)

        logs = fetch_logs_for("widget")
        self.assertEqual(sorted(r["object_pk"] for r in logs), ["0", "1", "2"])


class TestCacheKeys(AuditTableTestCase):
    def _key_for(self, alias, table="widget_log"):
        manager = AuditDatabaseManager()
        manager._adopt(connections[alias])
        return manager._cache_key(manager._connection, table)

    def test_same_table_on_different_aliases_does_not_collide(self):
        self.assertNotEqual(self._key_for("default"), self._key_for("postgres"))

    def test_same_table_on_two_postgres_aliases_does_not_collide(self):
        self.assertNotEqual(
            self._key_for("postgres"),
            self._key_for("postgres_with_different_schema"),
        )

    def test_same_table_in_different_postgres_schemas_does_not_collide(self):
        with override_settings(AWESOME_AUDIT_LOG={"PG_SCHEMA": "tenant_a"}):
            key_a = self._key_for("postgres")
        with override_settings(AWESOME_AUDIT_LOG={"PG_SCHEMA": "tenant_b"}):
            key_b = self._key_for("postgres")

        self.assertNotEqual(key_a, key_b)
        self.assertEqual((key_a[0], key_a[2]), (key_b[0], key_b[2]))
        self.assertEqual((key_a[1], key_b[1]), ("tenant_a", "tenant_b"))

    def test_non_postgres_vendors_key_on_a_null_schema(self):
        self.assertEqual(self._key_for("default"), ("default", None, "widget_log"))


class TestPostgresProbe(SimpleTestCase):
    def test_probe_uses_to_regclass_not_information_schema(self):
        sql, params = PostgresDatabaseVendor().get_table_exist_query("widget_log")

        self.assertIn("to_regclass", sql)
        self.assertNotIn("information_schema", sql)
        self.assertEqual(params, ("public.widget_log",))

    def test_probe_qualifies_the_configured_schema(self):
        with override_settings(AWESOME_AUDIT_LOG={"PG_SCHEMA": "audit_log"}):
            _sql, params = PostgresDatabaseVendor().get_table_exist_query("widget_log")

        self.assertEqual(params, ("audit_log.widget_log",))


class TestUndefinedTableDetection(SimpleTestCase):
    def test_sqlite_detects_missing_table(self):
        vendor = SQLiteDatabaseVendor()

        self.assertTrue(
            vendor.is_undefined_table_error(
                OperationalError("no such table: widget_log")
            )
        )

    def test_sqlite_ignores_other_operational_errors(self):
        vendor = SQLiteDatabaseVendor()

        self.assertFalse(
            vendor.is_undefined_table_error(OperationalError("database is locked"))
        )

    def test_postgres_detects_sqlstate_on_the_driver_exception(self):
        class DriverError(Exception):
            sqlstate = "42P01"

        wrapped = ProgrammingError('relation "widget_log" does not exist')
        wrapped.__cause__ = DriverError()

        self.assertTrue(PostgresDatabaseVendor().is_undefined_table_error(wrapped))

    def test_postgres_reads_sqlstate_from_diag(self):
        class Diag:
            sqlstate = "42P01"

        class DriverError(Exception):
            diag = Diag()

        wrapped = ProgrammingError('relation "widget_log" does not exist')
        wrapped.__cause__ = DriverError()

        self.assertTrue(PostgresDatabaseVendor().is_undefined_table_error(wrapped))

    def test_postgres_reads_psycopg2_pgcode(self):
        class DriverError(Exception):
            pgcode = "42P01"

        wrapped = ProgrammingError('relation "widget_log" does not exist')
        wrapped.__cause__ = DriverError()

        self.assertTrue(PostgresDatabaseVendor().is_undefined_table_error(wrapped))

    def test_postgres_ignores_a_permission_error(self):
        class DriverError(Exception):
            sqlstate = "42501"

        wrapped = ProgrammingError("permission denied for table widget_log")
        wrapped.__cause__ = DriverError()

        self.assertFalse(PostgresDatabaseVendor().is_undefined_table_error(wrapped))

    def test_mysql_detects_errno_1146(self):
        exc = ProgrammingError(1146, "Table 'test.widget_log' doesn't exist")

        self.assertTrue(MySQlDatabaseVendor().is_undefined_table_error(exc))

    def test_mysql_detects_errno_1146_on_the_driver_exception(self):
        class DriverError(Exception):
            pass

        wrapped = ProgrammingError("wrapped")
        wrapped.__cause__ = DriverError(1146, "Table 'test.widget_log' doesn't exist")

        self.assertTrue(MySQlDatabaseVendor().is_undefined_table_error(wrapped))

    def test_mysql_ignores_other_errnos(self):
        exc = ProgrammingError(1064, "You have an error in your SQL syntax")

        self.assertFalse(MySQlDatabaseVendor().is_undefined_table_error(exc))


class TestUndefinedTableDetectionOnSqlite(AuditTableTestCase):
    def test_detects_the_error_the_driver_actually_raises(self):
        manager = AuditDatabaseManager()
        manager._get_connection()

        with self.assertRaises(Exception) as caught:
            with connection.cursor() as c:
                c.execute("INSERT INTO widget_log (action) VALUES ('x')")

        self.assertTrue(manager._vendor.is_undefined_table_error(caught.exception))


class TestFailedRetry(AuditTableTestCase):
    def test_a_retry_that_still_misses_surfaces_the_backend_error(self):
        # A create that does not make the table reachable from the INSERT -- the
        # wrong-schema case -- must not leak the internal LogTableMissing marker.
        with patch.object(AuditDatabaseManager, "_create_log_table", autospec=True):
            with self.assertRaises(OperationalError) as caught:
                AuditDatabaseManager().insert_log_row(Widget, _payload("1"))

        self.assertIn("no such table", str(caught.exception))

    @override_settings(AWESOME_AUDIT_LOG={"RAISE_ERROR_IF_DB_UNAVAILABLE": True})
    def test_an_unreachable_audit_database_still_raises(self):
        manager = AuditDatabaseManager()
        manager._get_connection()

        with patch.object(
            AuditDatabaseManager,
            "_insert_rows",
            autospec=True,
            side_effect=OperationalError("connection refused"),
        ):
            with patch.object(
                AuditDatabaseManager, "_ping", autospec=True, return_value=False
            ):
                with self.assertRaises(AuditDBIsNotAvailable):
                    manager._write_rows("widget_log", [_payload("1")])


class TestWriteRoundTrips(AuditTableTestCase):
    def test_steady_state_write_costs_one_round_trip(self):
        conn = connections["default"]

        with CaptureQueriesContext(conn) as cold:
            AuditDatabaseManager().insert_log_row(Widget, _payload("1"))

        # INSERT (fails, table absent) -> CREATE TABLE -> INSERT
        self.assertEqual(len(cold.captured_queries), 3)

        with CaptureQueriesContext(conn) as warm:
            AuditDatabaseManager().insert_log_row(Widget, _payload("2"))

        self.assertEqual(len(warm.captured_queries), 1)
        self.assertIn("INSERT INTO widget_log", warm.captured_queries[0]["sql"])

    def test_steady_state_takes_no_savepoint_outside_a_transaction(self):
        AuditDatabaseManager().insert_log_row(Widget, _payload("1"))

        with CaptureQueriesContext(connections["default"]) as warm:
            AuditDatabaseManager().insert_log_row(Widget, _payload("2"))

        sql = " ".join(q["sql"] for q in warm.captured_queries).upper()
        self.assertNotIn("SAVEPOINT", sql)

    def test_missing_table_recovers_under_a_savepoint_inside_a_transaction(self):
        manager = AuditDatabaseManager()
        manager._get_connection()

        with CaptureQueriesContext(connections["default"]) as captured:
            with transaction.atomic(using="default"):
                manager._write_rows("widget_log", [_payload("7")])

        sql = " ".join(q["sql"] for q in captured.captured_queries).upper()
        self.assertIn("SAVEPOINT", sql)
        self.assertEqual([r["object_pk"] for r in fetch_logs_for("widget")], ["7"])
