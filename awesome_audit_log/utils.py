import datetime as dt
import decimal
import json
from typing import Any

from django.db import models


def _to_primitive(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return str(value)

def serialize_instance(instance: models.Model) -> dict:
    """Serialize concrete fields of a model instance to a JSON-serializable dict."""
    data = {}
    for field in instance._meta.fields:
        if (
            getattr(field, "concrete", False)
            and not getattr(field, "many_to_many", False)
        ):
            name = field.attname if hasattr(field, "attname") else field.name
            try:
                data[name] = _to_primitive(getattr(instance, name))
            except Exception:
                data[name] = None
    return data

def diff_dicts(before: dict | None, after: dict | None) -> dict:
    before = before or {}
    after = after or {}
    changes = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        if before.get(k) != after.get(k):
            changes[k] = {"from": before.get(k), "to": after.get(k)}
    return changes

def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
