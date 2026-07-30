import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterable, Iterator

from django.db import connections, models, router
from django.db.models import Q

from awesome_audit_log.conf import get_setting
from awesome_audit_log.db import AuditDatabaseManager
from awesome_audit_log.signals import (
    _complete_request_data,
    _insert_audit_logs,
    _should_audit_model,
)
from awesome_audit_log.utils import diff_dicts, dumps, serialize_instance

logger = logging.getLogger(__name__)

_audit_disabled = ContextVar("awesome_audit_log_bulk_audit_disabled", default=False)


def audited_bulk_create(manager_or_queryset, objs, **kwargs):
    objs = list(objs)
    model = manager_or_queryset.model
    audited = _should_audit_model(model)
    upsert = bool(kwargs.get("update_conflicts"))

    unique_fields = []
    existing_by_key = {}
    if audited and upsert:
        # An upsert updates some of the rows it is handed. Which ones can only be told
        # from the state that existed *before* the statement ran.
        unique_fields = _resolve_unique_fields(model, kwargs.get("unique_fields"))
        existing_by_key = _fetch_instances_by_unique_key(
            model,
            objs,
            unique_fields,
            using=_write_alias(manager_or_queryset),
        )

    with _disable_nested_bulk_audit():
        created = manager_or_queryset.bulk_create(objs, **kwargs)

    if not audited:
        return created

    if upsert:
        _log_bulk_upsert(
            model,
            created,
            unique_fields,
            existing_by_key,
            update_fields=kwargs.get("update_fields"),
        )
    else:
        _log_bulk_create(model, created)
    return created


def audited_bulk_update(manager_or_queryset, objs, fields, **kwargs):
    objs = list(objs)

    if not _should_audit_model(manager_or_queryset.model):
        with _disable_nested_bulk_audit():
            return manager_or_queryset.bulk_update(objs, fields, **kwargs)

    using = _write_alias(manager_or_queryset)
    old_instances = _fetch_existing_instances(
        manager_or_queryset.model,
        objs,
        using=using,
    )
    with _disable_nested_bulk_audit():
        count = manager_or_queryset.bulk_update(objs, fields, **kwargs)
    _log_bulk_update(
        manager_or_queryset.model,
        objs,
        old_instances,
        updated_fields=fields,
    )
    return count


def audited_queryset_update(queryset, **kwargs):
    if not _should_audit_model(queryset.model):
        with _disable_nested_bulk_audit():
            return queryset.update(**kwargs)

    using = _write_alias(queryset)
    chunk_size = _chunk_size(using)
    before_snapshot = _snapshot_queryset(queryset, using=using, chunk_size=chunk_size)

    # The UPDATE stays a single statement on purpose: splitting it would re-apply F()
    # expressions to rows that later chunks match again.
    with _disable_nested_bulk_audit():
        count = queryset.update(**kwargs)

    _log_queryset_update(
        queryset.model,
        before_snapshot,
        using=using,
        chunk_size=chunk_size,
    )
    return count


class AuditedBulkQuerySetMixin:
    def bulk_create(self, objs, **kwargs):
        if _audit_disabled.get():
            return super().bulk_create(objs, **kwargs)
        return audited_bulk_create(self, objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if _audit_disabled.get():
            return super().bulk_update(objs, fields, **kwargs)
        return audited_bulk_update(self, objs, fields, **kwargs)

    def update(self, **kwargs):
        if _audit_disabled.get():
            return super().update(**kwargs)
        return audited_queryset_update(self, **kwargs)


class AuditedBulkQuerySet(AuditedBulkQuerySetMixin, models.QuerySet):
    pass


@contextmanager
def _disable_nested_bulk_audit():
    token = _audit_disabled.set(True)
    try:
        yield
    finally:
        _audit_disabled.reset(token)


def _write_alias(manager_or_queryset) -> str:
    """Alias the pending write will land on.

    ``Manager.db`` and ``QuerySet.db`` route through ``db_for_read`` until the queryset
    is marked for writing, which would take pre-write snapshots from a replica.
    """
    explicit = getattr(manager_or_queryset, "_db", None)
    if explicit:
        return explicit
    hints = getattr(manager_or_queryset, "_hints", None) or {}
    return router.db_for_write(manager_or_queryset.model, **hints)


def _chunk_size(using: str) -> int:
    configured = get_setting("BULK_CHUNK_SIZE")
    if configured:
        return max(1, int(configured))
    # A chunk feeds one ``pk__in`` refetch and one batched audit insert. The insert is
    # the tighter of the two (one placeholder per log column instead of one per row),
    # so sizing on it keeps both under the backend's placeholder limit.
    return AuditDatabaseManager._insert_batch_size(
        connections[using], len(AuditDatabaseManager.LOG_COLUMNS)
    )


def _resolve_unique_fields(model: type[models.Model], unique_fields) -> list:
    if not unique_fields:
        raise NotImplementedError(
            f"{model._meta.label}: bulk_create(update_conflicts=True) cannot be "
            "audited without 'unique_fields' - there is no way to tell which rows "
            "were inserted and which were updated, and recording an update as an "
            "insert would corrupt the audit trail. MySQL does not support a conflict "
            "target, so 'unique_fields' cannot be supplied there; split the call into "
            "audited_bulk_create() for new rows and audited_bulk_update() for "
            "existing ones."
        )
    return [
        model._meta.get_field(model._meta.pk.name if name == "pk" else name)
        for name in unique_fields
    ]


def _unique_key(instance: models.Model, fields: Iterable) -> tuple | None:
    key = []
    for field in fields:
        value = field.get_prep_value(getattr(instance, field.attname))
        if value is None:
            # A NULL never collides with anything, so such a row cannot be an update.
            return None
        key.append(value)
    return tuple(key)


def _fetch_instances_by_unique_key(
    model: type[models.Model],
    instances: Iterable[models.Model],
    fields: list,
    *,
    using: str,
) -> dict:
    keys = []
    seen = set()
    for instance in instances:
        key = _unique_key(instance, fields)
        if key is not None and key not in seen:
            seen.add(key)
            keys.append(key)

    if not keys:
        return {}

    manager = model._base_manager.using(using)
    attnames = [field.attname for field in fields]
    chunk_size = max(1, _chunk_size(using) // len(fields))

    existing = {}
    for start in range(0, len(keys), chunk_size):
        chunk = keys[start : start + chunk_size]
        if len(fields) == 1:
            lookup = Q(**{f"{attnames[0]}__in": [key[0] for key in chunk]})
        else:
            lookup = Q()
            for key in chunk:
                lookup |= Q(**dict(zip(attnames, key)))
        for instance in manager.filter(lookup):
            key = _unique_key(instance, fields)
            if key is not None:
                existing[key] = instance
    return existing


def _snapshot_queryset(queryset, *, using: str, chunk_size: int) -> list:
    # Serialized eagerly so only one chunk of model instances is alive at a time. The
    # snapshot itself has to outlive the UPDATE, which is what forces it to be held.
    return [
        (instance.pk, serialize_instance(instance))
        for instance in queryset.using(using).iterator(chunk_size=chunk_size)
    ]


def _fetch_existing_instances(
    model: type[models.Model],
    instances: Iterable[models.Model],
    *,
    using: str,
) -> list[models.Model | None]:
    instances = list(instances)
    existing = _iter_instances_by_pk(
        model,
        [instance.pk for instance in instances if instance.pk is not None],
        using=using,
        chunk_size=_chunk_size(using),
    )
    existing_map = {instance.pk: instance for instance in existing}
    return [existing_map.get(instance.pk) for instance in instances]


def _iter_instances_by_pk(
    model: type[models.Model], pks: Iterable, *, using: str, chunk_size: int
) -> Iterator[models.Model]:
    pks = list(pks)
    for start in range(0, len(pks), chunk_size):
        yield from _fetch_instances_by_pk(
            model, pks[start : start + chunk_size], using=using
        )


def _fetch_instances_by_pk(
    model: type[models.Model], pks: Iterable, *, using: str
) -> models.QuerySet:
    return model._base_manager.using(using).filter(pk__in=list(pks))


def _insert_payload(instance: models.Model) -> dict:
    after = serialize_instance(instance)
    return _complete_request_data(
        {
            "action": "insert",
            "object_pk": str(instance.pk),
            "before": dumps(None),
            "after": dumps(after),
            "changes": dumps(
                {k: {"from": None, "to": v} for k, v in (after or {}).items()}
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _update_payload(pk, before: dict | None, after: dict | None, changes: dict) -> dict:
    return _complete_request_data(
        {
            "action": "update",
            "object_pk": str(pk),
            "before": dumps(before),
            "after": dumps(after),
            "changes": dumps(changes),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _log_bulk_create(
    model: type[models.Model], instances: Iterable[models.Model]
) -> None:
    if not _should_audit_model(model):
        return

    payloads = []
    skipped_without_pk = 0
    for instance in instances:
        if instance.pk is None:
            skipped_without_pk += 1
            continue
        payloads.append(_insert_payload(instance))

    _warn_skipped_without_pk(model, skipped_without_pk)
    _insert_audit_logs(model, payloads)


def _log_bulk_upsert(
    model: type[models.Model],
    instances: Iterable[models.Model],
    unique_fields: list,
    existing_by_key: dict,
    update_fields: Iterable[str] | None = None,
) -> None:
    if not _should_audit_model(model):
        return

    updated_attnames = {
        model._meta.get_field(name).attname for name in (update_fields or [])
    }

    payloads = []
    skipped_without_pk = 0
    for instance in instances:
        key = _unique_key(instance, unique_fields)
        existing = existing_by_key.get(key) if key is not None else None

        if existing is None:
            if instance.pk is None:
                skipped_without_pk += 1
                continue
            payloads.append(_insert_payload(instance))
            continue

        before = serialize_instance(existing)
        # ON CONFLICT DO UPDATE only writes ``update_fields``; every other column keeps
        # what was stored, not what the in-memory object happens to hold.
        after = dict(before or {})
        after.update(
            {
                k: v
                for k, v in serialize_instance(instance).items()
                if k in updated_attnames
            }
        )
        changes = diff_dicts(before, after)
        if not changes:
            continue
        payloads.append(_update_payload(existing.pk, before, after, changes))

    _warn_skipped_without_pk(model, skipped_without_pk)
    _insert_audit_logs(model, payloads)


def _log_bulk_update(
    model: type[models.Model],
    instances: Iterable[models.Model],
    old_instances: Iterable[models.Model | None],
    updated_fields: Iterable[str] | None = None,
) -> None:
    if not _should_audit_model(model):
        return

    # serialize_instance() keys on attname, so a ForeignKey passed as "user" has to be
    # matched against "user_id" or its change is filtered out and never logged.
    updated_attnames = {
        model._meta.get_field(name).attname for name in (updated_fields or [])
    }
    old_instances_map = {
        str(instance.pk): serialize_instance(instance)
        for instance in old_instances
        if instance is not None
    }

    payloads = []
    for instance in instances:
        before = old_instances_map.get(str(instance.pk))
        serialized = serialize_instance(instance)

        if updated_attnames and before is not None:
            # bulk_update() only writes the named fields; every other column keeps what
            # was stored, not what the in-memory object happens to hold. Without a
            # stored baseline there is nothing to overlay onto, so fall back to the
            # instance as-is.
            after = dict(before)
            after.update({k: v for k, v in serialized.items() if k in updated_attnames})
        else:
            after = serialized

        changes = diff_dicts(before, after)

        if updated_attnames:
            changes = {
                k: v for k, v in (changes or {}).items() if k in updated_attnames
            }

        if not changes:
            continue

        payloads.append(_update_payload(instance.pk, before, after, changes))

    _insert_audit_logs(model, payloads)


def _log_queryset_update(
    model: type[models.Model],
    before_snapshot: list,
    *,
    using: str,
    chunk_size: int,
) -> None:
    if not _should_audit_model(model):
        return

    for start in range(0, len(before_snapshot), chunk_size):
        chunk = before_snapshot[start : start + chunk_size]
        after_map = {
            str(instance.pk): serialize_instance(instance)
            for instance in _fetch_instances_by_pk(
                model, [pk for pk, _ in chunk], using=using
            )
            if instance.pk is not None
        }

        payloads = []
        for pk, before in chunk:
            after = after_map.get(str(pk))
            changes = diff_dicts(before, after)
            if not changes:
                continue
            payloads.append(_update_payload(pk, before, after, changes))

        _insert_audit_logs(model, payloads)


def _warn_skipped_without_pk(model: type[models.Model], skipped: int) -> None:
    if not skipped:
        return
    logger.warning(
        "%s: %d row(s) had no primary key after bulk_create "
        "(e.g. ignore_conflicts) and were not audited.",
        model._meta.label,
        skipped,
    )
