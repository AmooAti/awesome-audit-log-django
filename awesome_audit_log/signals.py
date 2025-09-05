from django.db import models
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from awesome_audit_log.conf import get_setting
from awesome_audit_log.context import get_request_ctx
from awesome_audit_log.db import AuditDatabaseManager
from awesome_audit_log.utils import diff_dicts, dumps, serialize_instance


def _should_audit_model(model: models.Model) -> bool:
    if model._meta.app_label == "awesome_audit_log":
        return False
    if not get_setting("ENABLED"):
        return False
    models_opt_out = get_setting("NOT_AUDIT_MODELS")
    label = f"{model._meta.app_label}.{model._meta.model_name}"
    if models_opt_out and label in set(models_opt_out or []):
        return False
    models_opt = get_setting("AUDIT_MODELS")
    if models_opt == "all":
        return True
    print(label in set(models_opt or []))
    return label in set(models_opt or [])


@receiver(pre_save)
def _audit_pre_save(sender, instance, **kwargs):
    if not _should_audit_model(sender):
        return
    if instance.pk:
        try:
            old = sender._default_manager.get(pk=instance.pk)
            instance.__audit_before = serialize_instance(old)
        except sender.DoesNotExist:
            instance.__audit_before = None
    else:
        instance.__audit_before = None


@receiver(post_save)
def _audit_post_save(sender, instance, created, **kwargs):
    if not _should_audit_model(sender):
        return

    before = getattr(instance, "__audit_before", None)
    after = serialize_instance(instance)
    payload = {
        "action": "insert" if created else "update",
        "object_pk": str(instance.pk),
        "before": dumps(before),
        "after": dumps(after),
        "changes": dumps(diff_dicts(before, after)),
    }

    payload = _complete_request_data(payload)

    _audit_database_manager = AuditDatabaseManager()
    _audit_database_manager.insert_log_row(sender, payload)


@receiver(pre_delete)
def _audit_pre_delete(sender, instance, **kwargs):
    if not _should_audit_model(sender):
        return
    before = serialize_instance(instance)
    payload = {
        "action": "delete",
        "object_pk": str(instance.pk),
        "before": dumps(before),
        "after": dumps(None),
        "changes": dumps(
            {k: {"from": v, "to": None} for k, v in (before or {}).items()}
        ),
    }

    payload = _complete_request_data(payload)

    _audit_database_manager = AuditDatabaseManager()
    _audit_database_manager.insert_log_row(sender, payload)


def _complete_request_data(payload: dict[str, str]):
    ctx = get_request_ctx()
    if ctx:
        payload.update(
            {
                "entry_point": ctx.entry_point,
                "route": ctx.route,
                "path": ctx.path,
                "method": ctx.method,
                "ip": ctx.ip,
                "user_id": ctx.user_id,
                "user_name": ctx.user_name,
                "user_agent": ctx.user_agent,
            }
        )
    return payload
