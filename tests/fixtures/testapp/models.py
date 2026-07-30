from django.db import models

from awesome_audit_log.bulk import AuditedBulkQuerySet


class Widget(models.Model):
    name = models.CharField(max_length=100)
    qty = models.IntegerField(default=0)

    objects = models.Manager()
    audited_objects = AuditedBulkQuerySet.as_manager()

    class Meta:
        db_table = "widget"


class Category(models.Model):
    name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)


class UpsertWidget(models.Model):
    code = models.CharField(max_length=100, unique=True)
    qty = models.IntegerField(default=0)
    note = models.CharField(max_length=100, default="")

    class Meta:
        db_table = "upsert_widget"


class Assignment(models.Model):
    label = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.CASCADE
    )

    class Meta:
        db_table = "assignment"
