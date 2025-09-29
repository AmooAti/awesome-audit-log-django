from django.db import models


class Widget(models.Model):
    name = models.CharField(max_length=100)
    qty = models.IntegerField(default=0)

    class Meta:
        db_table = "widget"


class Category(models.Model):
    name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)
