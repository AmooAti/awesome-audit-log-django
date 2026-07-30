from django.test import TransactionTestCase

from awesome_audit_log.bulk import audited_bulk_update
from tests.fixtures.testapp.models import Assignment, Category
from tests.helpers import fetch_logs_for


class TestBulkUpdateForeignKeyLogging(TransactionTestCase):
    @staticmethod
    def _updates_for(base_table):
        return [row for row in fetch_logs_for(base_table) if row["action"] == "update"]

    def test_bulk_update_logs_foreign_key_changes(self):
        old = Category.objects.create(name="old")
        new = Category.objects.create(name="new")
        first = Assignment.objects.create(label="first", category=old)
        second = Assignment.objects.create(label="second", category=old)

        first.category = new
        second.category = new
        audited_bulk_update(Assignment.objects, [first, second], ["category"])

        updates = self._updates_for("assignment")
        self.assertEqual(len(updates), 2)

        by_pk = {str(row["object_pk"]): row for row in updates}
        for obj in (first, second):
            changes = by_pk[str(obj.pk)]["changes"]
            # The field is named "category" but serializes as "category_id".
            self.assertEqual(set(changes), {"category_id"})
            self.assertEqual(changes["category_id"]["from"], old.pk)
            self.assertEqual(changes["category_id"]["to"], new.pk)

    def test_bulk_update_logs_foreign_key_set_to_null(self):
        category = Category.objects.create(name="c")
        obj = Assignment.objects.create(label="l", category=category)

        obj.category = None
        audited_bulk_update(Assignment.objects, [obj], ["category"])

        updates = self._updates_for("assignment")
        self.assertEqual(len(updates), 1)
        self.assertEqual(
            updates[0]["changes"]["category_id"],
            {"from": category.pk, "to": None},
        )

    def test_bulk_update_still_filters_to_named_fields(self):
        old = Category.objects.create(name="old")
        new = Category.objects.create(name="new")
        obj = Assignment.objects.create(label="before", category=old)

        # Only "category" is passed to bulk_update, so the label is never written and
        # must not appear in the log even though the in-memory object carries it.
        obj.category = new
        obj.label = "not-persisted"
        audited_bulk_update(Assignment.objects, [obj], ["category"])

        updates = self._updates_for("assignment")
        self.assertEqual(len(updates), 1)
        self.assertEqual(set(updates[0]["changes"]), {"category_id"})

        # "after" is the post-update row, not the in-memory object: the unwritten
        # label must still read as what is actually stored.
        after = updates[0]["after"]
        self.assertEqual(after["label"], "before")
        self.assertEqual(after["category_id"], new.pk)
        self.assertEqual(
            Assignment.objects.get(pk=obj.pk).label,
            after["label"],
        )

    def test_bulk_update_mixing_relation_and_plain_fields(self):
        old = Category.objects.create(name="old")
        new = Category.objects.create(name="new")
        obj = Assignment.objects.create(label="before", category=old)

        obj.category = new
        obj.label = "after"
        audited_bulk_update(Assignment.objects, [obj], ["category", "label"])

        updates = self._updates_for("assignment")
        self.assertEqual(len(updates), 1)
        changes = updates[0]["changes"]
        self.assertEqual(set(changes), {"category_id", "label"})
        self.assertEqual(changes["label"], {"from": "before", "to": "after"})
        self.assertEqual(changes["category_id"], {"from": old.pk, "to": new.pk})

        # Both fields were written, so "after" carries both new values.
        self.assertEqual(updates[0]["after"]["label"], "after")
        self.assertEqual(updates[0]["after"]["category_id"], new.pk)
