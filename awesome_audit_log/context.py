from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestContext:
    entry_point: str # http, management, shell, celery
    path: Optional[str] = None
    route: Optional[str] = None
    method: Optional[str] = None
    ip: Optional[str] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    user_agent: Optional[str] = None

_ctx: ContextVar[Optional[RequestContext]] = ContextVar('awesome_audit_log_ctx', default=None)

def set_request_ctx(ctx: RequestContext):
    _ctx.set(ctx)

def clear_request_ctx():
    _ctx.set(None)

def get_request_ctx(default: Optional[RequestContext] = None) -> Optional[RequestContext]:
    try:
        return _ctx.get()
    except KeyError:
        return default