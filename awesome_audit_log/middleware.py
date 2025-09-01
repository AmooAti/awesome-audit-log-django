from __future__ import annotations

from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin

from awesome_audit_log.conf import get_setting
from awesome_audit_log.context import RequestContext, clear_request_ctx, set_request_ctx


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

class RequestEntryPointMiddleware(MiddlewareMixin):
    """
    Stores HTTP context (path, route, method, ip, user, ua) in a ContextVar
    so signal handlers can include it in audit rows.
    """
    def process_request(self, request):
        if not get_setting('CAPTURE_HTTP') or not get_setting('ENABLED'):
            return
        try:
            resolver_match = resolve(request.path_info)
            route = resolver_match.view_name
        except Exception:
            route = None
        user = getattr(request, "user", None)
        user_id = user.pk if getattr(user, 'is_authenticated', None) else None
        user_name = getattr(user, 'get_username', lambda: None)()
        ua = request.META.get('HTTP_USER_AGENT')
        set_request_ctx(RequestContext(
            entry_point="http",
            path=request.get_full_path(),
            route=route,
            method=request.method,
            ip=_client_ip(request),
            user_id=user_id,
            user_name=user_name,
            user_agent=ua
        ))

    def process_response(self, request, response):
        clear_request_ctx()
        return response

    def process_exception(self, request, exception):
        clear_request_ctx()
        return None
