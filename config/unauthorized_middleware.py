from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from zoneinfo import ZoneInfo

class UnauthorizedBlankPageMiddleware:
    """
    Render 401 as a blank white HTML page for browser requests (Accept: text/html).
    Does not affect API clients requesting JSON (Accept application/json).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate(ZoneInfo("Asia/Jakarta"))
        try:
            response = self.get_response(request)
        finally:
            timezone.deactivate()

        # Only override for 401 and when browser expects HTML
        accept = (request.META.get('HTTP_ACCEPT', '') or '').lower()
        content_type = (response.headers.get('Content-Type', '') or '').lower()

        if response.status_code == 401 and 'text/html' in accept:
            # Keep JSON responses intact
            if 'application/json' in content_type:
                return response
            html = render_to_string('401.html')
            return HttpResponse(html, status=401, content_type='text/html')

        return response
