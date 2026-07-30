import uuid

from django.test import TransactionTestCase

from tests.helpers import fetch_logs_for
from tests.fixtures.testapp.models import Widget


class TestPlainBulkOperations(TransactionTestCase):
    reset_sequences = True
    databases = ["default"]

    def test_plain_bulk_create_is_not_automatically_logged(self):
        tag = str(uuid.uuid4())[:8]
        widgets = [
            Widget(name=f"bulk_{tag}_1", qty=10),
            Widget(name=f"bulk_{tag}_2", qty=20),
            Widget(name=f"bulk_{tag}_3", qty=30),
        ]

        created_widgets = Widget.objects.bulk_create(widgets)
        created_pks = [str(w.pk) for w in created_widgets]

        logs = fetch_logs_for("widget")
        insert_logs = [
            r for r in logs if r["action"] == "insert" and r["object_pk"] in created_pks
        ]

        self.assertEqual(len(insert_logs), 0)
        self.assertEqual(len(created_widgets), 3)

    def test_plain_queryset_update_is_not_automatically_logged(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"update_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"update_{tag}_2", qty=20)
        widget3 = Widget.objects.create(name=f"update_{tag}_3", qty=30)
        pks = [str(widget1.pk), str(widget2.pk), str(widget3.pk)]

        updated_count = Widget.objects.filter(
            pk__in=[widget1.pk, widget2.pk, widget3.pk]
        ).update(qty=100)

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 3)
        self.assertEqual(len(update_logs), 0)

    def test_plain_bulk_update_is_not_automatically_logged(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"bulkupd_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"bulkupd_{tag}_2", qty=20)
        widget3 = Widget.objects.create(name=f"bulkupd_{tag}_3", qty=30)

        pks = [str(widget1.pk), str(widget2.pk), str(widget3.pk)]

        widget1.qty = 15
        widget2.qty = 25
        widget3.qty = 35

        updated_count = Widget.objects.bulk_update(
            [widget1, widget2, widget3], fields=["qty"]
        )

        logs = fetch_logs_for("widget")
        update_logs = [
            r for r in logs if r["action"] == "update" and r["object_pk"] in pks
        ]

        self.assertEqual(updated_count, 3)
        self.assertEqual(len(update_logs), 0)

    def test_queryset_delete_is_logged_by_delete_signals(self):
        tag = str(uuid.uuid4())[:8]
        widget1 = Widget.objects.create(name=f"delete_{tag}_1", qty=10)
        widget2 = Widget.objects.create(name=f"delete_{tag}_2", qty=20)
        widget3 = Widget.objects.create(name=f"delete_{tag}_3", qty=30)

        pks = [str(widget1.pk), str(widget2.pk), str(widget3.pk)]

        deleted_count, _ = Widget.objects.filter(
            pk__in=[widget1.pk, widget2.pk, widget3.pk]
        ).delete()

        logs = fetch_logs_for("widget")
        delete_logs = [
            r for r in logs if r["action"] == "delete" and r["object_pk"] in pks
        ]

        self.assertEqual(deleted_count, 3)
        self.assertEqual(len(delete_logs), 3)

        for log in delete_logs:
            self.assertIsNone(log["after"])
            self.assertIsNotNone(log["before"])
            self.assertIn("name", log["before"])

    def test_single_save_still_logged(self):
        tag = str(uuid.uuid4())[:8]
        widget = Widget.objects.create(name=f"single_{tag}", qty=5)

        logs = fetch_logs_for("widget")
        insert_logs = [
            r
            for r in logs
            if r["action"] == "insert" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(insert_logs), 1)
        self.assertEqual(insert_logs[0]["after"]["name"], f"single_{tag}")
        self.assertEqual(insert_logs[0]["after"]["qty"], 5)

        widget.qty = 10
        widget.save()

        logs = fetch_logs_for("widget")
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 5)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 10)

    def test_get_or_create_and_update_or_create_are_logged_by_save_signals(self):
        tag = str(uuid.uuid4())[:8]
        name = f"save_helpers_{tag}"

        widget, created = Widget.objects.get_or_create(name=name, defaults={"qty": 100})

        self.assertTrue(created)

        widget2, created2 = Widget.objects.update_or_create(
            name=name, defaults={"qty": 200}
        )

        logs = fetch_logs_for("widget")
        insert_logs = [
            r
            for r in logs
            if r["action"] == "insert" and r["object_pk"] == str(widget.pk)
        ]
        update_logs = [
            r
            for r in logs
            if r["action"] == "update" and r["object_pk"] == str(widget.pk)
        ]

        self.assertFalse(created2)
        self.assertEqual(widget.pk, widget2.pk)
        self.assertEqual(len(insert_logs), 1)
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0]["changes"]["qty"]["from"], 100)
        self.assertEqual(update_logs[0]["changes"]["qty"]["to"], 200)
