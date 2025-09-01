from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestContext:
    entry_point: str # http, management, shell, celery
    path: str | None = None
    route: str | None = None
    method: str | None = None
    ip: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    user_agent: str | None = None

_ctx: ContextVar[RequestContext | None] = ContextVar(
    'awesome_audit_log_ctx',
    default=None
)

def set_request_ctx(ctx: RequestContext):
    _ctx.set(ctx)

def clear_request_ctx():
    _ctx.set(None)

def get_request_ctx(default: RequestContext | None = None) -> RequestContext | None:
    try:
        return _ctx.get()
    except KeyError:
        return default
