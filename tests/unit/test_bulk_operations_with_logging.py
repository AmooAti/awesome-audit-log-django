import uuid
from contextlib import contextmanager
from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError, connection
from django.db.models import F
from django.test import TransactionTestCase, override_settings

from awesome_audit_log import bulk
from awesome_audit_log.bulk import (
    audited_bulk_create,
    audited_bulk_update,
    audited_queryset_update,
)
from tests.helpers import fetch_logs_for
from tests.fixtures.testapp.models import UpsertWidget, Widget


class _ReplicaReadRouter:
    """Sends reads to an alias that is not configured.

    Any pre-write snapshot still taken from the read alias therefore fails loudly
    instead of silently returning stale rows.
    """

    active = False

    def db_for_read(self, model, **hints):
        return "replica" if _ReplicaReadRouter.active else None

    def db_for_write(self, model, **hints):
        return "default" if _ReplicaReadRouter.active else None


@contextmanager
def _split_read_write_router():
    with override_settings(DATABASE_ROUTERS=[_ReplicaReadRouter()]):
        _ReplicaReadRouter.active = True
        try:
            yield
        finally:
            _ReplicaReadRouter.active = False


@contextmanager
def _capture_refetch_alias(captured):
    original = bulk._fetch_instances_by_pk

    def _spy(model, pks, *, using):
        captured.append(using)
        return original(model, pks, using=using)

    with patch.object(bulk, "_fetch_instances_by_pk", _spy):
        yield


def _audit_settings(**overrides):
    return override_settings(
        AWESOME_AUDIT_LOG={**settings.AWESOME_AUDIT_LOG, **overrides}
    )


class TestExplicitBulkOperationsLogging(TransactionTestCase):
    reset_sequences = True
    databases = ["default"]

    def test_audited_bulk_create_helper_logs_inserts(self):
        tag = str(uuid.uuid4())[:8]
        widgets = [
            Widget(name=f"bulk_{tag}_1", qty=10),
            Widget(name=f"bulk_{tag}_2", qty=20),
            Widget(name=f"bulk_{tag}_3", qty=30),
        ]

        created_widgets = audited_bulk_create(Widget.objects, widgets)
        created_pks = [str(w.pk) for w in created_widgets]

        logs = fetch_logs_for("widget")
        insert_logs = [
            r for r in logs if r["action"] == "insert" and r["object_pk"] in created_pks
        ]

        self.assertEqual(len(insert_logs), 3)
        self.assertEqual(len(created_widgets), 3)

        for log in insert_logs:
            self.assertIsNone(log["before"])
            self.assertIsNotNone(log["after"])
            self.assertIn("qty", log["after"])

    def test_audited_bulk_update_helper_logs_updates(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"bulkupd_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"bulkupd_{tag}_2", qty=20)
        widget3 = Widget.objects.create(name=f"bulkupd_{tag}_3", qty=30)

        pks = [str(widget1.pk), str(widget2.pk), str(widget3.pk)]

        widget1.qty = 15
        widget2.qty = 25
        widget3.qty = 35

        updated_count = audited_bulk_update(
            Widget.objects,
            [widget1, widget2, widget3],
            fields=["qty"],
        )

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 3)
        self.assertEqual(len(update_logs), 3)

        for log in update_logs:
            self.assertIn("qty", log["changes"])
            self.assertNotEqual(
                log["changes"]["qty"]["from"], log["changes"]["qty"]["to"]
            )

    def test_audited_queryset_update_helper_logs_updates(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"qsupd_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"qsupd_{tag}_2", qty=20)
        widget3 = Widget.objects.create(name=f"qsupd_{tag}_3", qty=30)

        pks = [str(widget1.pk), str(widget2.pk), str(widget3.pk)]

        queryset = Widget.objects.filter(pk__in=[widget1.pk, widget2.pk, widget3.pk])
        updated_count = audited_queryset_update(queryset, qty=100)

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 3)
        self.assertEqual(len(update_logs), 3)

        for log in update_logs:
            self.assertIn("qty", log["changes"])
            self.assertEqual(log["changes"]["qty"]["to"], 100)

    def test_audited_queryset_update_helper_logs_expression_values(self):
        tag = str(uuid.uuid4())[:8]
        widget = Widget.objects.create(name=f"expr_{tag}", qty=10)

        audited_queryset_update(Widget.objects.filter(pk=widget.pk), qty=F("qty") + 5)

        logs = fetch_logs_for("widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 10)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 15)

    def test_audited_bulk_update_helper_only_logs_requested_fields(self):
        tag = str(uuid.uuid4())[:8]
        widget = Widget.objects.create(name=f"change_{tag}", qty=10)

        widget.qty = 99
        widget.name = f"updated_{tag}"

        audited_bulk_update(Widget.objects, [widget], fields=["qty"])

        logs = fetch_logs_for("widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(update_logs), 1)
        self.assertIn("qty", update_logs[0]["changes"])
        self.assertNotIn("name", update_logs[0]["changes"])

    def test_bulk_create_writes_audit_rows_in_a_single_batch(self):
        tag = str(uuid.uuid4())[:8]
        widgets = [Widget(name=f"batch_{tag}_{i}", qty=i) for i in range(5)]

        with patch("awesome_audit_log.bulk._insert_audit_logs") as mock_batch:
            audited_bulk_create(Widget.objects, widgets)

        mock_batch.assert_called_once()
        _, payloads = mock_batch.call_args[0]
        self.assertEqual(len(payloads), 5)

    def test_audited_queryset_mixin_logs_bulk_create(self):
        tag = str(uuid.uuid4())[:8]
        widgets = [
            Widget(name=f"mixin_{tag}_1", qty=10),
            Widget(name=f"mixin_{tag}_2", qty=20),
        ]

        created_widgets = Widget.audited_objects.bulk_create(widgets)
        created_pks = [str(w.pk) for w in created_widgets]

        logs = fetch_logs_for("widget")
        insert_logs = [
            r for r in logs if r["action"] == "insert" and r["object_pk"] in created_pks
        ]

        self.assertEqual(len(insert_logs), 2)

    def test_audited_queryset_mixin_logs_bulk_update(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"mixin_bu_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"mixin_bu_{tag}_2", qty=20)
        pks = [str(widget1.pk), str(widget2.pk)]

        widget1.qty = 15
        widget2.qty = 25

        updated_count = Widget.audited_objects.bulk_update(
            [widget1, widget2], fields=["qty"]
        )

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 2)
        self.assertEqual(len(update_logs), 2)

    def test_audited_queryset_mixin_logs_queryset_update(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"mixin_qs_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"mixin_qs_{tag}_2", qty=20)
        pks = [str(widget1.pk), str(widget2.pk)]

        updated_count = Widget.audited_objects.filter(pk__in=pks).update(qty=50)

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 2)
        self.assertEqual(len(update_logs), 2)

    def test_audited_queryset_on_an_excluded_model_stays_unaudited(self):
        tag = str(uuid.uuid4())[:8]

        with _audit_settings(NOT_AUDIT_MODELS=["tests_testapp.widget"]):
            created = Widget.audited_objects.bulk_create(
                [Widget(name=f"optout_{tag}", qty=1)]
            )
            widget = created[0]
            widget.qty = 2
            Widget.audited_objects.bulk_update([widget], fields=["qty"])
            Widget.audited_objects.filter(pk=widget.pk).update(qty=3)

        logs = fetch_logs_for("widget")

        self.assertEqual(
            [r for r in logs if r["object_pk"] == str(widget.pk)],
            [],
        )

    def test_upsert_logs_conflicting_rows_as_updates_and_the_rest_as_inserts(self):
        tag = str(uuid.uuid4())[:8]
        existing = UpsertWidget.objects.create(
            code=f"up_{tag}_a", qty=1, note="untouched"
        )

        created = audited_bulk_create(
            UpsertWidget.objects,
            [
                UpsertWidget(code=f"up_{tag}_a", qty=100, note="ignored"),
                UpsertWidget(code=f"up_{tag}_b", qty=300, note="brand-new"),
            ],
            update_conflicts=True,
            update_fields=["qty"],
            unique_fields=["code"],
        )

        new_pk = str(created[1].pk)
        logs = fetch_logs_for("upsert_widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(existing.pk)
        ]
        insert_logs = [
            r for r in logs if r["action"] == "insert" and r["object_pk"] == new_pk
        ]

        # The conflicting row was updated, not inserted.
        self.assertEqual(
            [r for r in logs if r["object_pk"] == str(existing.pk)][0]["action"],
            "update",
        )
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 100)
        self.assertEqual(update_logs[0]["before"]["qty"], 1)
        # ``note`` was not in update_fields, so the stored row kept its old value even
        # though the in-memory object carried a different one.
        self.assertEqual(update_logs[0]["before"]["note"], "untouched")
        self.assertEqual(update_logs[0]["after"]["note"], "untouched")
        self.assertNotIn("note", update_logs[0]["changes"])

        self.assertEqual(len(insert_logs), 1)
        self.assertIsNone(insert_logs[0]["before"])
        self.assertEqual(insert_logs[0]["after"]["qty"], 300)

        existing.refresh_from_db()
        self.assertEqual(existing.qty, 100)
        self.assertEqual(existing.note, "untouched")

    def test_composite_unique_key_lookup_matches_whole_tuples(self):
        tag = str(uuid.uuid4())[:8]
        stored = UpsertWidget.objects.create(code=f"comp_{tag}_a", qty=7)
        UpsertWidget.objects.create(code=f"comp_{tag}_b", qty=8)

        fields = [
            UpsertWidget._meta.get_field("code"),
            UpsertWidget._meta.get_field("qty"),
        ]
        existing = bulk._fetch_instances_by_unique_key(
            UpsertWidget,
            [
                UpsertWidget(code=f"comp_{tag}_a", qty=7),
                # same code, different qty: not the same unique tuple
                UpsertWidget(code=f"comp_{tag}_b", qty=99),
            ],
            fields,
            using="default",
        )

        self.assertEqual(list(existing), [(f"comp_{tag}_a", 7)])
        self.assertEqual(existing[(f"comp_{tag}_a", 7)].pk, stored.pk)

    def test_upsert_without_unique_fields_refuses_and_writes_nothing(self):
        tag = str(uuid.uuid4())[:8]
        objs = [UpsertWidget(code=f"norefuse_{tag}", qty=5)]

        with self.assertRaises(NotImplementedError) as ctx:
            audited_bulk_create(
                UpsertWidget.objects,
                objs,
                update_conflicts=True,
                update_fields=["qty"],
            )

        message = str(ctx.exception)
        self.assertIn("update_conflicts", message)
        self.assertIn("unique_fields", message)
        self.assertFalse(UpsertWidget.objects.filter(code=f"norefuse_{tag}").exists())
        self.assertEqual(fetch_logs_for("upsert_widget"), [])

    def test_queryset_update_chunks_snapshot_and_refetch(self):
        tag = str(uuid.uuid4())[:8]
        Widget.objects.bulk_create(
            [Widget(name=f"chunk_{tag}_{i}", qty=i) for i in range(10)]
        )
        widgets = list(Widget.objects.filter(name__startswith=f"chunk_{tag}"))
        pks = [str(w.pk) for w in widgets]

        captured = []
        with _audit_settings(BULK_CHUNK_SIZE=3), _capture_refetch_alias(captured):
            updated_count = audited_queryset_update(
                Widget.objects.filter(name__startswith=f"chunk_{tag}"),
                qty=F("qty") + 1,
            )

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]
        by_pk = {r["object_pk"]: r for r in update_logs}

        self.assertEqual(updated_count, 10)
        # exactly one audit row per changed object, and no double-applied F()
        self.assertEqual(len(update_logs), 10)
        self.assertEqual(len(by_pk), 10)
        for widget in widgets:
            log = by_pk[str(widget.pk)]
            self.assertEqual(log["changes"]["qty"]["from"], widget.qty)
            self.assertEqual(log["changes"]["qty"]["to"], widget.qty + 1)

        # 10 rows at a chunk size of 3 is four refetches, none of them unbounded
        self.assertEqual(len(captured), 4)

    def test_queryset_update_past_the_sqlite_variable_limit_does_not_raise(self):
        connection.ensure_connection()
        if not hasattr(connection.connection, "setlimit"):
            self.skipTest("sqlite3.Connection.setlimit requires Python 3.11+")

        import sqlite3

        tag = str(uuid.uuid4())[:8]
        total = 1200
        Widget.objects.bulk_create(
            [Widget(name=f"limit_{tag}_{i}", qty=i) for i in range(total)]
        )
        queryset = Widget.objects.filter(name__startswith=f"limit_{tag}")
        pks = list(queryset.values_list("pk", flat=True))

        previous = connection.connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999
        )
        try:
            # one IN clause for the whole set is exactly what used to blow up here
            with self.assertRaisesMessage(OperationalError, "too many SQL variables"):
                list(bulk._fetch_instances_by_pk(Widget, pks, using="default"))

            updated_count = audited_queryset_update(queryset, qty=F("qty") + 1)
        finally:
            connection.connection.setlimit(
                sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous
            )

        logs = fetch_logs_for("widget")
        update_logs = [r for r in logs if r["action"] == "update"]

        self.assertEqual(updated_count, total)
        self.assertEqual(len(update_logs), total)
        self.assertEqual(len({r["object_pk"] for r in update_logs}), total)

    def test_bulk_update_reads_its_before_snapshot_from_the_write_alias(self):
        tag = str(uuid.uuid4())[:8]
        widget = Widget.objects.create(name=f"router_bu_{tag}", qty=10)
        widget.qty = 42

        captured = []
        with _split_read_write_router(), _capture_refetch_alias(captured):
            # the manager's own ``.db`` is the (unconfigured) read alias
            self.assertEqual(Widget.objects.db, "replica")
            audited_bulk_update(Widget.objects, [widget], fields=["qty"])

        logs = fetch_logs_for("widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(captured, ["default"])
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 10)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 42)

    def test_queryset_update_reads_its_before_snapshot_from_the_write_alias(self):
        tag = str(uuid.uuid4())[:8]
        widget = Widget.objects.create(name=f"router_qs_{tag}", qty=10)

        captured = []
        with _split_read_write_router(), _capture_refetch_alias(captured):
            queryset = Widget.objects.filter(pk=widget.pk)
            # the before-snapshot runs before ``update()`` marks the queryset for
            # writing, so an unpinned read would land on the replica
            self.assertEqual(queryset.db, "replica")
            audited_queryset_update(queryset, qty=77)

        logs = fetch_logs_for("widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(captured, ["default"])
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 10)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 77)
