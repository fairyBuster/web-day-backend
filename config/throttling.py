from rest_framework.throttling import UserRateThrottle
from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler


class RoleBasedUserRateThrottle(UserRateThrottle):
    """
    User throttle dengan rate berbeda untuk admin.
    - user biasa: gunakan scope 'user'
    - admin (is_staff): gunakan scope 'admin_user'
    """

    def allow_request(self, request, view):
        original_scope = getattr(self, 'scope', None)
        try:
            if getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_staff:
                self.scope = 'admin_user'
            else:
                self.scope = 'user'
            return super().allow_request(request, view)
        finally:
            # Kembalikan scope agar tidak bocor ke request lain
            self.scope = original_scope


def drf_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return response

    if isinstance(exc, Throttled):
        request = context.get('request')
        view = context.get('view')
        scope = getattr(view, 'throttle_scope', None) if view is not None else None

        response.data = {
            'code': 'rate_limited',
            'detail': 'Terlalu banyak request, coba lagi nanti.',
            'wait_seconds': int(exc.wait) if exc.wait is not None else None,
            'scope': scope,
            'path': getattr(request, 'path', None),
            'method': getattr(request, 'method', None),
        }

    return response
